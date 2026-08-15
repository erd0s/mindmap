#!/usr/bin/env python3
"""Opt-in live-agent eval for causal frontier handoff across fresh sessions."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "frontier-handoff.json"


def run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    input_text: str | None = None,
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def prepare_codex_home(
    codex: str, environment: dict[str, str], temporary_home: Path
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
            cwd=ROOT,
            environment=isolated,
            input_text=environment["OPENAI_API_KEY"],
            timeout=60,
        )
        if login.returncode != 0:
            raise RuntimeError("Could not authenticate the isolated Codex eval home.")
    elif environment.get("CODEX_ACCESS_TOKEN"):
        login = run(
            [codex, "login", "--with-access-token"],
            cwd=ROOT,
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

    login = run([codex, "login", "status"], cwd=ROOT, environment=isolated, timeout=30)
    if login.returncode != 0:
        raise RuntimeError("Codex login was not available inside the isolated eval home.")
    marketplace = run(
        [codex, "plugin", "marketplace", "add", str(ROOT), "--json"],
        cwd=ROOT,
        environment=isolated,
        timeout=60,
    )
    if marketplace.returncode != 0:
        raise RuntimeError(
            "Could not add the checkout as an isolated marketplace:\n"
            + marketplace.stderr
        )
    install = run(
        [codex, "plugin", "add", "mindmap@erd0s-mindmap", "--json"],
        cwd=ROOT,
        environment=isolated,
        timeout=60,
    )
    if install.returncode != 0:
        raise RuntimeError(
            "Could not install the checkout's Mindmap plugin:\n" + install.stderr
        )
    return isolated


def require_current_package() -> None:
    comparisons = [
        (
            ROOT / "src" / "mindmap" / "store.py",
            ROOT / "plugins" / "mindmap" / "lib" / "mindmap" / "store.py",
        ),
        (
            ROOT / "core" / "skills" / "mindmap" / "SKILL.md",
            ROOT / "plugins" / "mindmap" / "skills" / "manage" / "SKILL.md",
        ),
    ]
    stale = [
        target
        for source, target in comparisons
        if not target.is_file() or source.read_bytes() != target.read_bytes()
    ]
    if stale:
        raise RuntimeError(
            "The generated Codex plugin is stale; run `make package` before the live eval."
        )


def require_codex_plugin(codex: str, environment: dict[str, str]) -> None:
    login = run([codex, "login", "status"], cwd=ROOT, environment=environment, timeout=30)
    if login.returncode != 0:
        raise RuntimeError("Codex must be logged in before running the live frontier eval.")
    listing = run(
        [codex, "plugin", "list", "--json"],
        cwd=ROOT,
        environment=environment,
        timeout=30,
    )
    if listing.returncode != 0:
        raise RuntimeError("Could not inspect installed Codex plugins:\n" + listing.stderr)
    plugins = json.loads(listing.stdout).get("installed", [])
    if not any(plugin.get("name") == "mindmap" and plugin.get("enabled") for plugin in plugins):
        raise RuntimeError(
            "The checkout's Mindmap plugin was not enabled in the isolated Codex home."
        )


def mindmap(
    arguments: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = run(
        [sys.executable, "-m", "mindmap", *arguments],
        cwd=cwd,
        environment=environment,
        input_text=json.dumps(payload) if payload is not None else None,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"mindmap {' '.join(arguments)} failed:\n{result.stdout}{result.stderr}"
        )
    return json.loads(result.stdout)


def graph_lines(items: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"  {item['id']}: parent={item['parent_id']!r}, state={item['state']}, title={item['title']}"
        for item in items
    )


def run_trial(
    codex: str,
    fixture: dict[str, Any],
    *,
    base_environment: dict[str, str],
    model: str | None,
    trial: int,
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix=f"mindmap-frontier-{trial}-") as temporary:
        base = Path(temporary)
        home = base / "home"
        project = home / "frontier-eval"
        data = base / "mindmap-data"
        project.mkdir(parents=True)
        data.mkdir()
        (project / "README.md").write_text(
            "# Webhook delivery\n\nA disposable project for the Mindmap frontier handoff eval.\n",
            encoding="utf-8",
        )

        environment = base_environment.copy()
        existing_pythonpath = environment.get("PYTHONPATH")
        environment.update(
            {
                "MINDMAP_HOME_DIR": str(home),
                "MINDMAP_DATA_DIR": str(data),
                "PYTHONPATH": str(ROOT / "src")
                + (os.pathsep + existing_pythonpath if existing_pythonpath else ""),
            }
        )
        git = run(
            ["git", "init", "--quiet"], cwd=project, environment=environment, timeout=30
        )
        if git.returncode != 0:
            raise RuntimeError("Could not initialize the disposable Git project:\n" + git.stderr)

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
                "summary": "Seeded a graph with one target frontier and one plausible decoy.",
                "operations": fixture["nodes"],
            },
        )

        last_message = project / ".eval-last-message.txt"
        command = [
            codex,
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
        command.append(fixture["prompt"])
        agent = run(command, cwd=project, environment=environment)
        final_message = (
            last_message.read_text(encoding="utf-8") if last_message.exists() else ""
        )
        if agent.returncode != 0:
            return False, (
                f"Codex exited {agent.returncode}.\nSTDOUT:\n{agent.stdout}\n"
                f"STDERR:\n{agent.stderr}\nFINAL:\n{final_message}"
            )

        snapshot = mindmap(
            ["snapshot", "--root", str(project)], cwd=project, environment=environment
        )
        items = snapshot["items"]
        by_id = {item["id"]: item for item in items}
        seed_parents = {node["id"]: node["parent_id"] for node in fixture["nodes"]}
        seeded = set(seed_parents)
        new_items = [item for item in items if item["id"] not in seeded]
        target_children = [
            item for item in new_items if item["parent_id"] == fixture["target_id"]
        ]
        target_descendant_ids = {fixture["target_id"]}
        changed = True
        while changed:
            changed = False
            for item in new_items:
                if (
                    item["id"] not in target_descendant_ids
                    and item["parent_id"] in target_descendant_ids
                ):
                    target_descendant_ids.add(item["id"])
                    changed = True
        target_descendants = [
            item for item in new_items if item["id"] in target_descendant_ids
        ]
        misparented = [
            item for item in new_items if item["id"] not in target_descendant_ids
        ]
        new_roots = [item for item in new_items if item["parent_id"] is None]
        decoy_children = [
            item for item in new_items if item["parent_id"] == fixture["decoy_id"]
        ]
        missing_seeded = sorted(seeded - set(by_id))
        moved_seeded = sorted(
            item_id
            for item_id, parent_id in seed_parents.items()
            if item_id in by_id and by_id[item_id]["parent_id"] != parent_id
        )
        searchable = " ".join(
            str(item.get(field) or "")
            for item in target_descendants
            for field in ("title", "summary", "resume")
        ).lower()
        missing_terms = [
            term for term in fixture["expected_terms"] if term not in searchable
        ]
        note = project / "RETRY_POLICY.md"
        problems = []
        if not target_children:
            problems.append(
                f"no new concept was parented to [{fixture['target_id']}]"
            )
        if new_roots:
            problems.append("new concepts were incorrectly attached as roots")
        if decoy_children:
            problems.append(
                f"new concepts were incorrectly attached to decoy [{fixture['decoy_id']}]"
            )
        if misparented and not new_roots and not decoy_children:
            problems.append(
                "new concepts escaped the target frontier subtree: "
                + ", ".join(item["id"] for item in misparented)
            )
        if missing_seeded:
            problems.append("seed concepts were removed: " + ", ".join(missing_seeded))
        if moved_seeded:
            problems.append("seed concepts were reparented: " + ", ".join(moved_seeded))
        if target_descendants and missing_terms:
            problems.append(
                "the target subtree did not preserve expected semantics: "
                + ", ".join(missing_terms)
            )
        if not note.is_file() or "decorrelated jitter" not in note.read_text(
            encoding="utf-8"
        ).lower():
            problems.append("Codex did not complete the RETRY_POLICY.md task")

        report = (
            f"Final agent message:\n{final_message.strip()}\n\n"
            f"Resulting graph:\n{graph_lines(items)}"
        )
        if problems:
            return (
                False,
                "\n".join(f"- {problem}" for problem in problems)
                + "\n\n"
                + report,
            )
        return True, report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a live Codex eval of fresh-session Mindmap frontier parentage."
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=int(os.environ.get("MINDMAP_FRONTIER_EVAL_RUNS", "1")),
        help="Number of isolated fresh-session trials (default: 1).",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("MINDMAP_FRONTIER_EVAL_MODEL"),
        help="Optional exact Codex model override.",
    )
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    codex = shutil.which("codex")
    if not codex:
        raise SystemExit("Codex CLI is not installed; the live frontier eval cannot run.")
    try:
        require_current_package()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    passed = 0
    with tempfile.TemporaryDirectory(prefix="mindmap-frontier-codex-") as codex_temporary:
        try:
            environment = prepare_codex_home(
                codex, os.environ.copy(), Path(codex_temporary) / "home"
            )
            require_codex_plugin(codex, environment)
        except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            raise SystemExit(str(exc)) from exc

        for trial in range(1, args.runs + 1):
            print(f"\n=== frontier handoff trial {trial}/{args.runs} ===", flush=True)
            try:
                success, report = run_trial(
                    codex,
                    fixture,
                    base_environment=environment,
                    model=args.model,
                    trial=trial,
                )
            except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                success, report = False, str(exc)
            print(report)
            print("PASS" if success else "FAIL", flush=True)
            passed += int(success)

    print(f"\nFrontier handoff: {passed}/{args.runs} trials passed.")
    return 0 if passed == args.runs else 1


if __name__ == "__main__":
    raise SystemExit(main())
