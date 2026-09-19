#!/usr/bin/env python3
"""Measure bounded hook preparation on disposable maximum-field graphs."""
from __future__ import annotations

import json
import os
import shlex
import tempfile
import time
import tracemalloc
from pathlib import Path

from mindmap.lifecycle import handle_hook
from mindmap.store import Store


def main() -> None:
    rows = []
    with tempfile.TemporaryDirectory(prefix='mindmap-profile-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'home' / 'project'
        root.mkdir(parents=True)
        os.environ.update(MINDMAP_HOME_DIR=str(base / 'home'), MINDMAP_DATA_DIR=str(base / 'data'), MINDMAP_TRACKING='on')
        store = Store()
        project = store.activate(root)
        populated = 0
        for count, events in ((0, 0), (21, 0), (101, 0), (1001, 0), (1001, 10000)):
            for start in range(populated, count, 8):
                store.record(root, 'codex', 'seed', str(start), {'summary': 'Fixture', 'operations': [
                    {'op': 'upsert', 'id': f'idea-{i}', 'parent_id': 'idea-0' if i else None,
                     'title': '🧭' * 160, 'summary': '🧭' * 1200, 'resume': '🧭' * 600}
                    for i in range(start, min(start + 8, count))]})
            populated = count
            if events:
                with store.transaction() as db:
                    for i in range(events):
                        store._event(db, project['id'], 'item.updated', {'operation': {
                            'op': 'upsert', 'id': 'idea-0', 'state': 'open', 'summary': 'History'},
                            'previous_state': 'open'}, item_id='idea-0')
            for host in ('codex', 'claude'):
                for event in ('SessionStart', 'UserPromptSubmit', 'Stop'):
                    payload = {'hook_event_name': event, 'cwd': str(root), 'session_id': host,
                               'turn_id': f'{count}-{events}', 'prompt': 'Review idea-1000',
                               'last_assistant_message': 'Complete'}
                    tracemalloc.start()
                    started = time.perf_counter()
                    result = handle_hook(host, payload, store)
                    elapsed = time.perf_counter() - started
                    _, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    text = result.get('reason') or result['hookSpecificOutput']['additionalContext']
                    encoded = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode()
                    rows.append({'concepts': count, 'extra_history_events': events, 'host': host, 'event': event,
                                 'seconds': round(elapsed, 4), 'peak_python_bytes': peak,
                                 'serialized_bytes': len(encoded) + 1, 'decoded_bytes': len(text.encode())})
        with store.read_connection() as db:
            for row in db.execute('SELECT command FROM context_bindings'):
                Path(shlex.split(row[0])[1]).unlink(missing_ok=True)
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
