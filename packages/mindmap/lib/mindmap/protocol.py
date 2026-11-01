"""Explicit reconciliation and correlated, immutable commit requests."""
from __future__ import annotations

import json
import os
import shlex
import stat
import sys
import uuid
from pathlib import Path
from typing import Any

from .errors import MindmapError


def install_schema(db: Any) -> None:
    db.executescript('''
        CREATE TABLE IF NOT EXISTS context_bindings (
          token TEXT PRIMARY KEY, turn_id INTEGER UNIQUE REFERENCES turns(id) ON DELETE CASCADE,
          project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          command TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS record_requests (
          token TEXT PRIMARY KEY, binding_token TEXT NOT NULL REFERENCES context_bindings(token),
          turn_id INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
          payload_json TEXT NOT NULL, supersedes TEXT, prompt_version INTEGER NOT NULL,
          safe_generation INTEGER NOT NULL, checkpoint_token TEXT, command TEXT NOT NULL UNIQUE);
        CREATE INDEX IF NOT EXISTS idx_events_context ON events(project_id, event_type, item_id, id);
    ''')


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise MindmapError('Unsafe Mindmap command directory.')


def binding(store: Any, project_id: int, turn_id: int | None) -> dict[str, Any]:
    with store.transaction() as db:
        row = db.execute('SELECT * FROM context_bindings WHERE turn_id = ?', (turn_id,)).fetchone() if turn_id else None
        token = row['token'] if row else uuid.uuid4().hex
        directory = store.path.resolve().parent / 'commands'
        if len(str(directory).encode()) > 32:
            directory = Path('/tmp') / f'mindmap-{os.getuid()}'
        _private_directory(directory)
        script = directory / token
        command = 'sh ' + shlex.quote(str(script))
        # The short command binds even arbitrarily long roots and host identities
        # in SQLite. It uses this runtime and this database, independent of cwd.
        code = (
            'import sys; sys.dont_write_bytecode=True; '
            f'sys.path.insert(0,{str(Path(__file__).resolve().parents[1])!r}); '
            'from mindmap.cli import main; '
            f'raise SystemExit(main(["--database",{str(store.path.resolve())!r},'
            f'"bound",{token!r}]+sys.argv[1:]))'
        )
        content = '#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -c ' + shlex.quote(code) + ' "$@"\n'
        if not script.exists():
            fd = os.open(script, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
            with os.fdopen(fd, 'w') as output:
                output.write(content)
        elif script.is_symlink() or script.read_text() != content:
            raise MindmapError('Mindmap command binding changed; restart from a fresh hook.')
        if not row:
            db.execute('INSERT INTO context_bindings VALUES (?, ?, ?, ?)', (token, turn_id, project_id, command))
        return {'token': token, 'command': command}


def resolve_binding(db: Any, token: str) -> dict[str, Any]:
    row = db.execute('''SELECT b.*, p.root_path, t.interaction_id, s.host, s.session_id
        FROM context_bindings b JOIN projects p ON p.id=b.project_id
        LEFT JOIN turns t ON t.id=b.turn_id LEFT JOIN sessions s ON s.id=t.session_pk
        WHERE b.token=?''', (token,)).fetchone()
    if not row:
        raise MindmapError('Unknown context binding; obtain fresh hook context.')
    return dict(row)


def prompt_version(db: Any, turn_id: int) -> int:
    return db.execute('SELECT coalesce(max(id),0) FROM turn_prompts WHERE turn_id=?', (turn_id,)).fetchone()[0]


def prepare(store: Any, binding_token: str, payload: dict[str, Any], supersedes: str | None) -> dict[str, Any]:
    # Apply shape/size validation before retaining request JSON; graph validation
    # and revision checks still happen atomically at commit time.
    store.validate_payload(payload)
    token = uuid.uuid4().hex
    with store.transaction() as db:
        bound = resolve_binding(db, binding_token)
        turn = db.execute('SELECT * FROM turns WHERE id=?', (bound['turn_id'],)).fetchone()
        if not turn:
            raise MindmapError('This context has no prompt identity; wait for UserPromptSubmit.')
        if turn['checkpointed_at'] and supersedes != turn['checkpoint_token']:
            raise MindmapError('Already checkpointed; review later work and prepare with --supersedes ' + str(turn['checkpoint_token']))
        if supersedes and supersedes != turn['checkpoint_token']:
            raise MindmapError('Checkpoint changed; refresh state and reconcile again.')
        command = bound['command'] + ' commit ' + token
        db.execute('INSERT INTO record_requests VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)',
                   (token, binding_token, turn['id'], json.dumps(payload, ensure_ascii=False), supersedes,
                    prompt_version(db, turn['id']), turn['tool_activity_generation'], command))
    return {'request': token, 'commit_command': command,
            'instruction': 'Run exactly this command as the final tool, in the foreground. Retry the same command only for transport failure. Any other tool requires preparation again.'}


def correlate_commit(db: Any, turn_id: int, generation: int, payload: dict[str, Any]) -> None:
    """Only an exact registered foreground command advances a safe request chain.

    Deliberately no shell parsing: quotes, pipes, redirects, JS wrappers and
    bundled work must not become evidence of a pure retry.
    """
    name = payload.get('tool_name')
    fields = {'Bash': 'command', 'exec_command': 'cmd', 'functions.exec_command': 'cmd'}
    field = fields.get(name)
    value = payload.get('tool_input')
    if not field or not isinstance(value, dict) or not isinstance(value.get(field), str):
        return
    if value.get('run_in_background') or value.get('tty'):
        return
    command = value[field]
    updated = db.execute('''UPDATE record_requests SET safe_generation=?
        WHERE turn_id=? AND command=? AND safe_generation=?''',
        (generation, turn_id, command, generation - 1))
    from .diagnostics import emit
    emit('tool_correlation', tool=name, input_keys=sorted(value), matched=updated.rowcount == 1)


def check_request(db: Any, request: Any, turn: Any) -> None:
    if not turn or prompt_version(db, turn['id']) != request['prompt_version']:
        raise MindmapError('A new prompt superseded this request; prepare the incremental delta again.')
    if request['safe_generation'] != turn['tool_activity_generation']:
        raise MindmapError('Uncorrelated tool activity followed preparation; review the work and prepare again. Run the commit command alone using Bash or exec_command.')


def commit(store: Any, binding_token: str, request_token: str) -> dict[str, Any]:
    with store.read_connection() as db:
        bound = resolve_binding(db, binding_token)
        request = db.execute('SELECT * FROM record_requests WHERE token=? AND binding_token=?', (request_token, binding_token)).fetchone()
        if not request:
            raise MindmapError('Unknown prepared request for this binding.')
        payload = json.loads(request['payload_json'])
    return store.record(bound['root_path'], bound['host'], bound['session_id'], bound['interaction_id'],
                        payload, supersedes=request['supersedes'], request_token=request_token)
