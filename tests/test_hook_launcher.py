from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "platforms" / "run_hook.sh"


class HookLauncherTests(unittest.TestCase):
    def _fake_python(self, path: Path, supported: bool) -> None:
        version_status = 0 if supported else 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "-c" ]; then\n'
            f"  exit {version_status}\n"
            "fi\n"
            'IFS= read -r payload || payload=\n'
            'printf "%s\\n" "$@" > "$MINDMAP_TEST_ARGS"\n'
            'printf "%s\\n" "$payload" > "$MINDMAP_TEST_STDIN"\n',
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _run(
        self,
        environment: dict[str, str],
        capture_root: Path,
        launcher: Path = LAUNCHER,
    ) -> subprocess.CompletedProcess[str]:
        args_file = capture_root / "args"
        stdin_file = capture_root / "stdin"
        return subprocess.run(
            ["/bin/sh", str(launcher), "--host", "claude"],
            input='{"hook_event_name":"SessionStart"}\n',
            text=True,
            capture_output=True,
            check=False,
            env={
                "HOME": str(capture_root),
                "PATH": "/path-not-inherited-from-a-shell",
                "MINDMAP_TEST_ARGS": str(args_file),
                "MINDMAP_TEST_STDIN": str(stdin_file),
                **environment,
            },
        )

    def test_uses_absolute_python_override_with_a_stripped_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            python = root / "custom python" / "python3"
            self._fake_python(python, supported=True)

            result = self._run({"MINDMAP_PYTHON": str(python)}, root)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (root / "args").read_text(encoding="utf-8").splitlines(),
                [str(ROOT / "platforms" / "hook.py"), "--host", "claude"],
            )
            self.assertIn("SessionStart", (root / "stdin").read_text(encoding="utf-8"))

    def test_rejects_old_override_and_uses_saved_setup_interpreter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_python = root / "old" / "python3"
            saved_python = root / "saved" / "python3"
            self._fake_python(old_python, supported=False)
            self._fake_python(saved_python, supported=True)
            # os.UserConfigDir writes here on macOS. The launcher must read it
            # without relying on the Finder process's PATH.
            config = root / "Library" / "Application Support" / "mindmap" / "python-path"
            config.parent.mkdir(parents=True)
            config.write_text(str(saved_python) + "\n", encoding="utf-8")

            result = self._run({"MINDMAP_PYTHON": str(old_python)}, root)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (root / "args").read_text(encoding="utf-8").splitlines()[0],
                str(ROOT / "platforms" / "hook.py"),
            )

    def test_packaged_command_uses_the_same_path_independent_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "bin" / "mindmap"
            entrypoint = root / "bin" / "mindmap.py"
            binary.parent.mkdir()
            shutil.copy2(LAUNCHER, binary)
            entrypoint.touch()
            python = root / "runtime" / "python3"
            self._fake_python(python, supported=True)

            result = self._run({"MINDMAP_PYTHON": str(python)}, root, binary)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (root / "args").read_text(encoding="utf-8").splitlines(),
                [str(entrypoint), "--host", "claude"],
            )


if __name__ == "__main__":
    unittest.main()
