"""Endpoint-choice tests with mocked sockets/CDP; no live ports or profiles."""
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

from copilot_agent.app import choose_browser_endpoint
from copilot_agent.reused_browser import EndpointError


class FakeSockets:
    def __init__(self, busy=(), allocated=50001):
        self.busy = set(busy)
        self.allocated = allocated
        self.binds = []

    def socket(self):
        owner = self
        class Socket:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def bind(self, address):
                owner.binds.append(address)
                if address[1] in owner.busy:
                    raise OSError('Synthetic occupied port')
            def getsockname(self):
                return ('127.0.0.1', owner.allocated)
        return Socket()


class BrowserEndpointTests(unittest.IsolatedAsyncioTestCase):
    def config(self, port=9443, attach_existing=False):
        return SimpleNamespace(debug_port=port, attach_existing=attach_existing,
                               profile_dir=Path('synthetic-owned-profile'))

    async def exercise(self, config, settings, *, explicit_port=None, busy=(), payload=None, ownership_error=None):
        sockets = FakeSockets(busy)
        with patch('copilot_agent.app.machine_key', return_value='vdi-synthetic'), \
             patch('copilot_agent.app.system'), \
             patch('copilot_agent.app.socket', SimpleNamespace(socket=sockets.socket)), \
             patch('copilot_agent.app.edge.get_cdp_version', return_value=payload) as get_version, \
             patch('copilot_agent.app.edge.validate_endpoint') as validate_endpoint, \
             patch('copilot_agent.app.edge.validate_profile_ownership', side_effect=ownership_error) as validate_owner:
            result = await choose_browser_endpoint(config, SimpleNamespace(port=explicit_port), settings)
        return result, sockets, get_version, validate_endpoint, validate_owner

    async def test_free_default_port_is_remembered_for_this_machine(self):
        settings = {'debug_ports': {'vdi-other': 9555}}
        config, sockets, get_version, endpoint, owner = await self.exercise(self.config(), settings)
        self.assertFalse(config.attach_existing)
        self.assertEqual(9443, config.debug_port)
        self.assertEqual({'vdi-other': 9555, 'vdi-synthetic': 9443}, settings['debug_ports'])
        self.assertEqual([('127.0.0.1', 9443)], sockets.binds)
        get_version.assert_called_once_with('http://127.0.0.1:9443')
        endpoint.assert_not_called()
        owner.assert_not_called()

    async def test_remembered_owned_endpoint_is_preferred_and_proven_before_reuse(self):
        payload = {'Browser': 'Edg/synthetic', 'webSocketDebuggerUrl': 'ws://127.0.0.1:9555/devtools/browser/test'}
        config = self.config()
        settings = {'debug_ports': {'vdi-synthetic': 9555}}
        result, sockets, get_version, endpoint, owner = await self.exercise(config, settings, busy=[9555], payload=payload)
        self.assertTrue(result.attach_existing)
        self.assertEqual(9555, result.debug_port)
        self.assertEqual([], sockets.binds)
        self.assertCountEqual(
            [call.args[0] for call in get_version.call_args_list],
            ['http://127.0.0.1:9555', 'http://127.0.0.1:9443'])
        endpoint.assert_called_once_with('http://127.0.0.1:9555', payload)
        owner.assert_called_once_with(9555, config.profile_dir)

    async def test_other_profile_is_not_attached_and_free_port_is_remembered(self):
        settings = {}
        config, sockets, get_version, endpoint, owner = await self.exercise(
            self.config(), settings, busy=[9443], payload={'Browser': 'Edg/other'},
            ownership_error=EndpointError('Different Edge profile'))
        self.assertFalse(config.attach_existing)
        self.assertEqual(50001, config.debug_port)
        self.assertEqual(50001, settings['debug_ports']['vdi-synthetic'])
        self.assertEqual([('127.0.0.1', 9443), ('127.0.0.1', 0)], sockets.binds)
        owner.assert_called_once()

    async def test_invalid_edge_endpoint_never_passes_to_profile_reuse(self):
        sockets = FakeSockets([9443])
        config = self.config()
        with patch('copilot_agent.app.machine_key', return_value='vdi-synthetic'), \
             patch('copilot_agent.app.system'), \
             patch('copilot_agent.app.socket', SimpleNamespace(socket=sockets.socket)), \
             patch('copilot_agent.app.edge.get_cdp_version', return_value={'Browser': 'OtherBrowser'}), \
             patch('copilot_agent.app.edge.validate_endpoint', side_effect=EndpointError('Not Edge')), \
             patch('copilot_agent.app.edge.validate_profile_ownership') as owner:
            await choose_browser_endpoint(config, SimpleNamespace(port=None), {})
        self.assertFalse(config.attach_existing)
        self.assertEqual(50001, config.debug_port)
        owner.assert_not_called()

    async def test_explicit_attach_existing_is_unchanged_and_deferred_to_adapter(self):
        config = self.config(9666, True)
        settings = {'debug_ports': {'vdi-synthetic': 9555}}
        result, sockets, get_version, endpoint, owner = await self.exercise(config, settings, explicit_port=9666)
        self.assertIs(result, config)
        self.assertTrue(result.attach_existing)
        self.assertEqual(9666, result.debug_port)
        self.assertEqual({'vdi-synthetic': 9555}, settings['debug_ports'])
        self.assertEqual([], sockets.binds)
        get_version.assert_not_called()

    async def test_explicit_port_does_not_use_the_remembered_port(self):
        settings = {'debug_ports': {'vdi-synthetic': 9555}}
        config, sockets, get_version, endpoint, owner = await self.exercise(self.config(9666), settings, explicit_port=9666)
        self.assertEqual(9666, config.debug_port)
        get_version.assert_called_once_with('http://127.0.0.1:9666')
        self.assertEqual(9666, settings['debug_ports']['vdi-synthetic'])

    async def test_invalid_remembered_port_is_ignored(self):
        for value in (True, '9555', -1, 70000):
            with self.subTest(value=value):
                settings = {'debug_ports': {'vdi-synthetic': value}}
                config, sockets, get_version, endpoint, owner = await self.exercise(self.config(), settings)
                self.assertEqual(9443, config.debug_port)
                get_version.assert_called_once_with('http://127.0.0.1:9443')

    async def test_busy_remembered_unowned_port_can_fall_back_to_free_default(self):
        settings = {'debug_ports': {'vdi-synthetic': 9555}}
        config, sockets, get_version, endpoint, owner = await self.exercise(self.config(), settings, busy=[9555])
        self.assertEqual(9443, config.debug_port)
        self.assertFalse(config.attach_existing)
        self.assertEqual([('127.0.0.1', 9555), ('127.0.0.1', 9443)], sockets.binds)
        self.assertEqual(2, get_version.call_count)

    async def test_remembered_and_default_endpoint_probes_start_in_parallel(self):
        sockets = FakeSockets()
        barrier = threading.Barrier(2)
        observed = []
        def probe(endpoint):
            observed.append(endpoint)
            barrier.wait(timeout=2)
            return None
        config = self.config()
        settings = {'debug_ports': {'vdi-synthetic': 9555}}
        with patch('copilot_agent.app.machine_key', return_value='vdi-synthetic'), \
             patch('copilot_agent.app.system'), \
             patch('copilot_agent.app.socket', SimpleNamespace(socket=sockets.socket)), \
             patch('copilot_agent.app.edge.get_cdp_version', side_effect=probe):
            await choose_browser_endpoint(config, SimpleNamespace(port=None), settings)
        self.assertCountEqual(observed, ['http://127.0.0.1:9555', 'http://127.0.0.1:9443'])
