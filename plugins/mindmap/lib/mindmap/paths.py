from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from .errors import MindmapError


def home_dir() -> Path:
    override = os.environ.get("MINDMAP_HOME_DIR")
    return Path(override).expanduser().resolve() if override else Path.home().resolve()


def data_dir() -> Path:
    override = os.environ.get("MINDMAP_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else home_dir() / ".local" / "share"
    return (base / "mindmap").resolve()


def database_path() -> Path:
    return data_dir() / "mindmap.sqlite3"


def canonical_path(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def discover_project_root(value: str | os.PathLike[str]) -> Path:
    """Use the closest Git root, falling back to the supplied directory."""
    candidate = canonical_path(value)
    if candidate.is_file():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if (directory / ".git").exists():
            return directory
        if directory == home_dir():
            break
    return candidate


def route_for_root(value: str | os.PathLike[str]) -> str:
    root = canonical_path(value)
    try:
        relative = root.relative_to(home_dir())
    except ValueError as exc:
        raise MindmapError(
            f"Project root {root} is outside the home directory {home_dir()}; "
            "stable project identities are only defined beneath the home directory."
        ) from exc
    if not relative.parts:
        raise MindmapError("The home directory itself cannot be a Mindmap project root.")
    lowered = [part.lower() for part in relative.parts]
    return "/" + "/".join(quote(part, safe="") for part in lowered)


def is_within(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> bool:
    candidate = canonical_path(path)
    ancestor = canonical_path(root)
    try:
        candidate.relative_to(ancestor)
        return True
    except ValueError:
        return False
