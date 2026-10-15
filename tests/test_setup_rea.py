"""Portable REA provisioning: integrity, archive safety and recovery contracts."""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('setup_rea', Path(__file__).resolve().parents[1] / 'bootstrap' / 'setup_rea.py')
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class ReaSetupTests(unittest.TestCase):
    def make_archive(self, path, entries):
        with tarfile.open(path, 'w:gz') as archive:
            for name, data, kind in entries:
                item = tarfile.TarInfo(name)
                item.type = kind
                item.size = len(data) if kind == tarfile.REGTYPE else 0
                item.linkname = '../escape'
                archive.addfile(item, io.BytesIO(data) if kind == tarfile.REGTYPE else None)

    def test_candidates_keep_project_local_and_temp_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(helper.tempfile, 'gettempdir', return_value=str(root / 'scratch')):
                candidates = helper.runtime_candidates(root / 'project', {'LOCALAPPDATA': str(root / 'local'), 'TEMP': 'ignored-unresolved-alias'})
            self.assertEqual(root / 'project' / '.runtime' / 'rea', candidates[0])
            self.assertEqual(root / 'local' / 'Copilot Local Agent' / 'runtimes' / 'rea' / '6.5.0', candidates[1])
            self.assertEqual(root / 'scratch' / 'Copilot Local Agent' / 'runtimes' / 'rea' / '6.5.0', candidates[2])

    def test_offline_archive_requires_exact_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'rea.tgz'
            archive.write_bytes(b'fixture')
            with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
                helper.archive_bytes({'COPILOT_REA_ARCHIVE': str(archive)})
            digest = base64.b64encode(hashlib.sha512(b'fixture').digest()).decode()
            with patch.object(helper, 'INTEGRITY', digest):
                self.assertEqual(b'fixture', helper.archive_bytes({'COPILOT_REA_ARCHIVE': str(archive)}))

    def test_extract_accepts_regular_package_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_archive(root / 'rea.tgz', [('package/dist/cli.js', b'hello', tarfile.REGTYPE)])
            helper.extract_archive(root / 'rea.tgz', root / 'output')
            self.assertEqual(b'hello', (root / 'output' / 'dist' / 'cli.js').read_bytes())

    def test_extract_rejects_traversal_links_devices_duplicate_and_wrong_prefix(self):
        bad = [('package/../escape', tarfile.REGTYPE), ('package\\escape', tarfile.REGTYPE),
               ('/package/root', tarfile.REGTYPE), ('other/escape', tarfile.REGTYPE),
               ('package/link', tarfile.SYMTYPE), ('package/hard', tarfile.LNKTYPE),
               ('package/device', tarfile.CHRTYPE), ('package/C:escape', tarfile.REGTYPE)]
        for name, kind in bad:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.make_archive(root / 'rea.tgz', [(name, b'x', kind)])
                with self.assertRaisesRegex(ValueError, 'unsafe'):
                    helper.extract_archive(root / 'rea.tgz', root / 'output')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_archive(root / 'rea.tgz', [('package/same', b'x', tarfile.REGTYPE)] * 2)
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                helper.extract_archive(root / 'rea.tgz', root / 'output')

    def test_expansion_budget_enforced_before_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_archive(root / 'rea.tgz', [('package/big', b'abcd', tarfile.REGTYPE)])
            with patch.object(helper, 'MAX_EXPANDED', 3), self.assertRaisesRegex(ValueError, 'expanded size'):
                helper.extract_archive(root / 'rea.tgz', root / 'output')

    def test_disabled_config_never_requires_node_or_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'config.local.json').write_text(json.dumps({'rea_enabled': False}))
            with patch.object(helper, 'find_node') as node, patch.object(helper, 'archive_bytes') as download:
                self.assertTrue(helper.provision(root)['disabled'])
            node.assert_not_called()
            download.assert_not_called()

    def test_existing_healthy_install_skips_npm_and_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(helper, 'find_node', return_value=root / 'node.exe'), \
                 patch.object(helper, 'validate_runtime', return_value=True), \
                 patch.object(helper, 'find_npm') as npm, patch.object(helper, 'archive_bytes') as download:
                result = helper.provision(root, environ={})
            self.assertTrue(result['reused'])
            npm.assert_not_called()
            download.assert_not_called()

    def test_authoritative_override_does_not_reuse_another_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = root / 'selected'
            (root / 'config.local.json').write_text(json.dumps({'rea_repository': str(selected), 'rea_node_executable': str(root / 'node.exe')}))
            with patch.object(helper, 'find_node', return_value=root / 'node.exe') as node, \
                 patch.object(helper, 'validate_runtime', return_value=True) as validate:
                result = helper.provision(root, environ={})
            self.assertEqual(str(selected), result['repository'])
            self.assertEqual(str(root / 'node.exe'), node.call_args.args[0]['COPILOT_REA_NODE'])
            self.assertEqual(selected, validate.call_args.args[0])

    def test_writable_candidate_fallback_and_offline_cache_then_online(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            blocked = root / 'blocked'
            blocked.write_text('not a directory')
            chosen = root / 'working' / 'rea'
            def extract(archive, destination):
                (destination / 'package.json').write_text('{}')
            calls = []
            def run(command, **kwargs):
                calls.append((command, kwargs))
                return SimpleNamespace(returncode=1 if '--offline' in command else 0)
            def validate(path, node, env):
                if path == chosen or path.name == 'package':
                    return True
                raise ValueError('missing')
            with patch.object(helper, 'find_node', return_value=root / 'node.exe'), \
                 patch.object(helper, 'find_npm', return_value=root / 'npm-cli.js'), \
                 patch.object(helper, 'runtime_candidates', return_value=[blocked / 'rea', chosen]), \
                 patch.object(helper, 'validate_runtime', side_effect=lambda path, node, env: True if path.name == 'package' else (_ for _ in ()).throw(ValueError('missing'))), \
                 patch.object(helper, 'archive_bytes', return_value=b'archive'), \
                 patch.object(helper, 'extract_archive', side_effect=extract), \
                 patch.object(helper, '_run_command', side_effect=run):
                result = helper.provision(root, environ={})
            self.assertEqual(str(chosen), result['repository'])
            self.assertTrue((chosen / 'package.json').is_file())
            self.assertEqual(2, len(calls))
            self.assertIn('--offline', calls[0][0])
            self.assertNotIn('--offline', calls[1][0])
            for command, kwargs in calls:
                self.assertIn('--ignore-scripts', command)
                self.assertIn('--omit=optional', command)
                self.assertNotIn('shell', kwargs)
                self.assertTrue(kwargs['env']['npm_config_cache'])
                self.assertLessEqual(kwargs['timeout'], 60)
            self.assertFalse(list(chosen.parent.glob('.rea-install-*')))

    def test_no_offline_archive_is_actionable_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'config.local.json').write_text(json.dumps({'rea_backend': 'node_cli'}))
            with patch.object(helper, 'find_node', return_value=root / 'node.exe'), \
                 patch.object(helper, 'find_npm', return_value=root / 'npm-cli.js'), \
                 patch.object(helper, 'validate_runtime', side_effect=ValueError('missing')), \
                 patch.object(helper, 'archive_bytes') as archive:
                with self.assertRaisesRegex(RuntimeError, 'Offline repair needs COPILOT_REA_ARCHIVE'):
                    helper.provision(root, environ={}, offline=True)
            archive.assert_not_called()

    def test_node_version_compatibility_and_explicit_invalid_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            node = root / 'node.exe'
            node.touch()
            for version, valid in [('v24.13.0\n', True), ('v22.19.0', True), ('v26.0.0', True),
                                   ('v24.10.0', False), ('v25.0.0', False), ('nonsense', False)]:
                with self.subTest(version=version), patch.object(helper, '_run_command', return_value=SimpleNamespace(returncode=0, stdout=version)):
                    if valid:
                        self.assertEqual(node, helper.find_node({'COPILOT_REA_NODE': str(node)}))
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'Compatible native Node not found'):
                            helper.find_node({'COPILOT_REA_NODE': str(node)})


if __name__ == '__main__':
    unittest.main()
