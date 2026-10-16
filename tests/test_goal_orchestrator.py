"""Goal completion/correlation checks through the existing orchestrator seam."""
import json
import unittest

from copilot_agent.goal_navigation import GOAL_SPECS
from copilot_agent.orchestrator import Orchestrator
from tests import test_orchestrator as fixture
from tests.test_protocol_state import FixtureRegistry, make_fixture
from tests.test_goal_navigation import request


class GoalRegistry(FixtureRegistry):
    def __init__(self, result_status):
        super().__init__()
        self.result_status = result_status
        self.steering_queue = None

    def definitions(self):
        return [*super().definitions(), {'name': 'browser.navigate_goal', 'version': '1.0',
                'approval_policy': 'user_approval', 'timeout': 1,
                'input_schema': GOAL_SPECS['browser.navigate_goal'][0]}]

    async def execute(self, name, arguments, context):
        if name != 'browser.navigate_goal':
            return await super().execute(name, arguments, context)
        self.calls.append((name, arguments, context))
        # The transport mock reads attachments as text. This is metadata-only
        # authority testing; real image capture is exercised by browser fixtures.
        picture = context['session_dir'] / 'synthetic-visual.pdf'
        picture.write_text('synthetic image transport fixture', encoding='utf-8')
        context['pending_visual_attachments'].append(str(picture))
        if self.steering_queue is not None:
            self.steering_queue.append({'message_id': 'changed-goal', 'sequence': 1,
                'text': 'Withdraw navigation and acknowledge this changed request.', 'attachments': []})
        return {'ok': True, 'tool': name, 'result': {'status': self.result_status,
                'target_verified': self.result_status == 'target_verified',
                'observation_id': 'a'*64, 'side_effects_uncertain': False,
                'visual_context': {'path': str(picture), 'queued_for_copilot': True}}}


class GoalOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_transport_omits_only_hash_bound_startup_upload_history(self):
        from unittest.mock import AsyncMock
        root, config, state, registry = make_fixture('startup-history-transport-')
        config._automation_test_mode = True
        browser = fixture.MockBrowser([])
        browser.composer_character_limit = AsyncMock(return_value=9000)
        app = Orchestrator(config, browser, registry, state, display=lambda text: None)
        startup = [{'path': path, 'sha256': digest, 'ordinal': 1}
                   for path, digest in app.prompts.bundle['sha256_by_path'].items()]
        user = {'path': '/synthetic/current-user-file.txt', 'sha256': 'b'*64}
        changed = dict(startup[0], sha256='c'*64)
        context = {'requirements': ['exact current task'], 'constraints': ['scope ' + 'x'*7000],
                   'pending_operations': {'pending': {'status': 'uncertain'}},
                   'approval_state': {'grant': 'exact-hash'}, 'attachments': [*startup, user, changed]}
        message = {'protocol_version': '1.0', 'session_id': state.session_id,
                   'request_id': 'current-request', 'kind': 'user_turn',
                   'content': 'exact current task', 'context': context}
        packed, paths = await app._pack_outbound_response(json.dumps(message), [])
        sent = json.loads(packed)
        self.assertEqual([], paths)
        self.assertEqual([user, changed], sent['context']['attachments'])
        for key in ('requirements', 'constraints', 'pending_operations', 'approval_state'):
            self.assertEqual(context[key], sent['context'][key])
        self.assertEqual(len(startup), sent['startup_upload_history_reference']['omitted_records'])

    async def test_large_verified_rea_metadata_uses_startup_reference_without_private_spill(self):
        from unittest.mock import patch
        from copilot_agent.tools import ToolRegistry
        from copilot_agent.state import canonical_hash
        root, config, state, _ = make_fixture('large-rea-transport-')
        config._automation_test_mode = True
        health = {'available': False, 'status': 'unavailable', 'reason': 'Synthetic missing runtime',
                  'diagnostics': ['public repair detail ' * 1500]}
        with patch('copilot_agent.tools.rea_health', return_value=health):
            app = Orchestrator(config, fixture.MockBrowser([]), ToolRegistry(config), state,
                               display=lambda text: None)
        content = 'Read-only discover https://example.com/; keep this exact current task inline.'
        state.data['requirements'] = [content]
        text, _ = app.prompts.build('user_turn', content, 'large-rea-request')
        packed, paths = await app._pack_outbound_response(text, [])
        sent = json.loads(packed)
        self.assertEqual([], paths)
        self.assertEqual(content, sent['content'])
        self.assertEqual(state.data['requirements'], sent['context']['requirements'])
        self.assertEqual(state.data['constraints'], sent['context']['constraints'])
        reference = sent['research_routing']['rea']['details_reference']
        self.assertEqual(canonical_hash(health), reference['sha256'])
        self.assertEqual('tool-catalogue.json', reference['startup_component'])
        self.assertEqual(health, app.prompts.rea_availability)
        self.assertFalse((state.directory / 'tool-results').exists())

    async def test_unregistered_rea_is_not_probed_or_advertised(self):
        from unittest.mock import patch
        from copilot_agent.prompts import PromptBuilder
        root, config, state, registry = make_fixture('no-rea-registry-')
        with patch('copilot_agent.rea.rea_health', side_effect=AssertionError('unregistered probe')):
            builder = PromptBuilder(config, registry, state, None)
        self.assertFalse(builder.rea_availability['available'])
        self.assertEqual('not_registered', builder.rea_availability['status'])

    async def run_case(self, status, steer=False):
        root, config, state, _ = make_fixture('goal-turn-')
        config.rea_enabled = False
        registry = GoalRegistry(status)
        responders = [fixture.final_response,
                      lambda message: fixture.tool_response(message, call_id='goal-call',
                            name='browser.navigate_goal', arguments=request()),
                      fixture.final_response, fixture.final_response, fixture.final_response]
        browser = fixture.MockBrowser(responders)
        queued = []
        if steer:
            registry.steering_queue = queued
        def poll():
            items = list(queued); queued.clear()
            return items
        app = Orchestrator(config, browser, registry, state,
                           approval_decider=lambda preview: 'once', display=lambda text: None,
                           steering_poll=poll if steer else None)
        await app.initialize()
        result = await app.turn('Reach the requested target in the approved website.')
        return result, browser, app

    async def test_unverified_target_cannot_be_claimed_complete(self):
        result, browser, app = await self.run_case('needs_visual_decision')
        self.assertEqual('blocked', result['completion_status'])
        self.assertEqual(5, len(browser.sent))
        self.assertEqual(2, sum('navigation_results' in item['message'].get('content', {})
                                for item in browser.sent if isinstance(item['message'].get('content'), dict)))

    async def test_verified_target_returns_through_original_turn_with_visual_packet(self):
        result, browser, app = await self.run_case('target_verified')
        self.assertEqual('complete', result['completion_status'])
        self.assertEqual(3, len(browser.sent))
        self.assertTrue(browser.sent[-1]['attachments'])
        self.assertIn('navigation_response_style', browser.sent[-1]['message'])
        self.assertIn('browser.navigate_goal', browser.sent[-1]['message']['execution_strategy']['target_navigation'])
        trace = app.performance.path.read_text(encoding='utf-8')
        rows = [json.loads(line) for line in trace.splitlines()]
        self.assertTrue({'tool', 'validation', 'task_total', 'browser_exchange'} <= {r['phase'] for r in rows})
        self.assertNotIn('Reach the requested target', trace)

    async def test_first_useful_preview_is_recorded_once_with_correlation(self):
        result, browser, app = await self.run_case('target_verified')
        from copilot_agent.protocol import BEGIN
        raw = BEGIN + '\n' + json.dumps({'session_id': app.state.session_id,
              'request_id': 'preview-id', 'user_response': 'Next move.'})[:-1]
        event = {'type': 'candidate', 'request_id': 'preview-id', 'raw': raw}
        app._live_feedback(event); app._live_feedback(event)
        marks = [r for r in app.performance.records if r['phase'] == 'first_useful_output']
        self.assertEqual(1, len(marks))

    async def test_steering_withdraws_old_goal_and_invalidates_its_continuations(self):
        result, browser, app = await self.run_case('needs_visual_decision', steer=True)
        self.assertEqual('complete', result['completion_status'])
        self.assertEqual('steering', browser.sent[-1]['message']['kind'])
        self.assertEqual({}, app.browser._goal_navigation)

    async def test_compact_packet_removes_repeated_strategy_but_preserves_constraints_and_ids(self):
        result, browser, app = await self.run_case('target_verified')
        app.state.data['constraints'] = ['Use only the approved synthetic origin.']
        content = {'results': [{'tool': 'browser.navigate_goal', 'ok': True,
                   'result': {'status': 'needs_visual_decision', 'observation_id': 'a'*64}}]}
        compact, _ = app.prompts.build('tool_results', content, 'same-request')
        app.config.compact_navigation = False
        ordinary, _ = app.prompts.build('tool_results', content, 'same-request')
        packet = json.loads(compact)
        self.assertLess(len(compact), len(ordinary))
        self.assertEqual('same-request', packet['request_id'])
        self.assertEqual(app.state.session_id, packet['session_id'])
        self.assertEqual(content, packet['content'])
        self.assertEqual(app.state.data['constraints'], packet['context']['constraints'])
        self.assertIn('scoped_discovery_session', packet)
        self.assertIn('pending_operations', packet['context'])
        self.assertNotIn('automation_packages', packet['execution_strategy'])
        transport = json.loads(ordinary)
        transport['kind'] = 'steering'
        transport['context']['recent_messages'] = [{'role': 'copilot', 'content': 'older evidence ' * 2000}]
        packed, paths = await app._pack_outbound_response(json.dumps(transport), [])
        sent = json.loads(packed)
        self.assertEqual([], paths)
        self.assertEqual(content, sent['content'])
        self.assertEqual(transport['context']['constraints'], sent['context']['constraints'])
        self.assertEqual(transport['context']['pending_operations'], sent['context']['pending_operations'])
        self.assertGreater(sent['older_messages_omitted_for_transport'], 0)
