from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def test_retired_shell_hook_needs_no_python_and_never_reads_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                ['/bin/sh', str(ROOT / 'platforms/run_hook.sh'), '--host', 'claude'],
                input='not JSON', capture_output=True, text=True, timeout=5,
                env={'HOME': temporary, 'PATH': '/missing', 'MINDMAP_DATA_DIR': temporary},
            )
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_standalone_launcher_accepts_explicit_python_without_client_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / 'bin' / 'mindmap'
            binary.parent.mkdir()
            shutil.copy2(ROOT / 'platforms/run_cli.sh', binary)
            (binary.parent / 'mindmap.py').write_text('print("standalone works")\n')
            result = subprocess.run(
                ['/bin/sh', str(binary)], capture_output=True, text=True, timeout=5,
                env={'HOME': temporary, 'PATH': '/missing', 'MINDMAP_PYTHON': shutil.which('python3')},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'standalone works\n')


if __name__ == '__main__':
    unittest.main()
