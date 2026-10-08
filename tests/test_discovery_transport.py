"""NOT RUN. Future isolated transport accounting tests; no socket/network creation."""
import asyncio
import ssl
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from copilot_agent.discovery_contracts import DiscoveryError, compile_manifest
from copilot_agent.discovery_http import PublicReader, TLSStream, ReadFailure, retry_after
from copilot_agent.discovery_scope import Scope
from copilot_agent.discovery_store import Store
from tests.discovery_fixtures import ORIGIN, manifest, workspace


class FakeTLS:
    def __init__(self, incoming, outgoing):
        self.incoming, self.outgoing = incoming, outgoing
    def read(self, n):
        if self.incoming.pending:
            return self.incoming.read(n)
        if self.incoming.eof:
            return b''
        raise ssl.SSLWantReadError()
    def do_handshake(self):
        return None
    def selected_alpn_protocol(self):
        return 'http/1.1'
    def write(self, data):
        self.outgoing.write(data)
        return len(data)


class FakeTLSContext:
    def wrap_bio(self, incoming, outgoing, server_side=False, server_hostname=None):
        assert server_side is False
        assert server_hostname == 'fixture.example'
        return FakeTLS(incoming, outgoing)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def make_reader(self, context, byte_limit=10):
        graph = compile_manifest(manifest())
        store = Store(context)
        store.create_run('run', graph, 'partition', 'owner')
        b = manifest()['budgets']; b['bytes'] = byte_limit
        reader = PublicReader(Scope(manifest()['scope']), store, 'run', b, lambda: False)
        return store, reader

    async def test_wire_read_reserves_before_receipt_and_no_prefetch(self):
        with workspace() as (_, context):
            store, reader = self.make_reader(context, 5)
            try:
                raw = SimpleNamespace(close=lambda: None)
                tls = TLSStream(raw, FakeTLSContext(), 'fixture.example', reader, time.time() + 10)
                calls = []
                async def receive(sock, size):
                    calls.append(size)
                    self.assertEqual(store.counters('run')['bytes_reserved'], size)
                    return b'abcde'[:size]
                loop = asyncio.get_running_loop()
                with patch.object(loop, 'sock_recv', side_effect=receive):
                    self.assertEqual(await tls.read(1), b'a')
                    self.assertEqual(await tls.read(4), b'bcde')
                    with self.assertRaises(DiscoveryError): await tls.pump()
                self.assertEqual(calls, [5])
                self.assertEqual(store.counters('run')['bytes'], 5)
                self.assertEqual(store.counters('run')['bytes_reserved'], 0)
            finally: store.close()

    async def test_dns_private_mixture_stops_before_socket_connect(self):
        with workspace() as (_, context):
            store, reader = self.make_reader(context)
            try:
                loop = asyncio.get_running_loop()
                rows = [(2, 1, 6, '', ('8.8.8.8', 443)), (2, 1, 6, '', ('127.0.0.1', 443))]
                with patch.object(loop, 'getaddrinfo', return_value=rows), patch.object(loop, 'sock_connect') as connect:
                    with self.assertRaises(ReadFailure): await reader.addresses('fixture.example', time.time() + 10)
                    connect.assert_not_called()
                self.assertEqual(store.counters('run')['requests'], 0)
            finally: store.close()

    async def test_cancel_before_wire_dispatch_zero_calls(self):
        with workspace() as (_, context):
            store, reader = self.make_reader(context)
            try:
                reader.cancelled = lambda: True
                loop = asyncio.get_running_loop()
                with patch.object(loop, 'getaddrinfo') as resolve:
                    with self.assertRaises(ReadFailure): await reader.one(ORIGIN + '/', 'GET', time.time() + 10)
                    resolve.assert_not_called()
            finally: store.close()

    async def test_origin_pressure_halves_caps_and_blocks_early_retry(self):
        with workspace() as (_, context):
            store, reader = self.make_reader(context)
            try:
                store.cooldown('run', ORIGIN, 120)
                pressure = store.origin('run', ORIGIN)
                self.assertEqual(pressure['cap'], 1)
                self.assertEqual(pressure['rate'], 2.5)
                self.assertGreater(store.request_slot('run', ORIGIN), 100)
            finally: store.close()

    async def test_retry_after_http_date_never_retries_early(self):
        from datetime import datetime, timezone
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(retry_after('Thu, 01 Jan 2026 00:02:00 GMT', now), 121)
