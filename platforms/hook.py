#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "lib"))
os.environ.setdefault("MINDMAP_RUNNER", str(PLUGIN_ROOT / "bin" / "mindmap"))

from mindmap.lifecycle import run_hook  # noqa: E402


parser = argparse.ArgumentParser()
parser.add_argument("--host", required=True, choices=["codex", "claude"])
args = parser.parse_args()
raise SystemExit(run_hook(args.host))
