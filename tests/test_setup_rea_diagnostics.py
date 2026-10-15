"""Sanitized setup stages and mandatory Python fallback regression coverage."""
import contextlib
import errno
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('setup_rea_diagnostics', Path(__file__).resolve().parents[1] / 'bootstrap' / 'setup_rea.py')
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class SetupBackendDiagnosticsTests(unittest.TestCase):
    def test_python_only_setup_never_discovers_node_or_installs(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / 'config.local.json').write_text('{"rea_backend":"python_native"}')
            with patch.object(helper, '_provision_node') as provision, \
                 patch.object(helper, 'find_node') as node, \
                 patch.object(helper, 'find_npm') as npm, \
                 patch.object(helper, 'archive_bytes') as archive, \
                 patch('copilot_agent.rea.rea_health', return_value={'available': True, 'selected_backend': 'python_native'}):
                result = helper.provision(project, environ={})
            self.assertTrue(result['available'])
            self.assertEqual('python_native', result['selected_backend'])
            for method in (provision, node, npm, archive):
                method.assert_not_called()

    def test_auto_setup_recovers_from_node_install_and_smoke_failures(self):
        for failure in (OSError(errno.ENOSPC, 'no space'), ValueError('native_verify mismatch'),
                        subprocess.TimeoutExpired(['node', 'npm'], 90)):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as temporary:
                with patch.object(helper, '_provision_node', side_effect=failure), \
                     patch('copilot_agent.rea.rea_health', return_value={'available': True, 'selected_backend': 'python_native'}) as health:
                    result = helper.provision(temporary, environ={})
                self.assertTrue(result['available'])
                self.assertTrue(result['node_repair_failed'])
                self.assertEqual('python_native', health.call_args.args[0]['rea_backend'])

    def test_diagnostics_keep_exact_archive_verify_stage_and_filesystem_codes(self):
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = helper.SetupDiagnostics(Path(temporary), {})
            token = helper._DIAGNOSTICS.set(diagnostics)
            try:
                def acquire():
                    return helper._stage('archive_verify', lambda: (_ for _ in ()).throw(OSError(errno.ENOSPC, 'full')))
                with self.assertRaises(OSError):
                    helper._stage('archive_acquire', acquire)
            finally:
                helper._DIAGNOSTICS.reset(token)
            self.assertEqual('archive_verify', diagnostics.records[-1]['stage'])
            self.assertEqual(errno.ENOSPC, diagnostics.records[-1]['errno'])
            self.assertEqual('failed', diagnostics.records[-1]['termination'])

    def test_safe_diagnostics_never_expose_paths_or_secrets(self):
        diagnostics = helper.SetupDiagnostics(Path('C:/project'), {'COPILOT_REA_NODE': 'S:/portable/node.exe', 'npm_config_cache': 'S:/cache'})
        value = diagnostics.safe('C:/project/file node=S:/portable/node.exe npm S:/cache/noise\n\\\\server\\share\\private\nC:\\Users\\example\\file\ntoken=secret-value')
        self.assertIn('<project-root>', value)
        self.assertIn('<node-runtime>', value)
        self.assertIn('<npm-cache>', value)
        for forbidden in ('server', 'share', 'private', 'example', 'secret-value'):
            self.assertNotIn(forbidden, value)
        self.assertLessEqual(len(value), 2048)

    def test_command_retains_bounded_output_and_safe_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = helper.SetupDiagnostics(Path(temporary), {})
            token = helper._DIAGNOSTICS.set(diagnostics)
            try:
                result = helper._run_command([sys.executable, '-c', 'print("x"*5000)'],
                                             stage='npm_probe', identity='node npm --version', timeout=5)
            finally:
                helper._DIAGNOSTICS.reset(token)
            record = diagnostics.records[-1]
            self.assertEqual(0, result.returncode)
            self.assertLessEqual(len(record['stdout']), 2048)
            self.assertEqual('npm_probe', record['stage'])
            self.assertEqual('node npm --version', record['command'])
            self.assertEqual('completed', record['termination'])
            self.assertGreater(record['duration_seconds'], 0)
            self.assertEqual(5, record['timeout_seconds'])

    def test_timeout_reports_owned_subtree_termination(self):
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = helper.SetupDiagnostics(Path(temporary), {})
            token = helper._DIAGNOSTICS.set(diagnostics)
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    helper._run_command([sys.executable, '-c', 'import time;time.sleep(30)'],
                                        stage='dependency_install', identity='node npm install', timeout=.1)
            finally:
                helper._DIAGNOSTICS.reset(token)
            self.assertEqual('dependency_install', diagnostics.records[-1]['stage'])
            self.assertEqual('terminated_owned_subtree', diagnostics.records[-1]['termination'])
            self.assertEqual('TimeoutExpired', diagnostics.records[-1]['error_type'])

    def test_failed_cache_override_uses_verified_setup_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            target = project / '.runtime' / 'rea'
            cache = project / 'old-cache'
            calls = []
            def probe(path):
                if path == cache:
                    raise OSError(errno.ENOSPC, 'full old cache')
                path.mkdir(parents=True, exist_ok=True)
            def extract(archive, root):
                (root / 'package.json').write_text('{}')
            def run(command, **kwargs):
                calls.append(kwargs['env']['npm_config_cache'])
                return SimpleNamespace(returncode=0, stdout='', stderr='')
            with patch.object(helper, 'find_node', return_value=project / 'node.exe'), \
                 patch.object(helper, 'find_npm', return_value=project / 'npm-cli.js'), \
                 patch.object(helper, 'runtime_candidates', return_value=[target]), \
                 patch.object(helper, 'validate_runtime', side_effect=lambda root, *_: True if root.name == 'package' else (_ for _ in ()).throw(ValueError('missing'))), \
                 patch.object(helper, 'archive_bytes', return_value=b'archive'), \
                 patch.object(helper, 'extract_archive', side_effect=extract), \
                 patch.object(helper, '_verify_scratch', side_effect=probe), \
                 patch.object(helper, '_run_command', side_effect=run):
                result = helper.provision(project, environ={'NPM_CONFIG_CACHE': str(cache)})
            self.assertTrue(result['available'])
            self.assertEqual(1, len(calls))
            self.assertNotEqual(str(cache), calls[0])
            self.assertIn('npm-cache', calls[0])
            failures = [record for record in result['diagnostics'] if record.get('errno') == errno.ENOSPC]
            self.assertTrue(failures)
            persisted = json.loads((project / '.setup-cache' / 'rea-setup-diagnostics.json').read_text())
            self.assertTrue(persisted['stages'])


if __name__ == '__main__':
    unittest.main()
