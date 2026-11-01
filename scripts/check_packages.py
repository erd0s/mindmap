#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import subprocess
import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"package check failed: {message}")


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    subprocess.run([sys.executable, str(ROOT / "scripts/update_record_limits.py"), "--check"], check=True)
    version_match = re.search(
        r'^version\s*=\s*"([^"]+)"',
        (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    check(bool(version_match), "pyproject version missing")
    version = version_match.group(1)
    check(
        'authors = [{ name = "Dirk Stewart" }]' in (ROOT / "pyproject.toml").read_text(),
        "package author metadata is incorrect",
    )
    check("Copyright (c) 2026 Dirk Stewart" in (ROOT / "LICENSE").read_text(), "license attribution is incorrect")
    check("Copyright © 2026 Dirk Stewart" in (ROOT / "desktop" / "Info.plist").read_text(), "app attribution is incorrect")
    init_match = re.search(
        r'^__version__\s*=\s*"([^"]+)"',
        (ROOT / "src" / "mindmap" / "__init__.py").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    check(bool(init_match) and init_match.group(1) == version, "runtime version differs from pyproject")
    go_bindings = (ROOT / "desktop" / "bindings.go").read_text()
    js_bindings = (
        ROOT / "desktop" / "frontend" / "src" / "bindings" / "github.com" /
        "erd0s" / "mindmap" / "desktop" / "desktopservice.js"
    ).read_text()
    for method, binding_id in re.findall(r'\(\*DesktopService\)\.(\w+),\s*(\d+)', go_bindings):
        check(
            bool(re.search(rf'function {method}\b[\s\S]*?ByID\({binding_id}\b', js_bindings)),
            f"desktop binding ID mismatch for {method}",
        )
    check(
        "function DeleteSubtree(projectID, itemID, confirmed)" in js_bindings,
        "desktop delete binding omits the confirmation token",
    )
    for retired in (
        ".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json",
        "plugins/mindmap", "plugins/claude/mindmap", "plugins/mindmap.manifest.json",
        "platforms/claude/plugin.json", "platforms/hooks.template.json",
    ):
        check(not (ROOT / retired).exists(), f"retired integration path exists: {retired}")
    root = ROOT / "packages" / "mindmap"
    for forbidden in ("hooks", "scripts", "skills", ".codex-plugin", ".claude-plugin"):
        check(not (root / forbidden).exists(), f"standalone package contains {forbidden}")
    for generated, source in (("bin/mindmap", "platforms/run_cli.sh"), ("bin/mindmap.py", "platforms/launcher.py")):
        check(file_digest(root / generated) == file_digest(ROOT / source), f"stale launcher: {generated}")
        check(os.access(root / generated, os.X_OK), f"launcher is not executable: {generated}")
    for source in sorted((ROOT / "src" / "mindmap").rglob("*")):
        if source.is_file() and "__pycache__" not in source.parts and source.suffix not in {".pyc", ".pyo"}:
            generated = root / "lib" / "mindmap" / source.relative_to(ROOT / "src" / "mindmap")
            check(generated.is_file() and file_digest(generated) == file_digest(source), f"stale runtime: {source.name}")
    subprocess.run([str(root / "bin" / "mindmap"), "--help"], check=True, stdout=subprocess.DEVNULL)

    archives = sorted((ROOT / "dist").glob("mindmap-*.zip"))
    check(
        {archive.name for archive in archives}
        == {f"mindmap-cli-{version}.zip"},
        "archive names do not match the canonical version",
    )
    for archive in archives:
        with zipfile.ZipFile(archive) as bundle:
            check("mindmap/LICENSE" in bundle.namelist(), f"{archive.name} omits LICENSE")
            command = bundle.getinfo("mindmap/bin/mindmap")
            check((command.external_attr >> 16) & 0o111, f"{archive.name} command launcher is not executable")
            check(set(bundle.namelist()) == {
                "mindmap/" + path.relative_to(root).as_posix()
                for path in root.rglob("*") if path.is_file()
            }, "archive differs from standalone tree")
            for name in bundle.namelist():
                check(bundle.read(name) == (root / Path(name).relative_to("mindmap")).read_bytes(), f"stale archive entry {name}")
                check(not name.startswith("/") and ".." not in Path(name).parts, f"unsafe zip path {name}")
                check("__pycache__" not in Path(name).parts and not name.endswith((".pyc", ".pyo")), f"bytecode in zip {name}")
    initial_digests = {archive.name: file_digest(archive) for archive in archives}
    subprocess.run([sys.executable, "scripts/build_plugins.py"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    rebuilt_digests = {
        archive.name: file_digest(archive)
        for archive in sorted((ROOT / "dist").glob("mindmap-*.zip"))
    }
    check(initial_digests == rebuilt_digests, "standalone archive is not reproducible")
    print("Standalone package checks passed; no agent packages or marketplaces.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
