import json
import os
from pathlib import Path
import tempfile
import unittest

from copilot_agent.config import PROJECT_ROOT
from copilot_agent.diagnostics import DiagnosticReports, validate_external
from copilot_agent.feedback import Feedback


class DiagnosticReportTests(unittest.TestCase):
    def raised_error(self):
        namespace = {}
        code = "def fail():\n    raise RuntimeError('password=synthetic-secret AZURE_CLIENT_SECRET=synthetic-env-secret Authorization: Bearer synthetic-token user@example.invalid 123-456-7890')\n"
        exec(compile(code, str(PROJECT_ROOT / 'copilot_agent' / 'diagnostic_probe.py'), 'exec'), namespace)
        try:
            namespace['fail']()
        except RuntimeError as exc:
            return exc

    def test_internal_and_external_reports_are_separate_and_external_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = DiagnosticReports(Path(temporary), 'session-reference', 'testing').create(
                self.raised_error(), operation='local operation', stage='turn',
                events=[{'event': 'operation_started', 'timestamp': '2026-10-07T10:00:00Z', 'message': 'private'}])
            internal = json.loads(result['internal_path'].read_text(encoding='utf-8'))
            external = json.loads(result['external_path'].read_text(encoding='utf-8'))
            self.assertNotEqual(result['internal_path'].parent, result['external_path'].parent)
            self.assertEqual('INTERNAL_RESTRICTED', internal['classification'])
            self.assertEqual('EXTERNAL_SANITIZED', external['classification'])
            self.assertEqual('testing', internal['execution_mode'])
            self.assertEqual('copilot_agent/diagnostic_probe.py', internal['origin']['path'])
            self.assertEqual('tests/test_diagnostics.py', internal['caught_at']['path'])
            self.assertEqual(internal['candidate_files'], internal['FILES TO PROVIDE TO AUTHORIZED COPILOT'])
            self.assertNotIn('synthetic-secret', json.dumps(internal))
            self.assertNotIn('synthetic-env-secret', json.dumps(internal))
            self.assertNotIn('synthetic-token', json.dumps(internal))
            self.assertNotIn('user@example.invalid', json.dumps(internal))
            self.assertNotIn('123-456-7890', json.dumps(internal))
            self.assertEqual('FILES OR CODE EXCERPTS NEEDED FOR EXTERNAL REVIEW', external['candidate_files']['section'])
            self.assertNotIn('diagnostic_probe', json.dumps(external))
            self.assertNotIn(str(PROJECT_ROOT), json.dumps(external))
            self.assertNotIn('synthetic-secret', json.dumps(external))
            self.assertNotIn('user@example.invalid', json.dumps(external))
            self.assertEqual('testing', external['execution_mode'])
            validate_external(external)

    def test_external_allowlist_rejects_added_fields_and_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = DiagnosticReports(Path(temporary), 's').create(self.raised_error(), operation='op', stage='turn')['external']
            with self.assertRaises(ValueError):
                validate_external(dict(report, repository_path='C:\\sensitive\\repo'))
            altered = dict(report, summary='C:\\Users\\employee\\private')
            with self.assertRaises(ValueError):
                validate_external(altered)

    def test_bug_fix_terminal_label_is_visible_with_yellow_background(self):
        lines = []
        Feedback(lines.append, color=True).emit('BUG FIX', 'Actionable failure')
        self.assertIn('\x1b[30;103m BUG FIX ', lines[0])
        self.assertIn('Actionable failure', lines[0])


if __name__ == '__main__':
    unittest.main()
