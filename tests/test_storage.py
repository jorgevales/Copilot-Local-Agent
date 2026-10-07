"""Isolated storage selection checks; never scan an actual S: drive/account."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from copilot_agent.config import Config, PROJECT_ROOT
from copilot_agent.storage import (OneDriveAccount, default_storage, discover_onedrive_accounts,
                                  machine_key, profile_directory, read_user_settings,
                                  save_user_settings, saved_storage_choice,
                                  shared_python_candidates, validate_storage_directory)


class StorageTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('COPILOT_TEST_ROOT', str(PROJECT_ROOT / 'runtime' / 'test-runs')))
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='storage-', dir=base))
        self.first = self.root / 'OneDrive - Example A'
        self.second = self.root / 'OneDrive - Example B'
        self.first.mkdir()
        self.second.mkdir()
        self.accounts = [OneDriveAccount(self.first.name, self.first), OneDriveAccount(self.second.name, self.second)]

    def test_config_defaults_to_gpt_6_sol(self):
        self.assertEqual('GPT-6 Sol', Config().model)

    def test_discovery_deduplicates_env_and_registry_without_scanning_contents(self):
        accounts = discover_onedrive_accounts({'OneDrive': str(self.first), 'OneDriveCommercial': str(self.first)}, [str(self.second)])
        self.assertEqual([self.first, self.second], [item.path for item in accounts])
        self.assertFalse((self.first / 'Documents' / 'Copilot' / 'Created').exists())
        self.assertFalse((self.second / 'Copilot Agent').exists())

    def test_multiple_accounts_need_choice_until_one_account_has_saved_settings(self):
        self.assertIsNone(saved_storage_choice(self.accounts))
        selected = default_storage(self.accounts[1])
        save_user_settings(selected, {'python_executable': r'S:\Python\python.exe'})
        self.assertEqual(selected, saved_storage_choice(self.accounts))
        self.assertEqual(r'S:\Python\python.exe', read_user_settings(selected)['python_executable'])
        save_user_settings(default_storage(self.accounts[0]), {})
        self.assertIsNone(saved_storage_choice(self.accounts))

    def test_storage_must_be_inside_discovered_account_and_not_the_account_root(self):
        expected = self.first / 'Copilot Agent'
        self.assertEqual(expected, validate_storage_directory(expected, self.accounts))
        for path in (self.first, self.root / 'unrelated', self.first / '..' / 'unrelated'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_storage_directory(path, self.accounts)

    def test_machine_profiles_are_distinct_safe_and_case_consistent(self):
        self.assertEqual(machine_key('VDI-A'), machine_key('vdi-a'))
        self.assertNotEqual(machine_key('VDI-A'), machine_key('VDI-B'))
        selected = self.first / 'Copilot Agent'
        path = profile_directory(selected, 'unsafe/hostname:token')
        self.assertTrue(path.is_relative_to(selected / 'runtime' / 'edge-profiles'))
        self.assertRegex(path.name, r'^vdi-[0-9a-f]{16}$')

    def test_personal_settings_preserve_older_versions_without_shared_source_writes(self):
        selected = self.first / 'Copilot Agent'
        save_user_settings(selected, {'config': {'model': 'synthetic-model'}})
        save_user_settings(selected, {'config': {'model': 'new-synthetic-model'}})
        self.assertEqual('new-synthetic-model', read_user_settings(selected)['config']['model'])
        self.assertTrue(list((selected / '.history' / 'settings.json').glob('*.bak')))
        self.assertFalse((self.root / 'config.local.json').exists())

    def test_shared_python_filter_is_pure_s_only_deduplicated(self):
        paths = [r'S:\Python\python.exe', r's:\python\PYTHON.EXE', r'C:\Python\python.exe',
                 r'S:\Python\pythonw.exe', r'\\server\share\python.exe', 'python.exe']
        self.assertEqual([r'S:\Python\python.exe'], shared_python_candidates(paths))
        self.assertIn(r'C:\Python\python.exe', shared_python_candidates(paths, require_shared=False))

    def test_config_selected_storage_separates_source_and_mutable_paths(self):
        source = self.root / 'shared-source'
        source.mkdir()
        selected = self.first / 'Copilot Agent'
        config = Config(root=source)
        config.validate()
        with patch('copilot_agent.config.discover_onedrive_accounts', return_value=self.accounts):
            config.select_storage(selected)
        self.assertEqual(source, config.root)
        self.assertEqual(selected / 'runtime', config.runtime_dir)
        self.assertEqual(selected / 'workspace', config.workspace_dir)
        self.assertEqual([str(selected / 'workspace'), str(selected / 'deliveries')], config.allowed_roots)
        self.assertTrue(config.profile_dir.is_relative_to(selected / 'runtime' / 'edge-profiles'))
        self.assertFalse((source / 'runtime').exists())

    def test_explicit_custom_root_test_fixture_keeps_isolated_runtime(self):
        config = Config(root=self.root, profile_dir=self.root / 'profile', allowed_roots=[str(self.root / 'workspace')])
        config.validate()
        self.assertEqual(self.root / 'runtime', config.runtime_dir)
        self.assertEqual(self.root / 'profile', config.profile_dir)

    def test_config_load_restores_only_saved_discovered_account(self):
        selected = self.first / 'Copilot Agent'
        save_user_settings(selected, {})
        with patch('copilot_agent.config.discover_onedrive_accounts', return_value=self.accounts):
            config = Config.load()
        self.assertEqual(selected, config.storage_dir)
        self.assertEqual(selected / 'runtime', config.runtime_dir)

    def test_config_load_does_not_autochoose_between_unselected_accounts(self):
        with patch('copilot_agent.config.discover_onedrive_accounts', return_value=self.accounts):
            config = Config.load()
        self.assertIsNone(config.storage_dir)
        self.assertFalse((self.first / 'Copilot Agent').exists())
        self.assertFalse((self.second / 'Copilot Agent').exists())

    def test_custom_source_cannot_bypass_loaded_storage_policy(self):
        path = self.root / 'invalid-storage.json'
        path.write_text(json.dumps({'root': str(self.root / 'custom-source'),
                                    'storage_dir': str(self.root / 'outside-account')}), encoding='utf-8')
        with patch('copilot_agent.config.discover_onedrive_accounts', return_value=self.accounts), self.assertRaises(ValueError):
            Config.load(path)

    def test_select_storage_rejects_unrelated_directory_even_for_custom_source(self):
        config = Config(root=self.root / 'custom-source')
        with patch('copilot_agent.config.discover_onedrive_accounts', return_value=self.accounts), self.assertRaises(ValueError):
            config.select_storage(self.root / 'unrelated')
