"""Keep JSON and bound-command text independent of host terminal encodings."""
from __future__ import annotations

import sys


def configure_stdio() -> None:
    # Test streams may be StringIO; real CLI pipes use TextIOWrapper. Apply at
    # entrypoints, before reading input or writing model-visible UTF-8 output.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
