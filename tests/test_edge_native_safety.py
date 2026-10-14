"""Exercise actual Windows ownership inspection without unsafe pointer reads."""
import ctypes
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from copilot_agent import reused_browser as edge
from copilot_agent.browser import BrowserAdapter


@unittest.skipUnless(os.name == 'nt', 'Windows process inspection')
class NativeInspectionSafetyTests(unittest.TestCase):
    def test_process_query_never_dereferences_an_unvalidated_unicode_pointer(self):
        with patch.object(ctypes, 'wstring_at', side_effect=AssertionError('Unsafe native string-pointer read')):
            details = edge._windows_process_details_native(os.getpid())
        self.assertTrue(details['Name'].lower().endswith('.exe'))
        self.assertTrue(details['CommandLine'])

    def test_invalid_pointer_and_length_are_rejected_without_dereference(self):
        class Header(ctypes.Structure):
            _fields_ = [('Length', ctypes.c_ushort), ('MaximumLength', ctypes.c_ushort), ('Buffer', ctypes.c_void_p)]
        for pointer, length, maximum, returned in ((1, 20, 20, 128), (0, 20, 20, 128),
                (None, 21, 22, 128), (None, 200, 200, 128), (None, 20, 18, 128), (None, 20, 20, 500)):
            buffer = ctypes.create_string_buffer(128)
            address = pointer if pointer is not None else ctypes.addressof(buffer) + ctypes.sizeof(Header)
            header = Header(length, maximum, address)
            ctypes.memmove(buffer, ctypes.byref(header), ctypes.sizeof(header))
            with self.subTest(pointer=pointer, length=length, returned=returned), self.assertRaises(OSError):
                edge._decode_process_command(buffer, returned)

    def test_bounded_utf16_read_needs_no_terminator_and_preserves_unicode(self):
        class Header(ctypes.Structure):
            _fields_ = [('Length', ctypes.c_ushort), ('MaximumLength', ctypes.c_ushort), ('Buffer', ctypes.c_void_p)]
        text = 'msedge.exe --user-data-dir=S:/Shared profile 😀'
        data = text.encode('utf-16-le')
        header_size = ctypes.sizeof(Header)
        buffer = ctypes.create_string_buffer(header_size + len(data))
        header = Header(len(data), len(data), ctypes.addressof(buffer) + header_size)
        ctypes.memmove(buffer, ctypes.byref(header), header_size)
        ctypes.memmove(ctypes.addressof(buffer) + header_size, data, len(data))
        self.assertEqual(text, edge._decode_process_command(buffer, ctypes.sizeof(buffer)))

    def test_crashed_probe_uses_cim_then_wmi_without_parent_native_calls(self):
        record = {'Name': 'msedge.exe', 'CommandLine': 'msedge.exe --remote-debugging-port=9222 --user-data-dir=S:/Agent'}
        with patch.object(edge, '_native_probe', side_effect=subprocess.CalledProcessError(0xc0000005, 'probe')), \
             patch.object(edge, '_hidden_command', side_effect=[OSError('CIM blocked'), json.dumps(record)]) as run:
            self.assertEqual(record, edge._windows_process_details(123))
        self.assertEqual(2, run.call_count)
        self.assertIn('Get-WmiObject', run.call_args.args[0][-1])

    def test_crashed_tcp_probe_and_provider_use_numeric_netstat(self):
        with patch.object(edge, '_native_probe', side_effect=OSError('Native crash')), \
             patch.object(edge, '_hidden_command', side_effect=[OSError('TCP provider unavailable'),
                ' TCP  0.0.0.0:9222  0.0.0.0:0  LISTENING 900\n TCP 127.0.0.1:9222 0.0.0.0:0 LISTENING 123\n']):
            self.assertEqual(123, edge.loopback_listener_pid(9222))

    def test_ipv6_listener_owner_matches_real_parent_process(self):
        if not socket.has_ipv6:
            self.skipTest('IPv6 unavailable')
        with socket.socket(socket.AF_INET6) as listener:
            try:
                listener.bind(('::1', 0))
            except OSError:
                self.skipTest('IPv6 loopback unavailable')
            listener.listen()
            self.assertEqual(os.getpid(), edge.loopback_listener_pid(listener.getsockname()[1]))


class LaunchCrashRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_installed_edge_opens_verified_cdp_with_owned_profile(self):
        from playwright.async_api import async_playwright
        try:
            executable = edge.find_edge_executable()
        except FileNotFoundError:
            self.skipTest('Installed Edge unavailable')
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / 'dedicated profile'
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            real_popen = subprocess.Popen
            def isolated_launch(command, **options):
                return real_popen([*command, '--headless=new'], **options)
            with patch.object(edge, 'profile_in_use', return_value=False), \
                 patch.object(edge.subprocess, 'Popen', side_effect=isolated_launch):
                process = edge.launch_edge_direct(executable, port, profile)
            browser = None
            try:
                async with async_playwright() as playwright:
                    browser = await edge.connect_bounded(playwright, edge.cdp_endpoint(port), 20,
                        process=process, endpoint_validator=lambda: edge.validate_launched_endpoint(port, profile, process))
                    self.assertTrue(browser.is_connected())
                    self.assertTrue(browser.contexts)
                    self.assertEqual(profile.resolve(), edge.validate_edge_listener(port, profile))
                    await browser.close()  # Only this isolated, proven owned fixture browser.
                    browser = None
            finally:
                edge.stop_launched_edge(process)

    async def test_direct_failure_continues_to_software_graphics(self):
        config = SimpleNamespace(attach_existing=False, profile_dir=Path('fixture-profile'),
            edge_executable='', debug_port=9222, startup_timeout=5)
        adapter = BrowserAdapter(config)
        adapter._playwright = SimpleNamespace()
        browser = SimpleNamespace()
        process = SimpleNamespace(poll=lambda: None)
        profile = config.profile_dir.resolve()
        with patch.object(edge, 'direct_profile_candidates', return_value=[('normal', profile, False), ('software', profile, True)]), \
             patch.object(edge, 'find_edge_executable', return_value=Path('msedge.exe')), \
             patch.object(edge, 'get_cdp_version', return_value=None), \
             patch.object(edge, 'launch_edge_direct', return_value=process) as launch, \
             patch.object(edge, 'connect_bounded', new=AsyncMock(side_effect=[edge.EndpointError('first route failed'), browser])):
            self.assertIs(browser, await adapter._connect_direct_edge_fallback())
        self.assertEqual([False, True], [call.kwargs['software_graphics'] for call in launch.call_args_list])

    async def test_direct_fallback_never_changes_exact_existing_proof(self):
        config = SimpleNamespace(attach_existing=True, _proof_exact_edge_endpoint=(9222, 'profile'))
        adapter = BrowserAdapter(config)
        with patch.object(edge, 'launch_edge_direct') as launch:
            self.assertIsNone(await adapter._connect_direct_edge_fallback())
        launch.assert_not_called()

    async def test_new_session_recovers_crashed_python_owner_by_direct_edge_launch(self):
        from copilot_agent.config import Config
        with tempfile.TemporaryDirectory() as temp:
            config = Config(root=Path(temp), storage_dir=Path(temp), profile_dir=Path(temp) / 'profile', debug_port=9222)
            config._new_edge_session = True
            config._automation_test_mode = True
            adapter = BrowserAdapter(config)
            browser = SimpleNamespace(contexts=[SimpleNamespace()])
            playwright = SimpleNamespace(stop=AsyncMock())
            manager = SimpleNamespace(start=AsyncMock(return_value=playwright))
            crashed_owner = SimpleNamespace(poll=lambda: -1073741819)
            direct_owner = SimpleNamespace(poll=lambda: None)
            async def claim(_):
                adapter.page = SimpleNamespace(set_default_timeout=lambda value: None)
            with patch.object(adapter, '_acquire_controller'), \
                 patch.object(adapter, '_claim_committed_request_page', new=AsyncMock(side_effect=claim)), \
                 patch.object(adapter, 'diagnostics', new=AsyncMock()), \
                 patch.object(edge, 'get_cdp_version', return_value=None), \
                 patch.object(edge, 'find_edge_executable', return_value=Path(temp) / 'msedge.exe'), \
                 patch.object(edge, 'launch_edge', return_value=crashed_owner), \
                 patch.object(edge, 'launch_edge_direct', create=True, return_value=direct_owner) as launch, \
                 patch.object(edge, 'validate_launched_endpoint'), \
                 patch.object(edge, 'connect_bounded', new=AsyncMock(side_effect=[edge.EndpointError('Python owner exited'), browser])), \
                 patch('playwright.async_api.async_playwright', return_value=manager):
                await adapter.start(resume_request_id='synthetic-resume')
            launch.assert_called_once()
            self.assertEqual(9222, config.debug_port)
            self.assertIs(direct_owner, adapter._launched_process)
