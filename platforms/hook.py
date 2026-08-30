#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "lib"))
os.environ.setdefault("MINDMAP_RUNNER", str(PLUGIN_ROOT / "bin" / "mindmap"))

parser = argparse.ArgumentParser()
parser.add_argument("--host", required=True, choices=["codex", "claude"])
args = parser.parse_args()
try:
    payload = json.load(sys.stdin)
    if payload.get("hook_event_name") == "PreToolUse":
        from mindmap.activity import run_pre_tool_hook  # noqa: E402

        raise SystemExit(run_pre_tool_hook(args.host, payload))
    from mindmap.lifecycle import run_hook_payload  # noqa: E402

    raise SystemExit(run_hook_payload(args.host, payload))
except SystemExit:
    raise
except Exception as exc:
    print(f"Mindmap hook warning: {exc}", file=sys.stderr)
    raise SystemExit(0)
