"""Fault-injection hook wrapper for test_stop_recovery.py, never packaged.

The real host invokes this copied wrapper, which invokes the unmodified package
hook. Only isolated test database finality metadata changes before Stop. Graph
writes and model-visible recovery instructions are the candidate's own.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def graph_digest(store, project_id):
    items = store.project_view(project_id)["items"]
    return hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()


def main():
    package = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(package / "lib"))
    from mindmap.store import Store
    from mindmap.activity import note_pre_tool_activity
    from mindmap.transport import configure_stdio
    configure_stdio()
    payload = json.load(sys.stdin)
    host = sys.argv[sys.argv.index("--host") + 1]
    event = payload.get("hook_event_name")
    log = Path(os.environ["MINDMAP_RECOVERY_PROBE_LOG"])
    prior = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    ordinal = 1 + sum(row["event"] == "Stop" for row in prior)
    entry = {"event": event, "adapter_host": host, "time": time.time(), "payload": payload}
    if event == "Stop":
        store = Store()
        turn_id = payload.get("turn_id") or payload.get("prompt_id")
        session = payload["session_id"]
        turn = store.turn(host, session, turn_id)
        entry["before"] = turn
        case = os.environ["MINDMAP_RECOVERY_PROBE_CASE"]
        entry["ordinal"] = ordinal
        if turn:
            project = store.session(host, session)["project_id"]
            entry["graph_before"] = graph_digest(store, project)
            if ordinal == 1:
                if case == "actual-later-tool":
                    if not turn['checkpointed_at'] or turn['tool_activity_generation'] <= turn['checkpoint_tool_activity_generation']:
                        entry['setup_error'] = 'model did not leave its real later tool uncovered'
                    entry['fault'] = 'none: model ran a real host tool after its checkpoint'
                elif case == "missing":
                    if turn["checkpointed_at"]:
                        store.invalidate_checkpoint(host, session, turn_id, "qualification_missing_checkpoint")
                    entry["fault"] = "checkpoint metadata missing; accepted graph writes retained"
                elif not turn["checkpointed_at"]:
                    entry["setup_error"] = "case requires an initial model checkpoint"
                elif case == "legacy-age":
                    with store.transaction() as db:
                        db.execute("""UPDATE turns SET tool_activity_generation=0,
                            checkpoint_tool_activity_generation=0,
                            checkpointed_at=datetime('now','-2 minutes') WHERE id=?""", (turn["id"],))
                    entry["fault"] = "legacy zero observed coverage, checkpoint aged 120 seconds"
                else:
                    note_pre_tool_activity(host, {**payload, "tool_name": "qualification_later_tool", "tool_input": {}})
                    entry["fault"] = "one later tool generation after accepted checkpoint"
            elif ordinal == 2 and case == "recovery-failure":
                note_pre_tool_activity(host, {**payload, "tool_name": "qualification_later_tool", "tool_input": {}})
                entry["fault"] = "recovery deliberately left stale by later tool generation"
        else:
            entry["setup_error"] = "host supplied no registered turn"
    result = subprocess.run([sys.executable, str(Path(__file__).with_name("real_hook.py")), *sys.argv[1:]],
                            input=json.dumps(payload).encode(), capture_output=True)
    entry.update(returncode=result.returncode, stdout=result.stdout.decode(), stderr=result.stderr.decode())
    if event == "Stop" and turn:
        entry["after"] = store.turn(host, session, turn_id)
        entry["graph_after"] = graph_digest(store, project)
        entry["project_active"] = bool(store.project_view(project)["project"]["active"])
    with log.open("a", encoding="utf-8") as output:
        output.write(json.dumps(entry, ensure_ascii=False) + "\n")
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
