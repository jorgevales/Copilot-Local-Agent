"""REA installation discovery and precise bounded availability diagnostics."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from copilot_agent.rea import rea_health


class REAAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rea_availability_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'agent'
        self.project.mkdir()
        self.local = self.root / 'local'
        self.node = self.root / 'node.exe'
        self.node.write_bytes(b'fixture; never executed')
        self.config = {'root': str(self.project), 'rea_node_executable': str(self.node)}
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {'LOCALAPPDATA': str(self.local)}).start()
        self.run = patch('copilot_agent.rea.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'v24.13.0\n', '')).start()

    def install(self, root):
        root.mkdir(parents=True, exist_ok=True)
        (root / 'package.json').write_text(json.dumps({'name': 'rea-agents', 'version': '6.5.0'}))
        for name in ('scripts/rea.mjs', 'dist/cli-runtime/cli.js', 'dist/cli-runtime/cliOutput.js', 'dist/cli-runtime/cliResultOutput.js'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('// fixture')
        dependency = root / 'node_modules/zod/package.json'
        dependency.parent.mkdir(parents=True)
        dependency.write_text('{}')
        native = root / 'native/windows/build'
        native.mkdir(parents=True)
        data = b'fixture; never loaded'
        (native / 'rea-windows-x64.node').write_bytes(data)
        (native / 'manifest.json').write_text(json.dumps({'packageVersion': '6.5.0', 'platform': 'win32', 'architecture': 'x64', 'artifactSha256': hashlib.sha256(data).hexdigest()}))
        return root

    def test_managed_repo_is_discovered_without_external_sibling(self):
        managed = self.install(self.project / '.runtime/rea')
        health = rea_health(self.config)
        self.assertTrue(health['available'], health)
        self.assertEqual(str(managed.resolve()), health['repository'])
        self.assertEqual('24.13.0', health['node_version'])

    def test_broken_default_candidate_falls_back_and_records_stage(self):
        broken = self.project / '.runtime/rea'
        broken.mkdir(parents=True)
        (broken / 'package.json').write_text('{broken')
        expected = self.install(self.local / 'Copilot Local Agent/runtimes/rea/6.5.0')
        health = rea_health(self.config)
        self.assertTrue(health['available'], health)
        self.assertEqual(str(expected.resolve()), health['repository'])
        self.assertEqual('manifest_invalid_json', health['diagnostics']['repository_candidates'][0]['code'])

    def test_invalid_explicit_override_never_uses_default_fallback(self):
        self.install(self.project / '.runtime/rea')
        health = rea_health({**self.config, 'rea_repository': str(self.root / 'explicit-missing')})
        self.assertFalse(health['available'])
        attempts = health['diagnostics']['repository_candidates']
        self.assertEqual(1, len(attempts))
        self.assertEqual('manifest_missing', attempts[0]['code'])
        self.assertEqual(str(self.root / 'explicit-missing/package.json'), attempts[0]['manifest'])

    def test_missing_manifest_reports_expected_paths_and_node_status(self):
        health = rea_health(self.config)
        self.assertFalse(health['available'])
        self.assertEqual('package.json', health['diagnostics']['manifest_filename'])
        self.assertGreaterEqual(len(health['diagnostics']['repository_candidates']), 3)
        self.assertTrue(health['diagnostics']['node_candidates'][0]['available'])
        self.assertEqual('repository', health['failure_stage'])

    def test_missing_compile_file_is_identified(self):
        package = self.install(self.project / '.runtime/rea')
        (package / 'dist/cli-runtime/cli.js').unlink()
        health = rea_health({**self.config, 'rea_repository': str(package)})
        self.assertEqual('compiled_runtime_missing', health['diagnostics']['repository_candidates'][0]['code'])
        self.assertIn(str(Path('dist/cli-runtime/cli.js')), health['reason'])

    def test_node_version_range_and_explicit_override_no_fallback(self):
        self.install(self.project / '.runtime/rea')
        for version, available in [('22.18.0', False), ('22.19.0', True), ('23.0.0', False), ('24.10.9', False), ('24.11.0', True), ('25.9.0', False), ('26.0.0', True)]:
            with self.subTest(version=version):
                self.run.return_value = subprocess.CompletedProcess([], 0, 'v' + version + '\n', '')
                health = rea_health(self.config)
                self.assertEqual(available, health['available'], health)
                self.assertEqual(1, len(health['diagnostics']['node_candidates']))

    def test_node_timeout_is_bounded_and_diagnostic(self):
        self.install(self.project / '.runtime/rea')
        self.run.side_effect = subprocess.TimeoutExpired([str(self.node), '--version'], 3)
        health = rea_health(self.config)
        self.assertEqual('node_probe_timeout', health['diagnostics']['node_candidates'][0]['code'])
        self.assertEqual('node', health['failure_stage'])
        self.assertLessEqual(self.run.call_args.kwargs['timeout'], 3)

    def test_node_program_files_fallback_after_path_candidate_invalid(self):
        self.install(self.project / '.runtime/rea')
        program = self.root / 'programs'
        alternate = program / 'nodejs/node.exe'
        alternate.parent.mkdir(parents=True)
        alternate.write_bytes(b'fixture')
        with patch.dict(os.environ, {'ProgramFiles': str(program)}), patch('copilot_agent.rea.shutil.which', return_value=str(self.root / 'missing-node.exe')):
            health = rea_health({'root': str(self.project)})
        self.assertTrue(health['available'], health)
        self.assertEqual(str(alternate.resolve()), health['node'])
        self.assertEqual('node_missing', health['diagnostics']['node_candidates'][0]['code'])

    def test_manifest_unreadable_is_not_misreported_missing(self):
        package = self.install(self.project / '.runtime/rea')
        original = Path.read_text
        def read(path, *args, **kwargs):
            if path == package / 'package.json':
                raise PermissionError('Access denied by fixture')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            health = rea_health({**self.config, 'rea_repository': str(package)})
        self.assertEqual('repository_unreadable', health['diagnostics']['repository_candidates'][0]['code'])
        self.assertIn('Access denied', health['reason'])

    def test_runtime_dependencies_absent_are_reported(self):
        package = self.install(self.project / '.runtime/rea')
        (package / 'node_modules/zod/package.json').unlink()
        health = rea_health({**self.config, 'rea_repository': str(package)})
        self.assertEqual('runtime_dependency_missing', health['diagnostics']['repository_candidates'][0]['code'])

    def test_manifest_stat_permission_denied_is_not_missing(self):
        expected = self.project / '.runtime/rea/package.json'
        original = Path.stat
        def stat(path, *args, **kwargs):
            if path == expected:
                raise PermissionError('Permission denied by fixture')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'stat', stat):
            health = rea_health({**self.config, 'rea_repository': str(expected.parent)})
        self.assertEqual('repository_unreadable', health['diagnostics']['repository_candidates'][0]['code'])

    def test_node_explicit_relative_override_does_not_use_path(self):
        self.install(self.project / '.runtime/rea')
        health = rea_health({**self.config, 'rea_node_executable': 'node.exe'})
        self.assertFalse(health['available'])
        self.assertEqual(1, len(health['diagnostics']['node_candidates']))
        self.assertEqual('node_missing', health['diagnostics']['node_candidates'][0]['code'])
