"""Large upstream observations and fallback provenance must remain distinguishable."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.policy import PathPolicy
from copilot_agent.rea import _save, execute_rea


class LargeResultTests(unittest.TestCase):
    def test_large_verified_node_observation_is_retained_with_bounded_response(self):
        with tempfile.TemporaryDirectory() as directory:
            result = {'execution_id': 'large', 'backend': 'node_cli', 'tool': 'rea.inspect_page',
                      'status': 'completed', 'side_effects_uncertain': False,
                      'observation_verified': True, 'coverage_complete': True,
                      'target': 'https://example.com/', 'target_type': 'owned_browser',
                      'findings': {'dom': {'total_nodes': 9980, 'nodes': [{'id': i, 'tag': 'div'} for i in range(9980)]}},
                      'evidence': {'evidence_id': 'ev_fixture', 'provider': {'id': 'rea.web-page-inspection'}}}
            context = {'session_dir': directory, 'config': {'rea_max_output_bytes': 16384}}
            actual = _save(result, context)
            self.assertEqual('completed', actual['status'])
            self.assertTrue(actual['response_truncated'])
            artifact = Path(actual['full_evidence_path'])
            content = artifact.read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), actual['full_evidence_sha256'])
            self.assertEqual(9980, len(json.loads(content)['findings']['dom']['nodes']))
            self.assertLessEqual(len(json.dumps(actual, ensure_ascii=True).encode()), 16384)

    def test_auto_uses_full_node_allowance_and_preserves_degraded_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / 'fixture.har'
            capture.write_text('{"log":{"entries":[]}}')
            node = {'execution_id': 'node-attempt', 'backend': 'node_cli', 'status': 'output_limit',
                    'side_effects_uncertain': False, 'failure_stage': 'transport',
                    'process_diagnostics': {'stdout_bytes': 4008122, 'returncode': 0}}
            run = AsyncMock(return_value=node)
            context = {'session_dir': directory, 'config': {'root': str(root), 'rea_timeout_seconds': 45}}
            with patch('copilot_agent.rea._node_health', return_value={'available': True}), \
                 patch('copilot_agent.rea._execute_node', run):
                actual = asyncio.run(execute_rea('rea.analyze_capture', {'path': str(capture), 'format': 'har'}, context, PathPolicy([root])))
            self.assertTrue(actual['degraded'])
            self.assertTrue(actual['fallback_used'])
            self.assertFalse(actual['intended_backend_succeeded'])
            self.assertEqual('node_cli', actual['intended_backend'])
            self.assertEqual(4008122, actual['prior_backend_attempt']['process_diagnostics']['stdout_bytes'])
            self.assertEqual('output_limit', actual['prior_backend_attempt']['status'])
            self.assertEqual(45, run.call_args.args[2]['config']['rea_timeout_seconds'])


if __name__ == '__main__':
    unittest.main()
