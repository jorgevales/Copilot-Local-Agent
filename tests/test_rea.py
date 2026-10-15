"""REA boundary contracts; ordinary tests use no internet or model credentials."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.policy import PathPolicy, PolicyError
from copilot_agent.rea import (REA_SPECS, _normalize, _run, _safe, execute_rea,
                               _stage_input, rea_health, validate_rea)


def evidence(**changes):
    value = {'evidence_id': 'ev_' + 'a' * 64, 'provider': {'id': 'fixture', 'version': '1'},
             'operation': 'inspect_go_binary', 'confidence': 'observed', 'limitations': [],
             'normalized_result': {'build_info': None, 'limitations': ['No metadata is not proof of absence.']},
             'raw_result': None, 'locations': [{'kind': 'file-offset', 'offset': 12}]}
    value.update(changes)
    return json.dumps({'ok': True, 'data': value, 'meta': {'command': 'fixture'}}).encode()


class REATests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='copilot_rea_'))
        self.package = self.root / 'rea-package'
        self.package.mkdir()
        (self.package / 'package.json').write_text(json.dumps({'name': 'rea-agents', 'version': '6.5.0'}))
        for relative in ['scripts/rea.mjs', 'dist/cli-runtime/cli.js',
                         'dist/cli-runtime/cliOutput.js', 'dist/cli-runtime/cliResultOutput.js']:
            file = self.package / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('// fixture\n')
        native = self.package / 'native' / 'windows' / 'build'
        native.mkdir(parents=True)
        (native / 'rea-windows-x64.node').write_bytes(b'health fixture; never loaded')
        (native / 'manifest.json').write_text(json.dumps({'packageVersion': '6.5.0',
            'platform': 'win32', 'architecture': 'x64',
            'artifactSha256': hashlib.sha256((native / 'rea-windows-x64.node').read_bytes()).hexdigest()}))
        self.config = {'root': str(self.root), 'rea_repository': str(self.package),
                       'rea_node_executable': sys.executable, 'allowed_roots': [str(self.root)],
                       'allowed_domains': ['example.com'], 'rea_timeout_seconds': 5}
        self.context = {'session_dir': str(self.root / 'session'), 'config': self.config}
        self.policy = PathPolicy([self.root])
        self.input = self.root / 'sample.exe'
        self.input.write_bytes(b'fixture bytes; never executed')

    def test_health_disabled_missing_incompatible_and_ready(self):
        self.assertTrue(rea_health(self.config)['available'])
        self.assertEqual('disabled', rea_health({**self.config, 'rea_enabled': False})['status'])
        (self.package / 'dist/cli-runtime/cli.js').unlink()
        self.assertIn('compiled runtime missing', rea_health(self.config)['reason'])
        (self.package / 'package.json').write_text('{"name":"another-package","version":"6.5.0"}')
        self.assertFalse(rea_health(self.config)['available'])

    def test_source_checkout_discovery_uses_sibling_convention(self):
        project = self.root / 'Agent'
        expected = self.root / 'Copilot Local Agent Research' / 'rea'
        expected.parent.mkdir()
        shutil.copytree(self.package, expected)
        config = {**self.config, 'root': str(project), 'rea_repository': ''}
        self.assertEqual(str(expected.resolve()), rea_health(config)['repository'])

    def test_strict_schemas_reject_command_raw_mcp_executable_and_unknown_kind(self):
        args = {'path': str(self.input), 'kind': 'go'}
        for key in ('command', 'arguments', 'executable', 'env', 'mcp', 'server_args'):
            with self.subTest(key=key), self.assertRaises((ValueError, TypeError)):
                validate_rea('rea.analyze_artifact', {**args, key: 'untrusted'}, self.context, self.policy)
        with self.assertRaises(ValueError):
            validate_rea('rea.raw', {}, self.context, self.policy)
        with self.assertRaises(ValueError):
            validate_rea('rea.analyze_artifact', {**args, 'kind': 'execute'}, self.context, self.policy)

    def test_path_traversal_outside_root_and_credentials_rejected(self):
        for path in (self.root / '..' / self.root.name / 'sample.exe', self.root.parent,
                     self.root / '.env'):
            with self.subTest(path=str(path)), self.assertRaises((PolicyError, FileNotFoundError)):
                validate_rea('rea.analyze_artifact', {'path': str(path), 'kind': 'go'}, self.context, self.policy)

    def test_directory_members_all_admitted_before_static_js(self):
        app = self.root / 'app'
        app.mkdir()
        (app / 'main.js').write_text('export const answer = 42;')
        prepared = validate_rea('rea.analyze_artifact', {'path': str(app), 'kind': 'javascript'}, self.context, self.policy)
        self.assertEqual(1, prepared['input']['file_count'])
        (app / '.env').write_text('DO_NOT_READ=secret')
        with self.assertRaises(PolicyError):
            validate_rea('rea.analyze_artifact', {'path': str(app), 'kind': 'javascript'}, self.context, self.policy)

    def test_input_and_config_limits(self):
        self.config['rea_max_input_bytes'] = 1024
        self.input.write_bytes(b'x' * 1025)
        with self.assertRaises(PolicyError):
            validate_rea('rea.analyze_capture', {'path': str(self.input), 'format': 'har'}, self.context, self.policy)
        self.config['rea_max_parallel'] = 100
        with self.assertRaises(ValueError):
            validate_rea('rea.analyze_capture', {'path': str(self.input), 'format': 'har'}, self.context, self.policy)

    def test_normalization_retains_provenance_locations_and_absence_uncertainty(self):
        result = _normalize(evidence(), 0)
        self.assertEqual('completed', result['status'])
        self.assertIsNone(result['findings']['build_info'])
        self.assertEqual(12, result['evidence']['locations'][0]['offset'])
        self.assertEqual('observed', result['confidence'])
        self.assertIn('not proof', result['findings']['limitations'][0])

    def test_partial_unknown_coverage_never_becomes_complete(self):
        result = _normalize(evidence(normalized_result={'graph': {'coverage': {'status': 'partial'}}}), 0)
        self.assertEqual('partial', result['status'])

    def test_upstream_wrapped_errors_partial_and_cleanup_uncertainty(self):
        for code, expected in [('capability_unavailable', 'unavailable'), ('cleanup_incomplete', 'uncertain'),
                               ('cancelled', 'cancelled'), ('timeout', 'timeout')]:
            data = json.dumps({'ok': False, 'error': {'code': code, 'category': 'failure',
                                                     'message': 'controlled'}}).encode()
            result = _normalize(data, 1)
            self.assertEqual(expected, result['status'])
        value = {'code': 'timeout', 'details': {'partial_observation': {'complete': False}}}
        result = _normalize(json.dumps(value).encode(), 0)
        self.assertEqual('partial', result['status'])

    def test_malformed_ambiguous_duplicate_nonfinite_and_unsupported_output_fail(self):
        for data in (b'progress\n{}', b'[]', b'{"a":1,"a":2}', b'{"x":NaN}',
                     b'{"success":true}', b'{}\n{}', b'\xff'):
            with self.subTest(data=data), self.assertRaises((ValueError, UnicodeError)):
                _normalize(data, 0)

    def test_capture_projection_keeps_endpoints_status_and_source_but_drops_payloads(self):
        payload = {'raw_result': {'password': 'rawsecret'}, 'normalized_result': {
            'records': [{'ordinal': 0, 'location': {'kind': 'json-pointer', 'pointer': '/log/entries/0'},
                'reported': {'request': {'method': 'GET', 'url': 'https://example.com/items?session=secret#x',
                                         'headers': [{'name': 'Authorization', 'value': 'bearer-secret'}]},
                             'response': {'status': 200, 'content': {'text': 'customer-secret'}}},
                'binary_fields': [{'content_base64': 'encoded-secret'}]}]},
            'access_token': 'token-secret', 'refreshToken': 'refresh-secret',
            'cookies': 'cookie-secret', 'authorization': 'auth-secret'}
        encoded = json.dumps(_safe(payload))
        for secret in ('rawsecret', 'bearer-secret', 'customer-secret', 'encoded-secret',
                       'token-secret', 'refresh-secret', 'cookie-secret', 'auth-secret', 'session=secret'):
            self.assertNotIn(secret, encoded)
        self.assertIn('https://example.com/items', encoded)
        self.assertIn('200', encoded)
        self.assertIn('/log/entries/0', encoded)

    def test_execute_uses_fixed_argument_vector_and_retains_redacted_evidence(self):
        fake = AsyncMock(return_value={'stdout': evidence(), 'stderr': b'', 'returncode': 0})
        with patch('copilot_agent.rea._run', fake):
            result = asyncio.run(execute_rea('rea.analyze_artifact', {'path': str(self.input), 'kind': 'go'}, self.context, self.policy))
        self.assertEqual('completed', result['status'])
        command = fake.call_args.args[0]
        self.assertEqual('inspect-go-binary', command[3])
        self.assertNotEqual(str(self.input.resolve()), command[4])
        self.assertEqual(self.input.name, Path(command[4]).name)
        self.assertFalse(Path(command[4]).exists(), 'The owned snapshot must be cleaned after confirmed completion')
        self.assertEqual(['--json', '--full-output'], command[-2:])
        self.assertTrue(Path(result['evidence_path']).is_file())
        self.assertEqual(result['evidence_sha256'], hashlib.sha256(Path(result['evidence_path']).read_bytes()).hexdigest())

    def test_missing_dependency_does_not_launch_and_returns_unavailable(self):
        self.config['rea_enabled'] = False
        fake = AsyncMock()
        with patch('copilot_agent.rea._run', fake):
            result = asyncio.run(execute_rea('rea.analyze_artifact', {'path': str(self.input), 'kind': 'go'}, self.context, self.policy))
        fake.assert_not_awaited()
        self.assertEqual('unavailable', result['status'])
        self.assertFalse(result['execution_started'])

    def test_evidence_storage_failure_never_reports_success(self):
        with patch('copilot_agent.rea._run', AsyncMock(return_value={'stdout': evidence(), 'stderr': b'', 'returncode': 0})), \
                patch('copilot_agent.rea.write_json', side_effect=OSError('fixture storage error')):
            result = asyncio.run(execute_rea('rea.analyze_artifact', {'path': str(self.input), 'kind': 'go'}, self.context, self.policy))
        self.assertEqual('uncertain', result['status'])
        self.assertEqual('evidence_storage_failed', result['error']['code'])

    def test_changed_input_is_partial(self):
        async def changed(*args, **kwargs):
            self.input.write_bytes(b'changed')
            return {'stdout': evidence(), 'stderr': b'', 'returncode': 0}
        with patch('copilot_agent.rea._run', changed):
            result = asyncio.run(execute_rea('rea.analyze_artifact', {'path': str(self.input), 'kind': 'go'}, self.context, self.policy))
        self.assertEqual('partial', result['status'])

    def test_local_snapshot_verified_content_and_scratch_fallback(self):
        prepared = validate_rea('rea.analyze_artifact', {'path': str(self.input), 'kind': 'go'}, self.context, self.policy)
        with patch('copilot_agent.rea._fixed_local', side_effect=[False, True]):
            staged = _stage_input(prepared, 'go', self.context, self.policy)
        self.assertEqual(self.input.read_bytes(), Path(staged['target']).read_bytes())
        self.assertEqual(prepared['input']['sha256'], staged['sha256'])
        self.assertEqual('copilot-rea-scratch', Path(staged['root']).parent.name)

    def test_local_scratch_exhaustion_is_unavailable_without_process(self):
        fake = AsyncMock()
        with patch('copilot_agent.rea._fixed_local', return_value=False), patch('copilot_agent.rea._run', fake):
            result = asyncio.run(execute_rea('rea.analyze_artifact', {'path': str(self.input), 'kind': 'go'}, self.context, self.policy))
        fake.assert_not_awaited()
        self.assertEqual('unavailable', result['status'])
        self.assertFalse(result['execution_started'])

    def test_uncertain_process_retains_snapshot(self):
        fake = AsyncMock(return_value={'status': 'uncertain', 'side_effects_uncertain': True, 'returncode': None})
        with patch('copilot_agent.rea._run', fake):
            result = asyncio.run(execute_rea('rea.analyze_artifact', {'path': str(self.input), 'kind': 'go'}, self.context, self.policy))
        self.assertTrue(Path(result['retained_scratch']).is_dir())
        self.assertTrue(result['side_effects_uncertain'])

    def test_owned_page_rejects_wrong_endpoint_and_unapproved_target(self):
        class Browser:
            endpoint = 'http://remote.example:9222'
        class Page:
            url = 'https://example.com/'
        self.context['browser'] = Browser()
        with patch('copilot_agent.web_navigation.get_navigation_page', return_value=Page()):
            with self.assertRaises(PolicyError):
                validate_rea('rea.inspect_page', {}, self.context, self.policy)
            self.context['browser'].endpoint = 'http://127.0.0.1:9222'
            Page.url = 'https://unapproved.example/'
            with self.assertRaises(PolicyError):
                validate_rea('rea.inspect_page', {}, self.context, self.policy)

    def test_process_timeout_cancellation_and_output_limit_cleanup(self):
        async def check():
            for command, timeout, context, expected in (
                ([sys.executable, '-c', 'import time; time.sleep(20)'], .15, {}, 'timeout'),
                ([sys.executable, '-c', 'import time; time.sleep(20)'], 5, {'cancelled': lambda: True}, 'cancelled'),
                ([sys.executable, '-c', "print('x'*40000)"], 5, {}, 'output_limit')):
                result = await _run(command, cwd=str(self.root), timeout=timeout, output_limit=16384, context=context)
                self.assertEqual(expected, result['status'])
                self.assertFalse(result['side_effects_uncertain'])
                self.assertIsNotNone(result['returncode'])
        asyncio.run(check())

    def test_termination_failure_remains_uncertain(self):
        async def check():
            with patch('copilot_agent.local_python_runner._terminate_pid', return_value=False):
                # A short-lived fixture exits itself after the forced deadline;
                # unsuccessful termination remains uncertain even after exit.
                result = await _run([sys.executable, '-c', 'import time; time.sleep(.3)'],
                                    cwd=str(self.root), timeout=.1, output_limit=16384, context={})
            self.assertEqual('uncertain', result['status'])
            self.assertTrue(result['side_effects_uncertain'])
        asyncio.run(check())


@unittest.skipUnless(os.environ.get('COPILOT_REA_INTEGRATION') == '1', 'Explicit local REA integration gate; no internet installation in tests')
class REALocalIntegrationTests(unittest.TestCase):
    def test_real_cli_owned_edge_page_inspection_preserves_browser(self):
        from playwright.async_api import async_playwright
        from copilot_agent.browser import BrowserAdapter
        async def run():
            root = Path(tempfile.mkdtemp(prefix='copilot_rea_edge_'))
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1', 0))
                port = reserve.getsockname()[1]
            async with async_playwright() as playwright:
                native = await playwright.chromium.launch(channel='msedge', headless=True,
                    args=['--remote-debugging-address=127.0.0.1', f'--remote-debugging-port={port}'])
                try:
                    browser = BrowserAdapter(SimpleNamespace(allowed_domains=['fixture.test'], debug_port=port))
                    browser.browser = native
                    browser.tool_context = await native.new_context(service_workers='block')
                    browser.context = browser.tool_context
                    browser.tool_page = await browser.tool_context.new_page()
                    await browser._configure_tool_context(browser.tool_page)
                    async def serve(route):
                        await route.fulfill(status=200, content_type='text/html',
                            body='<title>REA fixture</title><main><h1>Test</h1><button>Continue</button></main>')
                    await browser.tool_context.route('https://fixture.test/**', serve)
                    await browser.tool_page.route('https://fixture.test/**', serve)
                    await browser.tool_page.goto('https://fixture.test/')
                    config = {'root': str(Path(__file__).resolve().parents[1]), 'allowed_domains': ['fixture.test'],
                              'allowed_roots': [str(root)], 'rea_timeout_seconds': 30}
                    context = {'browser': browser, 'config': config, 'session_dir': str(root / 'session')}
                    result = await execute_rea('rea.inspect_page', {'observation_ms': 0}, context, PathPolicy([root]))
                    self.assertEqual('completed', result['status'], {key: result.get(key) for key in ('status', 'error')})
                    self.assertTrue(native.is_connected())
                    self.assertFalse(browser.tool_page.is_closed())
                    self.assertEqual('https://fixture.test/', browser.tool_page.url)
                    self.assertIn('evidence_id', Path(result['evidence_path']).read_text())
                finally:
                    await native.close()
        asyncio.run(run())

    def test_real_cli_capture_and_static_javascript(self):
        root = Path(tempfile.mkdtemp(prefix='copilot_rea_actual_'))
        config = {'root': str(Path(__file__).resolve().parents[1]), 'rea_timeout_seconds': 45,
                  'allowed_roots': [str(root)]}
        health = rea_health(config)
        self.assertTrue(health['available'], health)
        capture = root / 'synthetic.har'
        capture.write_text(json.dumps({'log': {'version': '1.2', 'creator': {'name': 'synthetic', 'version': '1'},
            'entries': [{'startedDateTime': '2026-10-15T09:00:00Z', 'time': 1,
                         'cache': {}, 'timings': {'send': 0, 'wait': 1, 'receive': 0},
                         'request': {'method': 'GET', 'url': 'https://example.com/api?session=fixture-secret',
                                    'httpVersion': 'HTTP/2', 'headersSize': -1, 'bodySize': 0,
                                    'headers': [{'name': 'Authorization', 'value': 'Bearer fixture-secret'}],
                                    'cookies': [], 'queryString': []},
                         'response': {'status': 200, 'statusText': 'OK', 'httpVersion': 'HTTP/2',
                                      'headersSize': -1, 'bodySize': 30, 'redirectURL': '',
                                      'headers': [], 'cookies': [],
                                      'content': {'size': 30, 'mimeType': 'application/json', 'text': '{"customer":"fixture-private"}'}}}]}}))
        app = root / 'application'
        app.mkdir()
        (app / 'package.json').write_text('{"name":"fixture","main":"main.js"}')
        (app / 'main.js').write_text('export function square(value) { return value * value; }\n')
        context = {'config': config, 'session_dir': str(root / 'session')}
        policy = PathPolicy([root])
        for tool, args in [('rea.analyze_capture', {'path': str(capture), 'format': 'har'}),
                           ('rea.analyze_artifact', {'path': str(app), 'kind': 'javascript'})]:
            with self.subTest(tool=tool):
                result = asyncio.run(execute_rea(tool, args, context, policy))
                expected = {'completed'} if tool == 'rea.analyze_capture' else {'completed', 'partial'}
                self.assertIn(result['status'], expected, {key: result.get(key) for key in ('status', 'error', 'limitations')})
                self.assertEqual(0, result['exit_status'])
                self.assertIsInstance(result['findings'], dict)
                saved = Path(result['evidence_path']).read_text()
                self.assertNotIn('fixture-secret', saved)
                self.assertNotIn('fixture-private', saved)
                self.assertIn('evidence_id', saved)


if __name__ == '__main__':
    unittest.main()
