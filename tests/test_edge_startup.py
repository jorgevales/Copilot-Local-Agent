"""Focused Edge startup and CDP failure tests; no real browser or user profile."""
import os
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, AsyncMock, Mock, patch
import urllib.request

from copilot_agent import reused_browser as edge
from copilot_agent.browser import BrowserAdapter


PAYLOAD = {'Browser': 'Edg/fixture',
           'webSocketDebuggerUrl': 'ws://127.0.0.1:9443/devtools/browser/fixture'}
ENDPOINT = 'http://127.0.0.1:9443'


class EdgeLaunchTests(unittest.TestCase):
    def test_cdp_http_probe_never_uses_corporate_proxy(self):
        handlers = [handler for handler in edge._LOOPBACK_HTTP.handlers
                    if isinstance(handler, urllib.request.ProxyHandler)]
        self.assertEqual([], handlers)

    def test_quoted_profile_argument_is_read_without_truncating_spaces(self):
        profile = Path(tempfile.gettempdir()) / 'Agent browser profile'
        self.assertEqual(profile, edge._profile_argument(f'"--user-data-dir={profile}"'))
        self.assertEqual(profile, edge._profile_argument(f'--user-data-dir="{profile}"'))

    @unittest.skipUnless(os.name == 'nt', 'Windows process command-line inspection')
    def test_existing_dedicated_profile_with_spaces_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / 'agent profile'
            profile.mkdir()
            command_line = f'msedge.exe "--user-data-dir={profile}"'
            with patch.object(edge, '_hidden_command', return_value=json.dumps({'CommandLine': command_line})):
                self.assertTrue(edge.profile_in_use(profile))

    def test_launch_uses_dedicated_profile_and_loopback_only(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / 'agent profile'
            with patch.object(edge, 'remote_debugging_blocked', return_value=False), \
                 patch.object(edge, 'profile_in_use', return_value=False), \
                 patch.object(edge, 'port_listening', return_value=False), \
                 patch.object(edge.subprocess, 'Popen', return_value=Mock()) as popen:
                edge.launch_edge(Path('msedge.exe'), 9443, profile)
            args = popen.call_args.args[0]
            self.assertIn(f'--user-data-dir={profile.resolve()}', args)
            self.assertIn('--remote-debugging-address=127.0.0.1', args)
            self.assertIn('--remote-debugging-port=9443', args)
            self.assertNotIn('--remote-allow-origins=*', args)

    def test_policy_profile_and_port_conflicts_stop_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / 'agent profile'
            for blocked, in_use, busy, message in (
                (True, False, False, 'policy disables remote debugging'),
                (False, True, False, 'profile is already open'),
                (False, False, True, 'port is already in use')):
                with self.subTest(message=message), \
                     patch.object(edge, 'remote_debugging_blocked', return_value=blocked), \
                     patch.object(edge, 'profile_in_use', return_value=in_use), \
                     patch.object(edge, 'port_listening', return_value=busy), \
                     patch.object(edge.subprocess, 'Popen') as popen:
                    with self.assertRaisesRegex(edge.EndpointError, message):
                        edge.launch_edge(Path('msedge.exe'), 9443, profile)
                    popen.assert_not_called()

    def test_launch_failure_hides_machine_path(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(edge, 'remote_debugging_blocked', return_value=False), \
                 patch.object(edge, 'profile_in_use', return_value=False), \
                 patch.object(edge, 'port_listening', return_value=False), \
                 patch.object(edge.subprocess, 'Popen', side_effect=OSError('private path: ' + directory)):
                with self.assertRaises(edge.EndpointError) as caught:
                    edge.launch_edge(Path('msedge.exe'), 9443, Path(directory) / 'profile')
            self.assertNotIn(directory, str(caught.exception))

    def test_only_launched_process_is_stopped(self):
        process = Mock()
        process.poll.return_value = None
        edge.stop_launched_edge(process)
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=3)
        exited = Mock()
        exited.poll.return_value = 0
        edge.stop_launched_edge(exited)
        exited.terminate.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows listener ownership API')
    def test_loopback_listener_owner_is_identified_without_cim(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            self.assertEqual(os.getpid(), edge.loopback_listener_pid(listener.getsockname()[1]))

    def test_fresh_launch_uses_exact_listener_pid_and_otherwise_checks_profile(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        with patch.object(edge, 'loopback_listener_pid', return_value=123), \
             patch.object(edge, 'validate_profile_ownership') as profile_check:
            edge.validate_launched_endpoint(9443, Path('profile'), process)
            profile_check.assert_not_called()
        with patch.object(edge, 'loopback_listener_pid', return_value=456), \
             patch.object(edge, 'validate_profile_ownership', side_effect=edge.EndpointError('wrong profile')):
            with self.assertRaisesRegex(edge.EndpointError, 'wrong profile'):
                edge.validate_launched_endpoint(9443, Path('profile'), process)

    @unittest.skipUnless(os.name == 'nt', 'Windows Edge policy registry')
    def test_explicit_remote_debugging_policy_disable_is_detected(self):
        import winreg
        key = Mock()
        key.__enter__ = Mock(return_value=key)
        key.__exit__ = Mock(return_value=False)
        with patch.object(winreg, 'OpenKey', return_value=key), \
             patch.object(winreg, 'QueryValueEx', return_value=(0, winreg.REG_DWORD)):
            self.assertTrue(edge.remote_debugging_blocked())
        with patch.object(winreg, 'OpenKey', return_value=key), \
             patch.object(winreg, 'QueryValueEx', return_value=(1, winreg.REG_DWORD)):
            self.assertFalse(edge.remote_debugging_blocked())


class EdgeHandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def _connect(self, *, payload=None, process=None, policy=False, busy=False, handshake=None):
        chromium = SimpleNamespace(connect_over_cdp=handshake or AsyncMock(side_effect=RuntimeError('private path')))
        playwright = SimpleNamespace(chromium=chromium)
        with patch.object(edge, 'remote_debugging_blocked', return_value=policy), \
             patch.object(edge, 'get_cdp_version', return_value=payload), \
             patch.object(edge, 'port_listening', return_value=busy):
            return await edge.connect_bounded(playwright, ENDPOINT, 0.1, process=process)

    async def test_explicit_policy_block_is_reported_without_handshake(self):
        with self.assertRaisesRegex(edge.EndpointError, 'policy disables remote debugging'):
            await self._connect(policy=True)

    async def test_exited_edge_is_distinct_from_occupied_port_and_missing_endpoint(self):
        for process, busy, expected in (
            (SimpleNamespace(poll=lambda: 0), False, 'Edge exited before opening'),
            (None, True, 'port is occupied'),
            (SimpleNamespace(poll=lambda: None), False, 'did not open a debugging endpoint')):
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(edge.EndpointError, expected):
                    await self._connect(process=process, busy=busy)

    async def test_responsive_endpoint_has_distinct_sanitized_handshake_error(self):
        with self.assertRaises(edge.EndpointError) as caught:
            await self._connect(payload=PAYLOAD)
        self.assertIn('endpoint responded', str(caught.exception))
        self.assertNotIn('private path', str(caught.exception))

    async def test_rejected_handshake_reports_security_policy_without_raw_error(self):
        handshake = AsyncMock(side_effect=RuntimeError('403 origin not allowed private path'))
        with self.assertRaises(edge.EndpointError) as caught:
            await self._connect(payload=PAYLOAD, handshake=handshake)
        self.assertIn('rejected Playwright', str(caught.exception))
        self.assertNotIn('private path', str(caught.exception))

    async def test_retries_browser_handshake_then_succeeds(self):
        browser = SimpleNamespace(is_connected=lambda: True, contexts=[object()])
        handshake = AsyncMock(side_effect=[RuntimeError('temporary timeout'), browser])
        result = await self._connect(payload=PAYLOAD, handshake=handshake)
        self.assertIs(result, browser)
        self.assertEqual(handshake.await_count, 2)
        self.assertEqual(handshake.await_args_list[0].args[0], PAYLOAD['webSocketDebuggerUrl'])
        self.assertEqual(handshake.await_args_list[1].args[0], ENDPOINT)

    async def test_prevalidated_initial_payload_connects_without_another_http_probe(self):
        browser = SimpleNamespace(is_connected=lambda: True, contexts=[object()])
        handshake = AsyncMock(return_value=browser)
        playwright = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=handshake))
        with patch.object(edge, 'remote_debugging_blocked', return_value=False), \
             patch.object(edge, 'get_cdp_version') as probe:
            result = await edge.connect_bounded(
                playwright, ENDPOINT, 1, initial_payload=PAYLOAD)
        self.assertIs(result, browser)
        probe.assert_not_called()
        handshake.assert_awaited_once_with(
            PAYLOAD['webSocketDebuggerUrl'], timeout=ANY)

    async def test_close_stops_owned_process_but_not_attached_browser(self):
        with patch.object(edge, 'stop_launched_edge') as stop:
            launched = BrowserAdapter(SimpleNamespace())
            launched._launched_process = Mock()
            await launched.close()
            stop.assert_called_once()
            stop.reset_mock()
            attached = BrowserAdapter(SimpleNamespace())
            await attached.close()
            stop.assert_not_called()


if __name__ == '__main__':
    unittest.main()
