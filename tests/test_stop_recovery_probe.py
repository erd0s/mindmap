from __future__ import annotations

import copy
import json
import unittest

from mindmap.delivery import contract, envelope
from scripts.stop_recovery_probe import MARKER_COMMAND, real_tool_problems, setup_context


class RecoveryProbeTests(unittest.TestCase):
    def test_ordering_fault_is_confined_to_initial_test_context(self):
        for case in ('missing', 'later-tool', 'legacy-age', 'explicit-stop', 'recovery-failure', 'actual-later-tool'):
            for event in ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'Stop'):
                original = json.dumps(envelope(event, contract('sh /tmp/bound', recovery=event == 'Stop'))).encode()
                delivered = setup_context(event, case, original)
                if case == 'actual-later-tool' and event == 'UserPromptSubmit':
                    text = json.loads(delivered)['hookSpecificOutput']['additionalContext']
                    self.assertIn('ISOLATED RECOVERY TEST SETUP', text)
                    self.assertIn(MARKER_COMMAND, text)
                    self.assertIn('prepare --file -', text)
                    self.assertIn('expected_revision', text)
                else:
                    self.assertEqual(delivered, original)

    def sequence(self):
        before = {'checkpoint_token': 'first-receipt', 'checkpointed_at': 'accepted',
                  'tool_activity_generation': 2, 'checkpoint_tool_activity_generation': 2}
        after = {**before, 'tool_activity_generation': 3}
        return [{'event': 'PreToolUse', 'payload': {'tool_input': {'command': MARKER_COMMAND}},
                 'before_tool': before, 'after_tool': after, 'stdout': ''},
                {'event': 'Stop', 'before': copy.deepcopy(after), 'stdout': 'unchanged recovery',
                 'runtime_stdout': 'unchanged recovery'}]

    def test_real_tool_evidence_requires_execution_and_unchanged_stale_receipt(self):
        events = self.sequence()
        self.assertEqual(real_tool_problems(events, 'qualification-later-tool\n'), [])
        self.assertTrue(real_tool_problems(events, None))
        events[0]['before_tool']['checkpoint_token'] = None
        self.assertIn('marker tool ran before an accepted checkpoint',
                      real_tool_problems(events, 'qualification-later-tool\n'))

    def test_injected_counters_fresh_corrections_and_changed_stop_feedback_cannot_pass(self):
        for field, value in (('tool_activity_generation', 4), ('checkpoint_token', 'corrected-receipt')):
            events = self.sequence()
            events[-1]['before'][field] = value
            self.assertTrue(real_tool_problems(events, 'qualification-later-tool\n'))
        events = self.sequence()
        events[-1]['stdout'] = 'altered recovery instructions'
        self.assertIn('test altered the production Stop response',
                      real_tool_problems(events, 'qualification-later-tool\n'))


if __name__ == '__main__':
    unittest.main()
