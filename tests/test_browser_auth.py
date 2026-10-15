"""Offline single-click authentication contracts; no credentials or live sites."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.browser_auth import (
    AUTH_SPECS, CONTROL_STATE, PAGE_STATE, execute_login, validate_login,
)
from copilot_agent.policy import PolicyError


def observation(**changes):
    state = dict(mfa=False, captcha=False, denied=False, credential_fields=True,
                 login_control=True, authenticated_control=False)
    return dict(state, **changes)


class LoginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.control = SimpleNamespace(
            is_visible=AsyncMock(return_value=True), is_enabled=AsyncMock(return_value=True),
            evaluate=AsyncMock(return_value=dict(login_control=True, fields_present=True,
                fields_populated=True, visible=True, enabled=True)), click=AsyncMock())
        self.locator = SimpleNamespace(count=AsyncMock(return_value=1),
                                       element_handle=AsyncMock(return_value=self.control))
        self.page = SimpleNamespace(url='https://fixture.test/login?token=private#secret',
            evaluate=AsyncMock(side_effect=[observation(), observation(
                credential_fields=False, login_control=False, authenticated_control=True)]),
            locator=lambda selector:self.locator)
        self.context = {'config': {'allowed_domains':['fixture.test'], '_discovery_session':True},
                        'session_login_authorized':True, 'login_attempts':{}}
        self.args = {'selector':'#login'}
        self.addCleanup(patch.stopall)
        patch('copilot_agent.browser_auth.get_navigation_page', return_value=self.page).start()
        self.guard = patch('copilot_agent.browser_auth._install_origin_guard', new=AsyncMock()).start()
        patch('copilot_agent.browser_auth.asyncio.sleep', new=AsyncMock()).start()

    async def test_session_authorized_prefilled_login_click_and_verified_transition(self):
        result = await execute_login(self.args,self.context)
        self.assertEqual('completed',result['status'])
        self.control.click.assert_awaited_once_with(timeout=5000,no_wait_after=True)
        self.assertTrue(result['evidence']['authenticated_signout_control_observed'])
        self.assertIn('https://fixture.test',self.context['login_attempts'])
        self.assertFalse(result['side_effects_uncertain'])
        self.assertNotIn('private',str(result))
        self.assertNotIn('secret',str(result))
        self.guard.assert_awaited_once()

    async def test_exact_approval_works_without_session_grant(self):
        self.context.update(session_login_authorized=False,approved=True)
        self.assertEqual('completed',(await execute_login(self.args,self.context))['status'])

    async def test_grant_requires_discovery_session_and_current_context_authorization(self):
        for discovery,authorized in ((False,True),(True,False)):
            self.context['config']['_discovery_session']=discovery
            self.context['session_login_authorized']=authorized
            with self.subTest(discovery=discovery),self.assertRaises(PolicyError):
                await execute_login(self.args,self.context)
        self.control.click.assert_not_awaited()

    async def test_existing_session_login_link_needs_no_credential_fields(self):
        self.control.evaluate.return_value.update(fields_present=False,fields_populated=True)
        self.assertEqual('completed',(await execute_login(self.args,self.context))['status'])

    async def test_mfa_captcha_and_denial_before_click_pause(self):
        for boundary in ('mfa','captcha','denied'):
            self.page.evaluate.side_effect=None
            self.page.evaluate.return_value=observation(**{boundary:True})
            with self.subTest(boundary=boundary):
                result=await execute_login(self.args,self.context)
                self.assertEqual('needs_user_input',result['status'])
                self.assertIn(boundary,result['reason'])
        self.control.click.assert_not_awaited()
        self.assertEqual({},self.context['login_attempts'])

    async def test_empty_fields_never_trigger_click(self):
        self.control.evaluate.return_value['fields_populated']=False
        result=await execute_login(self.args,self.context)
        self.assertEqual('needs_user_input',result['status'])
        self.assertIn('not already populated',result['reason'])
        self.control.click.assert_not_awaited()

    async def test_wrong_button_is_refused_even_with_exact_approval(self):
        self.context['approved']=True
        self.control.evaluate.return_value['login_control']=False
        result=await execute_login(self.args,self.context)
        self.assertEqual('needs_user_input',result['status'])
        self.control.click.assert_not_awaited()

    async def test_duplicate_hidden_or_disabled_button_is_refused(self):
        for attribute,value in (('count',2),('is_visible',False),('is_enabled',False)):
            with self.subTest(attribute=attribute):
                self.page.evaluate.side_effect=None
                self.page.evaluate.return_value=observation()
                target=self.locator if attribute=='count' else self.control
                target_method=getattr(target,attribute)
                prior=target_method.return_value
                target_method.return_value=value
                result=await execute_login(self.args,self.context)
                self.assertEqual('needs_user_input',result['status'])
                target_method.return_value=prior
        self.control.click.assert_not_awaited()

    async def test_duplicate_attempt_never_replays_even_with_new_exact_approval(self):
        await execute_login(self.args,self.context)
        self.context['approved']=True
        result=await execute_login(self.args,self.context)
        self.assertEqual('needs_user_input',result['status'])
        self.assertIn('already consumed',result['reason'])
        self.control.click.assert_awaited_once()

    async def test_unrelated_origin_requires_scope_even_if_click_is_approved(self):
        self.page.url='https://unrelated.test/login'
        self.context['approved']=True
        with self.assertRaises(PolicyError):
            await execute_login(self.args,self.context)
        self.control.click.assert_not_awaited()

    async def test_separately_approved_domain_is_used_by_scope_policy(self):
        self.page.url='https://approved.test/login'
        self.context['approved_domains']=['approved.test']
        self.assertEqual('completed',(await execute_login(self.args,self.context))['status'])

    async def test_click_failure_consumes_attempt_and_returns_uncertain_without_raw_error(self):
        self.control.click.side_effect=RuntimeError('private credential fixture must never be copied')
        result=await execute_login(self.args,self.context)
        self.assertEqual('needs_user_input',result['status'])
        self.assertTrue(result['side_effects_uncertain'])
        self.assertTrue(result['attempted'])
        self.assertNotIn('private credential',str(result))
        again=await execute_login(self.args,self.context)
        self.control.click.assert_awaited_once()
        self.assertIn('already consumed',again['reason'])

    async def test_mfa_denial_after_one_click_require_manual_completion(self):
        for boundary in ('mfa','captcha','denied'):
            self.context['login_attempts'].clear()
            self.page.evaluate.side_effect=[observation(),observation(**{boundary:True})]
            with self.subTest(boundary=boundary):
                result=await execute_login(self.args,self.context)
                self.assertEqual('needs_user_input',result['status'])
                self.assertEqual(boundary,result['evidence']['boundary'])
                self.assertTrue(result['attempted'])
                self.assertFalse(result['side_effects_uncertain'])

    async def test_unknown_success_never_claims_completion(self):
        self.page.evaluate.side_effect=None
        self.page.evaluate.return_value=observation(credential_fields=False,login_control=False)
        result=await execute_login(self.args,self.context)
        self.assertEqual('needs_user_input',result['status'])
        self.assertTrue(result['side_effects_uncertain'])
        self.control.click.assert_awaited_once()

    async def test_navigation_to_new_origin_after_click_needs_user(self):
        async def click(**kwargs):
            self.page.url='https://outside.test/home?token=do-not-log'
        self.control.click.side_effect=click
        result=await execute_login(self.args,self.context)
        self.assertEqual('needs_user_input',result['status'])
        self.assertTrue(result['side_effects_uncertain'])
        self.assertNotIn('do-not-log',str(result))

    async def test_credentials_in_unexpected_redirect_are_never_exported(self):
        async def click(**kwargs):
            self.page.url='https://name:private-password@outside.test/home'
        self.control.click.side_effect=click
        result=await execute_login(self.args,self.context)
        self.assertEqual('needs_user_input',result['status'])
        self.assertEqual('[unavailable]',result['url_after'])
        self.assertNotIn('private-password',str(result))

    async def test_two_parallel_calls_can_consume_only_one_click(self):
        self.page.evaluate.side_effect=None
        self.page.evaluate.return_value=observation()
        results=await asyncio.gather(execute_login(self.args,self.context),execute_login(self.args,self.context))
        self.control.click.assert_awaited_once()
        self.assertTrue(any('already consumed' in result['reason'] for result in results))

    def test_schema_strict_and_bounded(self):
        self.assertEqual({'browser.login_once'},set(AUTH_SPECS))
        for args in ({},{'selector':''},{'selector':'x'*1001},{'selector':'#login','password':'secret'},
                     {'selector':False},{'selector':'#login\nbutton'}):
            with self.subTest(args=args),self.assertRaises(ValueError):
                validate_login(args)

    def test_browser_local_observations_never_return_credential_values_or_raw_page_text(self):
        self.assertIn('fields.every(n=>!!n.value)',CONTROL_STATE)
        self.assertNotIn('value:',CONTROL_STATE)
        self.assertNotIn('value:',PAGE_STATE)


class LoginBrowserTests(unittest.IsolatedAsyncioTestCase):
    """Evaluate the real boolean-only DOM scripts on fully offline HTTPS pages."""
    async def asyncSetUp(self):
        from tests.test_web_navigation import NavigationBrowserTests
        self.fixture=NavigationBrowserTests()
        await self.fixture.asyncSetUp()
        self.addAsyncCleanup(self.fixture.asyncTearDown)
        self.page=self.fixture.page
        self.context=self.fixture.context
        self.context.update(approved=False,session_login_authorized=True,login_attempts={})
        self.context['config']['_discovery_session']=True

    async def test_real_prefilled_form_clicks_once_and_exports_only_transition_evidence(self):
        await self.page.set_content('''<form onsubmit="event.preventDefault();history.pushState({},'', '/home?token=private');document.body.innerHTML='<h1>Home</h1><button>Sign out</button>'">
          <input name=username value=fixture-user><input type=password value=fixture-password>
          <button id=login>Sign in</button></form>''')
        result=await execute_login({'selector':'#login'},self.context)
        self.assertEqual('completed',result['status'])
        self.assertEqual('https://fixture.test/home',result['url_after'])
        for secret in ('fixture-user','fixture-password','token=private'):
            self.assertNotIn(secret,str(result))
        repeated=await execute_login({'selector':'#login'},self.context)
        self.assertEqual('needs_user_input',repeated['status'])

    async def test_real_continue_empty_credentials_and_challenges_are_refused(self):
        for markup in (
            '<button id=login>Continue</button>',
            '<form><input name=username><input type=password><button id=login>Log in</button></form>',
            '<label>Verification code</label><input id=verificationCode><button id=login>Sign in</button>',
            '<h1>Access denied</h1><button id=login>Sign in</button>',
            '<div class=g-recaptcha style="height:40px">Challenge</div><button id=login>Sign in</button>',
        ):
            with self.subTest(markup=markup):
                await self.page.set_content(markup)
                await self.page.evaluate("() => { window.clickCount=0; document.querySelector('#login').onclick=()=>window.clickCount++; }")
                result=await execute_login({'selector':'#login'},self.context)
                self.assertEqual('needs_user_input',result['status'])
                self.assertEqual(0,await self.page.evaluate('window.clickCount'))
                self.assertEqual({},self.context['login_attempts'])


if __name__=='__main__':
    unittest.main()
