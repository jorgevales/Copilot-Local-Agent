"""Scoped session behavior through real orchestration, registry and local grants."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.approvals import ApprovalManager
from copilot_agent.orchestrator import Orchestrator
from copilot_agent.policy import PolicyError
from copilot_agent.session_mode import configure_session, discovery_mode, website_policy, START_PROMPT
from copilot_agent.site_knowledge import session_knowledge_authorized
from copilot_agent.state import SessionState
from copilot_agent.tools import ToolRegistry
from tests.test_orchestrator import MockBrowser, final_response, tool_response
from tests.test_protocol_state import make_fixture


class ScopedSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch('copilot_agent.policy.mapped_s_drive_root',side_effect=PolicyError('Offline fixture')).start()
        patch('copilot_agent.config.mapped_s_drive_root',side_effect=PolicyError('Offline fixture')).start()

    def fixture(self,responders=(),decide=None):
        root,config,state,_=make_fixture('scoped-research-')
        config.allowed_domains=[]
        configure_session(config,True)
        registry=ToolRegistry()
        browser=MockBrowser(responders)
        browser.authorize_tool_domain=lambda domain:None
        decider=decide or AsyncMock(return_value='deny')
        app=Orchestrator(config,browser,registry,state,approval_decider=decider,display=lambda text:None)
        return root,config,state,registry,browser,app,decider

    async def test_user_named_public_target_is_seeded_through_real_turn(self):
        _,config,state,_,_,app,decide=self.fixture([final_response,final_response])
        await app.initialize()
        await app.turn('Investigate https://docs.example.com/getting-started and report the useful paths.')
        self.assertEqual(['docs.example.com'],state.data['approved_domains'])
        self.assertIn('docs.example.com',app.navigation_domains)
        self.assertEqual({'https://docs.example.com'},config._session_approved_origins)
        decide.assert_not_awaited()

    def test_target_seeding_excludes_private_local_ip_and_injected_credentials(self):
        _,config,state,_,_,app,_=self.fixture()
        app._authorize_user_targets('Check https://127.0.0.1/ https://10.0.0.1/ https://intranet/ '
            'https://app.internal/ https://app.local/ https://user:secret@external.example/ '
            'http://external.example/ https://external.example:8443/')
        self.assertEqual([],state.data['approved_domains'])
        self.assertEqual(set(),config._session_approved_origins)

    def test_external_and_private_scope_requires_new_approval(self):
        _,config,state,registry,_,app,_=self.fixture()
        app._authorize_user_targets('Use https://docs.example.com/')
        policy=website_policy(config,state.data['approved_domains'])
        self.assertEqual('https://docs.example.com/guide',policy.resolve('https://docs.example.com/guide'))
        for url in ('https://unrelated.example/','https://127.0.0.1/','https://intranet/'):
            with self.subTest(url=url),self.assertRaises(PolicyError):
                policy.resolve(url)
        self.assertFalse(app.base_context['approved'])

    def test_fresh_resumed_orchestrator_does_not_restore_saved_target_or_login_grants(self):
        _,config,state,registry,browser,app,_=self.fixture()
        app._authorize_user_targets('Use https://docs.example.com/')
        app.base_context['login_attempts']['https://docs.example.com']={'attempted':True}
        state.data['approved_domains']=['docs.example.com']
        state.save()
        resumed=SessionState(state.directory,resume=True)
        configure_session(config,False)  # Fresh startup declined the new session grant.
        restarted=Orchestrator(config,browser,registry,resumed,display=lambda text:None)
        self.assertEqual([],resumed.data['approved_domains'])
        self.assertFalse(discovery_mode(config))
        self.assertEqual(set(),config._session_approved_origins)
        self.assertEqual(set(),restarted.navigation_domains)
        self.assertEqual({},restarted.base_context['login_attempts'])
        self.assertFalse(session_knowledge_authorized(restarted.base_context))
        self.assertFalse(ApprovalManager(resumed).discovery_session)

    def test_automatic_knowledge_grant_is_bound_to_session_and_approval_hash_and_revocable(self):
        _,config,_,_,_,app,_=self.fixture()
        context=dict(app.base_context)
        self.assertTrue(session_knowledge_authorized(context))
        changed_hash=dict(context,approval_hash='a'*64)
        changed_session=dict(context,session_dir=Path(context['session_dir'])/'other-session')
        self.assertFalse(session_knowledge_authorized(changed_hash))
        self.assertFalse(session_knowledge_authorized(changed_session))
        app.approvals.revoke_session_grants()
        self.assertFalse(discovery_mode(config))
        self.assertFalse(session_knowledge_authorized(context))

    async def test_file_write_is_denied_without_exact_approval_despite_session_grant(self):
        root,config,state,_,_,app,decide=self.fixture([
            final_response,
            lambda message:tool_response(message,'write','files.create',{'path':'pending.txt','text':'fixture'}),
            final_response])
        config._automation_test_mode=True  # Explicit isolated local fixture; approvals remain active.
        await app.initialize()
        await app.turn('Apply the requested workspace change.')
        decide.assert_awaited_once()
        self.assertFalse((root/'workspace'/'pending.txt').exists())
        self.assertTrue(any(call.get('result',{}).get('error',{}).get('code')=='approval_denied'
                            for call in state.data['calls'].values()))

    async def test_knowledge_save_dispatch_receives_automatic_bound_grant_without_prompt(self):
        _,_,_,_,_,app,decide=self.fixture([
            final_response,
            lambda message:tool_response(message,'remember','knowledge.note',
                {'title':'Verified navigation','content':'Open the documents menu to reach the list.'}),
            final_response])
        contexts=[]
        def save(name,args,context):
            contexts.append(dict(context))
            return {'status':'completed','note_id':'a'*64,'verified':True,'knowledge_saved':True}
        with patch('copilot_agent.knowledge_notes.execute_note',side_effect=save):
            await app.initialize()
            await app.turn('Remember the concise verified navigation method.')
        self.assertEqual(1,len(contexts))
        self.assertTrue(contexts[0]['approved'])
        self.assertTrue(session_knowledge_authorized(contexts[0]))
        decide.assert_not_awaited()

    async def test_revoking_session_removes_automatic_knowledge_write_authority(self):
        _,_,_,_,_,app,decide=self.fixture([
            final_response,
            lambda message:tool_response(message,'after-revoke','knowledge.note',
                {'title':'Verified navigation','content':'Open the documents menu to reach the list.'}),
            final_response])
        app.approvals.revoke_session_grants()
        with patch('copilot_agent.knowledge_notes.execute_note',return_value={'status':'completed'}) as save:
            await app.initialize()
            await app.turn('Remember the concise verified navigation method.')
        decide.assert_awaited_once()
        save.assert_not_called()
        self.assertFalse(app.base_context['local_navigation_grant'].approved)

    async def test_auth_dispatch_uses_scoped_session_grant_and_shared_once_ledger(self):
        _,_,state,_,browser,app,decide=self.fixture([
            final_response,
            lambda message:tool_response(message,'login','browser.login_once',{'selector':'#login'}),
            final_response])
        owner=object()
        class Page:
            url='https://docs.example.com/login'
            context=owner
            is_closed=lambda self:False
        page=Page()
        control=SimpleNamespace(is_visible=AsyncMock(return_value=True),is_enabled=AsyncMock(return_value=True),
            evaluate=AsyncMock(return_value={'login_control':True,'fields_present':True,'fields_populated':True,
                                            'visible':True,'enabled':True}),click=AsyncMock())
        locator=SimpleNamespace(count=AsyncMock(return_value=1),element_handle=AsyncMock(return_value=control))
        page.locator=lambda selector:locator
        page.evaluate=AsyncMock(side_effect=[
            {'mfa':False,'captcha':False,'denied':False,'credential_fields':True,'login_control':True,'authenticated_control':False},
            {'mfa':False,'captcha':False,'denied':False,'credential_fields':False,'login_control':False,'authenticated_control':True}])
        page.route=AsyncMock()
        page.unroute=AsyncMock()
        browser.tool_page=page
        browser.tool_context=owner
        browser._tool_pages=[page]
        await app.initialize()
        await app.turn('Use https://docs.example.com/ and click its prefilled login once.')
        control.click.assert_awaited_once()
        self.assertIn('https://docs.example.com',app.base_context['login_attempts'])
        self.assertTrue(any(call.get('result',{}).get('result',{}).get('status')=='completed'
                            for call in state.data['calls'].values()))
        decide.assert_not_awaited()

    async def test_option_four_does_not_autoapprove_later_effects_or_changed_plans(self):
        decide=AsyncMock(side_effect=['supervised','deny','deny'])
        _,_,_,_,_,app,_=self.fixture(decide=decide)
        calls=[{'call_id':str(index),'name':'files.create','arguments':{'path':name,'text':'fixture'}}
               for index,name in enumerate(('first.txt','second.txt','changed.txt'))]
        approved=[]
        hashes=[]
        for call in calls:
            allowed,digest=await app.approvals.request({'tool_requests':[call]},call)
            approved.append(allowed)
            hashes.append(digest)
        self.assertEqual([True,False,False],approved)
        self.assertEqual(3,decide.await_count)
        self.assertEqual(3,len(set(hashes)))
        self.assertFalse(app.approvals.supervised_session)
        self.assertFalse(app.approvals.fast_package_session)

    def test_startup_prompt_describes_actual_scope_and_manual_mfa(self):
        for phrase in ('scoped read-only','knowledge saves','login-button click','writes','MFA'):
            self.assertIn(phrase,START_PROMPT)
        _,_,_,_,_,app,_=self.fixture()
        raw,_=app.prompts.build('user_turn','Read the target.','scope-prompt')
        message=json.loads(raw)
        self.assertTrue(message['scoped_discovery_session']['active'])


if __name__=='__main__':
    unittest.main()
