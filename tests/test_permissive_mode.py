import asyncio
import hashlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from copilot_agent.code_runner import CodeRunner
from copilot_agent.config import Config
from copilot_agent.local_navigation import SessionFileAccessPolicy
from copilot_agent.policy import PathPolicy, PolicyError
from copilot_agent.reconciliation import close_quarantined_tabs
from copilot_agent.session_mode import configure_session, discovery_mode, fast_mode, website_policy
from copilot_agent.site_knowledge import _scope
from copilot_agent.tools import ToolRegistry
from copilot_agent.web_navigation import _same_origin, get_navigation_page


class PermissiveModeTests(unittest.IsolatedAsyncioTestCase):
    def test_single_ephemeral_choice_enables_scoped_discovery_and_keeps_package_review(self):
        config = Config()
        configure_session(config, True)
        self.assertTrue(discovery_mode(config))
        self.assertFalse(fast_mode(config))
        self.assertTrue(config._knowledge_session_confirmed)
        self.assertTrue(config._local_navigation_confirmed)
        self.assertFalse(config._supervised_session)
        self.assertFalse(config._continuous_package_session)
        self.assertTrue(config._package_review_enabled)
        self.assertNotIn('_permissive_session', config.as_dict())
        self.assertNotIn('_discovery_session', config.as_dict())
        configure_session(config, False)
        self.assertFalse(fast_mode(config))
        self.assertFalse(discovery_mode(config))
        self.assertFalse(config._knowledge_session_confirmed)
        self.assertFalse(config._local_navigation_confirmed)
        self.assertTrue(config._package_review_enabled)

    def test_navigation_is_not_bound_to_a_website_or_https_default_port(self):
        config = SimpleNamespace(_permissive_session=True)
        policy = website_policy(config, ['original.example'])
        for url in ('https://outside.example/path', 'http://10.0.0.8:8080/app', 'https://intranet:8443/data'):
            self.assertEqual(url, policy.resolve(url))
            self.assertEqual(url, _same_origin(url, 'https://original.example/', {'config': config}))
        for url in ('file:///C:/data.txt', 'javascript:alert(1)', 'https://user:password@example.com/'):
            with self.assertRaises(PolicyError):
                policy.resolve(url)

    async def test_registered_file_reads_and_edits_need_no_new_directory_grant(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / 'workspace'
            workspace.mkdir()
            target = root / 'business-data.txt'
            target.write_text('original', encoding='utf-8')
            config = {'allowed_roots': [str(workspace)], '_permissive_session': True}
            context = {'config': config, 'session_dir': root / 'runtime', 'approved': True}
            registry = ToolRegistry()
            read = await registry.execute('files.read', {'path': str(target)}, context)
            self.assertTrue(read['ok'], read)
            edited = await registry.execute('files.replace', {'path': str(target), 'text': 'edited',
                'expected_sha256': hashlib.sha256(b'original').hexdigest()}, context)
            self.assertTrue(edited['ok'], edited)
            self.assertEqual('edited', target.read_text(encoding='utf-8'))
            self.assertNotIn('files.delete', {tool['name'] for tool in registry.definitions()})

    def test_file_scope_is_revocable_and_credentials_remain_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / 'workspace'
            workspace.mkdir()
            target = root / 'data.txt'
            target.write_text('synthetic', encoding='utf-8')
            config = SimpleNamespace(_permissive_session=True)
            policy = SessionFileAccessPolicy(PathPolicy([workspace]), lambda: fast_mode(config))
            self.assertEqual(target.resolve(), policy.resolve(target, True))
            with self.assertRaises(PolicyError):
                policy.resolve(root / '.env')
            config._permissive_session = False
            with self.assertRaises(PolicyError):
                policy.resolve(target)

    def test_customer_task_tags_and_origin_do_not_prevent_owned_tab_access(self):
        owner = object()
        first = SimpleNamespace(url='https://one.example/', context=owner, is_closed=lambda: False)
        second = SimpleNamespace(url='https://two.example/customer', context=owner, is_closed=lambda: False)
        browser = SimpleNamespace(tool_page=first, tool_context=owner, _tool_pages=[first, second],
            _navigation_state={'tabs': {'tab-1': {'page': first, 'customer_key': None, 'task_id': None},
                'tab-2': {'page': second, 'customer_key': 'previous', 'task_id': 'previous'}}})
        context = {'browser': browser, 'config': {'_permissive_session': True},
                   'customer_key': 'new', 'task_id': 'new'}
        self.assertIs(second, get_navigation_page(context, 'tab-2', 'new', 'new'))

    def test_navigation_knowledge_does_not_require_a_manual_namespace_binding(self):
        owner = object()
        page = SimpleNamespace(url='https://company.example/profile', context=owner, is_closed=lambda: False)
        browser = SimpleNamespace(tool_page=page, tool_context=owner, _tool_pages=[page], page=object())
        context = {'browser': browser, 'config': {'_permissive_session': True}, 'session_dir': 'session-one'}
        first = _scope('site_knowledge.retrieve', {'origin': 'https://company.example'}, context)
        context['session_dir'] = 'session-two'
        self.assertEqual(first, _scope('site_knowledge.retrieve', {'origin': 'https://company.example'}, context))

    async def test_quarantined_tabs_close_without_closing_chat_current_or_unrelated_tabs(self):
        owner = object()
        def page():
            value = SimpleNamespace(context=owner, closed=False)
            value.is_closed = lambda: value.closed
            async def close():
                value.closed = True
            value.close = AsyncMock(side_effect=close)
            return value
        old, current, chat, unrelated = [page() for _ in range(4)]
        browser = SimpleNamespace(tool_context=owner, tool_page=current, page=chat, chat_page=chat,
            _tool_pages=[old, current, unrelated], _quarantined_tool_pages=[old], _reconciliation_pages={})
        self.assertEqual(1, await close_quarantined_tabs(browser))
        old.close.assert_awaited_once()
        for protected in (current, chat, unrelated):
            protected.close.assert_not_awaited()
        self.assertEqual([], browser._quarantined_tool_pages)

    async def test_quarantined_tab_close_failure_is_retried_on_next_cleanup(self):
        owner = object()
        old = SimpleNamespace(context=owner, closed=False)
        old.is_closed = lambda: old.closed
        async def close():
            old.closed = True
        old.close = AsyncMock(side_effect=[TimeoutError('temporary close failure'), None])
        browser = SimpleNamespace(tool_context=owner, tool_page=object(), page=object(),
            _tool_pages=[old], _quarantined_tool_pages=[old])
        self.assertEqual(0, await close_quarantined_tabs(browser))
        self.assertEqual([old], browser._quarantined_tool_pages)
        old.close.side_effect = close
        self.assertEqual(1, await close_quarantined_tabs(browser))
        self.assertEqual([], browser._quarantined_tool_pages)

    async def test_owned_popups_receive_stable_navigation_ids(self):
        owner = object()
        first = SimpleNamespace(context=owner, url='https://first.example/', is_closed=lambda: False)
        popup = SimpleNamespace(context=owner, url='https://other.example/', is_closed=lambda: False)
        browser = SimpleNamespace(tool_context=owner, tool_page=first,
            _tool_pages=[first, popup], _pending_popup_pages=[popup])
        context = {'browser': browser, 'config': {'_permissive_session': True}}
        self.assertIs(popup, get_navigation_page(context, 'tab-2'))
        self.assertIs(popup, get_navigation_page(context, 'tab-2'))
        self.assertEqual(2, len(browser._navigation_state['tabs']))

    def test_real_python_worker_can_read_and_edit_outside_declared_list_but_cannot_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / 'workspace'
            workspace.mkdir()
            target = root / 'customer.txt'
            target.write_text('original', encoding='utf-8')
            policy = SessionFileAccessPolicy(PathPolicy([workspace]), lambda: True)
            runner = CodeRunner(policy, root / 'runtime')
            def plan(script):
                return {'script': script, 'purpose': 'Synthetic broad read/edit proof', 'language': 'local_python',
                    'working_directory': str(workspace), 'read_paths': [], 'create_paths': [], 'modify_paths': [],
                    'expected_outputs': [], 'commands': [], 'subprocesses': [], 'network_destinations': [],
                    'permissions': ['read_files', 'create_files'], 'risk_summary': 'Synthetic local fixture only',
                    'recovery_notes': 'Retain evidence', 'interpreter': sys.executable, 'arguments': [],
                    'imports': ['pathlib'], 'timeout_seconds': 5, 'max_output_chars': 1000,
                    'expected_effects': ['read and edit synthetic file'], 'viewer_windows': []}
            args = plan('from pathlib import Path\np=Path(' + repr(str(target)) + ')\nprint(p.read_text())\np.write_text("edited")\n')
            prepared = runner.prepare(args)
            result = asyncio.run(runner.run_async(args, prepared['proposal_hash']))
            self.assertEqual('completed', result['status'], result)
            self.assertEqual('edited', target.read_text(encoding='utf-8'))
            delete = plan('from pathlib import Path\nPath(' + repr(str(target)) + ').unlink()\n')
            try:
                prepared = runner.prepare(delete)
                result = asyncio.run(runner.run_async(delete, prepared['proposal_hash']))
                self.assertNotEqual('completed', result['status'])
            except PolicyError:
                pass
            self.assertTrue(target.is_file())
