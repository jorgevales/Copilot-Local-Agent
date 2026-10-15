import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from copilot_agent.config import Config
from copilot_agent.logging_utils import now
from copilot_agent.policy import PathPolicy, PolicyError
from copilot_agent.research_routing import route_research
from copilot_agent.tools import ToolRegistry


class ResearchRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = SimpleNamespace(root=self.root, allowed_domains=['example.com'],
                                      operation_reuse=True, rea_enabled=True)
        self.context = {'config': self.config, 'approved_domains': ['example.com'],
                        'session_dir': self.root, 'session_state': SimpleNamespace(data={'calls': {}})}
        self.policy = PathPolicy([self.root])
        self.health = patch('copilot_agent.research_routing.rea_health', return_value={'available': True, 'status': 'available'})
        self.health.start()
        self.addCleanup(self.health.stop)
        self.args = {'target': 'https://example.com/', 'target_type': 'website', 'objective': 'investigate'}

    def route(self, **updates):
        return route_research(dict(self.args, **updates), self.context, self.policy)

    def prior(self, **updates):
        record = {'request': {'name': 'rea.inspect_page', 'arguments': {}}, 'status': 'completed',
                  'state_changing': False, 'finished_at': now(),
                  'result': {'ok': False, 'result': {'target': self.args['target'], 'status': 'partial',
                                                   'side_effects_uncertain': False}}}
        record.update(updates)
        self.context['session_state'].data['calls']['prior'] = record
        return record

    def test_rea_first_and_complementary_provenance_tools(self):
        result = self.route()
        self.assertEqual('rea.inspect_page', result['preferred'])
        self.assertIn('operation.call', result['complementary'])
        self.assertIn('crawl4ai.crawl', result['complementary'])
        self.assertIn('browser.screenshot', result['complementary'])
        self.assertTrue(result['prerequisites'])

    def test_known_api_and_specialized_objectives_take_precedence(self):
        for objective, expected in [('api', 'operation.list'), ('navigate', 'browser.route'),
                                    ('screenshot', 'browser.screenshot'), ('script', 'browser.javascript')]:
            self.assertEqual(expected, self.route(objective=objective)['preferred'])

    def test_crawl_prefers_existing_extractor_when_installed(self):
        with patch('copilot_agent.research_routing.importlib.util.find_spec', return_value=object()):
            self.assertEqual('crawl4ai.crawl', self.route(objective='crawl')['preferred'])

    def test_disabled_or_unavailable_rea_leaves_existing_stack(self):
        with patch('copilot_agent.research_routing.rea_health', return_value={'available': False, 'status': 'disabled'}):
            self.assertEqual('operation.list', self.route()['preferred'])
            self.config.operation_reuse = False
            with patch('copilot_agent.research_routing.importlib.util.find_spec', return_value=None):
                self.assertEqual('browser.recon', self.route()['preferred'])

    def test_artifact_and_capture_select_typed_static_capability(self):
        path = self.root / 'input.bin'
        path.write_bytes(b'bounded synthetic input')
        for kind in ('har', 'saz', 'managed', 'go', 'rust', 'javascript'):
            expected = 'rea.analyze_capture' if kind in {'har', 'saz'} else 'rea.analyze_artifact'
            self.assertEqual(expected, self.route(target=str(path), target_type=kind)['preferred'])

    def test_partial_rea_fallback_preserves_attempt_reference(self):
        self.prior()
        result = self.route(prior_call_id='prior')
        self.assertEqual('operation.list', result['preferred'])
        self.assertEqual('prior', result['prior_attempt']['call_id'])

    def test_denial_and_uncertainty_cannot_be_bypassed_by_fallback(self):
        for code in ('approval_denied', 'policy_denied'):
            self.prior()['result']['error'] = {'code': code}
            self.assertEqual('blocked', self.route(prior_call_id='prior')['status'])
        self.prior(status='uncertain')
        self.assertIsNone(self.route(prior_call_id='prior')['preferred'])

    def test_prior_result_cannot_claim_another_target(self):
        self.prior()['result']['result']['target'] = 'https://example.com/different'
        with self.assertRaises(PolicyError):
            self.route(prior_call_id='prior')
        with self.assertRaises(PolicyError):
            self.route(prior_call_id='unknown')

    def test_route_does_not_grant_origins_or_local_paths(self):
        for target in ('https://outside.example/', 'file:///sensitive', 'https://user:pass@example.com/'):
            with self.assertRaises(PolicyError):
                self.route(target=target)
        with self.assertRaises(PolicyError):
            self.route(target=str(Path(__file__).resolve()), target_type='har')

    def test_fresh_hash_verified_evidence_reused_and_refresh_overrides(self):
        path = self.root / 'rea' / 'evidence.json'
        path.parent.mkdir()
        path.write_text(json.dumps({'status': 'completed'}))
        record = self.prior()
        record['result'] = {'ok': True, 'result': {'status': 'completed', 'target': self.args['target'],
            'evidence_path': str(path), 'evidence_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}
        self.assertEqual('reuse_available', self.route()['status'])
        self.assertEqual('planned', self.route(refresh=True)['status'])
        path.write_text('changed')
        self.assertEqual('planned', self.route()['status'])

    def test_later_browser_effect_prevents_snapshot_reuse(self):
        self.test_fresh_hash_verified_evidence_reused_and_refresh_overrides()
        self.context['session_state'].data['calls']['later'] = {
            'request': {'name': 'browser.click'}, 'state_changing': True}
        self.assertIsNone(self.route()['retained_evidence'])

    async def test_registry_schemas_reject_shell_and_raw_arguments(self):
        registry = ToolRegistry(self.config)
        for name, args in [('rea.analyze_artifact', {'path': 'x', 'kind': 'managed', 'command': 'anything'}),
                           ('rea.inspect_page', {'endpoint': 'http://outside.example'}),
                           ('research.route', dict(self.args, shell='anything'))]:
            with self.assertRaises(ValueError):
                registry.validate_input(name, args)

    def test_optional_catalogue_has_explicit_health_and_bounded_schemas(self):
        registry = ToolRegistry({'rea_enabled': False})
        definitions = {item['name']: item for item in registry.definitions()}
        self.assertFalse(definitions['rea.inspect_page']['availability']['available'])
        self.assertIn('crawl4ai.crawl', definitions)
        self.assertIn('operation.call', definitions)
        self.assertIn('browser.recon', definitions)
        self.assertFalse(definitions['rea.analyze_capture']['input_schema']['additionalProperties'])

    def test_invalid_trusted_configuration_rejected(self):
        for setting in ({'rea_max_parallel': 999}, {'rea_timeout_seconds': 0},
                        {'rea_repository': 'relative/path'}, {'rea_node_executable': 'node --unsafe'}):
            config = Config(**setting)
            with self.assertRaises(ValueError):
                config.validate()
