"""Mandatory bundled backend selection without platform installations."""
import unittest
import asyncio
import json
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, patch

from copilot_agent.rea import rea_health
from copilot_agent.policy import PathPolicy
from copilot_agent.rea import execute_rea


class BackendSelectionTests(unittest.TestCase):
    def test_python_only_does_not_discover_node(self):
        with patch('copilot_agent.rea._node_health', side_effect=AssertionError('Node must not be consulted')):
            result = rea_health({'rea_backend': 'python_native'})
        self.assertTrue(result['available'])
        self.assertEqual('python_native', result['selected_backend'])

    def test_auto_recovers_missing_native_and_failed_smoke_backends(self):
        for stage in ('repository', 'node', 'native_verify', 'cli_smoke'):
            with self.subTest(stage=stage), patch('copilot_agent.rea._node_health', return_value={
                    'available': False, 'status': 'unavailable', 'failure_stage': stage}):
                result = rea_health({'rea_backend': 'auto'})
            self.assertTrue(result['available'])
            self.assertEqual('python_native', result['selected_backend'])
            self.assertFalse(result['upstream_available'])
            self.assertEqual('Setup REA.cmd', result['upstream_repair_command'])
            self.assertEqual(stage, result['backends']['node_cli']['failure_stage'])

    def test_auto_recovers_node_validation_exception(self):
        with patch('copilot_agent.rea._node_health', side_effect=OSError(28, 'no space')):
            self.assertEqual('python_native', rea_health({})['selected_backend'])

    def test_auto_prefers_verified_node(self):
        with patch('copilot_agent.rea._node_health', return_value={'available': True, 'version': '6.5.0'}):
            self.assertEqual('node_cli', rea_health({})['selected_backend'])

    def test_both_unhealthy_are_unavailable_and_explicit_node_does_not_override(self):
        with patch('copilot_agent.rea._node_health', return_value={'available': False}), \
             patch('copilot_agent.rea_backends.PythonNativeREABackend.health', return_value={'available': False}):
            self.assertFalse(rea_health({})['available'])
        with patch('copilot_agent.rea._node_health', return_value={'available': False}):
            self.assertFalse(rea_health({'rea_backend': 'node_cli'})['available'])


class BackendExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_clean_node_timeout_falls_back_with_retained_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'fixture.har'
            path.write_text(json.dumps({'log': {'entries': []}}))
            context = {'config': {'root': root, 'rea_backend': 'auto'}, 'session_dir': str(root / 'session')}
            node = {'backend': 'node_cli', 'execution_id': 'a' * 32, 'status': 'timeout',
                    'side_effects_uncertain': False}
            with patch('copilot_agent.rea._node_health', return_value={'available': True}), \
                 patch('copilot_agent.rea._execute_node', new=AsyncMock(return_value=node)):
                result = await execute_rea('rea.analyze_capture', {'path': str(path), 'format': 'har'}, context, PathPolicy([root]))
            self.assertEqual('python_native', result['backend'])
            self.assertIn(result['status'], {'completed', 'partial'})
            self.assertEqual('timeout', result['prior_backend_attempt']['status'])
            saved = json.loads((Path(context['session_dir']) / result['evidence_path']).read_text())
            self.assertEqual(result['prior_backend_attempt'], saved['prior_backend_attempt'])

    async def test_python_static_calls_share_bounded_concurrency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'fixture.js'
            path.write_text('export const count = 1;')
            config = {'root': root, 'rea_backend': 'python_native', 'rea_max_parallel': 2}
            runtime, active, maximum = {}, 0, 0
            async def observe(*args, **kwargs):
                nonlocal active, maximum
                active += 1
                maximum = max(maximum, active)
                await asyncio.sleep(.02)
                active -= 1
                return {'stdout': b'{"status":"completed","findings":{"count":1}}', 'stderr': b'', 'returncode': 0}
            with patch('copilot_agent.rea._run', side_effect=observe):
                results = await asyncio.gather(*(execute_rea('rea.analyze_artifact', {'path': str(path), 'kind': 'javascript'},
                    {'config': config, 'session_dir': str(root / 'session'), '_rea_runtime': runtime}, PathPolicy([root])) for _ in range(5)))
            self.assertEqual(2, maximum)
            self.assertTrue(all(result['status'] == 'completed' for result in results))
