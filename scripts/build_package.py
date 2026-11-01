#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
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
TARGET = ROOT / "packages" / "mindmap"
RETIRED_TARGETS = (ROOT / "plugins" / "mindmap", ROOT / "plugins" / "claude" / "mindmap")


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


def remove_retired_packages() -> None:
    for target in RETIRED_TARGETS:
        if target.exists():
            if not (target / ".mindmap-generated").is_file():
                raise RuntimeError(f"Refusing to remove an unmarked directory: {target}")
            safe_remove(target)
    for host in ("codex", "claude"):
        for path in (ROOT / "dist").glob(f"mindmap-{host}-*.zip"):
            path.unlink()


def build_target() -> Path:
    target = TARGET
    if target.exists() and not (target / ".mindmap-generated").is_file():
        raise RuntimeError(f"Refusing to replace an unmarked directory: {target}")
    safe_remove(target)
    (target / "bin").mkdir(parents=True)
    shutil.copytree(
        ROOT / "src" / "mindmap", target / "lib" / "mindmap",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    shutil.copy2(ROOT / "platforms" / "launcher.py", target / "bin" / "mindmap.py")
    shutil.copy2(ROOT / "platforms" / "run_cli.sh", target / "bin" / "mindmap")
    shutil.copy2(ROOT / "LICENSE", target / "LICENSE")
    (target / ".mindmap-generated").write_text(f"standalone {VERSION}\n")
    normalize_tree(target)
    return target


def archive(target: Path) -> Path:
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    for obsolete in dist.glob("mindmap-cli-*.zip"):
        obsolete.unlink()
    output = dist / f"mindmap-cli-{VERSION}.zip"
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
    parser = argparse.ArgumentParser(description="Build the standalone Mindmap Python CLI (agent integration paused)")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    remove_retired_packages()
    if args.clean:
        if TARGET.joinpath(".mindmap-generated").exists():
            safe_remove(TARGET)
        for path in (ROOT / "dist").glob("mindmap-cli-*.zip"):
            path.unlink()
        return 0
    target = build_target()
    output = archive(target)
    print(f"Built standalone CLI: {target}")
    print(f"Packed standalone CLI: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
