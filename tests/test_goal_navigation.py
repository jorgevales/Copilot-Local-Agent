"""Real-browser offline fixtures for the registered goal continuation interface."""
import json
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.goal_navigation import validate_goal, execute_goal, page_lock
from copilot_agent.tools import ToolRegistry
from copilot_agent.policy import PathPolicy
from copilot_agent.reconciliation import navigation_scope_allows, _navigation_only
from tests import test_web_navigation as fixture


def request():
    return {'task_id': 'goal-documents', 'goal': 'Reach Documents',
            'success': [{'kind': 'url', 'value': 'https://fixture.test/documents'},
                        {'kind': 'text', 'locator': {'role': 'heading', 'name': 'Documents'}, 'value': 'Documents'}]}


def document_step():
    return {'id': 'documents', 'op': 'click', 'locator': {'id': 'documents'},
            'effect': 'navigation', 'expect': [{'kind': 'url', 'value': 'https://fixture.test/documents'}]}


class GoalSchemaTests(unittest.TestCase):
    def test_requires_rendered_target_and_rejects_effects_and_missing_observation(self):
        validate_goal(request())
        bad = []
        only_url = request(); only_url['success'] = only_url['success'][:1]; bad.append(only_url)
        missing = request(); missing['steps'] = [document_step()]; bad.append(missing)
        form = request(); form.update(observation_id='a'*64, steps=[dict(document_step(), op='fill', value='private')]); bad.append(form)
        search = request(); search.update(observation_id='a'*64, steps=[dict(document_step(), effect='search')]); bad.append(search)
        empty = request(); empty['goal'] = ' '; bad.append(empty)
        cross_tab = request(); cross_tab.update(observation_id='a'*64, steps=[dict(document_step(), tab_id='tab-2')]); bad.append(cross_tab)
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_goal(value)

    def test_unknown_route_accepts_exact_visible_text_without_inventing_url(self):
        value = request(); value['success'] = value['success'][1:]
        validate_goal(value)
        value['success'][0]['value'] = ''
        with self.assertRaises(ValueError):
            validate_goal(value)


class GoalBrowserTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.NavigationBrowserTests.asyncSetUp
    asyncTearDown = fixture.NavigationBrowserTests.asyncTearDown

    async def run_goal(self, args):
        self.context['path_policy'] = PathPolicy([self.context['session_dir']])
        return await ToolRegistry().execute('browser.navigate_goal', args, self.context)

    async def test_registered_visual_continuation_arrives_and_preserves_originals(self):
        args = request()
        observed = await self.run_goal(args)
        self.assertTrue(observed['ok'], observed)
        self.assertEqual('needs_visual_decision', observed['result']['status'])
        self.assertEqual('Documents', observed['result']['candidates'][0]['label'])
        visual = observed['result']['visual_context']
        self.assertTrue(visual['queued_for_copilot'])
        self.assertTrue(visual['compact_current_view'])
        self.assertEqual(1, visual['pictures'])
        from pathlib import Path
        manifest = json.loads(Path(visual['path']).with_suffix('.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(manifest['records']), 3)
        self.assertTrue(all(Path(r['image_path']).is_file() for r in manifest['records']))
        step = document_step(); step['locator'] = observed['result']['candidates'][0]['locator']
        args.update(observation_id=observed['result']['observation_id'], steps=[step])
        outcome = await self.run_goal(args)
        self.assertTrue(outcome['ok'], outcome)
        self.assertEqual('target_verified', outcome['result']['status'])
        self.assertEqual(1, outcome['result']['actions'])
        self.assertEqual('https://fixture.test/documents', self.page.url)

    async def test_stale_observation_never_executes(self):
        args = request()
        observed = await self.run_goal(args)
        await self.page.locator('#query').fill('changed after observation')
        args.update(observation_id=observed['result']['observation_id'], steps=[document_step()])
        outcome = await self.run_goal(args)
        self.assertFalse(outcome['ok'])
        self.assertEqual('stale_observation', outcome['result']['reason'])
        self.assertEqual('https://fixture.test/', self.page.url)
        self.assertFalse(outcome['result']['side_effects_uncertain'])

    async def test_target_stops_burst_before_a_later_action(self):
        args = request()
        observed = await self.run_goal(args)
        step = document_step(); step['locator'] = observed['result']['candidates'][0]['locator']
        args.update(observation_id=observed['result']['observation_id'], steps=[step,
            {'id': 'must-not-execute', 'op': 'navigate', 'url': 'https://fixture.test/',
             'expect': [{'kind': 'url', 'value': 'https://fixture.test/'}]}])
        outcome = await self.run_goal(args)
        self.assertTrue(outcome['ok'], outcome)
        self.assertEqual('target_reached', outcome['result']['plan']['status'])
        self.assertEqual(1, outcome['result']['plan']['completed_steps'])
        self.assertEqual('https://fixture.test/documents', self.page.url)

    async def test_missing_current_image_prevents_action(self):
        with patch('copilot_agent.automatic_visuals.capture_action_phase', AsyncMock(return_value=None)):
            outcome = await execute_goal(request(), self.context)
        self.assertEqual('blocked', outcome['status'])
        self.assertEqual('observation_unstable', outcome['reason'])
        self.assertFalse(outcome['side_effects_uncertain'])

    async def test_login_and_wrong_origin_stop_without_mutation(self):
        await self.page.goto('https://fixture.test/login')
        outcome = await self.run_goal(request())
        self.assertFalse(outcome['ok'])
        self.assertFalse(outcome['result']['side_effects_uncertain'])
        self.assertEqual('authentication_required', outcome['result']['reason'])
        await self.page.goto('https://fixture.test/')
        args = request(); args['success'][0]['value'] = 'https://outside.test/documents'
        outcome = await self.run_goal(args)
        self.assertFalse(outcome['ok'])
        self.assertEqual('https://fixture.test/', self.page.url)

    async def test_authorization_and_grant_are_navigation_only(self):
        args = request()
        call = {'name': 'browser.navigate_goal', 'arguments': args}
        self.assertTrue(navigation_scope_allows(call, self.adapter, ['fixture.test']))
        self.context['approved'] = False
        denied = await self.run_goal(args)
        self.assertFalse(denied['ok'])
        self.context['approved'] = True
        observed = await self.run_goal(args)
        args.update(observation_id=observed['result']['observation_id'], steps=[document_step()])
        self.assertTrue(_navigation_only(call))
        self.assertTrue(navigation_scope_allows(call, self.adapter, ['fixture.test']))
        args['steps'][0]['effect'] = 'consequential'
        self.assertFalse(navigation_scope_allows(call, self.adapter, ['fixture.test']))

    async def test_unknown_route_target_and_no_progress_budget(self):
        args = request(); args['success'] = args['success'][1:]
        first = await self.run_goal(args)
        second = await self.run_goal(args)
        third = await self.run_goal(args)
        self.assertEqual('needs_visual_decision', second['result']['status'])
        self.assertEqual('no_progress', third['result']['reason'])
        args.update(observation_id=first['result']['observation_id'], steps=[document_step()])
        stale = await self.run_goal(args)
        self.assertEqual('stale_observation', stale['result']['reason'])

    async def test_same_page_transaction_lock_is_shared(self):
        self.assertIs(page_lock(self.context, {}), page_lock(dict(self.context), {'tab_id': 'tab-1'}))

    async def test_forged_route_and_changed_budgets_are_rejected(self):
        args = request(); args['max_steps'] = 2
        observed = await self.run_goal(args)
        args.update(observation_id=observed['result']['observation_id'], steps=[
            {'id': 'invented', 'op': 'navigate', 'url': 'https://fixture.test/unobserved',
             'expect': [{'kind': 'url', 'value': 'https://fixture.test/unobserved'}]}])
        result = await self.run_goal(args)
        self.assertFalse(result['ok'])
        self.assertEqual('https://fixture.test/', self.page.url)
        args['steps'] = [document_step()]; args['max_steps'] = 10
        result = await self.run_goal(args)
        self.assertFalse(result['ok'])

    async def test_duplicate_landmark_cannot_be_target_proof(self):
        await self.page.goto('https://fixture.test/documents')
        await self.page.evaluate("() => document.body.insertAdjacentHTML('beforeend', '<h1>Documents</h1>')")
        result = await self.run_goal(request())
        self.assertFalse(result['ok'])
        self.assertNotEqual('target_verified', result['result']['status'])

    async def test_frame_change_invalidates_observation_and_frame_target_is_visible(self):
        args = request()
        observed = await self.run_goal(args)
        await self.page.frame_locator('#embedded').locator('h1').evaluate("n => n.textContent = 'Changed frame'")
        args.update(observation_id=observed['result']['observation_id'], steps=[document_step()])
        result = await self.run_goal(args)
        self.assertEqual('stale_observation', result['result']['reason'])
        target = {'task_id': 'frame-target', 'goal': 'Changed frame', 'success': [
            {'kind': 'text', 'locator': {'role': 'heading', 'frame_selector': '#embedded'}, 'value': 'Changed frame'}]}
        result = await self.run_goal(target)
        self.assertEqual('target_verified', result['result']['status'])

    async def test_unexpected_dialog_stops_before_navigation(self):
        await self.page.evaluate("() => document.body.insertAdjacentHTML('beforeend', '<div role=dialog>Unexpected popup</div>')")
        result = await self.run_goal(request())
        self.assertFalse(result['ok'])
        self.assertEqual('unexpected_dialog', result['result']['reason'])
        self.assertEqual('https://fixture.test/', self.page.url)

    async def test_tenant_change_invalidates_continuation(self):
        args = request()
        observed = await self.run_goal(args)
        self.context['tenant_id'] = 'another-synthetic-tenant'
        step = document_step(); step['locator'] = observed['result']['candidates'][0]['locator']
        args.update(observation_id=observed['result']['observation_id'], steps=[step])
        result = await self.run_goal(args)
        self.assertFalse(result['ok'])
        self.assertFalse(result['result']['side_effects_uncertain'])
        self.assertEqual('https://fixture.test/', self.page.url)

    async def test_failed_postcondition_preserves_uncertainty_without_replay(self):
        args = request()
        observed = await self.run_goal(args)
        step = document_step(); step['locator'] = observed['result']['candidates'][0]['locator']
        step.update(expect=[{'kind': 'url', 'value': 'https://fixture.test/'}])
        args.update(observation_id=observed['result']['observation_id'], steps=[step])
        result = await self.run_goal(args)
        self.assertFalse(result['ok'])
        self.assertEqual('interrupted', result['result']['status'])
        self.assertTrue(result['result']['side_effects_uncertain'])
        self.assertEqual('documents', result['result']['plan']['uncertain_step'])
        self.assertEqual('https://fixture.test/documents', self.page.url)
