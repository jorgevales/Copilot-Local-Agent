"""Useful partial observations succeed without hiding failed verification."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.logging_utils import now
from copilot_agent.policy import PathPolicy
from copilot_agent.rea import observation_usable, _save
from copilot_agent.research_routing import route_research
from copilot_agent.tools import ToolRegistry


class PartialObservationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / 'input.js'
        self.path.write_text('export const answer = 42;')
        self.config = {'root': self.root, 'rea_backend': 'python_native', 'allowed_roots': [self.root]}
        self.context = {'config': self.config, 'session_dir': str(self.root / 'session'),
                        'path_policy': PathPolicy([self.root]), '_rea_runtime': {}}
        self.registry = ToolRegistry(self.config)

    async def test_real_partial_analysis_is_success_with_gaps(self):
        result = await self.registry.execute('rea.analyze_artifact', {'path': str(self.path), 'kind': 'javascript'}, self.context)
        self.assertTrue(result['ok'], result)
        self.assertEqual('partial', result['result']['status'])
        self.assertTrue(result['result']['observation_verified'])
        self.assertFalse(result['result']['coverage_complete'])
        self.assertTrue(result['result']['limitations'])
        self.assertTrue(result['result']['findings'])
        self.assertNotIn('error', result)

    async def test_changed_input_is_not_successful_partial(self):
        async def changed(*args, **kwargs):
            self.path.write_text('export const changed = 2;')
            return {'stdout': b'{"status":"partial","findings":{"count":1}}', 'stderr': b'', 'returncode': 0}
        with patch('copilot_agent.rea._run', side_effect=changed):
            result = await self.registry.execute('rea.analyze_artifact', {'path': str(self.path), 'kind': 'javascript'}, self.context)
        self.assertFalse(result['ok'])
        self.assertEqual('partial', result['result']['status'])
        self.assertFalse(result['result']['observation_verified'])

    def test_empty_failed_unverified_and_uncertain_partials_do_not_succeed(self):
        base = {'status': 'partial', 'observation_verified': True, 'findings': {'count': 1}}
        self.assertTrue(observation_usable(base))
        for update in ({'findings': {}}, {'observation_verified': False}, {'side_effects_uncertain': True},
                       {'error': {'code': 'failed'}}, {'status': 'cancelled'}, {'status': 'timeout'}):
            with self.subTest(update=update):
                self.assertFalse(observation_usable(dict(base, **update)))

    async def test_verified_partial_evidence_is_reused_with_limitations(self):
        result = await self.registry.execute('rea.analyze_artifact', {'path': str(self.path), 'kind': 'javascript'}, self.context)
        self.assertTrue(result['ok'], result)
        state = SimpleNamespace(data={'calls': {'previous': {
            'request': {'name': 'rea.analyze_artifact', 'arguments': {'path': str(self.path), 'kind': 'javascript'}},
            'status': 'completed', 'finished_at': now(), 'result': result}}})
        context = dict(self.context, session_state=state, _rea_availability={'available': True})
        route = route_research({'target': str(self.path), 'target_type': 'javascript', 'objective': 'investigate'}, context, self.context['path_policy'])
        self.assertEqual('reuse_available', route['status'], route)
        self.assertEqual('partial', route['retained_evidence']['status'])
        self.assertFalse(route['retained_evidence']['coverage_complete'])
        self.assertTrue(route['retained_evidence']['limitations'])

    def test_readiness_and_analysis_have_separate_budgets(self):
        with patch('copilot_agent.tools.rea_health', return_value={'available': True}):
            definitions = ToolRegistry(dict(self.config, rea_backend='auto')).definition('rea.analyze_artifact')
        self.assertEqual(180, definitions['limits']['readiness_timeout_seconds'])
        self.assertEqual(45, definitions['limits']['analysis_timeout_seconds'])
        self.assertEqual(237, definitions['limits']['timeout_seconds'])

    def test_complete_path_restoration_cannot_exceed_output_budget_as_success(self):
        result = _save({'execution_id': 'a' * 32, 'backend': 'python_native', 'tool': 'rea.analyze_artifact',
                        'target': str(self.path), 'target_type': 'javascript', 'status': 'partial',
                        'observation_verified': True, 'side_effects_uncertain': False,
                        'findings': {'inventory': ['x' * 1000] * 40}},
                       dict(self.context, config=dict(self.config, rea_max_output_bytes=16384)))
        self.assertEqual('output_limit', result['status'])
        self.assertFalse(observation_usable(result))
        self.assertEqual(str(self.path), result['target'])
