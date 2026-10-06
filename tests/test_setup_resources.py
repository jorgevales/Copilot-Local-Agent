"""Exercise resource choices without launching executables or scanning real accounts."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from copilot_agent.config import Config, PROJECT_ROOT
from copilot_agent.setup_resources import choose_account, choose_edge, pasted_path
from copilot_agent.storage import OneDriveAccount, machine_key, read_user_settings


class ResourceSetupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        base=Path(os.environ.get('COPILOT_TEST_ROOT',str(PROJECT_ROOT/'runtime/test-runs')))
        base.mkdir(parents=True,exist_ok=True)
        self.root=Path(tempfile.mkdtemp(prefix='setup-resources-',dir=base))
        self.account=self.root/'OneDrive - Synthetic'
        self.account.mkdir()
        self.accounts=[OneDriveAccount(self.account.name,self.account)]
        self.folder=self.root/'Edge Application'
        self.folder.mkdir()
        self.executable=self.folder/'msedge.exe'
        self.executable.write_bytes(b'fixture only; never executed')
        self.config=SimpleNamespace(attach_existing=False,edge_executable='')
        self.messages=[]

    async def test_account_auto_and_quoted_paste_select_same_registered_root(self):
        for replies in (['',''],['2','"'+str(self.account)+'"']):
            selected=await choose_account(self.accounts,AsyncMock(side_effect=replies),self.messages.append)
            self.assertEqual(self.account,selected.path)
        self.assertFalse((self.account/'Copilot Agent').exists())

    async def test_unknown_or_subfolder_one_drive_paste_cannot_expand_storage(self):
        unrelated=self.root/'unrelated'
        unrelated.mkdir()
        read=AsyncMock(side_effect=['2',str(unrelated),str(self.account/'workspace'),str(self.account)])
        selected=await choose_account(self.accounts,read,self.messages.append)
        self.assertEqual(self.account,selected.path)
        self.assertTrue(any('not a registered' in message for message in self.messages))

    async def test_no_accounts_and_exhausted_selection_fail_without_creating_storage(self):
        with self.assertRaisesRegex(RuntimeError,'Sign in'):
            await choose_account([],AsyncMock(),self.messages.append)
        with self.assertRaisesRegex(RuntimeError,'five attempts'):
            await choose_account(self.accounts,AsyncMock(side_effect=['wrong']*5),self.messages.append)
        self.assertFalse((self.account/'Copilot Agent').exists())

    async def test_edge_manual_file_and_folder_are_validated_then_remembered_per_machine(self):
        for text in ('"'+str(self.executable)+'"',str(self.folder)):
            settings={}
            with patch('copilot_agent.setup_resources.edge.find_edge_executable',return_value=self.executable) as finder:
                await choose_edge(self.config,settings,AsyncMock(side_effect=['2',text]),self.messages.append,force=True)
            finder.assert_called_once_with(str(self.executable))
            self.assertEqual(str(self.executable),settings['edge_executables'][machine_key()])

    async def test_missing_edge_auto_detection_falls_back_to_paste(self):
        settings={}
        def detect(value=None):
            if value is None: raise FileNotFoundError('synthetic unavailable')
            return Path(value)
        with patch('copilot_agent.setup_resources.edge.find_edge_executable',side_effect=detect):
            await choose_edge(self.config,settings,AsyncMock(side_effect=['1',str(self.folder)]),self.messages.append,force=True)
        self.assertEqual(str(self.executable),self.config.edge_executable)

    async def test_edge_wrong_executable_or_relative_path_is_rejected_before_use(self):
        wrong=self.folder/'other.exe'
        wrong.write_bytes(b'fixture')
        read=AsyncMock(side_effect=['2',str(wrong),'msedge.exe',str(self.executable)])
        with patch('copilot_agent.setup_resources.edge.find_edge_executable',return_value=self.executable) as finder:
            await choose_edge(self.config,{},read,self.messages.append,force=True)
        finder.assert_called_once_with(str(self.executable))
        self.assertTrue(any('existing msedge.exe' in message for message in self.messages))

    async def test_saved_edge_reuses_without_prompt_and_existing_session_needs_no_binary(self):
        settings={'edge_executables':{machine_key():str(self.executable)}}
        read=AsyncMock()
        with patch('copilot_agent.setup_resources.edge.find_edge_executable',return_value=self.executable) as finder:
            await choose_edge(self.config,settings,read,self.messages.append)
        finder.assert_called_once_with(str(self.executable))
        read.assert_not_awaited()
        self.config.attach_existing=True
        with patch('copilot_agent.setup_resources.edge.find_edge_executable') as finder:
            await choose_edge(self.config,settings,read,self.messages.append,force=True)
        finder.assert_not_called()
        read.assert_not_awaited()

    def test_manual_paths_require_absolute_values_and_accept_explorer_quotes(self):
        self.assertEqual(self.executable,pasted_path('  "'+str(self.executable)+'"  '))
        for value in ('','msedge.exe','.; do something'):
            with self.subTest(value=value),self.assertRaises(ValueError): pasted_path(value)

    async def test_setup_only_persists_manual_edge_without_starting_browser(self):
        from copilot_agent.app import run
        config=Config(root=self.root)
        config._storage_candidates=self.accounts
        config.select_storage(self.account/'Copilot Agent')
        args=SimpleNamespace(config=None,attach_existing=False,port=None,profile=None,
                             model=None,setup_only=True,resume=None,yes_setup=True)
        with patch('copilot_agent.app.Config.load',return_value=config), \
             patch('copilot_agent.app.ask',AsyncMock(side_effect=['2',str(self.executable)])), \
             patch('copilot_agent.app.BrowserAdapter') as browser, \
             patch('copilot_agent.app.system',self.messages.append):
            await run(args)
        browser.assert_not_called()
        settings=read_user_settings(config.storage_dir)
        self.assertEqual(str(self.executable),settings['edge_executables'][machine_key()])
        self.assertTrue(settings['selected_account'])
