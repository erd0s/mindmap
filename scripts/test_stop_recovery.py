#!/usr/bin/env python3
"""Opt-in real-host, autonomous recovery qualification in disposable stores.

Controlled faults create missing/stale/legacy checkpoints at the host's first
Stop. The host and model must consume the candidate's own Stop response, obtain
a new prepared request and finish. This measures recovery, not natural fault
incidence. Nothing is installed into the user's live host or map directories.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import shlex
import sqlite3
import tempfile
from pathlib import Path

from scripts.run_semantic_evals import (ROOT, claude_trial, codex_trial, executable_version,
    mindmap, prepare_codex_home, require_package, run)
from scripts.stop_recovery_probe import MARKER_COMMAND, real_tool_problems


CASES = ("missing", "later-tool", "actual-later-tool", "legacy-age", "explicit-stop", "recovery-failure")


def qualify(host, case, trial, package, base_environment, model):
    with tempfile.TemporaryDirectory(prefix=f"mindmap-stop-{host}-{case}-") as temporary:
        base = Path(temporary).resolve()
        home, data = base / "home", base / "data"
        project = home / "synthetic"
        project.mkdir(parents=True)
        data.mkdir()
        log = base / "hooks.jsonl"
        diagnostic = base / "diagnostics.jsonl"
        env = {**base_environment, "MINDMAP_HOME_DIR": str(home), "MINDMAP_DATA_DIR": str(data),
               "MINDMAP_TRACKING": "on", "MINDMAP_RECOVERY_PROBE_LOG": str(log),
               "MINDMAP_RECOVERY_PROBE_CASE": case, "MINDMAP_DIAGNOSTICS_PATH": str(diagnostic),
               "PYTHONPATH": str(package / "src")}
        run(["git", "init", "--quiet"], cwd=project, environment=env, timeout=30)
        mindmap(["start", "--root", str(project)], cwd=project, environment=env)
        mindmap(["record", "--root", str(project), "--host", host, "--session-id", "seed",
                 "--interaction-id", "seed", "--file", "-"], cwd=project, environment=env,
                payload={"summary": "Seed recovery fixture.", "operations": [
                    {"op": "upsert", "id": "recovery-goal", "title": "Qualify checkpoint recovery",
                     "summary": "Isolated test only; accepted graph writes must survive recovery.",
                     "resume": "Continue qualification when requested.", "state": "open"}]})
        prompt = ("Planning update only: qualification remains open. Do not edit project files. "
                  "There are no map changes. Respond briefly after completing the required checkpoint.")
        if case == 'explicit-stop':
            # Lifecycle actions intentionally require an exact invocation.
            prompt = '$mindmap:manage stop' if host == 'codex' else '/mindmap:manage stop'
        if case == 'actual-later-tool':
            prompt = ("This is an isolated checkpoint recovery test. No map changes or project edits are needed. "
                      "Prepare and commit an empty Mindmap checkpoint. After that successful commit, run "
                      + MARKER_COMMAND + " as a separate shell tool call; that disposable marker is the only allowed file write. Then respond briefly. "
                      "For this test, do not prepare another checkpoint until the Stop hook asks you to recover. "
                      "When it does ask, follow its recovery instructions and finish normally.")
        executable = shutil.which(host)
        if host == "codex":
            code, final, diagnostics = codex_trial(executable, prompt, project=project, data=data, environment=env, model=model)
        else:
            code, final, diagnostics = claude_trial(executable, prompt, project=project, data=data, environment=env,
                                                   model=model, package_root=package)
        snapshot = mindmap(["snapshot", "--root", str(project)], cwd=project, environment=env)
        events = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        stops = [e for e in events if e["event"] == "Stop"]
        with sqlite3.connect(data / 'mindmap.sqlite3') as db:
            db.row_factory = sqlite3.Row
            requests = [dict(row) for row in db.execute('SELECT token, supersedes, checkpoint_token, turn_id FROM record_requests')]
            commands = [row[0] for row in db.execute('SELECT command FROM context_bindings')]
        for command in commands:
            # Only files registered by this disposable database are removed.
            Path(shlex.split(command)[1]).unlink(missing_ok=True)
        blocks = [e for e in stops if e["stdout"] and json.loads(e["stdout"]).get("decision") == "block"]
        problems = []
        if case == 'actual-later-tool':
            marker = project / '.qualification-later-tool'
            problems.extend(real_tool_problems(events, marker.read_text() if marker.exists() else None))
        if code != 0:
            problems.append(f"host exited {code}")
        if len(stops) != 2 or len(blocks) != 1:
            problems.append(f"expected two Stops and one recovery block; got {len(stops)} / {len(blocks)}")
        for event in events:
            if event.get("adapter_host") != host:
                problems.append("host loaded the wrong package adapter")
            if event.get("setup_error"):
                problems.append(event["setup_error"])
            if event["returncode"] or event["stderr"]:
                problems.append(f"{event['event']} hook error: {event['stderr']}")
        if len(stops) == 2:
            first, last = stops
            if not last["payload"].get("stop_hook_active"):
                problems.append("host did not mark recovery Stop active")
            if any(len(s["stdout"].encode()) > 2048 for s in stops):
                problems.append("Stop exceeded its byte budget")
            if any('PARTIAL MAP:' in s["stdout"] or 'Qualify checkpoint recovery' in s["stdout"] for s in stops):
                problems.append("Stop unexpectedly included map content")
            if first.get("graph_before") != last.get("graph_after"):
                problems.append("empty recovery changed accepted graph writes")
            checkpointed = bool(last.get("after", {}).get("checkpointed_at"))
            if checkpointed != (case != "recovery-failure"):
                problems.append("final checkpoint freshness did not match expected outcome")
            if last.get("project_active") != (case != "explicit-stop"):
                problems.append("tracking activation did not match expected outcome")
            recovered_token = last.get("before", {}).get("checkpoint_token")
            if not recovered_token or recovered_token == first.get("before", {}).get("checkpoint_token"):
                problems.append("recovery did not create a fresh checkpoint receipt")
            if not any(r['checkpoint_token'] == recovered_token and r['supersedes'] is None for r in requests):
                problems.append("recovery did not use a fresh preparation without supersedes")
            if not last.get('after', {}).get('last_assistant_message') or last['after']['last_assistant_message'] != last['payload'].get('last_assistant_message'):
                problems.append("final response was not retained")
            unresolved = sum(s.get('unresolved_checkpoint_count', 0) for s in snapshot['sessions'])
            if unresolved != int(case == 'recovery-failure'):
                problems.append("unresolved checkpoint count is inaccurate")
        return {"host": host, "host_version": executable_version(executable), "model": model,
                "case": case, "trial": trial, "passed": not problems, "problems": problems,
                "final": final, "diagnostics": diagnostics, "hooks": events, "snapshot": snapshot, "requests": requests,
                "delivery_evidence": [json.loads(line) for line in diagnostic.read_text().splitlines()] if diagnostic.exists() else [],
                "recovery_seconds": stops[-1]["time"] - stops[0]["time"] if len(stops) > 1 else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("codex", "claude", "both"), default="both")
    parser.add_argument("--case", action="append", choices=CASES)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--codex-model", default="gpt-6-astra")
    parser.add_argument("--claude-model", default="fable[1m]")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.trials < 1:
        parser.error('--trials must be at least 1')
    require_package(ROOT)
    report = {"schema_version": 1, "purpose": "controlled fault recovery, not natural incidence", "inputs": {},
              "harness": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                          ('scripts/test_stop_recovery.py', 'scripts/stop_recovery_probe.py')}, "results": []}
    for folder in ("src/mindmap", "plugins/mindmap", "plugins/claude/mindmap"):
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                report["inputs"][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('.agents/plugins/marketplace.json', '.claude-plugin/marketplace.json'):
        report['inputs'][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.parent.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix="mindmap-stop-package-") as temporary:
        package = Path(temporary) / "package"
        package.mkdir()
        for folder in ("src", "plugins", ".agents", ".claude-plugin"):
            shutil.copytree(ROOT / folder, package / folder, ignore=shutil.ignore_patterns("__pycache__"))
        for relative in ("plugins/mindmap", "plugins/claude/mindmap"):
            hook = package / relative / "scripts/hook.py"
            hook.rename(hook.with_name("real_hook.py"))
            shutil.copyfile(ROOT / "scripts/stop_recovery_probe.py", hook)
        hosts = ("codex", "claude") if args.host == "both" else (args.host,)
        environments = {host: os.environ.copy() for host in hosts}
        if "codex" in hosts:
            environments["codex"] = prepare_codex_home(shutil.which("codex"), os.environ.copy(), Path(temporary) / "codex-home", package)
        for host in hosts:
            for case in args.case or CASES:
                for trial in range(1, args.trials + 1):
                    result = qualify(host, case, trial, package, environments[host], args.codex_model if host == "codex" else args.claude_model)
                    report["results"].append(result)
                    args.output.write_text(json.dumps(report, indent=2) + "\n")
                    args.output.chmod(0o600)
                    print(f"{host} {case} {trial}: {'PASS' if result['passed'] else result['problems']}", flush=True)
    return 0 if all(result["passed"] for result in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
