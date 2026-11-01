"""Opt-in local qualification evidence; never adds model-visible text."""
from __future__ import annotations

import json
import os


def emit(kind: str, **fields) -> None:
    path = os.environ.get('MINDMAP_DIAGNOSTICS_PATH')
    if not path:
        return
    try:
        # Each small event is appended in one write. This is private diagnostic
        # evidence, not a source of checkpoint identity or correctness.
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, 'ab') as output:
            output.write((json.dumps({'kind': kind, **fields}, ensure_ascii=False, separators=(',', ':')) + '\n').encode())
    except OSError:
        pass  # Diagnostics must never affect recording or hook enforcement.
