"""Credential-safe setup stages and mandatory Python fallback regression coverage."""
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

    def test_diagnostics_retain_full_paths_but_not_credentials(self):
        diagnostics = helper.SetupDiagnostics(Path('C:/project'), {'COPILOT_REA_NODE': 'S:/portable/node.exe', 'npm_config_cache': 'S:/cache'})
        value = diagnostics.safe('C:/project/file node=S:/portable/node.exe npm S:/cache/noise\n\\\\server\\share\\private\nC:\\Users\\example\\file\ntoken=secret-value')
        for expected in ('C:/project/file', 'S:/portable/node.exe', 'S:/cache/noise', r'\\server\share\private', r'C:\Users\example\file'):
            self.assertIn(expected, value)
        self.assertNotIn('secret-value', value)
        self.assertLessEqual(len(value), 2048)

    def test_sensitive_values_removed_without_masking_company_paths(self):
        diagnostics = helper.SetupDiagnostics(Path('S:/Company/project'), {})
        original = ('S:/Company/project/node.exe\nAuthorization: Bearer very-secret\n'
                    'Cookie: session=private-cookie\npassword="two words" token=hidden-token\n'
                    'https://user:private-password@internal.example/path')
        result = diagnostics.safe(original)
        self.assertIn('S:/Company/project/node.exe', result)
        for secret in ('very-secret', 'private-cookie', 'two words', 'hidden-token', 'private-password'):
            self.assertNotIn(secret, result)

    def test_default_setup_and_cli_forward_one_180_second_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(helper, '_provision_node', return_value={'available': True}) as install:
                helper.provision(temporary, environ={})
            self.assertEqual(180, install.call_args.kwargs['deadline_seconds'])
        with patch.object(helper.sys, 'argv', ['setup_rea.py', '--non-interactive']), \
             patch.object(helper, 'provision', return_value={'available': True}) as provision:
            self.assertEqual(0, helper.main())
        self.assertEqual(180, provision.call_args.kwargs['deadline_seconds'])

    def test_node_probe_receives_remaining_budget_instead_of_five_seconds(self):
        with tempfile.TemporaryDirectory() as temporary:
            node = Path(temporary) / 'node.exe'
            node.touch()
            clock = [0]
            with patch.object(helper.time, 'monotonic', side_effect=lambda: clock[0]):
                token = helper._BUDGET.set(helper.SetupBudget(180))
                try:
                    clock[0] = 40
                    with patch.object(helper, '_run_command', return_value=SimpleNamespace(returncode=0, stdout='v24.13.0')) as run:
                        self.assertEqual(node, helper.find_node({'COPILOT_REA_NODE': str(node)}))
                    self.assertEqual(140, run.call_args.kwargs['timeout'])
                finally:
                    helper._BUDGET.reset(token)

    def test_install_beyond_90_seconds_shares_remaining_budget_between_phases(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            target = project / '.runtime' / 'rea'
            clock, timeouts = [0], []
            def advance(seconds, result):
                clock[0] += seconds
                return result
            def validate(path, *_):
                if path.name != 'package':
                    raise ValueError('missing existing install')
                return advance(10, True)
            def extract(archive, root):
                clock[0] += 15
                (root / 'package.json').write_text('{}')
            def run(command, **kwargs):
                timeouts.append(kwargs['timeout'])
                return advance(35 if '--offline' in command else 25,
                               SimpleNamespace(returncode=1 if '--offline' in command else 0))
            with patch.object(helper.time, 'monotonic', side_effect=lambda: clock[0]), \
                 patch.object(helper, 'find_node', side_effect=lambda *_: advance(40, project / 'node.exe')), \
                 patch.object(helper, 'find_npm', side_effect=lambda *_: advance(20, project / 'npm-cli.js')), \
                 patch.object(helper, 'archive_bytes', side_effect=lambda *_: advance(20, b'archive')), \
                 patch.object(helper, 'runtime_candidates', return_value=[target]), \
                 patch.object(helper, 'validate_runtime', side_effect=validate), \
                 patch.object(helper, 'extract_archive', side_effect=extract), \
                 patch.object(helper, '_run_command', side_effect=run):
                result = helper.provision(project, environ={})
            self.assertTrue(result['available'])
            self.assertEqual([85, 50], timeouts)
            self.assertEqual(165, clock[0])

    def test_expired_budget_does_not_start_a_retry(self):
        clock = [0]
        with patch.object(helper.time, 'monotonic', side_effect=lambda: clock[0]):
            token = helper._BUDGET.set(helper.SetupBudget(180))
            try:
                clock[0] = 180
                with patch.object(helper.subprocess, 'Popen') as spawn, self.assertRaises(helper.SetupBudgetExpired):
                    helper._run_command(['node', '--version'], timeout=180)
                spawn.assert_not_called()
            finally:
                helper._BUDGET.reset(token)

    def test_unconfirmed_cleanup_prevents_any_additional_setup_command(self):
        diagnostics = helper.SetupDiagnostics(Path('S:/project'), {})
        diagnostics.record('node_probe', termination='subtree_cleanup_unconfirmed')
        token = helper._DIAGNOSTICS.set(diagnostics)
        try:
            with patch.object(helper.subprocess, 'Popen') as spawn, self.assertRaisesRegex(RuntimeError, 'cleanup is unconfirmed'):
                helper._run_command(['node', '--version'], timeout=180)
            spawn.assert_not_called()
        finally:
            helper._DIAGNOSTICS.reset(token)

    def test_operator_typing_does_not_consume_node_setup_budget(self):
        clock = [0]
        def ask(_):
            clock[0] += 600
            return 'S:/portable/node.exe'
        with patch.object(helper.time, 'monotonic', side_effect=lambda: clock[0]):
            token = helper._BUDGET.set(helper.SetupBudget(180))
            try:
                with patch.object(helper, '_operator_node', return_value=Path('S:/portable/node.exe')):
                    helper._select_node(Path('S:/project'), {}, prompt_for_node=True, input_fn=ask)
                self.assertEqual(180, helper._remaining())
            finally:
                helper._BUDGET.reset(token)

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
            self.assertEqual(sys.executable, record['executable'])
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
