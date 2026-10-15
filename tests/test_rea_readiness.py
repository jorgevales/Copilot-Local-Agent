"""Shared readiness budget, real bundled checks and runtime identity caching."""
import asyncio
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from copilot_agent.rea import _node_health, _node_cli_probe, _check_node
from copilot_agent.rea_backends import PythonNativeREABackend
from copilot_agent.rea_readiness import HEALTH_CACHE, UNCERTAIN_NODE_PROBES, native_probe, file_stamp, scratch_directory


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        HEALTH_CACHE.clear()
        UNCERTAIN_NODE_PROBES.clear()
        temporary = tempfile.TemporaryDirectory(prefix='rea_readiness_')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / 'rea'
        self.package.mkdir()
        (self.package / 'package.json').write_text('{"name":"rea-agents","version":"6.5.0"}')
        for name in ('scripts/rea.mjs', 'dist/cli-runtime/cli.js', 'dist/cli-runtime/cliOutput.js', 'dist/cli-runtime/cliResultOutput.js', 'node_modules/zod/package.json'):
            path = self.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}')
        native = self.package / 'native/windows/build'
        native.mkdir(parents=True)
        (native / 'rea-windows-x64.node').write_bytes(b'fixture')
        (native / 'manifest.json').write_text(json.dumps({'packageVersion': '6.5.0', 'platform': 'win32', 'architecture': 'x64', 'artifactSha256': hashlib.sha256(b'fixture').hexdigest()}))
        self.config = {'root': str(self.root), 'rea_repository': str(self.package), 'rea_node_executable': sys.executable}

    def test_verified_node_reuses_probe_until_source_or_native_identity_changes(self):
        with patch('copilot_agent.rea._check_node', return_value='24.13.0') as version, patch('copilot_agent.rea._node_cli_probe', return_value=None) as cli:
            first = _node_health(self.config)
            self.assertTrue(first['available'], first)
            for _ in range(5):
                self.assertEqual(first, _node_health(self.config))
            self.assertEqual(1, version.call_count)
            self.assertEqual(1, cli.call_count)
            (self.package / 'dist/cli-runtime/transitive.js').write_text('export const ready=true;')
            self.assertTrue(_node_health(self.config)['available'])
            self.assertEqual(2, cli.call_count)
            (self.package / 'native/windows/build/manifest.json').write_text('{}')
            health = _node_health(self.config)
            if os.name == 'nt':
                self.assertFalse(health['available'])
            else:
                self.assertTrue(health['available'])
                self.assertEqual(3, cli.call_count)

    def test_shared_180_second_allowance_is_not_restarted_for_cli(self):
        clock = [1000.0]
        def version(executable, timeout):
            self.assertEqual(180, timeout)
            clock[0] += 125
            return '24.13.0'
        with patch('copilot_agent.rea.time.monotonic', side_effect=lambda: clock[0]), patch('copilot_agent.rea._check_node', side_effect=version), patch('copilot_agent.rea._node_cli_probe', return_value=None) as cli:
            result = _node_health(self.config)
        self.assertTrue(result['available'], result)
        self.assertEqual(55, cli.call_args.kwargs['timeout'])
        self.assertEqual(180, result['diagnostics']['readiness_timeout_seconds'])

    def test_no_second_probe_after_unconfirmed_cleanup_even_when_sources_change(self):
        with patch('copilot_agent.rea._check_node', return_value='24.13.0'), patch('copilot_agent.rea._node_cli_probe', return_value='cli_smoke_cleanup_uncertain') as cli:
            result = _node_health(self.config)
            self.assertTrue(result['cleanup_uncertain'])
            (self.package / 'scripts/rea.mjs').write_text('new deployment')
            self.assertEqual(result, _node_health(self.config))
            self.assertEqual(1, cli.call_count)

    def test_installing_missing_repository_invalidates_failure_immediately(self):
        target = self.root / 'missing'
        config = {**self.config, 'rea_repository': str(target)}
        with patch('copilot_agent.rea._check_node', return_value='24.13.0'), patch('copilot_agent.rea._node_cli_probe', return_value=None):
            self.assertFalse(_node_health(config)['available'])
            self.package.rename(target)
            self.assertTrue(_node_health(config)['available'])

    def test_failed_node_probe_is_reused_for_full_readiness_allowance(self):
        clock = [1000.0]
        with patch('copilot_agent.rea.time.monotonic', side_effect=lambda: clock[0]), patch('copilot_agent.rea._check_node', return_value='24.13.0'), patch('copilot_agent.rea._node_cli_probe', return_value='cli_smoke_timeout') as cli:
            self.assertFalse(_node_health(self.config)['available'])
            clock[0] += 179
            self.assertFalse(_node_health(self.config)['available'])
            self.assertEqual(1, cli.call_count)
            clock[0] += 2
            self.assertFalse(_node_health(self.config)['available'])
            self.assertEqual(2, cli.call_count)

    def test_writable_project_scratch_survives_failed_default_temp(self):
        with patch('copilot_agent.rea_readiness.tempfile.gettempdir', side_effect=OSError(28, 'full')):
            with scratch_directory(self.root) as scratch:
                self.assertTrue(scratch.is_relative_to(self.root / '.runtime/rea-readiness'))
                (scratch / 'sample').write_bytes(b'working')

    def test_scratch_recovers_when_initial_candidate_is_unwritable(self):
        bad, good = self.root / 'unwritable', self.root / 'working'
        original = Path.mkdir
        def mkdir(path, *args, **kwargs):
            if path == bad:
                raise OSError(28, 'no space')
            return original(path, *args, **kwargs)
        with patch('copilot_agent.rea_readiness.scratch_roots', return_value=[bad, good]), patch.object(Path, 'mkdir', mkdir):
            with scratch_directory() as scratch:
                self.assertTrue(scratch.is_relative_to(good))

    def test_stamp_includes_raw_parent_reparse_identity(self):
        original = Path.lstat
        before = file_stamp(self.package / 'package.json', include_parents=True)
        class Replacement:
            def __init__(self, value):
                for key in ('st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_ino'):
                    setattr(self, key, getattr(value, key))
                self.st_file_attributes = 0x400
                self.st_reparse_tag = 0xa0000003
        def lstat(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            return Replacement(value) if path == self.package else value
        with patch.object(Path, 'lstat', lstat):
            self.assertNotEqual(before, file_stamp(self.package / 'package.json', include_parents=True))

    def test_python_functional_readiness_covers_every_advertised_capability(self):
        with patch('subprocess.Popen', side_effect=AssertionError('No process launch for bundled readiness')):
            result = PythonNativeREABackend().health()
        self.assertTrue(result['available'], result)
        self.assertEqual({'rea.inspect_page', 'rea.analyze_capture', 'rea.analyze_artifact'}, set(result['capability_checks']))
        self.assertTrue(all(item['status'] == 'verified' for item in result['capability_checks'].values()))

    def test_python_checks_are_cached_and_do_not_hide_broken_parsers(self):
        from copilot_agent import rea_python_readiness
        with patch.object(rea_python_readiness, 'run_functional_checks', wraps=rea_python_readiness.run_functional_checks) as check:
            self.assertTrue(PythonNativeREABackend().health()['available'])
            self.assertTrue(PythonNativeREABackend().health()['available'])
            self.assertEqual(1, check.call_count)
        with patch('copilot_agent.rea_python_capture.analyze_capture', return_value={'findings': {'analyzed_request_count': 0}}):
            result = PythonNativeREABackend().health()
        self.assertFalse(result['available'])

    def test_python_health_works_inside_existing_async_session(self):
        async def session():
            return PythonNativeREABackend().health()
        self.assertTrue(asyncio.run(session())['available'])

    def test_real_native_probe_bounds_output_and_reports_deadline_cleanup(self):
        result = native_probe([sys.executable, '-c', 'print("x" * 8192)'], timeout=3, output_limit=1024)
        self.assertEqual('output_limit', result['error'])
        self.assertFalse(result['cleanup_uncertain'])
        result = native_probe([sys.executable, '-c', 'import time; time.sleep(10)'], timeout=.1)
        self.assertEqual('timeout', result['error'])
        self.assertFalse(result['cleanup_uncertain'], result)

    def test_default_native_probe_gets_full_allowance_and_cli_missing_capability_fails(self):
        with patch('copilot_agent.rea_readiness.native_probe', return_value={'returncode': 0, 'stdout': 'v24.13.0\n'}) as probe:
            self.assertEqual('24.13.0', _check_node(Path(sys.executable)))
            self.assertEqual(180, probe.call_args.kwargs['timeout'])
            probe.return_value = {'returncode': 0, 'stdout': 'inspect-web-page'}
            self.assertEqual('cli_smoke_failed_or_capabilities_missing', _node_cli_probe(self.package, Path(sys.executable)))
