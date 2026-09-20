from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from mindmap.activity import note_pre_tool_activity
from mindmap.delivery import contract
from mindmap.errors import MindmapError
from mindmap.lifecycle import handle_hook
from mindmap.limits import compact_guidance
from mindmap.protocol import binding, commit, prepare
from mindmap.retrieval import encode, graph_data, read_page
from mindmap.store import Store

EMPTY = {'summary': 'Reviewed; no map change', 'operations': []}
ROOT = Path(__file__).resolve().parents[1]


def size(event, text):
    output = {'decision': 'block', 'reason': text} if event == 'Stop' else {
        'hookSpecificOutput': {'hookEventName': event, 'additionalContext': text}}
    return len(json.dumps(output, ensure_ascii=False, separators=(',', ':')).encode()) + 1


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'home' / 'project'
        self.root.mkdir(parents=True)
        self.env = patch.dict(os.environ, {'MINDMAP_HOME_DIR': str(self.base / 'home'),
                                          'MINDMAP_DATA_DIR': str(self.base / 'data'),
                                          'MINDMAP_TRACKING': 'on'})
        self.env.start()
        self.store = Store()
        self.project = self.store.activate(self.root)
        self.host = 'codex'
        self.start()

    def tearDown(self):
        # Short fallback commands intentionally survive process restarts, but
        # these isolated test bindings need not outlive their databases.
        with self.store.read_connection() as db:
            import shlex
            for row in db.execute('SELECT command FROM context_bindings'):
                Path(shlex.split(row[0])[1]).unlink(missing_ok=True)
        self.env.stop()
        self.temp.cleanup()

    def start(self, prompt='Work on the current request', turn='turn'):
        return handle_hook(self.host, {'hook_event_name': 'UserPromptSubmit', 'cwd': str(self.root),
                           'session_id': 'session', 'turn_id': turn, 'prompt': prompt}, self.store)

    def bound(self):
        turn = self.store.turn(self.host, 'session', 'turn')
        return binding(self.store, self.project['id'], turn['id'])

    def tool(self, command=None, **extra):
        payload = {'cwd': str(self.root), 'session_id': 'session', 'tool_name': 'Bash',
                   'tool_input': {'command': command or 'do substantive work'}}
        if self.host == 'codex':
            payload['turn_id'] = 'turn'
        payload.update(extra)
        note_pre_tool_activity(self.host, payload)

    def stop(self, active=False):
        return handle_hook(self.host, {'hook_event_name': 'Stop', 'cwd': str(self.root),
            'session_id': 'session', 'turn_id': 'turn', 'stop_hook_active': active,
            'last_assistant_message': 'Completed the requested work.'}, self.store)

    def record(self, payload=EMPTY, **kwargs):
        return self.store.record(self.root, self.host, 'session', 'turn', payload, **kwargs)

    def checkpoint_events(self):
        return [e for e in self.store.project_snapshot(self.project['id'])['events'] if e['event_type'] == 'turn.checkpointed']

    def test_correlated_retries_refresh_coverage_without_duplicate_mutations_for_both_hosts(self):
        for host in ('codex', 'claude'):
            with self.subTest(host=host):
                self.host = host
                self.start()
                bound = self.bound()
                self.tool('prepare payload')
                request = prepare(self.store, bound['token'], {'summary': 'Captured idea', 'operations': [
                    {'op': 'upsert', 'id': host, 'title': host}]}, None)
                for _ in range(3):
                    self.tool(request['commit_command'])
                    result = commit(Store(), bound['token'], request['request'])
                    self.assertIsNone(self.stop())
                self.assertTrue(result['idempotent_replay'])
                item = next(i for i in self.store.project_view(self.project['id'])['items'] if i['id'] == host)
                self.assertEqual(item['revision'], 1)
                events = [e for e in self.checkpoint_events() if e['host'] == host]
                self.assertEqual(len(events), 1)

    def test_correction_before_stop_and_repeated_empty_cycles_have_distinct_receipts(self):
        first = self.record({'summary': 'Start', 'operations': [{'op': 'upsert', 'id': 'idea', 'title': 'Idea'}]})
        self.tool()
        delta = {'summary': 'Corrected', 'operations': [{'op': 'upsert', 'id': 'idea', 'expected_revision': 1, 'summary': 'New evidence'}]}
        with self.assertRaisesRegex(MindmapError, 'different payload'):
            self.record(delta)
        correction = self.record(delta, supersedes=first['checkpoint_token'])
        self.assertIsNone(self.stop())
        for _ in range(3):
            self.tool()
            correction = self.record(EMPTY, supersedes=correction['checkpoint_token'])
            self.assertIsNone(self.stop())
        self.assertEqual(len(self.checkpoint_events()), 5)
        self.assertEqual(self.store.project_view(self.project['id'])['items'][0]['revision'], 2)

    def test_ordinary_retry_never_claims_unreviewed_work(self):
        self.record()
        self.tool()
        self.assertTrue(self.record()['idempotent_replay'])
        self.assertEqual(self.stop()['decision'], 'block')

    def test_prepared_retry_rejects_real_work_bundling_background_and_unknown_wrappers(self):
        for mode in ('later_work', 'bundled', 'background', 'unknown', 'failed_tool'):
            with self.subTest(mode=mode):
                self.start('New prompt ' + mode)
                bound = self.bound()
                self.tool('prepare')
                request = prepare(self.store, bound['token'], EMPTY, None)
                if mode in ('later_work', 'failed_tool'):
                    self.tool(request['commit_command'])
                    commit(self.store, bound['token'], request['request'])
                    self.tool('false' if mode == 'failed_tool' else 'work')
                if mode == 'bundled':
                    self.tool(request['commit_command'] + '; do more work')
                elif mode == 'background':
                    self.tool(tool_input={'command': request['commit_command'], 'run_in_background': True})
                elif mode == 'unknown':
                    self.tool(request['commit_command'], tool_name='functions.exec')
                else:
                    self.tool(request['commit_command'])
                with self.assertRaisesRegex(MindmapError, 'Uncorrelated'):
                    commit(self.store, bound['token'], request['request'])

    def test_invalid_correction_rolls_back_and_competing_corrections_compare_tokens(self):
        receipt = self.record({'summary': 'Initial', 'operations': [{'op': 'upsert', 'id': 'idea', 'title': 'Idea'}]})
        self.tool()
        with self.assertRaisesRegex(MindmapError, 'changed concurrently'):
            self.record({'summary': 'Invalid', 'operations': [
                {'op': 'upsert', 'id': 'other', 'title': 'Other'},
                {'op': 'upsert', 'id': 'idea', 'expected_revision': 9, 'title': 'Bad'}]}, supersedes=receipt['checkpoint_token'])
        self.assertEqual([i['id'] for i in self.store.project_view(self.project['id'])['items']], ['idea'])
        self.assertEqual(self.store.turn(self.host, 'session', 'turn')['checkpoint_token'], receipt['checkpoint_token'])
        def attempt(_):
            try:
                return self.record(supersedes=receipt['checkpoint_token'])
            except MindmapError:
                return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(len(self.checkpoint_events()), 2)
        self.assertIsNone(self.stop())

    def test_stale_invalidation_cannot_erase_corrected_checkpoint_token(self):
        receipt = self.record()
        self.tool()
        observed = self.store.turn(self.host, 'session', 'turn')
        corrected = self.record(supersedes=receipt['checkpoint_token'])
        self.assertFalse(self.store.invalidate_checkpoint(self.host, 'session', 'turn', 'post_checkpoint_tool_activity',
            expected_token=observed['checkpoint_token'], expected_generation=observed['tool_activity_generation']))
        self.assertEqual(self.store.turn(self.host, 'session', 'turn')['checkpoint_token'], corrected['checkpoint_token'])
        self.assertIsNone(self.stop())

    def test_steering_session_end_and_deactivation_reject_prepared_requests(self):
        for mode in ('steer', 'end', 'deactivate'):
            with self.subTest(mode=mode):
                self.store.activate(self.root)
                self.start('Prompt ' + mode)
                bound = self.bound()
                request = prepare(self.store, bound['token'], EMPTY, None)
                if mode == 'steer':
                    self.start('Additional steering')
                elif mode == 'end':
                    self.store.end_session(self.host, 'session')
                else:
                    self.store.deactivate(self.root)
                with self.assertRaises(MindmapError):
                    commit(self.store, bound['token'], request['request'])

    def test_recovery_remains_one_pass_and_later_work_leaves_honest_unresolved_state(self):
        self.assertEqual(self.stop()['decision'], 'block')
        self.record()
        self.tool()
        self.assertIsNone(self.stop(active=True))
        self.assertFalse(self.store.is_checkpointed(self.host, 'session', 'turn'))
        output = self.start('Next request', turn='next')
        self.assertIn('MINDMAP_PRIOR_CHECKPOINT_MISSING', output['hookSpecificOutput']['additionalContext'])

    def test_stop_guides_fresh_preparation_after_invalidating_the_old_token(self):
        bound = self.bound()
        first = prepare(self.store, bound['token'], EMPTY, None)
        self.tool(first['commit_command'])
        commit(self.store, bound['token'], first['request'])
        self.tool('Work after the first checkpoint')
        recovery = self.stop()['reason']
        self.assertIn('without --supersedes', recovery)
        self.assertIsNone(self.store.turn(self.host, 'session', 'turn')['checkpoint_token'])
        self.tool('Reviewed later work; prepare an empty delta')
        request = prepare(self.store, bound['token'], EMPTY, None)
        self.tool(request['commit_command'])
        commit(self.store, bound['token'], request['request'])
        self.assertIsNone(self.stop(active=True))
        self.assertEqual(len(self.checkpoint_events()), 2)

    def test_bare_stale_replay_rejects_but_fresh_identical_preparation_reconciles(self):
        for reason in ('stop', 'prompt'):
            self.start('First request ' + reason, turn=reason)
            self.store.record(self.root, self.host, 'session', reason, EMPTY)
            if reason == 'stop':
                self.store.note_tool_activity(self.project['id'], self.host, 'session', reason, 'later-work')
                handle_hook(self.host, {'hook_event_name': 'Stop', 'cwd': str(self.root), 'session_id': 'session', 'turn_id': reason}, self.store)
            else:
                self.start('Additional steering', turn=reason)
            before = self.store.turn(self.host, 'session', reason)
            with self.assertRaisesRegex(MindmapError, 'already committed before the turn reopened'):
                self.store.record(self.root, self.host, 'session', reason, EMPTY)
            self.assertEqual(self.store.turn(self.host, 'session', reason), before)
            bound = binding(self.store, self.project['id'], before['id'])
            request = prepare(self.store, bound['token'], EMPTY, None)
            result = commit(self.store, bound['token'], request['request'])
            self.assertTrue(result['checkpointed'])

    def test_fast_hook_before_protocol_migration_preserves_activity(self):
        self.record()
        with self.store.transaction() as db:
            db.execute('DROP TABLE record_requests')
        note_pre_tool_activity(self.host, {'cwd': str(self.root), 'session_id': 'session',
            'turn_id': 'turn', 'tool_name': 'Bash', 'tool_input': {'command': 'true'}})
        self.store = Store()
        self.assertEqual(self.store.turn(self.host, 'session', 'turn')['tool_activity_generation'], 1)
        self.assertEqual(self.stop()['decision'], 'block')

    def seed(self, count, unicode=False):
        text = '🧭' if unicode else 'x'
        existing = len(self.store.project_view(self.project['id'])['items'])
        for start in range(existing, count, 8):
            ops = []
            for index in range(start, min(start + 8, count)):
                ops.append({'op': 'upsert', 'id': f'concept-{index:04d}', 'parent_id': None if index == 0 else 'concept-0000',
                    'title': ('Relevant zeppelin constraint' if index == count - 1 else text * 160),
                    'summary': text * 1200, 'resume': text * 600, 'state': 'settled' if index == count - 1 else 'open'})
            self.store.record(self.root, self.host, 'seed', f'seed-{start}', {'summary': 'Fixture', 'operations': ops})

    def test_graph_growth_unicode_lifecycle_budgets_and_preview_contract(self):
        for count in (0, 21, 101, 1001):
            self.seed(count, unicode=True)
            before = self.store.project_view(self.project['id'])
            for host in ('codex', 'claude'):
                self.host = host
                for prompt in ('Explain the zeppelin constraint', '$mindmap:manage status', '$mindmap:manage sync', '$mindmap:manage stop'):
                    output = self.start(prompt)
                    text = output['hookSpecificOutput']['additionalContext']
                    self.assertLessEqual(size('UserPromptSubmit', text), 8192)
                    preview = text.encode()[:1800].decode('utf-8', errors='ignore')
                    for word in ('prepare --file -', 'expected_revision', '100000', 'resume', 'supersedes', 'read (paged'):
                        self.assertIn(word, preview)
                    if count and 'zeppelin' in prompt:
                        self.assertIn('Relevant zeppelin constraint', text)
                    self.assertIn('omitted', text)
                start = handle_hook(host, {'hook_event_name': 'SessionStart', 'cwd': str(self.root), 'session_id': 'session', 'source': 'compact'}, self.store)
                self.assertLessEqual(size('SessionStart', start['hookSpecificOutput']['additionalContext']), 4096)
                self.assertNotIn('prepare --file', start['hookSpecificOutput']['additionalContext'])
                for event in ('PreCompact', 'PostCompact'):
                    self.assertIsNone(handle_hook(host, {'hook_event_name': event, 'cwd': str(self.root), 'session_id': 'session'}, self.store))
                stop = self.stop()
                self.assertLessEqual(size('Stop', stop['reason']), 2048)
                self.assertNotIn('Relevant zeppelin constraint', stop['reason'])
            self.assertEqual(before, self.store.project_view(self.project['id']))

    def test_paging_full_fields_and_change_detection(self):
        self.seed(101, unicode=True)
        page = read_page(self.store, self.project['id'])
        first_cursor = page['next_cursor']
        seen = []
        while True:
            self.assertLessEqual(len(encode(page).encode()) + 1, 16384)
            seen.extend(page['records'])
            if not page['next_cursor']:
                break
            page = read_page(self.store, self.project['id'], cursor=page['next_cursor'])
        self.assertEqual(len(seen), 101)
        self.assertEqual(len({i['id'] for i in seen}), 101)
        self.assertEqual(len(seen[0]['summary']), 1200)
        self.assertEqual(read_page(self.store, self.project['id'], roots=True)['total'], 1)
        self.assertEqual(read_page(self.store, self.project['id'], parent='concept-0000')['total'], 100)
        self.record({'summary': 'Edit', 'operations': [{'op': 'upsert', 'id': 'concept-0000', 'expected_revision': 1, 'resume': ''}]})
        with self.assertRaisesRegex(MindmapError, 'refresh'):
            read_page(self.store, self.project['id'], cursor=first_cursor)

    def test_large_diagnostics_and_identity_do_not_overflow_or_truncate_commands(self):
        payload = {'hook_event_name': 'UserPromptSubmit', 'cwd': str(self.root),
                   'session_id': 'session' * 1000, 'turn_id': 'turn' * 1000,
                   'prompt': 'New unrelated task'}
        with patch.object(self.store, 'import_transcript', side_effect=OSError('🧭' * 10000)):
            result = handle_hook('claude', payload, self.store)
        text = result['hookSpecificOutput']['additionalContext']
        self.assertLessEqual(size('UserPromptSubmit', text), 8192)
        command = re.search(r'pipe JSON to (.+?) prepare --file -', text).group(1)
        completed = subprocess.run(command + ' prepare --file -', input=json.dumps(EMPTY), shell=True, text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        prepared = json.loads(completed.stdout)
        completed = subprocess.run(prepared['commit_command'], shell=True, text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(self.store.is_checkpointed('claude', payload['session_id'], payload['turn_id']))

    def test_new_prompt_does_not_authorize_old_frontier(self):
        self.seed(21)
        text = self.start('Write a poem about the ocean')['hookSpecificOutput']['additionalContext']
        self.assertIn('Historical plans are context, not authorization; follow the current request', text)
        self.assertNotIn('continue the first', text.casefold())

    def test_validation_field_boundaries_and_advertised_authority(self):
        from mindmap import limits
        self.assertIn(compact_guidance(), contract(self.bound()['command']))
        for field, maximum in (('id', limits.MAX_ID_LENGTH), ('title', limits.MAX_TITLE_LENGTH),
                               ('summary', limits.MAX_ITEM_SUMMARY_LENGTH), ('resume', limits.MAX_RESUME_LENGTH)):
            for count in (maximum, maximum + 1):
                op = {'op': 'upsert', 'id': 'valid', 'title': 'Valid', field: '🧭' * count}
                payload = {'summary': 'OK', 'operations': [op]}
                if count == maximum:
                    self.store.validate_payload(payload)
                else:
                    with self.assertRaises(MindmapError):
                        self.store.validate_payload(payload)
        self.store.validate_payload({'summary': ' ' + 'x' * 498 + ' ', 'operations': []})
        with self.assertRaises(MindmapError):
            self.store.validate_payload({'summary': ' ' + 'x' * 499 + ' ', 'operations': []})
        for payload in ({'summary': 'x'}, {'summary': 'x', 'operations': [], 'unknown': True},
                        {'summary': 'x', 'operations': [{'op': 'upsert', 'id': 'x', 'title': 'X'}, {'op': 'settle', 'id': ' x ', 'expected_revision': 1}]}):
            with self.assertRaises(MindmapError):
                self.store.validate_payload(payload)

    def test_canonical_payload_byte_boundary(self):
        payload = {'summary': 'x', 'operations': [{'op': 'upsert', 'id': f'c-{i}', 'title': 'x', 'summary': '🧭' * 1200} for i in range(20)]}
        # Add ASCII resume bytes to land exactly on the canonical byte limit.
        payload['operations'] += [{'op': 'settle', 'id': f'existing-{i}', 'expected_revision': 1, 'summary': 'x' * 1200} for i in range(2)]
        encoded = self.store.validate_payload(payload)[3]
        remaining = 100000 - len(encoded.encode()) - len(',"resume":""')
        self.assertGreaterEqual(remaining, 0)
        self.assertLessEqual(remaining, 600)
        payload['operations'][0]['resume'] = 'x' * remaining
        self.assertEqual(len(self.store.validate_payload(payload)[3].encode()), 100000)
        payload['operations'][0]['resume'] += 'x'
        with self.assertRaisesRegex(MindmapError, 'bytes'):
            self.store.validate_payload(payload)

    def test_both_generated_launchers_execute_prompt_prepare_retry_and_stop(self):
        self.seed(21, unicode=True)
        for host, relative in (('codex', 'plugins/mindmap'), ('claude', 'plugins/claude/mindmap')):
            with self.subTest(host=host):
                package = ROOT / relative
                session_id = 'packaged-' + host
                hook = package / 'scripts/run_hook.sh'
                def invoke(event, **fields):
                    payload = {'hook_event_name': event, 'cwd': str(self.root), 'session_id': session_id,
                               ('turn_id' if host == 'codex' else 'prompt_id'): 'packaged-turn', **fields}
                    if host == 'claude' and event == 'PreToolUse':
                        payload.pop('prompt_id')
                    result = subprocess.run([str(hook), '--host', host], input=json.dumps(payload), capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, '')
                    self.assertLessEqual(len(result.stdout.encode()), 2048 if event == 'Stop' else 4096 if event == 'SessionStart' else 8192)
                    return json.loads(result.stdout) if result.stdout.strip() else None
                output = invoke('UserPromptSubmit', prompt='Record no map change')
                text = output['hookSpecificOutput']['additionalContext']
                command = re.search(r'pipe JSON to (.+?) prepare --file -', text).group(1)
                tool_name, field = ('exec_command', 'cmd') if host == 'codex' else ('Bash', 'command')
                invoke('PreToolUse', tool_name=tool_name, tool_input={field: command + ' prepare --file -'})
                preparation = subprocess.run(command + ' prepare --file -', input=json.dumps(EMPTY), shell=True, text=True, capture_output=True)
                self.assertEqual(preparation.returncode, 0, preparation.stderr)
                request = json.loads(preparation.stdout)
                for repeat in range(2):
                    invoke('PreToolUse', tool_name=tool_name, tool_input={field: request['commit_command']})
                    result = subprocess.run(request['commit_command'], shell=True, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    receipt = json.loads(result.stdout)
                    self.assertEqual(receipt.get('idempotent_replay', False), bool(repeat))
                    self.assertIsNone(invoke('Stop', last_assistant_message='Complete'))
                self.assertIsNone(invoke('PreCompact'))
                self.assertIsNone(invoke('PostCompact'))

    def test_packaged_utf8_transport_ignores_host_encoding_for_hooks_and_bound_commands(self):
        self.record({'summary': 'Unicode seed', 'operations': [
            {'op': 'upsert', 'id': 'unicode', 'title': '漢字 — 🚀', 'summary': 'Preserve Unicode.'}]})
        for host, relative in (('codex', 'plugins/mindmap'), ('claude', 'plugins/claude/mindmap')):
            for encoding in ('ascii', 'cp1252', 'utf-16', 'utf-8'):
                with self.subTest(host=host, encoding=encoding):
                    env = {**os.environ, 'PYTHONIOENCODING': encoding, 'LC_ALL': 'C', 'PYTHONUTF8': '0'}
                    session = host + '-' + encoding
                    def hook(event, **extra):
                        payload = {'hook_event_name': event, 'cwd': str(self.root), 'session_id': session,
                                   'turn_id': 'unicode-turn', 'prompt_id': 'unicode-turn', **extra}
                        result = subprocess.run([str(ROOT / relative / 'scripts/run_hook.sh'), '--host', host],
                            input=json.dumps(payload, ensure_ascii=False).encode(), capture_output=True, env=env)
                        self.assertEqual((result.returncode, result.stderr), (0, b''))
                        return json.loads(result.stdout.decode('utf-8')) if result.stdout else None
                    output = hook('UserPromptSubmit', prompt='Discuss 漢字 — 🚀 without changing it.')
                    text = output['hookSpecificOutput']['additionalContext']
                    self.assertIn('漢字 — 🚀', text)
                    self.assertIn('漢字 — 🚀', hook('SessionStart')['hookSpecificOutput']['additionalContext'])
                    prefix = re.search(r'pipe JSON to (.+?) prepare --file -', text).group(1)
                    payload = {'summary': 'Discussed 漢字 — 🚀; no change.', 'operations': []}
                    prepared = subprocess.run(prefix + ' prepare --file -', shell=True,
                        input=json.dumps(payload, ensure_ascii=False).encode(), capture_output=True, env=env)
                    self.assertEqual((prepared.returncode, prepared.stderr), (0, b''))
                    command = json.loads(prepared.stdout)['commit_command']
                    hook('PreToolUse', tool_name='Bash', tool_input={'command': command})
                    result = subprocess.run(command, shell=True, capture_output=True, env=env)
                    self.assertEqual((result.returncode, result.stderr), (0, b''))
                    self.assertTrue(json.loads(result.stdout)['checkpointed'])
                    read = subprocess.run(prefix + ' read --id unicode', shell=True, capture_output=True, env=env)
                    self.assertEqual(json.loads(read.stdout.decode())['records'][0]['title'], '漢字 — 🚀')
                    hook('PreToolUse', tool_name='Bash', tool_input={'command': 'true'})
                    self.assertEqual(hook('Stop')['decision'], 'block')

    def test_warning_identities_survive_large_map_and_count_omitted_details(self):
        self.seed(101, unicode=True)
        with self.store.transaction() as db:
            db.execute("UPDATE items SET state='settled', resume='Run the acceptance test' WHERE project_id=?", (self.project['id'],))
        warnings = graph_data(self.store, self.project['id'])['warnings']
        expected = [{k: w[k] for k in ('code', 'item_id')} for w in sorted(warnings, key=lambda w: (w['item_id'], w['code']))[:5]]
        for host in ('codex', 'claude'):
            self.host = host
            for event in ('UserPromptSubmit', 'SessionStart'):
                text = handle_hook(host, {'hook_event_name': event, 'cwd': str(self.root), 'session_id': 'session',
                    'turn_id': 'turn', 'prompt': 'Explain concept-0100'}, self.store)['hookSpecificOutput']['additionalContext']
                actual = [json.loads(line[len('WARNING '):]) for line in text.splitlines() if line.startswith('WARNING ')]
                self.assertEqual(actual, expected)
                self.assertIn('warning codes shown 5, details omitted 101', text)
                self.assertLessEqual(size(event, text), 4096 if event == 'SessionStart' else 8192)

    def test_warning_and_deletion_pages_retain_protection_when_not_in_context(self):
        self.seed(101)
        with self.store.transaction() as db:
            db.execute("UPDATE items SET state='settled', resume='Run a new test' WHERE project_id=?", (self.project['id'],))
            for i in range(100):
                self.store._event(db, self.project['id'], 'item.subtree_deleted', {
                    'root_id': f'deleted-{i}', 'deleted': [f'deleted-{i}'],
                    'deleted_items': [{'id': f'deleted-{i}', 'title': '🧭' * 160}], 'source': 'user'}, item_id=f'deleted-{i}')
        before = self.store.project_snapshot(self.project['id'])
        text = self.start('Explain an unrelated idea')['hookSpecificOutput']['additionalContext']
        self.assertIn('user-deleted 100', text)
        self.assertIn('warnings 101', text)
        page = read_page(self.store, self.project['id'], notices=True)
        notices = []
        while True:
            notices.extend(page['records'])
            if not page['next_cursor']:
                break
            page = read_page(self.store, self.project['id'], notices=True, cursor=page['next_cursor'])
        self.assertEqual(len(notices), 201)
        self.assertEqual(graph_data(self.store, self.project['id'])['warnings'], before['semantic_warnings'])
        with self.assertRaisesRegex(MindmapError, 'explicitly deleted'):
            self.record({'summary': 'Unrequested restoration', 'operations': [{'op': 'upsert', 'id': 'deleted-99', 'title': 'Deleted'}]})
        self.assertEqual(self.store.project_view(self.project['id'])['items'], before['items'])
        self.store.deactivate(self.root)
        retained = self.start('$mindmap:manage status')['hookSpecificOutput']['additionalContext']
        self.assertLessEqual(size('UserPromptSubmit', retained), 8192)
        self.assertIn('RETAINED_READ_ONLY', retained)

    def test_exact_structural_limits_and_one_over_rollback(self):
        ops = [{'op': 'upsert', 'id': f'branch-{i}', 'title': 'Branch', 'parent_id': f'branch-{i-1}' if i and i < 10 else None if i < 13 else 'branch-0'} for i in range(20)]
        receipt = self.record({'summary': 'Exact limits', 'operations': ops})
        self.assertEqual(len(self.store.project_view(self.project['id'])['items']), 20)
        for operation, message in (
            ({'op': 'upsert', 'id': 'fifth-root', 'title': 'Fifth'}, 'roots'),
            ({'op': 'upsert', 'id': 'too-deep', 'title': 'Deep', 'parent_id': 'branch-9'}, 'deep'),
        ):
            with self.assertRaisesRegex(MindmapError, message):
                self.record({'summary': 'Over', 'operations': [operation]}, supersedes=receipt['checkpoint_token'])
        with self.assertRaisesRegex(MindmapError, '20 concepts'):
            self.record({'summary': 'Over count', 'operations': [{'op': 'upsert', 'id': f'extra-{i}', 'title': 'Extra', 'parent_id': 'branch-0'} for i in range(21)]}, supersedes=receipt['checkpoint_token'])
        self.assertEqual(len(self.checkpoint_events()), 1)
        self.assertEqual(len(self.store.project_view(self.project['id'])['items']), 20)

    def test_all_stop_reasons_with_legacy_and_import_diagnostics_fit(self):
        with self.store.transaction() as db:
            db.execute('UPDATE projects SET concept_model_version=1 WHERE id=?', (self.project['id'],))
        for reason in ('missing', 'old', 'tools'):
            self.start('Ordinary prompt ' + reason)
            if reason != 'missing':
                bound = self.bound()
                request = prepare(self.store, bound['token'], EMPTY, None)
                commit(self.store, bound['token'], request['request'])
                if reason == 'old':
                    with self.store.transaction() as db:
                        db.execute("UPDATE turns SET checkpointed_at=datetime('now','-2 minutes') WHERE interaction_id='turn'")
                else:
                    self.tool()
            with patch.object(self.store, 'import_transcript', side_effect=OSError('failure' * 10000)):
                stopped = self.stop()
            self.assertLessEqual(size('Stop', stopped['reason']), 2048)
            self.assertIn('concept_model', stopped['reason'])
            self.assertIsNone(self.stop(active=True))

    def test_deep_relevant_leaf_is_not_displaced_by_large_ancestors(self):
        operations = [{'op': 'upsert', 'id': f'layer-{i}', 'title': '🧭' * 160,
                       'summary': '🧭' * 1200, 'resume': '🧭' * 600,
                       'parent_id': f'layer-{i-1}' if i else None} for i in range(10)]
        self.record({'summary': 'Deep tree', 'operations': operations})
        text = self.start('Review layer-9')['hookSpecificOutput']['additionalContext']
        self.assertIn('[layer-9]', text)
        self.assertIn('parent layer-8', text)
        self.assertIn('ROOT ', text)
        self.assertLessEqual(size('UserPromptSubmit', text), 8192)

    def test_legacy_checkpoint_gets_stable_correction_identity_without_fabricating_coverage(self):
        self.record()
        with self.store.transaction() as db:
            db.execute('UPDATE turns SET checkpoint_token=NULL')
        migrated = Store()
        turn = migrated.turn(self.host, 'session', 'turn')
        self.assertTrue(turn['checkpoint_token'])
        self.assertEqual(turn['checkpoint_tool_activity_generation'], 0)
        self.assertEqual(Store().turn(self.host, 'session', 'turn')['checkpoint_token'], turn['checkpoint_token'])
        self.record(supersedes=turn['checkpoint_token'])
        self.assertIsNone(self.stop())

    def test_prepared_request_cannot_be_reused_for_different_json(self):
        bound = self.bound()
        request = prepare(self.store, bound['token'], EMPTY, None)
        with self.assertRaisesRegex(MindmapError, 'payload or correction token changed'):
            self.record({'summary': 'Changed', 'operations': []}, request_token=request['request'])
        self.assertFalse(self.store.is_checkpointed(self.host, 'session', 'turn'))

    def test_actual_stop_and_correction_serialize_without_losing_an_accepted_receipt(self):
        for index in range(5):
            self.start(f'Race {index}')
            bound = self.bound()
            request = prepare(self.store, bound['token'], EMPTY, None)
            initial = commit(self.store, bound['token'], request['request'])
            self.tool()
            def correct():
                try:
                    return self.record(supersedes=initial['checkpoint_token'])
                except MindmapError:
                    return None
            with ThreadPoolExecutor(max_workers=2) as executor:
                correction = executor.submit(correct)
                stopping = executor.submit(self.stop)
                accepted, response = correction.result(), stopping.result()
            current = self.store.turn(self.host, 'session', 'turn')
            if accepted:
                self.assertEqual(current['checkpoint_token'], accepted['checkpoint_token'])
                self.assertIsNotNone(current['checkpointed_at'])
                self.assertIsNone(response)
            else:
                self.assertEqual(response['decision'], 'block')
                self.assertIsNone(current['checkpointed_at'])

    def test_activity_waiting_on_commit_is_not_absorbed_into_checkpoint_coverage(self):
        initial = self.record()
        entered, release, activity_started = threading.Event(), threading.Event(), threading.Event()
        original = self.store._assert_valid_graph
        def hold(db, project_id):
            original(db, project_id)
            entered.set()
            self.assertTrue(release.wait(5))
        def activity():
            activity_started.set()
            self.tool('Real work queued while checkpoint commits')
        with patch.object(self.store, '_assert_valid_graph', hold), ThreadPoolExecutor(max_workers=2) as pool:
            record = pool.submit(self.record, {'summary': 'Accepted concept before later work', 'operations': [
                {'op': 'upsert', 'id': 'accepted', 'title': 'Accepted before the queued tool'}]},
                supersedes=initial['checkpoint_token'])
            try:
                self.assertTrue(entered.wait(5))
                tool = pool.submit(activity)
                self.assertTrue(activity_started.wait(5))
            finally:
                release.set()
            record.result(timeout=5)
            tool.result(timeout=5)
        turn = self.store.turn(self.host, 'session', 'turn')
        self.assertEqual(turn['tool_activity_generation'], turn['checkpoint_tool_activity_generation'] + 1)
        self.assertEqual(self.stop()['decision'], 'block')

    def test_correction_waiting_on_activity_covers_the_committed_generation(self):
        initial = self.record()
        started = threading.Event()
        def record():
            started.set()
            return self.record(supersedes=initial['checkpoint_token'])
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.store.transaction() as db:
                db.execute('UPDATE turns SET tool_activity_generation=tool_activity_generation+1')
                future = pool.submit(record)
                self.assertTrue(started.wait(5))
            self.assertTrue(future.result(timeout=5)['checkpointed'])
        turn = self.store.turn(self.host, 'session', 'turn')
        self.assertEqual(turn['checkpoint_tool_activity_generation'], 1)
        self.assertIsNone(self.stop())

    def test_long_project_path_uses_an_executable_bound_command(self):
        long_root = self.root
        for _ in range(8):
            long_root /= 'long-project-component-' * 4
        long_root.mkdir(parents=True)
        project = self.store.activate(long_root)
        output = handle_hook('claude', {'hook_event_name': 'UserPromptSubmit', 'cwd': str(long_root),
            'session_id': 'long-project', 'prompt_id': 'long-prompt', 'prompt': 'Current task'}, self.store)
        text = output['hookSpecificOutput']['additionalContext']
        command = re.search(r'pipe JSON to (.+?) prepare --file -', text).group(1)
        self.assertLess(len(command.encode()), 120)
        prepared = subprocess.run(command + ' prepare --file -', input=json.dumps(EMPTY), shell=True, text=True, capture_output=True)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        committed = subprocess.run(json.loads(prepared.stdout)['commit_command'], shell=True, text=True, capture_output=True)
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.assertEqual(self.store.session('claude', 'long-project')['project_id'], project['id'])
        self.assertTrue(self.store.is_checkpointed('claude', 'long-project', 'long-prompt'))
        self.assertLessEqual(size('UserPromptSubmit', text), 8192)

    def test_sort_order_exact_boundaries_are_advertised_and_enforced(self):
        from mindmap.limits import MIN_SORT_ORDER, MAX_SORT_ORDER
        for value in (MIN_SORT_ORDER, MAX_SORT_ORDER):
            self.store.validate_payload({'summary': 'Ordering', 'operations': [
                {'op': 'upsert', 'id': 'ordered', 'title': 'Ordered', 'sort_order': value}]})
            self.assertIn(str(value), compact_guidance())
        for value in (MIN_SORT_ORDER - 1, MAX_SORT_ORDER + 1):
            with self.assertRaises(MindmapError):
                self.store.validate_payload({'summary': 'Ordering', 'operations': [
                    {'op': 'upsert', 'id': 'ordered', 'title': 'Ordered', 'sort_order': value}]})

    def test_small_map_frontier_survives_preview_without_repeating_resume(self):
        self.record({'summary': 'Initial goal', 'operations': [{'op': 'upsert', 'id': 'main-goal',
            'title': 'Main goal', 'summary': 'Current comparison', 'resume': 'Finish the current comparison.'}]})
        text = self.start('Resolve the separate prerequisite')['hookSpecificOutput']['additionalContext']
        self.assertIn('Leave explicitly unchanged branches untouched', text.encode()[:1800].decode())
        self.assertIn('Unrelated one-off questions with no lasting decision or follow-up need an empty delta.', text.encode()[:1800].decode())
        preview = text.encode()[:2048].decode()
        self.assertIn('[main-goal]', preview)
        self.assertIn('parent root; frontier', preview)
        self.assertEqual(text.count('Finish the current comparison.'), 1)

    def test_four_maximum_roots_leave_space_for_requested_child(self):
        ids = [str(i) + '🧭' * 99 for i in range(5)]
        self.record({'summary': 'Four roots and a requested child', 'operations': [
            {'op': 'upsert', 'id': item_id, 'title': '🧭' * 160, 'summary': '🧭' * 1200,
             'resume': '🧭' * 600, 'parent_id': ids[0] if index == 4 else None}
            for index, item_id in enumerate(ids)]})
        for host in ('codex', 'claude'):
            self.host = host
            text = self.start('Review ' + ids[4])['hookSpecificOutput']['additionalContext']
            self.assertLessEqual(size('UserPromptSubmit', text), 8192)
            self.assertIn('[' + ids[4] + ']', text)
            self.assertIn('parent ' + ids[0], text)
            self.assertIn('Fields omitted', text)
            self.assertIn('PARTIAL MAP:', text)

    def test_legacy_start_recovery_with_import_warning_keeps_all_obligations(self):
        with self.store.transaction() as db:
            db.execute('UPDATE projects SET concept_model_version=1 WHERE id=?', (self.project['id'],))
        self.start('$mindmap:manage start', turn='legacy')
        with patch.object(self.store, 'import_transcript', side_effect=OSError('Long diagnostic ' * 1000)):
            text = handle_hook(self.host, {'hook_event_name': 'Stop', 'cwd': str(self.root),
                'session_id': 'session', 'turn_id': 'legacy',
                'last_assistant_message': 'Reconciled the legacy map.'}, self.store)['reason']
        self.assertLessEqual(size('Stop', text), 2048)
        self.assertIn('Start/sync', text)
        self.assertIn('concept_model', text)
        self.assertIn('Transcript import incomplete', text)
