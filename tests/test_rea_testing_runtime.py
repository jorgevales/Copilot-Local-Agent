"""Testing copies inherit provisioned REA paths without inheriting grants."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import version_launcher as launcher
from copilot_agent import config


class ReaTestingRuntimeTests(unittest.TestCase):
    def setUp(self):
        offline = patch.object(config, 'mapped_s_drive_root', side_effect=config.PolicyError('offline fixture'))
        offline.start()
        self.addCleanup(offline.stop)

    def test_launcher_passes_only_curated_runtime_preferences(self):
        with tempfile.TemporaryDirectory() as temporary:
            live = Path(temporary)
            (live / 'config.local.json').write_text(json.dumps({
                'rea_repository': str(live / '.runtime' / 'rea'),
                'rea_node_executable': str(live / 'node.exe'),
                'rea_backend': 'auto', 'rea_enabled': True,
                'rea_node_readiness_timeout_seconds': 180,
                'allowed_domains': ['private.example'], 'knowledge_write': False,
                'root': str(live), 'copilot_url': 'https://private.example'}))
            environment = {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}
            launcher.inherit_rea_runtime(live, environment)
            inherited = json.loads(environment['COPILOT_AGENT_REA_RUNTIME_SETTINGS'])
            self.assertEqual({'rea_repository', 'rea_node_executable', 'rea_backend', 'rea_enabled',
                              'rea_node_readiness_timeout_seconds'}, set(inherited))

    def test_testing_config_inherits_paths_but_keeps_selected_source_and_local_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            testing = root / 'testing'
            testing.mkdir()
            local = testing / 'config.local.json'
            local.write_text('{"rea_backend":"node_cli"}')
            inherited = {'rea_repository': str(root / 'live' / '.runtime' / 'rea'),
                         'rea_node_executable': str(root / 'portable' / 'node.exe'),
                         'rea_backend': 'auto', 'allowed_domains': ['unrelated.example'],
                         'root': str(root / 'live')}
            with patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing',
                                         'COPILOT_AGENT_REA_RUNTIME_SETTINGS': json.dumps(inherited)}), \
                 patch.object(config, 'PROJECT_ROOT', testing):
                result = config.Config.load(local, storage_override=root / 'storage')
            self.assertEqual(inherited['rea_repository'], result.rea_repository)
            self.assertEqual(inherited['rea_node_executable'], result.rea_node_executable)
            self.assertEqual('node_cli', result.rea_backend)
            self.assertEqual(testing.resolve(), result.root)
            self.assertEqual(['example.com'], result.allowed_domains)

    def test_inherited_values_still_require_configuration_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing',
                                         'COPILOT_AGENT_REA_RUNTIME_SETTINGS': '{"rea_repository":"relative/path"}'}):
                with self.assertRaisesRegex(ValueError, 'rea_repository'):
                    config.Config.load(root / 'missing.json', storage_override=root / 'storage')

    def test_live_launch_discards_stale_inherited_preferences(self):
        environment = {'COPILOT_AGENT_EXECUTION_MODE': 'live',
                       'COPILOT_AGENT_REA_RUNTIME_SETTINGS': '{"rea_backend":"python_native"}'}
        launcher.inherit_rea_runtime(Path('unused'), environment)
        self.assertNotIn('COPILOT_AGENT_REA_RUNTIME_SETTINGS', environment)

    def test_testing_launch_passes_runtime_preferences_without_setup(self):
        with tempfile.TemporaryDirectory() as temporary:
            live = Path(temporary).resolve()
            source = live / 'Copilot testing environment' / 'versions' / 'fixture' / 'source'
            source.mkdir(parents=True)
            repository = str(live / '.runtime' / 'rea')
            (live / 'config.local.json').write_text(json.dumps({'rea_repository': repository}))
            with patch.object(launcher, '__file__', str(live / 'version_launcher.py')), \
                 patch.object(launcher, 'choose_source', return_value=source), \
                 patch.object(launcher.subprocess, 'call', return_value=0) as run, \
                 patch.object(sys, 'argv', ['version_launcher.py', '2']):
                self.assertEqual(0, launcher.main())
            run.assert_called_once()
            inherited = json.loads(run.call_args.kwargs['env']['COPILOT_AGENT_REA_RUNTIME_SETTINGS'])
            self.assertEqual(repository, inherited['rea_repository'])
            self.assertEqual(source, run.call_args.kwargs['cwd'])

    def test_live_config_ignores_testing_runtime_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'live',
                                         'COPILOT_AGENT_REA_RUNTIME_SETTINGS': '{"rea_backend":"python_native"}'}):
                result = config.Config.load(root / 'missing.json', storage_override=root / 'storage')
            self.assertEqual('auto', result.rea_backend)


if __name__ == '__main__':
    unittest.main()
