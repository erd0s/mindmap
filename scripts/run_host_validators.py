#!/usr/bin/env python3
"""Verify retired marketplace ingestion fails in fresh, credential-free homes."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    for host in ('codex', 'claude'):
        executable = shutil.which(host)
        if executable is None:
            if os.environ.get('MINDMAP_REQUIRE_HOST_VALIDATORS') == '1':
                raise SystemExit(f'{host} is required for the isolated negative check')
            print(f'SKIP: {host} is unavailable')
            continue
        with tempfile.TemporaryDirectory(prefix=f'mindmap-paused-{host}-') as temporary:
            home = Path(temporary)
            (home / ".codex").mkdir()
            (home / ".claude").mkdir()
            environment = {
                'PATH': os.environ.get('PATH', os.defpath),
                'HOME': temporary,
                'CODEX_HOME': str(home / '.codex'),
                'CLAUDE_CONFIG_DIR': str(home / '.claude'),
                'XDG_CONFIG_HOME': str(home / '.config'),
                'XDG_DATA_HOME': str(home / '.local/share'),
                'XDG_CACHE_HOME': str(home / '.cache'),
            }
            result = subprocess.run(
                [executable, 'plugin', 'marketplace', 'add', str(ROOT), '--json'],
                cwd=home, env=environment, capture_output=True, text=True, timeout=30,
            )
            detail = result.stdout + result.stderr
            if result.returncode == 0 or not any(message in detail for message in ('marketplace.json', 'marketplace root does not contain a supported manifest')):
                raise SystemExit(f'{host}: expected missing marketplace manifest, got {result.returncode}: {detail}')
            listing = subprocess.run(
                [executable, 'plugin', 'marketplace', 'list', '--json'],
                cwd=home, env=environment, capture_output=True, text=True, timeout=30,
            )
            if listing.returncode != 0 or 'erd0s-mindmap' in listing.stdout:
                raise SystemExit(f'{host}: failed to verify an empty marketplace registration')
            print(f'PASS: {host} rejects this checkout as a marketplace; fresh home has no Mindmap registration')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
