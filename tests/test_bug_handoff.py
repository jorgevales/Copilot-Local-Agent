from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from copilot_agent.app import _record_bug_fix, _show_bug_handoff
from copilot_agent.config import Config
from copilot_agent.state import SessionState


class BugHandoffTests(unittest.TestCase):
    def test_recording_is_quiet_and_session_handoff_is_printed_at_end(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = Config(root=root, storage_dir=root)
            state = SessionState(root / 'runtime' / 'sessions' / 'session')
            reports = []
            try:
                raise RuntimeError('synthetic failure')
            except RuntimeError as exc:
                with patch('copilot_agent.app._TERMINAL.emit') as emit:
                    record = _record_bug_fix(state, config, exc, 'test operation', 'turn', reports)
                    emit.assert_not_called()
            self.assertIsNotNone(record)
            self.assertEqual(1, len(reports))
            self.assertTrue(state.data['bug_fix'])
            self.assertEqual('created', state.data['status'])
            with patch('copilot_agent.app.system') as system:
                _show_bug_handoff(reports)
            self.assertEqual(3, system.call_count)
            messages = '\n'.join(call.args[0] for call in system.call_args_list)
            self.assertIn('internal report(s)', messages)
            self.assertIn('08_GRAPHIFY_FINDINGS.md', messages)
            self.assertIn('Copilot handoff/full-discovery/README.md', messages)
            self.assertIn('recommended source/test files', messages)
            self.assertIn('within 20', messages)


if __name__ == '__main__':
    unittest.main()
