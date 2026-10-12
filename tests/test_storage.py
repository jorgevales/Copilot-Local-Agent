"""Isolated storage selection checks; never scan an actual S: drive/account."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from copilot_agent.config import Config, PROJECT_ROOT
from copilot_agent.storage import (machine_key, profile_directory, read_user_settings,
                                  save_user_settings, shared_python_candidates,
                                  default_local_storage, validate_user_storage_directory)


class StorageTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('COPILOT_TEST_ROOT', str(PROJECT_ROOT / 'runtime' / 'test-runs')))
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='storage-', dir=base))
    def test_config_defaults_to_gpt_6_sol(self):
        self.assertEqual('GPT-6 Sol', Config().model)

    def test_default_storage_uses_local_app_data_without_one_drive(self):
        onedrive = self.root / 'OneDrive - Example'
        onedrive.mkdir()
        self.assertEqual(self.root / 'LocalAppData' / 'CopilotLocalAgent',
                         default_local_storage({'LOCALAPPDATA': str(self.root / 'LocalAppData'),
                                                'OneDrive': str(onedrive)}))

    def test_machine_profiles_are_distinct_safe_and_case_consistent(self):
        self.assertEqual(machine_key('VDI-A'), machine_key('vdi-a'))
        self.assertNotEqual(machine_key('VDI-A'), machine_key('VDI-B'))
        selected = self.root / 'explicit-user-storage'
        path = profile_directory(selected, 'unsafe/hostname:token')
        self.assertTrue(path.is_relative_to(selected / 'runtime' / 'edge-profiles'))
        self.assertRegex(path.name, r'^vdi-[0-9a-f]{16}$')

    def test_personal_settings_preserve_older_versions_without_shared_source_writes(self):
        selected = self.root / 'explicit-user-storage'
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
        selected = self.root / 'explicit-user-storage'
        config = Config(root=source)
        config.validate()
        config.select_storage(selected)
        self.assertEqual(source, config.root)
        self.assertEqual(selected / 'runtime', config.runtime_dir)
        self.assertEqual(selected / 'workspace', config.workspace_dir)
        expected = [str(selected / 'workspace'), str(selected / 'deliveries')]
        if os.name == 'nt':
            expected.append(str(Path('C:/')))
        self.assertEqual(expected, config.allowed_roots)
        self.assertTrue(config.profile_dir.is_relative_to(selected / 'runtime' / 'edge-profiles'))
        self.assertFalse((source / 'runtime').exists())

    def test_explicit_custom_root_test_fixture_keeps_isolated_runtime(self):
        config = Config(root=self.root, profile_dir=self.root / 'profile', allowed_roots=[str(self.root / 'workspace')])
        config.validate()
        self.assertEqual(self.root / 'runtime', config.runtime_dir)
        self.assertEqual(self.root / 'profile', config.profile_dir)

    def test_config_load_defaults_local_without_probing_one_drive(self):
        onedrive = self.root / 'OneDrive - Legacy'
        onedrive.mkdir()
        save_user_settings(onedrive, {'selected_account': True})
        local = self.root / 'LocalAppData' / 'CopilotLocalAgent'
        with patch('copilot_agent.config.default_local_storage', return_value=local):
            config = Config.load()
        self.assertEqual(local, config.storage_dir)
        self.assertEqual(local / 'runtime', config.runtime_dir)
        self.assertNotIn('selected_account', read_user_settings(onedrive))

    def test_config_load_does_not_probe_or_autochoose_one_drive(self):
        local = self.root / 'LocalAppData' / 'CopilotLocalAgent'
        with patch('copilot_agent.config.default_local_storage', return_value=local):
            config = Config.load()
        self.assertEqual(local, config.storage_dir)
        self.assertFalse(hasattr(__import__('copilot_agent.config', fromlist=['*']), 'discover_onedrive_accounts'))

    def test_explicit_storage_path_is_respected_without_one_drive_discovery(self):
        path = self.root / 'invalid-storage.json'
        selected = self.root / 'explicit-user-storage'
        path.write_text(json.dumps({'root': str(self.root / 'custom-source'),
                                    'storage_dir': str(selected)}), encoding='utf-8')
        config = Config.load(path)
        self.assertEqual(selected, config.storage_dir)

    def test_select_storage_accepts_user_supplied_absolute_path(self):
        config = Config(root=self.root / 'custom-source')
        explicit = self.root / 'requested-local-storage'
        config.select_storage(explicit)
        self.assertEqual(explicit, config.storage_dir)
        self.assertEqual(explicit, validate_user_storage_directory(explicit))
        with self.assertRaises(ValueError):
            validate_user_storage_directory(Path(explicit.anchor))
