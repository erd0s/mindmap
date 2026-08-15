#!/usr/bin/env python3
from __future__ import annotations

import json
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
    source_manifests = [
        ROOT / "plugins" / "mindmap.manifest.json",
        ROOT / "platforms" / "claude" / "plugin.json",
    ]
    for manifest_path in source_manifests:
        check(json.loads(manifest_path.read_text())["version"] == version, f"version mismatch: {manifest_path}")
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    marketplace_plugin = next(plugin for plugin in marketplace["plugins"] if plugin["name"] == "mindmap")
    check(marketplace_plugin["version"] == version, "Claude marketplace version mismatch")
    check(marketplace["name"] == "erd0s-mindmap", "public marketplace name mismatch")
    frontier_script = (ROOT / "scripts" / "test_frontier_handoff.py").read_text()
    check("mindmap@erd0s-mindmap" in frontier_script, "frontier test uses a stale marketplace ID")
    check("mindmap@personal" not in frontier_script, "frontier test still uses the private marketplace")
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
    codex_agent_config = (
        ROOT / "core" / "skills" / "mindmap" / "agents" / "openai.yaml"
    ).read_text()
    default_match = re.search(r'^\s*default_prompt:\s*["\']([^"\']+)["\']\s*$', codex_agent_config, re.MULTILINE)
    check(
        bool(default_match) and default_match.group(1) == "$mindmap:manage start",
        "Codex skill default must be an exact executable action",
    )

    for host, manifest_dir in (("codex", ".codex-plugin"), ("claude", ".claude-plugin")):
        root = ROOT / "plugins" / ("mindmap" if host == "codex" else "claude/mindmap")
        manifest_path = root / manifest_dir / "plugin.json"
        manifest = json.loads(manifest_path.read_text())
        check(manifest["name"] == "mindmap", f"{host} manifest name")
        check(manifest["version"] == version, f"{host} generated version")
        check((root / "hooks" / "hooks.json").is_file(), f"{host} hooks")
        check((root / "scripts" / "run_hook.sh").is_file(), f"{host} hook launcher")
        check(os.access(root / "scripts" / "run_hook.sh", os.X_OK), f"{host} hook launcher is executable")
        check((root / "skills" / "manage" / "SKILL.md").is_file(), f"{host} skill")
        check((root / "bin" / "mindmap").is_file(), f"{host} launcher")
        check((root / "bin" / "mindmap.py").is_file(), f"{host} Python command entrypoint")
        check(
            file_digest(root / "scripts" / "run_hook.sh") == file_digest(ROOT / "platforms" / "run_hook.sh"),
            f"stale {host} hook launcher",
        )
        check(
            file_digest(root / "bin" / "mindmap") == file_digest(ROOT / "platforms" / "run_hook.sh"),
            f"stale {host} command launcher",
        )
        check(
            file_digest(root / "bin" / "mindmap.py") == file_digest(ROOT / "platforms" / "launcher.py"),
            f"stale {host} Python command entrypoint",
        )
        check((root / "LICENSE").is_file(), f"{host} license")
        check(not any(root.rglob("*.pyc")), f"{host} contains Python bytecode")
        check(not any(path.name == "__pycache__" for path in root.rglob("__pycache__")), f"{host} contains cache directories")
        skill = (root / "skills" / "manage" / "SKILL.md").read_text()
        check("[TODO" not in skill, f"{host} has TODO placeholder")
        check(("disable-model-invocation: true" in skill) == (host == "claude"), f"{host} invocation policy")
        for source in sorted((ROOT / "src" / "mindmap").rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts and source.suffix not in {".pyc", ".pyo"}:
                generated = root / "lib" / "mindmap" / source.relative_to(ROOT / "src" / "mindmap")
                check(generated.is_file() and file_digest(generated) == file_digest(source), f"stale {host} runtime: {source.name}")
        hooks = json.loads((root / "hooks" / "hooks.json").read_text())
        commands = [handler["command"] for groups in hooks["hooks"].values() for group in groups for handler in group["hooks"]]
        check(all(f"--host {host}" in command for command in commands), f"{host} hook adapter")
        check(all("scripts/run_hook.sh" in command for command in commands), f"{host} GUI-safe hook launcher")
        check(all(not command.startswith("python3 ") for command in commands), f"{host} hook must not depend on the host PATH")
        subprocess.run([str(root / "bin" / "mindmap"), "--help"], check=True, stdout=subprocess.DEVNULL)

    archives = sorted((ROOT / "dist").glob("mindmap-*.zip"))
    check(
        {archive.name for archive in archives}
        == {f"mindmap-codex-{version}.zip", f"mindmap-claude-{version}.zip"},
        "archive names do not match the canonical version",
    )
    for archive in archives:
        with zipfile.ZipFile(archive) as bundle:
            check("mindmap/LICENSE" in bundle.namelist(), f"{archive.name} omits LICENSE")
            launcher = bundle.getinfo("mindmap/scripts/run_hook.sh")
            check((launcher.external_attr >> 16) & 0o111, f"{archive.name} hook launcher is not executable")
            command = bundle.getinfo("mindmap/bin/mindmap")
            check((command.external_attr >> 16) & 0o111, f"{archive.name} command launcher is not executable")
            for name in bundle.namelist():
                check(not name.startswith("/") and ".." not in Path(name).parts, f"unsafe zip path {name}")
                check("__pycache__" not in Path(name).parts and not name.endswith((".pyc", ".pyo")), f"bytecode in zip {name}")
    initial_digests = {archive.name: file_digest(archive) for archive in archives}
    subprocess.run([sys.executable, "scripts/build_plugins.py"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    rebuilt_digests = {
        archive.name: file_digest(archive)
        for archive in sorted((ROOT / "dist").glob("mindmap-*.zip"))
    }
    check(initial_digests == rebuilt_digests, "plugin archives are not reproducible")
    print("Package checks passed for Codex and Claude Code.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
