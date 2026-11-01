"""Historical fault-injection helpers for offline review; live launcher disabled."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

MARKER_COMMAND = "printf 'qualification-later-tool\\n' > .qualification-later-tool"


def setup_context(event, case, output):
    """Induce the fault only in the initial disposable prompt, never recovery.

    A user prompt alone cannot override Codex's hook final-tool instruction.
    Replace that ordering instruction in the test copy's initial context, so
    the test can exercise actual host tools after an accepted checkpoint.
    The shipped plugin, commit correlation and Stop context remain unmodified.
    """
    if case != 'actual-later-tool' or event != 'UserPromptSubmit':
        return output
    value = json.loads(output)
    context = value['hookSpecificOutput']['additionalContext']
    replacements = {
        'as the final tool (foreground Bash/exec_command).': 'in the foreground using Bash/exec_command.',
        'Use a non-interactive pipe or heredoc, never TTY/write_stdin. Finish all tools, audio, clipboard, notifications and async work first; after commit send the final response without another tool.':
        'Use a non-interactive pipe or heredoc, never TTY/write_stdin.',
        'After later work, prepare --supersedes TOKEN with a reviewed delta. Retry only the same commit_command; replay alone cannot cover later work.':
        'Recovery will supply the next preparation instructions after the initial final response.',
    }
    for original, replacement in replacements.items():
        if context.count(original) != 1:
            raise ValueError('Recovery fixture no longer matches the initial ordering instruction')
        context = context.replace(original, replacement)
    value['hookSpecificOutput']['additionalContext'] = (
        'ISOLATED RECOVERY TEST SETUP: For this initial response only, deliberately leave the first '
        'checkpoint stale. Prepare and commit an empty delta, then run exactly ' + MARKER_COMMAND +
        ' as a separate shell tool, then finish. Do not move that tool before the commit or checkpoint '
        'again before the first Stop. This setup overrides the normal final-tool ordering only for '
        'this initial test phase. Follow the subsequent unmodified Stop recovery instructions normally.\n' + context)
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


def observed_turn(database, host, payload):
    """Read before/after real PreToolUse; this observer never increments state."""
    with sqlite3.connect(database) as db:
        db.row_factory = sqlite3.Row
        turn_id = payload.get('turn_id') or payload.get('prompt_id')
        row = db.execute('''SELECT t.id, t.checkpoint_token, t.checkpointed_at,
            t.tool_activity_generation, t.checkpoint_tool_activity_generation
            FROM turns t JOIN sessions s ON s.id=t.session_pk
            WHERE s.host=? AND s.session_id=? AND (? IS NULL OR t.interaction_id=?)
            ORDER BY t.id DESC LIMIT 1''', (host, payload['session_id'], turn_id, turn_id)).fetchone()
    return dict(row) if row else None


def real_tool_problems(events, marker):
    """Require execution plus a real checkpoint -> tool -> stale Stop chain."""
    problems = []
    stops = [index for index, entry in enumerate(events) if entry['event'] == 'Stop']
    if not stops:
        return ['no Stop observed after the real-tool fixture']
    tools = [entry for entry in events[:stops[0]] if entry['event'] == 'PreToolUse'
             and (entry['payload'].get('tool_input', {}).get('command') or
                  entry['payload'].get('tool_input', {}).get('cmd')) == MARKER_COMMAND]
    if len(tools) != 1 or marker != 'qualification-later-tool\n':
        return ['expected exactly one executed marker tool before first Stop']
    before, after = tools[0].get('before_tool') or {}, tools[0].get('after_tool') or {}
    stop = events[stops[0]].get('before') or {}
    token = before.get('checkpoint_token')
    if not token or not before.get('checkpointed_at'):
        problems.append('marker tool ran before an accepted checkpoint')
    if not (before.get('tool_activity_generation') == before.get('checkpoint_tool_activity_generation')
            and after.get('tool_activity_generation') == before.get('tool_activity_generation', -1) + 1
            and after.get('checkpoint_tool_activity_generation') == before.get('checkpoint_tool_activity_generation')
            and token == after.get('checkpoint_token') == stop.get('checkpoint_token')
            and after.get('tool_activity_generation') == stop.get('tool_activity_generation')):
        problems.append('real tool did not leave the same checkpoint stale through first Stop')
    if any(e.get('runtime_stdout', e['stdout']) != e['stdout'] for e in events if e['event'] == 'Stop'):
        problems.append('test altered the production Stop response')
    return problems


def graph_digest(store, project_id):
    items = store.project_view(project_id)["items"]
    return hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()


def main():
    raise SystemExit("Agent integration is paused; live hook probes are disabled pending review.")


if __name__ == "__main__":
    raise SystemExit(main())
