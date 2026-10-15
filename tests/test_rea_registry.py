"""Public registry/routing/ledger integration contracts for the REA adapter."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from jsonschema import Draft202012Validator

from copilot_agent.logging_utils import now
from copilot_agent.policy import PathPolicy, PolicyError
from copilot_agent.rea import REA_SPECS, validate_rea
from copilot_agent.research_routing import route_research
from copilot_agent.state import SessionState
from copilot_agent.tools import ToolRegistry, tool_path_policy
from tests.test_rea import evidence


def request(name, arguments, call_id='read'):
    return {'call_id': call_id, 'name': name, 'version': '1.0', 'arguments': arguments,
            'expected_result': 'Observe the bounded synthetic fixture.'}


def write_har(path):
    path.write_text(json.dumps({'log': {'version': '1.2', 'creator': {'name': 'registry-fixture', 'version': '1'},
        'entries': [{'startedDateTime': '2026-10-15T09:00:00Z', 'time': 1,
                     'cache': {}, 'timings': {'send': 0, 'wait': 1, 'receive': 0},
                     'request': {'method': 'GET', 'url': 'https://example.com/api?session=fixture-secret',
                                'httpVersion': 'HTTP/2', 'headersSize': -1, 'bodySize': 0,
                                'headers': [{'name': 'Authorization', 'value': 'Bearer fixture-secret'}],
                                'cookies': [], 'queryString': []},
                     'response': {'status': 200, 'statusText': 'OK', 'httpVersion': 'HTTP/2',
                                  'headersSize': -1, 'bodySize': 30, 'redirectURL': '',
                                  'headers': [], 'cookies': [],
                                  'content': {'size': 30, 'mimeType': 'application/json',
                                              'text': '{"customer":"fixture-private"}'}}}]}}))


class REARegistryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='copilot_rea_registry_')).resolve()
        self.file = self.root / 'input.bin'
        self.file.write_bytes(b'Original approved input')
        self.config = {'root': str(Path(__file__).resolve().parents[1]),
                       'allowed_roots': [str(self.root)], 'allowed_domains': ['example.com'],
                       '_discovery_session': True, 'rea_max_parallel': 1}
        self.state = SessionState(self.root / 'session')
        self.policy = PathPolicy([self.root])
        self.context = {'config': self.config, 'session_dir': str(self.state.directory),
                        'session_state': self.state, 'path_policy': self.policy,
                        'approved_domains': ['example.com'], 'session_path_extensions': [],
                        '_rea_runtime': {}}
        self.registry = ToolRegistry(self.config)
        self.args = {'path': str(self.file), 'kind': 'go'}

    def validate_output(self, tool, output):
        schema = self.registry.definition(tool)['output_schema']
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(output)

    async def test_every_rea_rejection_matches_advertised_output_schema(self):
        for tool, args in [('rea.analyze_artifact', {**self.args, 'command': 'not allowed'}),
                           ('rea.analyze_artifact', {'path': str(self.root.parent / 'outside.exe'), 'kind': 'go'}),
                           ('rea.analyze_capture', {'path': str(self.root / 'missing.har'), 'format': 'har'}),
                           ('rea.inspect_page', {'endpoint': 'http://outside.example'})]:
            with self.subTest(tool=tool, args=args):
                output = await self.registry.execute(tool, args, dict(self.context))
                self.assertFalse(output['ok'])
                self.validate_output(tool, output)
                self.assertFalse(output.get('result', {}).get('side_effects_uncertain', False))

    async def test_preflight_does_not_inherit_previous_call_runtime_markers(self):
        context = dict(self.context, rea_execution_started=True, rea_cleanup_confirmed=False)
        result = await self.registry.execute('rea.analyze_artifact', {**self.args, 'shell': 'forbidden'}, context)
        self.assertFalse(result['ok'])
        self.assertFalse(result['result']['side_effects_uncertain'])

    async def test_disabled_rea_does_not_break_existing_registry_tools(self):
        self.config['rea_enabled'] = False
        outcome = await self.registry.execute('rea.analyze_artifact', self.args, self.context)
        self.assertFalse(outcome['ok'])
        self.assertEqual('unavailable', outcome['result']['status'])
        self.validate_output('rea.analyze_artifact', outcome)
        ordinary = await self.registry.execute('files.metadata', {'path': str(self.file)}, self.context)
        self.assertTrue(ordinary['ok'])
        names = {item['name'] for item in self.registry.definitions()}
        self.assertTrue({'operation.call', 'crawl4ai.crawl', 'browser.recon'} <= names)
        for name in REA_SPECS:
            definition = self.registry.definition(name)
            self.assertFalse(definition['availability']['available'])
            self.assertFalse(definition['input_schema']['additionalProperties'])

    async def test_partial_and_uncertain_registry_results_preserve_their_status(self):
        for status, uncertain in [('partial', False), ('uncertain', True), ('timeout', False), ('cancelled', False)]:
            detail = {'status': status, 'execution_id': 'a' * 32, 'target': str(self.file),
                      'target_type': 'go', 'side_effects_uncertain': uncertain}
            with self.subTest(status=status), patch('copilot_agent.tools.execute_rea', AsyncMock(return_value=detail)):
                output = await self.registry.execute('rea.analyze_artifact', self.args, self.context)
                self.assertFalse(output['ok'])
                self.assertEqual(status, output['result']['status'])
                self.validate_output('rea.analyze_artifact', output)

    def test_read_only_process_uncertainty_is_retained_and_blocks_new_execution(self):
        call = request('rea.analyze_artifact', self.args)
        self.state.begin_call(call, state_changing=False)
        self.state.finish_call('read', {'ok': False, 'tool': call['name'],
            'error': {'code': 'uncertain', 'message': 'Owned process cleanup unconfirmed'},
            'result': {'status': 'uncertain', 'side_effects_uncertain': True}})
        self.assertEqual('uncertain', self.state.data['calls']['read']['status'])
        for name, args in [('rea.analyze_artifact', self.args),
                           ('files.metadata', {'path': str(self.file)}),
                           ('files.create', {'path': str(self.root / 'new.txt'), 'text': 'x'})]:
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                self.state.begin_call(request(name, args, name), state_changing=name == 'files.create')
        inventory = request('browser.tabs', {'operation': 'list'}, 'inventory')
        self.state.begin_call(inventory, state_changing=False)

    def test_interrupted_active_rea_call_stays_uncertain(self):
        self.state.begin_call(request('rea.analyze_artifact', self.args), state_changing=False)
        self.state.fail_active_turn()
        self.assertEqual('uncertain', self.state.data['calls']['read']['status'])

    async def test_exact_approved_file_extension_is_consumed_without_granting_siblings(self):
        external = self.root.parent / (self.root.name + '-external')
        external.mkdir()
        target = external / 'approved.bin'
        target.write_bytes(b'approved external artifact')
        sibling = external / 'unapproved.bin'
        sibling.write_bytes(b'not granted')
        args = {'path': str(target), 'scope': 'file', 'reason': 'Inspect this exact supplied artifact'}
        self.context['approved'] = True
        self.context['reviewed_path_extension'] = self.registry.validate_call('files.grant_path', args, self.context)
        granted = await self.registry.execute('files.grant_path', args, self.context)
        self.assertTrue(granted['ok'], granted)
        prepared = self.registry.validate_call('rea.analyze_artifact', {'path': str(target), 'kind': 'go'}, self.context)
        self.assertEqual(str(target.resolve()), prepared['target'])
        route = self.registry.validate_call('research.route', {'target': str(target), 'target_type': 'go',
                                                              'objective': 'investigate'}, self.context)
        self.assertEqual(str(target.resolve()), route['target'])
        with self.assertRaises(PolicyError):
            self.registry.validate_call('rea.analyze_artifact', {'path': str(sibling), 'kind': 'go'}, self.context)

    def test_changed_local_artifact_invalidates_retained_research_evidence(self):
        prepared = validate_rea('rea.analyze_artifact', self.args, self.context, self.policy)
        retained = self.state.directory / 'rea' / 'evidence.json'
        retained.parent.mkdir()
        retained.write_text('{"status":"completed"}')
        self.state.data['calls']['prior'] = {'request': request('rea.analyze_artifact', self.args),
            'status': 'completed', 'finished_at': now(), 'result': {'ok': True,
                'result': {'status': 'completed', 'target': str(self.file), 'provenance': {'input': prepared['input']},
                           'evidence_path': str(retained),
                           'evidence_sha256': hashlib.sha256(retained.read_bytes()).hexdigest()}}}
        args = {'target': str(self.file), 'target_type': 'go', 'objective': 'investigate'}
        with patch('copilot_agent.research_routing.rea_health', return_value={'available': True}):
            self.assertEqual('reuse_available', route_research(args, self.context, self.policy)['status'])
            self.file.write_bytes(b'Changed after the prior observation')
            self.assertEqual('planned', route_research(args, self.context, self.policy)['status'])

    async def test_shared_runtime_gate_bounds_distinct_execution_contexts(self):
        active, peak = 0, 0
        async def run(*args, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(.02)
            active -= 1
            return {'stdout': evidence(), 'stderr': b'', 'returncode': 0}
        # Real local package health plus an injected invocation boundary. No
        # process or model is required for the distinct-context gate contract.
        health = {'available': True, 'version': '6.5.0', 'node': 'unused-native-runtime',
                  'repository': str(self.root), 'selected_backend': 'node_cli'}
        with patch('copilot_agent.rea.rea_health', return_value=health), \
             patch('copilot_agent.rea._node_health', return_value=health), \
             patch('copilot_agent.rea._run', run):
            outcomes = await asyncio.gather(*(self.registry.execute('rea.analyze_artifact', self.args,
                                                 dict(self.context)) for _ in range(3)))
        self.assertTrue(all(outcome['ok'] for outcome in outcomes), outcomes)
        self.assertEqual(1, peak)


@unittest.skipUnless(os.environ.get('COPILOT_REA_INTEGRATION') == '1', 'Explicit actual local REA registry integration gate')
class REARegistryActualTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_registry_dispatches_har_and_retains_sanitized_evidence(self):
        root = Path(tempfile.mkdtemp(prefix='copilot_rea_registry_actual_')).resolve()
        capture = root / 'fixture.har'
        write_har(capture)
        config = {'root': str(Path(__file__).resolve().parents[1]), 'allowed_roots': [str(root)],
                  'allowed_domains': ['example.com'], 'rea_timeout_seconds': 30}
        registry = ToolRegistry(config)
        context = {'config': config, 'session_dir': str(root / 'session'),
                   'path_policy': PathPolicy([root]), '_rea_runtime': {}}
        outcome = await registry.execute('rea.analyze_capture', {'path': str(capture), 'format': 'har'}, context)
        self.assertTrue(outcome['ok'], outcome)
        Draft202012Validator(registry.definition('rea.analyze_capture')['output_schema']).validate(outcome)
        result = outcome['result']
        self.assertEqual('completed', result['status'])
        self.assertTrue(result['execution_started'])
        self.assertTrue(context['rea_cleanup_confirmed'])
        saved = Path(result['evidence_path']).read_bytes()
        self.assertEqual(hashlib.sha256(saved).hexdigest(), result['evidence_sha256'])
        self.assertNotIn(b'fixture-secret', saved)
        self.assertNotIn(b'fixture-private', saved)
        self.assertIn(b'https://example.com/api', saved)
        self.assertEqual(1, result['findings']['total_records'])


if __name__ == '__main__':
    unittest.main()
