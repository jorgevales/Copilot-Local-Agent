"""Credential-free pinned HTTPS transport; no browser, proxy, cookie or code lane."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import ipaddress
import re
import socket
import ssl
import time
from urllib.parse import urljoin

from .discovery_contracts import DiscoveryError
from .discovery_scope import public_address

MAX_BODY = 2 * 1024 * 1024
MAX_HEADERS = 16384


class ReadFailure(DiscoveryError):
    def __init__(self, code, retryable=False, delay=0):
        super().__init__(code, '$', 'Public read stopped at a bounded local policy/transport boundary')
        self.retryable, self.delay = retryable, delay


def retry_after(value, now=None):
    now = datetime.now(timezone.utc) if now is None else now
    if value is None:
        return 2.0
    if re.fullmatch(r'[0-9]{1,9}', value.strip()):
        return float(value.strip())
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return 2.0
        return max(0, (parsed - now).total_seconds()) + 1
    except (ValueError, TypeError, OverflowError):
        return 2.0


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    content_type: str
    body: bytes
    redirects: tuple[str, ...]


class TLSStream:
    """Memory-BIO TLS: socket reads are reserved before receipt, without prefetch.

    The byte ledger conservatively includes inbound TLS records/handshake, not
    just parsed HTML. No StreamReader/HTTP library can read ahead of this ledger.
    """
    def __init__(self, raw, context, host, owner, deadline):
        self.raw, self.owner, self.deadline = raw, owner, deadline
        self.incoming, self.outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        self.tls = context.wrap_bio(self.incoming, self.outgoing, server_side=False, server_hostname=host)
        self.wire_bytes = 0
        self.eof = False

    async def flush(self):
        while self.outgoing.pending:
            data = self.outgoing.read(16384)
            self.owner.check(self.deadline)
            await self.owner.io(asyncio.get_running_loop().sock_sendall(self.raw, data), self.deadline)

    async def pump(self):
        self.owner.check(self.deadline)
        if self.eof:
            return False
        resource_remaining = MAX_BODY + 256 * 1024 - self.wire_bytes
        if resource_remaining <= 0:
            raise ReadFailure('body_limit')
        granted = self.owner.store.reserve_bytes(self.owner.run, min(4096, resource_remaining), self.owner.budgets['bytes'])
        received, returned = 0, False
        try:
            data = await self.owner.io(asyncio.get_running_loop().sock_recv(self.raw, granted), self.deadline)
            received, returned = len(data), True
            self.wire_bytes += received
            if data:
                self.incoming.write(data)
            else:
                self.eof = True
                self.incoming.write_eof()
            return bool(data)
        finally:
            # On cancelled/failed receipt the actual consumed amount may be
            # unknown; conservatively charge the reservation instead of replaying
            # with a reset ledger or under-reporting potentially received bytes.
            self.owner.store.settle_bytes(self.owner.run, granted, received if returned else granted)

    async def handshake(self):
        while True:
            try:
                self.tls.do_handshake()
                await self.flush()
                if self.tls.selected_alpn_protocol() not in (None, 'http/1.1'):
                    raise ReadFailure('unsupported_protocol')
                return
            except ssl.SSLWantReadError:
                await self.flush()
                if not await self.pump():
                    raise ReadFailure('incomplete_response', True)
            except ssl.SSLWantWriteError:
                await self.flush()

    async def write(self, data):
        position = 0
        while position < len(data):
            self.owner.check(self.deadline)
            try:
                position += self.tls.write(data[position:])
                await self.flush()
            except ssl.SSLWantReadError:
                await self.flush()
                if not await self.pump():
                    raise ReadFailure('incomplete_response', True)
            except ssl.SSLWantWriteError:
                await self.flush()

    async def read(self, maximum):
        while True:
            self.owner.check(self.deadline)
            try:
                return self.tls.read(maximum)
            except ssl.SSLWantReadError:
                await self.flush()
                if not await self.pump():
                    try:
                        return self.tls.read(maximum)
                    except ssl.SSLZeroReturnError:
                        return b''
                    except ssl.SSLEOFError as error:
                        raise ReadFailure('incomplete_response', True) from error
            except ssl.SSLZeroReturnError:
                return b''
            except ssl.SSLEOFError as error:
                raise ReadFailure('incomplete_response', True) from error
            except ssl.SSLWantWriteError:
                await self.flush()

    def close(self):
        self.raw.close()


class PublicReader:
    def __init__(self, scope, store, run, budgets, cancelled, monotonic_deadline=None):
        self.scope, self.store, self.run = scope, store, run
        self.monotonic_deadline = monotonic_deadline if monotonic_deadline is not None else time.monotonic() + budgets['run_seconds'] - 1
        self.budgets, self.cancelled = budgets, cancelled
        self.writers = set()
        self.origin_active = {}
        self.origin_condition = asyncio.Condition()

    def check(self, deadline):
        if self.cancelled():
            raise ReadFailure('cancelled')
        if time.monotonic() >= self.monotonic_deadline:
            raise ReadFailure('runtime_limit')
        if time.time() >= deadline:
            raise ReadFailure('timeout', True)
        record = self.store.run(self.run)
        if record['generation'] or record['state'] != 'EXECUTING':
            raise ReadFailure('cancelled')
        if time.time() < record['last_clock'] - 1:
            raise ReadFailure('clock_anomaly')

    async def wait(self, seconds, deadline):
        end = time.time() + seconds
        if end >= deadline:
            raise ReadFailure('timeout', False)
        while time.time() < end:
            self.check(deadline)
            await asyncio.sleep(min(.05, max(0, end - time.time())))

    async def io(self, operation, deadline):
        task = asyncio.ensure_future(operation)
        try:
            while not task.done():
                self.check(deadline)
                await asyncio.wait({task}, timeout=min(.05, max(.001, deadline - time.time())))
            return task.result()
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise

    async def addresses(self, host, deadline):
        loop = asyncio.get_running_loop()
        rows = await self.io(loop.getaddrinfo(host, 443, family=socket.AF_UNSPEC,
                                             type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP), deadline)
        if not rows or len(rows) > 32 or any(not public_address(row[4][0]) for row in rows):
            raise ReadFailure('private_destination')
        return rows

    async def receive(self, reader, maximum, deadline):
        self.check(deadline)
        return await reader.read(maximum)

    async def line(self, reader, deadline, limit=4096):
        # No read-ahead outside the byte ledger. Header/chunk lines are deliberately
        # byte-wise and bounded; raw headers are discarded, not retained as evidence.
        result = bytearray()
        while len(result) < limit:
            data = await self.receive(reader, 1, deadline)
            if not data:
                raise ReadFailure('incomplete_response', True)
            result.extend(data)
            if result.endswith(b'\r\n'):
                return bytes(result)
        raise ReadFailure('header_limit')

    async def exact(self, reader, size, deadline):
        result = bytearray()
        while len(result) < size:
            data = await self.receive(reader, min(4096, size - len(result)), deadline)
            if not data:
                raise ReadFailure('incomplete_response', True)
            result.extend(data)
        return bytes(result)

    async def acquire_origin(self, origin, deadline):
        while True:
            self.check(deadline)
            cap = self.store.origin(self.run, origin)['cap']
            async with self.origin_condition:
                if self.origin_active.get(origin, 0) < cap:
                    self.origin_active[origin] = self.origin_active.get(origin, 0) + 1
                    return
            await asyncio.sleep(.05)

    async def one(self, url, method, deadline):
        scoped = self.scope.resolve(url)
        await self.acquire_origin(scoped.origin, deadline)
        raw, writer = None, None
        try:
            while True:
                self.check(deadline)
                delay = self.store.request_slot(self.run, scoped.origin)
                if not delay:
                    break
                await self.wait(delay, deadline)
            rows = await self.addresses(scoped.host, deadline)
            self.check(deadline)
            # Use one validated address only; retries consume the same task ledger.
            family, socktype, proto, _, address = rows[0]
            self.store.reserve(self.run, 'requests', 1, self.budgets['requests'])
            raw = socket.socket(family, socktype, proto)
            raw.setblocking(False)
            await self.io(asyncio.get_running_loop().sock_connect(raw, address), deadline)
            peer = raw.getpeername()[0]
            if not public_address(peer) or ipaddress.ip_address(peer) != ipaddress.ip_address(address[0]):
                raise ReadFailure('connection_mismatch')
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.set_alpn_protocols(['http/1.1'])
            reader = writer = TLSStream(raw, context, scoped.host, self, deadline)
            raw = None
            self.writers.add(writer)
            await writer.handshake()
            self.check(deadline)
            peer = writer.raw.getpeername()[0]
            if not public_address(peer) or ipaddress.ip_address(peer) != ipaddress.ip_address(address[0]):
                raise ReadFailure('connection_mismatch')
            request = (method + ' ' + scoped.path + ' HTTP/1.1\r\nHost: ' + scoped.host +
                       '\r\nUser-Agent: CopilotLocalAgent-Discovery/1\r\nAccept: text/html,text/plain\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n').encode('ascii')
            await writer.write(request)
            status_line = await self.line(reader, deadline)
            match = re.fullmatch(rb'HTTP/1\.[01] ([0-9]{3}) [^\r\n]*\r\n', status_line)
            if not match:
                raise ReadFailure('invalid_response')
            status = int(match[1])
            headers, total = {}, len(status_line)
            for _ in range(100):
                line = await self.line(reader, deadline)
                total += len(line)
                if total > MAX_HEADERS:
                    raise ReadFailure('header_limit')
                if line == b'\r\n':
                    break
                if line.startswith((b' ', b'\t')) or b':' not in line:
                    raise ReadFailure('invalid_response')
                name, value = line[:-2].split(b':', 1)
                if not re.fullmatch(rb'[A-Za-z0-9-]+', name):
                    raise ReadFailure('invalid_response')
                key = name.decode('ascii').lower()
                if key in headers:
                    raise ReadFailure('ambiguous_response')
                headers[key] = value.decode('latin-1').strip()
            else:
                raise ReadFailure('header_limit')
            if status == 429:
                delay = retry_after(headers.get('retry-after'))
                self.store.cooldown(self.run, scoped.origin, delay)
                raise ReadFailure('rate_limited', True, delay)
            if status in (401, 403):
                raise ReadFailure('authentication_required' if status == 401 else 'access_denied')
            if status == 404:
                raise ReadFailure('route_missing')
            if status in (500, 502, 503, 504):
                raise ReadFailure('server_error', True)
            if status in (301, 302, 303, 307, 308):
                location = headers.get('location')
                if location is None:
                    raise ReadFailure('invalid_redirect')
                return status, '', b'', self.scope.resolve(urljoin(scoped.url, location)).url
            if not 200 <= status < 300:
                raise ReadFailure('unsupported_status')
            content_type = headers.get('content-type', '').split(';')[0].strip().lower()
            if method == 'HEAD':
                return status, content_type, b'', None
            if content_type not in ('text/html', 'application/xhtml+xml', 'text/plain'):
                raise ReadFailure('unsupported_content')
            if headers.get('content-encoding', 'identity').lower() != 'identity':
                raise ReadFailure('compressed_content_unavailable')
            length = headers.get('content-length')
            transfer = headers.get('transfer-encoding')
            if length is not None and transfer is not None:
                raise ReadFailure('ambiguous_response')
            if length is not None:
                if not re.fullmatch(r'[0-9]{1,10}', length) or int(length) > MAX_BODY:
                    raise ReadFailure('body_limit')
                body = await self.exact(reader, int(length), deadline)
            elif transfer:
                if transfer.lower() != 'chunked':
                    raise ReadFailure('unsupported_transfer')
                parts, size = [], 0
                while True:
                    chunk = await self.line(reader, deadline, 64)
                    if not re.fullmatch(rb'[0-9a-fA-F]{1,8}\r\n', chunk):
                        raise ReadFailure('invalid_chunk')
                    count = int(chunk.strip(), 16)
                    if size + count > MAX_BODY:
                        raise ReadFailure('body_limit')
                    if count == 0:
                        if await self.line(reader, deadline) != b'\r\n':
                            raise ReadFailure('unsupported_trailer')
                        break
                    parts.append(await self.exact(reader, count, deadline))
                    size += count
                    if await self.exact(reader, 2, deadline) != b'\r\n':
                        raise ReadFailure('invalid_chunk')
                body = b''.join(parts)
            else:
                parts, size = [], 0
                while True:
                    data = await self.receive(reader, min(4096, MAX_BODY + 1 - size), deadline)
                    if not data:
                        break
                    size += len(data)
                    if size > MAX_BODY:
                        raise ReadFailure('body_limit')
                    parts.append(data)
                body = b''.join(parts)
            return status, content_type, body, None
        except (OSError, ssl.SSLError, asyncio.TimeoutError) as error:
            raise ReadFailure('transport_error', not isinstance(error, ssl.SSLCertVerificationError)) from error
        finally:
            if writer:
                self.writers.discard(writer)
                writer.close()
            if raw:
                raw.close()
            async with self.origin_condition:
                self.origin_active[scoped.origin] -= 1
                self.origin_condition.notify_all()

    async def fetch(self, url, deadline, method='GET'):
        if method not in {'GET', 'HEAD'}:
            raise ReadFailure('write_unavailable')
        current, seen, chain = self.scope.resolve(url).url, set(), []
        for hop in range(self.scope.redirect_limit + 1):
            self.check(deadline)
            if current in seen:
                raise ReadFailure('redirect_cycle')
            seen.add(current)
            status, kind, body, redirect = await self.one(current, method, deadline)
            if redirect is None:
                return Response(current, status, kind, body, tuple(chain))
            chain.append(current)
            current = redirect
        raise ReadFailure('redirect_limit')

    async def close(self):
        for writer in tuple(self.writers):
            writer.close()
        self.writers.clear()
