"""Known VDI sibling and portable npm layouts must be reusable offline."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from copilot_agent import rea_locations

SPEC = importlib.util.spec_from_file_location('setup_rea_locations', Path(__file__).resolve().parents[1] / 'bootstrap' / 'setup_rea.py')
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class ReaLocationsTests(unittest.TestCase):
    def test_known_layouts_prefer_working_global_package_then_source_repo(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'projects' / 'Copilot-Local-Agent'
            node = root / 'tools' / 'node-v24.x-win-x64' / 'node.exe'
            self.assertEqual([root / 'tools' / 'npm-data' / 'global' / 'node_modules' / 'rea-agents', project.parent / 'REA'],
                             rea_locations.existing_runtime_candidates(project, [node]))
            self.assertEqual([root / 'tools' / 'npm-data' / 'cache'], rea_locations.npm_cache_candidates([node, node]))

    def test_node_aliases_are_normalized_without_broad_filesystem_search(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            node = root / 'tools' / 'portable' / 'node.exe'
            with patch.object(rea_locations, 'node_path_candidates', return_value=[node]) as aliases:
                candidates = rea_locations.existing_runtime_candidates(root / 'projects' / 'agent', ['S:/portable/node.exe'])
            aliases.assert_called_once_with('S:/portable/node.exe')
            self.assertEqual(root / 'tools' / 'npm-data' / 'global' / 'node_modules' / 'rea-agents', candidates[0])

    def test_setup_reuses_working_global_package_before_managed_paths_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'projects' / 'Copilot-Local-Agent'
            project.mkdir(parents=True)
            node = root / 'tools' / 'portable' / 'node.exe'
            existing = (root / 'tools' / 'npm-data' / 'global' / 'node_modules' / 'rea-agents').resolve()
            with patch.object(setup, 'find_node', return_value=node), \
                 patch.object(setup, 'validate_runtime', return_value=True) as validate, \
                 patch.object(setup, 'find_npm') as npm, patch.object(setup, 'archive_bytes') as archive:
                result = setup.provision(project, environ={}, require_node=True)
            self.assertEqual(existing, Path(result['repository']).resolve())
            self.assertEqual(existing, validate.call_args.args[0].resolve())
            npm.assert_not_called()
            archive.assert_not_called()

    def test_setup_uses_existing_portable_cache_only_after_write_verification(self):
        for writable in (True, False):
            with self.subTest(writable=writable), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                project = root / 'projects' / 'agent'
                project.mkdir(parents=True)
                node = root / 'tools' / 'portable' / 'node.exe'
                cache = root / 'tools' / 'npm-data' / 'cache'
                cache.mkdir(parents=True)
                observed = {}
                def acquire(env):
                    observed.update(env)
                    raise RuntimeError('fixture stop before download')
                with patch.object(setup, 'find_node', return_value=node), \
                     patch.object(setup, 'validate_runtime', side_effect=ValueError('missing')), \
                     patch.object(setup, 'find_npm', return_value=root / 'npm-cli.js'), \
                     patch.object(setup, '_verify_scratch', side_effect=None if writable else OSError('unwritable')) as verify, \
                     patch.object(setup, 'archive_bytes', side_effect=acquire):
                    with self.assertRaisesRegex(RuntimeError, 'fixture stop'):
                        setup.provision(project, environ={}, require_node=True)
                verify.assert_called_once()
                self.assertEqual(str(cache) if writable else None, observed.get('npm_config_cache'))


if __name__ == '__main__':
    unittest.main()
