#!/usr/bin/env python3
"""Run sanitized Mindmap semantic fixtures through Codex and/or Claude Code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from scripts.semantic_eval import SCORER_VERSION, load_fixture, score_fixture
from scripts.test_frontier_handoff import (
    mindmap,
    run,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "semantic"


def package_revision(package_root: Path) -> str:
    completed = run(
        ["git", "rev-parse", "HEAD"],
        cwd=package_root,
        environment=os.environ.copy(),
        timeout=30,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def package_is_dirty(package_root: Path) -> bool | None:
    completed = run(
        ["git", "status", "--porcelain"],
        cwd=package_root,
        environment=os.environ.copy(),
        timeout=30,
    )
    return bool(completed.stdout.strip()) if completed.returncode == 0 else None


def executable_version(executable: str) -> str:
    completed = run(
        [executable, "--version"], cwd=ROOT, environment=os.environ.copy(), timeout=30
    )
    output = (completed.stdout or completed.stderr).strip()
    return output.splitlines()[0] if completed.returncode == 0 and output else "unknown"


def fixture_digest(fixture: dict[str, Any]) -> str:
    encoded = json.dumps(fixture, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def require_package(package_root: Path) -> None:
    comparisons = [
        (
            package_root / "src" / "mindmap" / "store.py",
            package_root / "plugins" / "mindmap" / "lib" / "mindmap" / "store.py",
        ),
        (
            package_root / "src" / "mindmap" / "store.py",
            package_root / "plugins" / "claude" / "mindmap" / "lib" / "mindmap" / "store.py",
        ),
        (
            package_root / "core" / "skills" / "mindmap" / "SKILL.md",
            package_root / "plugins" / "mindmap" / "skills" / "manage" / "SKILL.md",
        ),
    ]
    stale = [
        target
        for source, target in comparisons
        if not source.is_file() or not target.is_file() or source.read_bytes() != target.read_bytes()
    ]
    if stale:
        raise RuntimeError(
            "The selected package is incomplete or stale; run `make package` in that "
            "checkout before the live eval. Mismatches: "
            + ", ".join(str(path) for path in stale)
        )


def prepare_codex_home(
    codex: str,
    environment: dict[str, str],
    temporary_home: Path,
    package_root: Path,
) -> dict[str, str]:
    temporary_home.mkdir(mode=0o700)
    original_home = Path(
        environment.get("CODEX_HOME", str(Path.home() / ".codex"))
    ).expanduser()
    original_auth = original_home / "auth.json"
    isolated = environment.copy()
    isolated["CODEX_HOME"] = str(temporary_home)
    if original_auth.is_file():
        shutil.copy2(original_auth, temporary_home / "auth.json")
        (temporary_home / "auth.json").chmod(0o600)
    elif environment.get("OPENAI_API_KEY"):
        login = run(
            [codex, "login", "--with-api-key"],
            cwd=package_root,
            environment=isolated,
            input_text=environment["OPENAI_API_KEY"],
            timeout=60,
        )
        if login.returncode != 0:
            raise RuntimeError("Could not authenticate the isolated Codex eval home.")
    elif environment.get("CODEX_ACCESS_TOKEN"):
        login = run(
            [codex, "login", "--with-access-token"],
            cwd=package_root,
            environment=isolated,
            input_text=environment["CODEX_ACCESS_TOKEN"],
            timeout=60,
        )
        if login.returncode != 0:
            raise RuntimeError("Could not authenticate the isolated Codex eval home.")
    else:
        raise RuntimeError(
            "Codex must be logged in, or OPENAI_API_KEY/CODEX_ACCESS_TOKEN must be set."
        )
    login = run(
        [codex, "login", "status"], cwd=package_root, environment=isolated, timeout=30
    )
    if login.returncode != 0:
        raise RuntimeError("Codex login was not available inside the isolated eval home.")
    marketplace = run(
        [codex, "plugin", "marketplace", "add", str(package_root), "--json"],
        cwd=package_root,
        environment=isolated,
        timeout=60,
    )
    if marketplace.returncode != 0:
        raise RuntimeError(
            "Could not add the selected checkout as an isolated marketplace:\n"
            + marketplace.stderr
        )
    install = run(
        [codex, "plugin", "add", "mindmap@erd0s-mindmap", "--json"],
        cwd=package_root,
        environment=isolated,
        timeout=60,
    )
    if install.returncode != 0:
        raise RuntimeError(
            "Could not install the selected checkout's Mindmap plugin:\n" + install.stderr
        )
    return isolated


def require_codex_plugin(codex: str, environment: dict[str, str]) -> None:
    listing = run(
        [codex, "plugin", "list", "--json"], cwd=ROOT, environment=environment, timeout=30
    )
    if listing.returncode != 0:
        raise RuntimeError("Could not inspect installed Codex plugins:\n" + listing.stderr)
    plugins = json.loads(listing.stdout).get("installed", [])
    if not any(plugin.get("name") == "mindmap" and plugin.get("enabled") for plugin in plugins):
        raise RuntimeError("The selected Mindmap plugin was not enabled in the isolated Codex home.")


def checkpoint_count(snapshot: dict[str, Any]) -> int:
    return sum(int(session.get("turn_count") or 0) for session in snapshot.get("sessions", []))


def write_project_files(project: Path, fixture: dict[str, Any]) -> None:
    for specification in fixture.get("project_files", []):
        relative = Path(specification["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe fixture project path: {relative}")
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(specification["content"], encoding="utf-8")


def codex_trial(
    executable: str,
    prompt: str,
    *,
    project: Path,
    data: Path,
    environment: dict[str, str],
    model: str | None,
) -> tuple[int, str, str]:
    last_message = project / ".eval-codex-last-message.txt"
    command = [
        executable,
        "exec",
        "--ephemeral",
        "--sandbox",
        "workspace-write",
        "--dangerously-bypass-hook-trust",
        "--cd",
        str(project),
        "--add-dir",
        str(data),
        "--color",
        "never",
        "--output-last-message",
        str(last_message),
    ]
    if model:
        command.extend(["--model", model])
    command.append(prompt)
    completed = run(command, cwd=project, environment=environment)
    final = last_message.read_text(encoding="utf-8") if last_message.exists() else ""
    diagnostics = completed.stdout + completed.stderr
    return completed.returncode, final, diagnostics


def claude_trial(
    executable: str,
    prompt: str,
    *,
    project: Path,
    data: Path,
    environment: dict[str, str],
    model: str | None,
    package_root: Path,
) -> tuple[int, str, str]:
    command = [
        executable,
        "--print",
        "--output-format",
        "json",
        "--no-session-persistence",
        "--dangerously-skip-permissions",
        "--permission-mode",
        "bypassPermissions",
        "--plugin-dir",
        str(package_root / "plugins" / "claude" / "mindmap"),
        "--add-dir",
        str(data),
        "--session-id",
        str(uuid.uuid4()),
    ]
    if model:
        command.extend(["--model", model])
    command.append(prompt)
    completed = run(command, cwd=project, environment=environment)
    final = ""
    diagnostics = completed.stderr
    try:
        payload = json.loads(completed.stdout)
        final = str(payload.get("result") or "")
        diagnostics = json.dumps(
            {
                key: payload.get(key)
                for key in ("subtype", "is_error", "duration_ms", "num_turns", "total_cost_usd")
                if key in payload
            },
            sort_keys=True,
        ) + ("\n" + completed.stderr if completed.stderr else "")
    except json.JSONDecodeError:
        diagnostics = completed.stdout + completed.stderr
    return completed.returncode, final, diagnostics


def run_trial(
    host: str,
    executable: str,
    fixture: dict[str, Any],
    *,
    base_environment: dict[str, str],
    model: str | None,
    trial: int,
    package_root: Path,
    package_label: str,
    package_commit: str,
    package_dirty: bool | None,
    host_version: str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"mindmap-semantic-{host}-{fixture['id']}-{trial}-") as temporary:
        base = Path(temporary)
        home = base / "home"
        project = home / fixture["id"]
        data = base / "mindmap-data"
        project.mkdir(parents=True)
        data.mkdir()
        write_project_files(project, fixture)
        environment = base_environment.copy()
        existing_pythonpath = environment.get("PYTHONPATH")
        environment.update(
            {
                "MINDMAP_HOME_DIR": str(home),
                "MINDMAP_DATA_DIR": str(data),
                "PYTHONPATH": str(package_root / "src")
                + (os.pathsep + existing_pythonpath if existing_pythonpath else ""),
            }
        )
        initialized = run(
            ["git", "init", "--quiet"], cwd=project, environment=environment, timeout=30
        )
        if initialized.returncode != 0:
            raise RuntimeError("could not initialize semantic eval project")
        mindmap(["start", "--root", str(project)], cwd=project, environment=environment)
        mindmap(
            [
                "record",
                "--root",
                str(project),
                "--host",
                "codex",
                "--session-id",
                "fixture-seed",
                "--interaction-id",
                "fixture-seed",
                "--file",
                "-",
            ],
            cwd=project,
            environment=environment,
            payload={
                "summary": f"Seeded semantic fixture {fixture['id']}.",
                "operations": fixture["seed_operations"],
            },
        )
        before = mindmap(
            ["snapshot", "--root", str(project)], cwd=project, environment=environment
        )
        if host == "codex":
            returncode, final, diagnostics = codex_trial(
                executable,
                fixture["prompt"],
                project=project,
                data=data,
                environment=environment,
                model=model,
            )
        else:
            returncode, final, diagnostics = claude_trial(
                executable,
                fixture["prompt"],
                project=project,
                data=data,
                environment=environment,
                model=model,
                package_root=package_root,
            )
        after = mindmap(
            ["snapshot", "--root", str(project)], cwd=project, environment=environment
        )
        score = score_fixture(fixture, before["items"], after["items"])
        checkpointed = checkpoint_count(after) > checkpoint_count(before)
        problems = list(score.problems)
        if returncode != 0:
            problems.append(f"{host} exited {returncode}")
        if not checkpointed:
            problems.append("agent produced no new Mindmap checkpoint")
        return {
            "host": host,
            "host_version": host_version,
            "fixture": fixture["id"],
            "fixture_digest": fixture_digest(fixture),
            "trial": trial,
            "package": package_label,
            "package_commit": package_commit,
            "package_dirty": package_dirty,
            "model": model or "host-default",
            "scorer_version": SCORER_VERSION,
            "passed": not problems,
            "metrics": score.metrics,
            "matched": score.matched,
            "problems": problems,
            "final": final.strip(),
            "diagnostics": diagnostics.strip(),
            "items": after["items"],
            "checkpoint_delta": checkpoint_count(after) - checkpoint_count(before),
        }


def choose_fixtures(names: list[str]) -> list[dict[str, Any]]:
    paths = sorted(FIXTURES.glob("*.json"))
    fixtures = [load_fixture(path) for path in paths]
    if not names:
        return fixtures
    requested = set(names)
    selected = [fixture for fixture in fixtures if fixture["id"] in requested]
    missing = sorted(requested - {fixture["id"] for fixture in selected})
    if missing:
        raise ValueError("unknown semantic fixture(s): " + ", ".join(missing))
    return selected


def summarize(results: list[dict[str, Any]], hosts: tuple[str, ...]) -> dict[str, Any]:
    groups = {"all": results}
    groups.update(
        {host: [result for result in results if result["host"] == host] for host in hosts}
    )
    summary: dict[str, Any] = {}
    for name, group in groups.items():
        metrics: dict[str, dict[str, float]] = {}
        metric_names = sorted(
            {metric for result in group for metric in result.get("metrics", {})}
        )
        for metric in metric_names:
            values = [
                float(result["metrics"][metric])
                for result in group
                if metric in result.get("metrics", {})
            ]
            if values:
                metrics[metric] = {
                    "mean": sum(values) / len(values),
                    "minimum": min(values),
                }
        passed = sum(bool(result.get("passed")) for result in group)
        summary[name] = {
            "passed": passed,
            "trials": len(group),
            "pass_rate": passed / len(group) if group else 0.0,
            "metrics": metrics,
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", choices=("codex", "claude", "both"), default="both")
    parser.add_argument("--fixture", action="append", default=[], help="Fixture id; repeat to select several.")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--codex-model", default=os.environ.get("MINDMAP_SEMANTIC_CODEX_MODEL"))
    parser.add_argument("--claude-model", default=os.environ.get("MINDMAP_SEMANTIC_CLAUDE_MODEL"))
    parser.add_argument(
        "--package-root",
        type=Path,
        default=ROOT,
        help="Mindmap checkout/package to install; fixtures and scorer stay pinned to this harness.",
    )
    parser.add_argument("--label", help="Package label stored with results (default: directory name).")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the complete JSON report to this path while retaining console progress.",
    )
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    package_root = args.package_root.expanduser().resolve()
    package_label = args.label or package_root.name
    require_package(package_root)
    package_commit = package_revision(package_root)
    package_dirty = package_is_dirty(package_root)
    harness_commit = package_revision(ROOT)
    harness_dirty = package_is_dirty(ROOT)
    fixtures = choose_fixtures(args.fixture)
    hosts = ("codex", "claude") if args.host == "both" else (args.host,)
    executables = {host: shutil.which(host) for host in hosts}
    missing = [host for host, executable in executables.items() if not executable]
    if missing:
        raise SystemExit("missing host executable(s): " + ", ".join(missing))
    host_versions = {
        host: executable_version(str(executable)) for host, executable in executables.items()
    }

    environments: dict[str, dict[str, str]] = {}
    codex_temporary: tempfile.TemporaryDirectory[str] | None = None
    try:
        if "codex" in hosts:
            codex_temporary = tempfile.TemporaryDirectory(prefix="mindmap-semantic-codex-home-")
            environments["codex"] = prepare_codex_home(
                str(executables["codex"]),
                os.environ.copy(),
                Path(codex_temporary.name) / "home",
                package_root,
            )
            require_codex_plugin(str(executables["codex"]), environments["codex"])
        if "claude" in hosts:
            environments["claude"] = os.environ.copy()

        results = []
        for fixture in fixtures:
            for host in hosts:
                model = args.codex_model if host == "codex" else args.claude_model
                for trial in range(1, args.runs + 1):
                    if not args.json:
                        print(f"\n=== {host} / {fixture['id']} / trial {trial}/{args.runs} ===", flush=True)
                    try:
                        result = run_trial(
                            host,
                            str(executables[host]),
                            fixture,
                            base_environment=environments[host],
                            model=model,
                            trial=trial,
                            package_root=package_root,
                            package_label=package_label,
                            package_commit=package_commit,
                            package_dirty=package_dirty,
                            host_version=host_versions[host],
                        )
                    except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                        result = {
                            "host": host,
                            "host_version": host_versions[host],
                            "fixture": fixture["id"],
                            "fixture_digest": fixture_digest(fixture),
                            "trial": trial,
                            "package": package_label,
                            "package_commit": package_commit,
                            "package_dirty": package_dirty,
                            "model": model or "host-default",
                            "scorer_version": SCORER_VERSION,
                            "passed": False,
                            "metrics": {},
                            "matched": {},
                            "problems": [str(exc)],
                            "final": "",
                            "diagnostics": "",
                            "items": [],
                            "checkpoint_delta": 0,
                        }
                    results.append(result)
                    if not args.json:
                        print("PASS" if result["passed"] else "FAIL")
                        for problem in result["problems"]:
                            print(f"- {problem}")
                        if result["problems"] and result["items"]:
                            print("Graph:")
                            for item in result["items"]:
                                print(
                                    f"  {item['id']}: parent={item.get('parent_id')!r}, "
                                    f"state={item.get('state')}, resume={item.get('resume')!r}"
                                )
                        if result["final"]:
                            print("Final:", result["final"])
        summary = summarize(results, hosts)
        report = {
            "schema_version": 1,
            "package": package_label,
            "package_root": str(package_root),
            "package_commit": package_commit,
            "package_dirty": package_dirty,
            "harness_commit": harness_commit,
            "harness_dirty": harness_dirty,
            "scorer_version": SCORER_VERSION,
            "summary": summary,
            "results": results,
        }
        if args.output:
            args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            overall = summary["all"]
            print(
                f"\nSemantic evaluation ({package_label} @ {package_commit[:12]}): "
                f"{overall['passed']}/{overall['trials']} trials passed."
            )
            if package_dirty:
                print("- package working tree: dirty (result is not release-reproducible)")
            for host in hosts:
                host_summary = summary[host]
                print(f"- {host}: {host_summary['passed']}/{host_summary['trials']}")
            if args.output:
                print(f"- JSON report: {args.output}")
        return 0 if all(result["passed"] for result in results) else 1
    finally:
        if codex_temporary is not None:
            codex_temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
