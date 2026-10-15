"""Upstream installation must survive a missing npm/network and redirected roots."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bootstrap import setup_rea as helper


class UpstreamDeliveryTests(unittest.TestCase):
    def test_existing_repository_override_is_verified_reused_and_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            existing = project / 'Projects back' / 'rea'
            with patch.object(helper, 'find_node', return_value=project / 'node.exe'), \
                 patch.object(helper, 'validate_runtime', return_value=True) as validate, \
                 patch.object(helper, 'find_npm', side_effect=AssertionError('reuse must not install')):
                result = helper.provision(project, environ={'COPILOT_REA_REPOSITORY': str(existing)}, require_node=True)
            self.assertTrue(result['reused'])
            self.assertEqual(existing, validate.call_args.args[0])
            saved = json.loads((project / 'config.local.json').read_text())
            self.assertEqual(str(existing), saved['rea_repository'])

    def test_cli_accepts_exact_existing_repository_path(self):
        with patch.object(helper.sys, 'argv', ['setup_rea.py', '--require-node', '--repository', 'S:/Projects back/rea']), \
             patch.object(helper, 'provision', return_value={'available': True}) as provision:
            self.assertEqual(0, helper.main())
        self.assertEqual(str(Path('S:/Projects back/rea')), provision.call_args.kwargs['environ']['COPILOT_REA_REPOSITORY'])

    def test_complete_portable_runtime_does_not_require_npm_or_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            target = project / '.runtime' / 'rea'
            def unpack(archive, destination, **kwargs):
                destination.mkdir(parents=True, exist_ok=True)
                (destination / 'package.json').write_text('{"name":"rea-agents"}')
                self.assertEqual('a' * 64, kwargs['expected_sha256'])
                return destination
            def validate(root, *args):
                if not (root / 'package.json').is_file():
                    raise ValueError('manifest missing')
                return True
            env = {'COPILOT_REA_RUNTIME_ARCHIVE': str(project / 'runtime.zip'),
                   'COPILOT_REA_RUNTIME_SHA256': 'a' * 64}
            with patch.object(helper, 'find_node', return_value=project / 'node.exe'), \
                 patch.object(helper, 'find_npm', side_effect=AssertionError('npm must not run')), \
                 patch.object(helper, 'archive_bytes', side_effect=AssertionError('registry must not run')), \
                 patch.object(helper, 'runtime_candidates', return_value=[target]), \
                 patch.object(helper, 'validate_runtime', side_effect=validate), \
                 patch('bootstrap.rea_delivery.extract_runtime_archive', side_effect=unpack) as extract:
                result = helper.provision(project, environ=env, offline=True, require_node=True)
            self.assertEqual('node_cli', result['backend'])
            self.assertEqual(str(target), result['repository'])
            extract.assert_called_once()
            saved = json.loads((project / 'config.local.json').read_text())
            self.assertEqual(str(target), saved['rea_repository'])

    def test_portable_digest_is_required_before_any_dependency_install(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            with patch.object(helper, 'find_node', return_value=project / 'node.exe'), \
                 patch.object(helper, 'validate_runtime', side_effect=ValueError('missing')), \
                 patch.object(helper, 'find_npm', side_effect=AssertionError('npm must not run')):
                with self.assertRaisesRegex(RuntimeError, 'COPILOT_REA_RUNTIME_SHA256'):
                    helper.provision(project, environ={'COPILOT_REA_RUNTIME_ARCHIVE': str(project / 'runtime.zip')}, require_node=True)


if __name__ == '__main__':
    unittest.main()
