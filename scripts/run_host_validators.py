#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRE = os.environ.get("MINDMAP_REQUIRE_HOST_VALIDATORS") == "1"


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True, env=env)


def missing(message: str) -> None:
    if REQUIRE:
        raise SystemExit(message)
    print(f"SKIP: {message}")


def main() -> int:
    ran = 0
    claude = shutil.which("claude")
    if claude:
        run([claude, "plugin", "validate", "--strict", "plugins/claude/mindmap"])
        run([claude, "plugin", "validate", "--strict", "."])
        ran += 1
    else:
        missing("Claude Code CLI is not installed; official Claude validation did not run.")

    codex = shutil.which("codex")
    if codex:
        with tempfile.TemporaryDirectory(prefix="mindmap-codex-validate-") as temporary:
            environment = os.environ.copy()
            environment["CODEX_HOME"] = temporary
            run([codex, "plugin", "marketplace", "add", str(ROOT), "--json"], env=environment)
            run([codex, "plugin", "list", "--available", "--json"], env=environment)
        ran += 1
    else:
        missing("Codex CLI is not installed; Codex marketplace ingestion did not run.")

    validator = Path.home() / ".codex" / "skills" / ".system" / "plugin-creator" / "scripts" / "validate_plugin.py"
    candidates = [ROOT / ".venv" / "bin" / "python", Path(sys.executable)]
    python = next(
        (candidate for candidate in candidates if candidate.is_file() and subprocess.run(
            [str(candidate), "-c", "import yaml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode == 0),
        None,
    )
    if validator.is_file() and python:
        run([str(python), str(validator), "plugins/mindmap"])
        quick_validate = validator.parents[2] / "skill-creator" / "scripts" / "quick_validate.py"
        if quick_validate.is_file():
            run([str(python), str(quick_validate), "core/skills/mindmap"])
        ran += 1
    else:
        print("SKIP: supplemental Codex plugin-creator validator needs its system skill and PyYAML.")

    if ran:
        print(f"Official host validator groups passed: {ran}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
