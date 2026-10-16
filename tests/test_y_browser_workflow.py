"""Y task changes, exactly-once effects, and preflight certainty."""
import unittest
from unittest.mock import patch
from copilot_agent.tools import ToolRegistry
from copilot_agent.state import SessionState
from copilot_agent.policy import PolicyError
from copilot_agent.web_navigation import get_navigation_page, plan_hash
from tests import test_web_navigation as fixtures


class YBrowserWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = fixtures.NavigationBrowserTests()
        await self.fixture.asyncSetUp()
        self.page, self.context = self.fixture.page, self.fixture.context
        self.context['config']['allowed_roots'] = [str(self.context['session_dir'])]
        self.context['task_id'] = 'original-navigation-task'
        self.state = SessionState(self.context['session_dir'] / 'ledger')
        self.registry = ToolRegistry()
        await self.page.set_content('<h1 id="overview">Overview — synthetic instruction</h1>'
            '<button id="take" type="button" onclick="window.clicks=(window.clicks||0)+1;'
            'document.querySelector(\'#ownership\').textContent=\'Owned\';this.hidden=true">TAKE OWNERSHIP</button>'
            '<p id="ownership">Unowned</p>')
        get_navigation_page(self.context)

    async def asyncTearDown(self):
        await self.fixture.asyncTearDown()

    def plan(self, task='unrelated-new-task-label'):
        expected = [{'kind': 'text', 'locator': {'id': 'ownership'}, 'value': 'Owned'}]
        return {'task_id': task, 'steps': [
            {'id': 'verify', 'op': 'assert', 'expect': [{'kind': 'text', 'locator': {'id': 'overview'},
               'value': 'Overview — synthetic instruction'}]},
            {'id': 'take', 'op': 'click', 'locator': {'id': 'take'}, 'effect': 'consequential', 'expect': expected}],
            'success': expected}

    async def run_plan(self, args, call_id):
        self.context['consequential_approved_plan_hash'] = plan_hash(args)
        call = {'call_id': call_id, 'name': 'browser.plan', 'version': '1.0', 'arguments': args}
        self.state.begin_call(call, state_changing=True)
        result = await self.registry.execute(call['name'], args, self.context)
        self.state.finish_call(call_id, result)
        return result

    async def test_y_allows_changed_task_label_and_consequential_action_once(self):
        self.context['config']['_session_plan_approval'] = True
        result = await self.run_plan(self.plan(), 'take-once')
        self.assertTrue(result['ok'], result)
        self.assertEqual('verified', result['result']['status'])
        self.assertEqual(1, await self.page.evaluate('window.clicks'))
        self.assertFalse(await self.page.locator('#take').is_visible())

    async def test_denied_preflight_is_not_started_and_does_not_poison_corrected_call(self):
        result = await self.run_plan(self.plan(), 'denied')
        self.assertEqual('policy_denied', result['error']['code'])
        self.assertEqual({'status': 'not_started', 'side_effects_uncertain': False}, result['result'])
        self.assertEqual('completed', self.state.data['calls']['denied']['status'])
        self.assertFalse(await self.page.evaluate('!!window.clicks'))
        corrected = await self.run_plan(self.plan('original-navigation-task'), 'corrected')
        self.assertTrue(corrected['ok'], corrected)
        self.assertEqual(1, await self.page.evaluate('window.clicks'))

    async def test_post_click_policy_failure_stays_uncertain(self):
        self.context['config']['_session_plan_approval'] = True
        async def capture(page, context, label, phase, action_id):
            if phase == 'after':
                raise PolicyError('Synthetic post-click policy boundary')
        with patch('copilot_agent.automatic_visuals.capture_action_phase', new=capture):
            result = await self.run_plan(self.plan(), 'post-click')
        self.assertFalse(result['ok'])
        self.assertTrue(result['result']['side_effects_uncertain'])
        self.assertEqual('uncertain', self.state.data['calls']['post-click']['status'])
        self.assertEqual(1, await self.page.evaluate('window.clicks'))

    def test_semantic_argument_errors_are_rejected_before_dispatch(self):
        invalid = self.plan()
        invalid['steps'][1].pop('expect')
        with self.assertRaisesRegex(ValueError, 'postconditions'):
            self.registry.validate_input('browser.plan', invalid)
        with self.assertRaisesRegex(ValueError, 'Target needs'):
            self.registry.validate_input('browser.navigate_goal', {'task_id': 'next', 'goal': 'Overview',
                'success': [{'kind': 'url', 'value': 'https://fixture.test/overview'}]})

    async def test_y_does_not_allow_another_customer_binding(self):
        self.context['config']['_session_plan_approval'] = True
        self.context['customer_key'] = 'verified-record'
        with self.assertRaisesRegex(PolicyError, 'customer'):
            get_navigation_page(self.context, task_id='new-task', customer_key='different-record')

    async def test_transient_server_error_waits_for_automatic_recovery_without_click(self):
        from copilot_agent.web_navigation import _boundary
        await self.page.set_content('<h1>Bad gateway</h1><script>setTimeout(()=>{document.body.innerHTML="<h1>Overview</h1>"},250)</script>')
        result = await _boundary(self.page, self.context)
        self.assertEqual('ready', result['state'])
        self.assertFalse(await self.page.evaluate('!!window.clicks'))

    async def test_text_postconditions_verify_business_input_values_but_reject_credentials(self):
        from copilot_agent.web_navigation import _assertion
        await self.page.set_content('<label for="name">Name</label><input id="name" value="Synthetic patient">'
                                    '<input id="password" type="password" value="synthetic">')
        self.assertTrue(await _assertion(self.page, {'kind': 'text', 'locator': {'id': 'name'},
                                                   'value': 'Synthetic patient'}, self.context))
        with self.assertRaises(PolicyError):
            await _assertion(self.page, {'kind': 'text', 'locator': {'id': 'password'}, 'value': 'synthetic'}, self.context)

    def test_invalid_plan_reports_exact_step_and_assertion_location(self):
        invalid = self.plan()
        invalid['steps'][1]['expect'] = [{'kind': 'visible'}]
        with self.assertRaisesRegex(ValueError, r'steps\[take\].*expect.visible.locator'):
            self.registry.validate_input('browser.plan', invalid)

    async def test_y_can_capture_authorized_business_form_value(self):
        self.context['config']['_session_plan_approval'] = True
        await self.page.set_content('<input id="name" value="Synthetic patient">')
        result = await self.run_plan({'task_id': 'new-form-task', 'steps': [
            {'id': 'read-name', 'op': 'capture', 'locator': {'id': 'name'}}],
            'success': [{'kind': 'text', 'locator': {'id': 'name'}, 'value': 'Synthetic patient'}]}, 'read-form')
        self.assertTrue(result['ok'], result)
        self.assertEqual('Synthetic patient', result['result']['results'][0]['capture'])

    async def test_missing_owned_page_is_recoverable_resource_failure_not_authorization_denial(self):
        self.context['config']['_session_plan_approval'] = True
        self.context['browser'].tool_page = None
        result = await self.run_plan(self.plan(), 'missing-page')
        self.assertEqual('browser_unavailable', result['error']['code'])
        self.assertEqual('not_started', result['result']['status'])
        self.assertFalse(result['result']['side_effects_uncertain'])
