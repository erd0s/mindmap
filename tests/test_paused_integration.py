from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mindmap import activity, lifecycle
from mindmap.cli import main
from mindmap.store import Store

ROOT = Path(__file__).resolve().parents[1]


def tree_bytes(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob('*') if p.is_file()}


class PausedIntegrationTests(unittest.TestCase):
    def test_all_retired_hook_entries_leave_active_maps_and_transcripts_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / 'project'
            project.mkdir()
            transcript = base / 'transcript.jsonl'
            transcript.write_text('private existing transcript\n')
            environment = {'MINDMAP_HOME_DIR': str(base), 'MINDMAP_DATA_DIR': str(base / 'data')}
            with patch.dict(os.environ, environment):
                store = Store()
                active = store.activate(project)
                session = store.register_session(active['id'], 'codex', 'existing')
                store.begin_turn(active['id'], session['id'], 'turn', 'Existing work')
                before = tree_bytes(base)
                for host in ('codex', 'claude'):
                    for event in ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'Stop', 'PreCompact', 'PostCompact', 'SessionEnd'):
                        payload = {'hook_event_name': event, 'cwd': str(project), 'session_id': 'existing', 'turn_id': 'turn', 'prompt_id': 'turn', 'prompt': '$mindmap:manage start', 'transcript_path': str(transcript)}
                        output = io.StringIO()
                        with patch('sys.stdout', output), patch('sys.stderr', output), patch('sys.stdin', io.StringIO(json.dumps(payload))):
                            self.assertIsNone(lifecycle.handle_hook(host, payload, store))
                            self.assertEqual(lifecycle.run_hook_payload(host, payload), 0)
                            self.assertEqual(main(['hook', '--host', host]), 0)
                            self.assertEqual(activity.run_pre_tool_hook(host, payload), 0)
                            activity.note_pre_tool_activity(host, payload)
                        self.assertEqual(output.getvalue(), '')
                        self.assertEqual(tree_bytes(base), before)

    def test_hook_command_does_not_create_store_even_for_explicit_activation(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            with patch.dict(os.environ, {'MINDMAP_DATA_DIR': str(base / 'data')}), patch('sys.stdin', io.StringIO('$mindmap start')):
                self.assertEqual(main(['hook', '--host', 'claude']), 0)
                self.assertEqual(list(base.iterdir()), [])

    def test_install_and_reinstall_never_execute_downloaded_setup(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / 'home'
            home.mkdir()
            client = home / '.claude'
            client.mkdir()
            (client / 'settings.json').write_text('{"unrelated":true}\n')
            (home / 'retained-transcript').write_text('keep this\n')
            fixtures = base / 'fixtures'
            fixtures.mkdir()
            # A previously published binary still implements setup. The installer
            # must not invoke it, even before a new release is published.
            binary = b'#!/bin/sh\necho invoked >> "$HOME/unexpected-invocation"\nexit 0\n'
            (fixtures / 'mindmap_linux_amd64').write_bytes(binary)
            checksum = hashlib.sha256(binary).hexdigest()
            (fixtures / 'checksums.txt').write_text(checksum + '  mindmap_linux_amd64\n')
            commands = base / 'commands'
            commands.mkdir()
            (commands / 'uname').write_text('#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo x86_64;; esac\n')
            (commands / 'curl').write_text('#!/bin/sh\nwhile [ "$#" -gt 0 ]; do\n case "$1" in https://*) asset=${1##*/};; -o) shift; destination=$1;; esac\n shift\ndone\ncp "$FIXTURES/$asset" "$destination"\n')
            for p in commands.iterdir(): p.chmod(0o755)
            before = tree_bytes(home)
            environment = {**os.environ, 'HOME': str(home), 'PATH': str(commands) + os.pathsep + os.environ['PATH'], 'FIXTURES': str(fixtures), 'MINDMAP_INSTALL_DIR': str(base / 'installed'), 'MINDMAP_RELEASE_URL': 'https://fixture.invalid', 'MINDMAP_SKIP_SETUP': '0'}
            for _ in range(2):
                result = subprocess.run(['/bin/sh', str(ROOT / 'install.sh')], env=environment, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((base / 'installed/mindmap').read_bytes(), binary)
                self.assertEqual(tree_bytes(home), before)


if __name__ == '__main__':
    unittest.main()
