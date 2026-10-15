"""Real native subprocess checks for REA transport, without external services."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

from copilot_agent.rea import _process_command_diagnostic, _run


class REAProcessOutputTests(unittest.TestCase):
    def run_child(self, source, *, limit=1048576, timeout=10):
        with tempfile.TemporaryDirectory(prefix='rea-stream-') as directory:
            context = {}
            result = asyncio.run(_run([sys.executable, '-I', '-c', source],
                                     cwd=directory, timeout=timeout,
                                     output_limit=limit, context=context))
            self.assertTrue(context['rea_cleanup_confirmed'])
            return result

    def test_oversized_json_and_stderr_are_drained_until_native_child_exits(self):
        size = 4_008_122
        result = self.run_child(
            'import os\n'
            f'os.write(1, b"x" * {size})\n'
            'os.write(2, b"diagnostic" * 32768)\n'
            'os.write(2, b"END")\n')
        self.assertEqual('output_limit', result.get('status'))
        self.assertEqual(0, result['returncode'])
        self.assertEqual(size, result['process_diagnostics']['stdout_bytes'])
        self.assertEqual(10 * 32768 + 3, result['process_diagnostics']['stderr_bytes'])
        self.assertEqual(1048576, len(result['stdout']))
        self.assertTrue(result['process_diagnostics']['stdout_truncated'])
        self.assertTrue(result['process_diagnostics']['stderr_truncated'])
        self.assertFalse(result['side_effects_uncertain'])

    def test_supported_large_json_survives_separate_raw_transport_budget(self):
        size = 4_008_122
        result = self.run_child('import json,sys\n'
                               f'sys.stdout.write(json.dumps({{"payload":"x" * {size}}}))\n',
                               limit=32 * 1024 * 1024)
        self.assertNotIn('status', result)
        self.assertEqual(size, len(json.loads(result['stdout'])['payload']))
        self.assertFalse(result['process_diagnostics']['stdout_truncated'])
        self.assertEqual(0, result['process_diagnostics']['returncode'])

    def test_failure_exit_keeps_bounded_diagnostics(self):
        result = self.run_child('import sys; print("invalid argument",file=sys.stderr); sys.exit(7)')
        self.assertEqual(7, result['returncode'])
        self.assertIn('invalid argument', result['process_diagnostics']['stderr_preview'])
        self.assertGreater(result['process_diagnostics']['duration_ms'], 0)

    def test_analysis_timeout_has_distinct_process_diagnostics(self):
        result = self.run_child('import time; time.sleep(20)', timeout=.2)
        self.assertEqual('timeout', result['status'])
        self.assertEqual('analysis_timeout', result['process_diagnostics']['failure_class'])
        self.assertIsNotNone(result['returncode'])

    def test_stderr_is_drained_but_its_contents_are_not_exported(self):
        result = self.run_child('import os; os.write(2,b"Cookie: customer-secret="*20000); print("{}")')
        self.assertEqual(0, result['returncode'])
        self.assertNotIn('status', result)
        diagnostic = result['process_diagnostics']
        self.assertTrue(diagnostic['stderr_truncated'])
        self.assertNotIn('customer-secret', json.dumps(diagnostic))
        self.assertNotIn('Cookie', json.dumps(diagnostic))

    def test_oversize_then_hung_child_retains_output_limit_classification(self):
        result = self.run_child('import os,time; os.write(1,b"x"*2000000); time.sleep(20)', timeout=.4)
        self.assertEqual('output_limit', result['status'])
        self.assertTrue(result['process_diagnostics']['deadline_exceeded'])
        self.assertEqual(2000000, result['process_diagnostics']['stdout_bytes'])

    def test_command_mirrors_runtime_paths_and_preserves_argument_order(self):
        diagnostic = _process_command_diagnostic([
            r'S:\tools\node\node.exe', '--max-old-space-size=512',
            r'S:\tools\npm\node_modules\rea-agents\scripts\rea.mjs',
            'inspect-web-page', '--endpoint', 'http://127.0.0.1:9222',
            '--target-id', 'auth-target', '--observation-ms', '3000'])
        self.assertEqual('<NODE_ROOT>/node.exe', diagnostic['executable'])
        self.assertIn('<REA_RUNTIME_ROOT>', diagnostic['arguments'][1])
        self.assertEqual(['inspect-web-page', '--endpoint', '<BROWSER_CDP_ENDPOINT>',
                          '--target-id', '<BROWSER_TARGET_ID>', '--observation-ms', '3000'],
                         diagnostic['arguments'][2:])
        self.assertNotIn('S:', json.dumps(diagnostic))

    def test_spawn_failure_preserves_its_distinct_stage_without_claiming_execution(self):
        with tempfile.TemporaryDirectory(prefix='rea-spawn-') as directory:
            context = {}
            with self.assertRaises(OSError):
                asyncio.run(_run([str(Path(directory) / 'missing-node.exe')], cwd=directory,
                                 timeout=2, output_limit=16384, context=context))
        self.assertTrue(context['rea_cleanup_confirmed'])
        self.assertFalse(context.get('rea_execution_started', False))
        self.assertEqual('startup', context['rea_process_diagnostics']['stage'])
        self.assertEqual('spawn_failed', context['rea_process_diagnostics']['failure_class'])


if __name__ == '__main__':
    unittest.main()
