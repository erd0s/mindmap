#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "THIRD_PARTY_NOTICES.txt"
LICENSE_NAMES = ("license", "licence", "copying", "notice")
TUI_TARGETS = (
    ("darwin", "amd64"),
    ("darwin", "arm64"),
    ("freebsd", "amd64"),
    ("freebsd", "arm64"),
    ("linux", "386"),
    ("linux", "amd64"),
    ("linux", "arm"),
    ("linux", "arm64"),
    ("linux", "loong64"),
    ("linux", "ppc64le"),
    ("linux", "riscv64"),
    ("linux", "s390x"),
    ("openbsd", "amd64"),
    ("openbsd", "arm64"),
    ("windows", "386"),
    ("windows", "amd64"),
    ("windows", "arm64"),
)


def command_json(command: list[str], cwd: Path) -> object:
    output = subprocess.check_output(command, cwd=cwd, text=True)
    return json.loads(output)


def json_stream(
    command: list[str], cwd: Path, env: dict[str, str] | None = None
) -> list[dict[str, object]]:
    process_env = None if env is None else {**os.environ, **env}
    output = subprocess.check_output(command, cwd=cwd, env=process_env, text=True)
    decoder = json.JSONDecoder()
    values: list[dict[str, object]] = []
    offset = 0
    while offset < len(output):
        while offset < len(output) and output[offset].isspace():
            offset += 1
        if offset >= len(output):
            break
        value, offset = decoder.raw_decode(output, offset)
        values.append(value)
    return values


def license_file(directory: Path) -> Path | None:
    candidates = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.name.lower().startswith(LICENSE_NAMES)
    )
    return candidates[0] if candidates else None


def module_directory(module: dict[str, object], module_root: Path) -> Path:
    if module.get("Dir"):
        return Path(str(module["Dir"]))

    name = str(module["Path"])
    version = str(module.get("Version", ""))
    if not version:
        raise RuntimeError(f"Go module {name} has no source directory or version")

    downloaded = command_json(
        ["go", "mod", "download", "-json", f"{name}@{version}"], module_root
    )
    if not isinstance(downloaded, dict):
        raise RuntimeError(f"Could not inspect downloaded Go module {name} {version}")
    if downloaded.get("Error"):
        raise RuntimeError(
            f"Could not download Go module {name} {version}: {downloaded['Error']}"
        )
    if not downloaded.get("Dir"):
        raise RuntimeError(f"Downloaded Go module {name} {version} has no source directory")
    return Path(str(downloaded["Dir"]))


def compiled_go_modules() -> list[tuple[dict[str, object], Path]]:
    modules: dict[str, tuple[dict[str, object], Path]] = {}

    def add_packages(
        command: list[str], module_root: Path, env: dict[str, str]
    ) -> None:
        for package in json_stream(command, module_root, env):
            module = package.get("Module")
            if not isinstance(module, dict):
                continue
            name = str(module.get("Path", ""))
            if module.get("Main") or name == "github.com/erd0s/mindmap":
                continue
            modules.setdefault(name, (module, module_root))

    for goos, goarch in TUI_TARGETS:
        env = {"CGO_ENABLED": "0", "GOOS": goos, "GOARCH": goarch}
        if (goos, goarch) == ("linux", "arm"):
            env["GOARM"] = "7"
        add_packages(
            ["go", "list", "-mod=readonly", "-deps", "-json", "./cmd/mindmap"],
            ROOT,
            env,
        )

    for goarch in ("amd64", "arm64"):
        add_packages(
            [
                "go",
                "list",
                "-mod=readonly",
                "-deps",
                "-json",
                "-tags",
                "production",
                ".",
            ],
            ROOT / "desktop",
            {
                "CGO_ENABLED": "1",
                "GOOS": "darwin",
                "GOARCH": goarch,
                "MACOSX_DEPLOYMENT_TARGET": "12.0",
            },
        )

    return [modules[name] for name in sorted(modules)]


def collect() -> list[tuple[str, str]]:
    packages: dict[str, tuple[str, str]] = {}
    go_licenses: dict[str, str] = {}
    for module, module_root in compiled_go_modules():
        name = str(module["Path"])
        version = str(module.get("Version", "unknown"))
        source = license_file(module_directory(module, module_root))
        if source is None:
            raise RuntimeError(f"No license file found for Go module {name} {version}")
        text = source.read_text(encoding="utf-8", errors="replace").strip()
        packages[f"Go module {name} {version}"] = (text, source.name)
        go_licenses[name] = text

    frontend = ROOT / "desktop" / "frontend"
    npm_packages = command_json(["npm", "query", "*", "--json"], frontend)
    assert isinstance(npm_packages, list)
    for package in npm_packages:
        if not package.get("location") or package.get("dev") is True:
            continue
        name = str(package["name"])
        version = str(package["version"])
        source = license_file(frontend / str(package["location"]))
        if source is not None:
            text = source.read_text(encoding="utf-8", errors="replace").strip()
            source_name = source.name
        elif name == "@wailsio/runtime" and "github.com/wailsapp/wails/v3" in go_licenses:
            text = go_licenses["github.com/wailsapp/wails/v3"]
            source_name = "LICENSE (from the Wails v3 source module)"
        else:
            raise RuntimeError(f"No license file found for npm package {name} {version}")
        packages[f"npm package {name} {version}"] = (text, source_name)
    return [(name, values[0]) for name, values in sorted(packages.items())]


def render(packages: list[tuple[str, str]]) -> str:
    groups: dict[str, list[str]] = defaultdict(list)
    texts: dict[str, str] = {}
    for name, license_text in packages:
        digest = hashlib.sha256(license_text.encode()).hexdigest()
        groups[digest].append(name)
        texts[digest] = license_text

    lines = [
        "MINDMAP THIRD-PARTY NOTICES",
        "===========================",
        "",
        "Mindmap incorporates the following third-party software. The full license",
        "text for each dependency follows; identical texts are grouped together.",
        "",
    ]
    for index, digest in enumerate(sorted(groups, key=lambda value: groups[value][0]), start=1):
        lines.extend([f"NOTICE {index}", "-" * (7 + len(str(index)))])
        lines.extend(f"- {name}" for name in groups[digest])
        lines.extend(["", texts[digest], ""])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate bundled dependency license notices")
    parser.add_argument("--check", action="store_true", help="fail if the committed notices are stale")
    args = parser.parse_args()
    rendered = render(collect())
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != rendered:
            raise SystemExit("THIRD_PARTY_NOTICES.txt is stale; run scripts/generate_notices.py")
        print("Third-party notices are current.")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
