#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import stat
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_MATCH = re.search(
    r'^version\s*=\s*"([^"]+)"',
    (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
    re.MULTILINE,
)
if not VERSION_MATCH:
    raise RuntimeError("pyproject.toml does not declare a project version")
VERSION = VERSION_MATCH.group(1)
BUILD_EPOCH = min(
    4354819198,
    max(315532800, int(os.environ.get("SOURCE_DATE_EPOCH", "315532800"))),
)
TARGETS = {
    "codex": ROOT / "plugins" / "mindmap",
    "claude": ROOT / "plugins" / "claude" / "mindmap",
}


def safe_remove(path: Path) -> None:
    resolved = path.resolve()
    if ROOT.resolve() not in resolved.parents:
        raise RuntimeError(f"Refusing to remove path outside repository: {resolved}")
    if path.exists():
        # Generated runtime package directories are made read-only below to stop
        # hosts that import them directly from polluting the release tree.
        for directory in sorted(
            (candidate for candidate in path.rglob("*") if candidate.is_dir()),
            reverse=True,
        ):
            directory.chmod(0o755)
        path.chmod(0o755)
        shutil.rmtree(path)


def claude_skill(source: str) -> str:
    marker = "---\n"
    if not source.startswith(marker):
        raise RuntimeError("Shared skill is missing YAML frontmatter")
    end = source.find(marker, len(marker))
    if end == -1:
        raise RuntimeError("Shared skill frontmatter is not closed")
    frontmatter = source[len(marker):end]
    additions = 'argument-hint: "start | sync | status | stop"\ndisable-model-invocation: true\n'
    return marker + frontmatter + additions + marker + source[end + len(marker):]


def copy_runtime(target: Path) -> None:
    shutil.copytree(
        ROOT / "src" / "mindmap",
        target / "lib" / "mindmap",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    shutil.copy2(ROOT / "platforms" / "hook.py", target / "scripts" / "hook.py")
    shutil.copy2(ROOT / "platforms" / "run_hook.sh", target / "scripts" / "run_hook.sh")
    shutil.copy2(ROOT / "platforms" / "launcher.py", target / "bin" / "mindmap.py")
    shutil.copy2(ROOT / "platforms" / "run_hook.sh", target / "bin" / "mindmap")
    for executable in (
        target / "scripts" / "hook.py",
        target / "scripts" / "run_hook.sh",
        target / "bin" / "mindmap",
    ):
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def normalize_tree(target: Path) -> None:
    for path in sorted(target.rglob("*"), reverse=True):
        if path.is_dir():
            path.chmod(0o755)
        elif path.parent.name in {"bin", "scripts"}:
            path.chmod(0o755)
        else:
            path.chmod(0o644)
        os.utime(path, (BUILD_EPOCH, BUILD_EPOCH), follow_symlinks=False)
    target.chmod(0o755)
    os.utime(target, (BUILD_EPOCH, BUILD_EPOCH), follow_symlinks=False)
    # Python can write __init__.pyc before package-level code has a chance to set
    # dont_write_bytecode. The generated tree is immutable, so prevent cache
    # directory creation even when a host/validator bypasses our launchers.
    runtime_package = target / "lib" / "mindmap"
    runtime_package.chmod(0o555)


def build_target(host: str) -> Path:
    target = TARGETS[host]
    safe_remove(target)
    (target / ".codex-plugin" if host == "codex" else target / ".claude-plugin").mkdir(parents=True)
    (target / "skills" / "manage").mkdir(parents=True)
    (target / "hooks").mkdir()
    (target / "scripts").mkdir()
    (target / "bin").mkdir()
    (target / "assets").mkdir()

    if host == "codex":
        manifest = json.loads((ROOT / "plugins" / "mindmap.manifest.json").read_text())
        manifest_path = target / ".codex-plugin" / "plugin.json"
    else:
        manifest = json.loads((ROOT / "platforms" / "claude" / "plugin.json").read_text())
        manifest_path = target / ".claude-plugin" / "plugin.json"
    manifest["version"] = VERSION
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    shared_skill = (ROOT / "core" / "skills" / "mindmap" / "SKILL.md").read_text()
    skill_target = target / "skills" / "manage"
    skill_target.joinpath("SKILL.md").write_text(shared_skill if host == "codex" else claude_skill(shared_skill))
    shutil.copytree(ROOT / "core" / "skills" / "mindmap" / "references", skill_target / "references")
    shutil.copytree(ROOT / "core" / "skills" / "mindmap" / "assets", skill_target / "assets")
    if host == "codex":
        shutil.copytree(ROOT / "core" / "skills" / "mindmap" / "agents", skill_target / "agents")

    hooks = (ROOT / "platforms" / "hooks.template.json").read_text().replace("__HOST__", host)
    target.joinpath("hooks", "hooks.json").write_text(hooks)
    shutil.copy2(ROOT / "core" / "skills" / "mindmap" / "assets" / "icon.svg", target / "assets" / "icon.svg")
    shutil.copy2(ROOT / "LICENSE", target / "LICENSE")
    copy_runtime(target)
    target.joinpath(".mindmap-generated").write_text(f"{host} {VERSION}\n")
    normalize_tree(target)
    return target


def archive(host: str, target: Path) -> Path:
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    for obsolete in dist.glob(f"mindmap-{host}-*.zip"):
        obsolete.unlink()
    output = dist / f"mindmap-{host}-{VERSION}.zip"
    zip_time = datetime.datetime.fromtimestamp(BUILD_EPOCH, datetime.timezone.utc).timetuple()[:6]
    with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as bundle:
        for path in sorted(target.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
                archive_name = (Path("mindmap") / path.relative_to(target)).as_posix()
                info = zipfile.ZipInfo(archive_name, date_time=zip_time)
                # Stored entries are byte-for-byte reproducible across Python/zlib versions.
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = (stat.S_IMODE(path.stat().st_mode) & 0xFFFF) << 16
                bundle.writestr(info, path.read_bytes())
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Codex and Claude Code Mindmap plugins")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    if args.clean:
        for target in TARGETS.values():
            if target.joinpath(".mindmap-generated").exists():
                safe_remove(target)
        if (ROOT / "dist").exists():
            safe_remove(ROOT / "dist")
        return 0
    for host in TARGETS:
        target = build_target(host)
        output = archive(host, target)
        print(f"Built {host}: {target}")
        print(f"Packed {host}: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
