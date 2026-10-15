"""Upstream REA repair entry points cannot report Python fallback as success."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('setup_dependencies_entry', ROOT / 'bootstrap' / 'setup_dependencies.py')
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class ReaSetupEntryTests(unittest.TestCase):
    def invoke(self, *, settings=None, failure=None):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            (root / 'bootstrap').mkdir()
            (root / 'bootstrap' / 'setup_rea.py').write_text('# fixture')
            if settings is not None:
                (root / 'config.local.json').write_text(json.dumps(settings))
            provision = Mock(side_effect=failure)
            with patch.object(helper.sys, 'argv', ['setup_dependencies.py', 'install', str(root / 'requirements.lock.txt'), str(root / '.venv')]), patch.object(helper.sys, 'prefix', str(root / '.venv')), patch.object(helper.sys, 'base_prefix', str(root / 'base')), patch.object(helper.os.path, 'samefile', return_value=True), patch.object(helper, 'install'), patch.dict(sys.modules, {'setup_rea': SimpleNamespace(provision=provision)}), patch.object(helper.sys.stdin, 'isatty', return_value=True):
                helper.main()
            return provision

    def test_default_setup_requires_real_upstream_and_only_prompts_if_node_missing(self):
        provision = self.invoke()
        self.assertTrue(provision.call_args.kwargs['require_node'])
        self.assertTrue(provision.call_args.kwargs['ask_on_missing'])
        self.assertFalse(provision.call_args.kwargs.get('prompt_for_node', False))

    def test_node_setup_failure_stops_setup_before_success(self):
        with self.assertRaisesRegex(RuntimeError, 'upstream absent'):
            self.invoke(failure=RuntimeError('upstream absent'))

    def test_explicit_python_only_or_disabled_configuration_is_preserved(self):
        for settings in ({'rea_backend': 'python_native'}, {'rea_enabled': False}):
            with self.subTest(settings=settings):
                provision = self.invoke(settings=settings)
                self.assertFalse(provision.call_args.kwargs['require_node'])

    def test_launcher_repair_branch_runs_strict_node_setup_without_edge_setup(self):
        source = (ROOT / 'Launcher.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("'SetupREA'", source.splitlines()[0])
        match = re.search(r"if \(\$Mode -eq 'SetupREA'\) \{(.*?)\n\s*\} elseif", source, re.S)
        self.assertIsNotNone(match)
        body = match.group(1)
        script = "function Test-Python { $global:received = $args; $global:LASTEXITCODE=0 }; $python='Test-Python'; $pythonArgs=@('-B','-E','-s'); $repoRoot='C:\\Agent'; " + body + "; $received | ConvertTo-Json -Compress"
        completed = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True, text=True, check=True)
        args = json.loads(completed.stdout)
        self.assertIn('--require-node', args)
        self.assertIn('--project', args)
        self.assertIn('-E', args)
        self.assertNotIn('--setup-only', args)
        self.assertTrue(any(str(arg).endswith('bootstrap\\setup_rea.py') for arg in args))

    def test_one_click_repair_preserves_exit_code(self):
        source = (ROOT / 'Setup REA.cmd').read_text()
        self.assertIn('-Mode SetupREA', source)
        self.assertIn('set "agent_result=%errorlevel%"', source)
        self.assertIn('exit /b %agent_result%', source)
