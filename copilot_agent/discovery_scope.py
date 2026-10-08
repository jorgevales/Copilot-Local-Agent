"""One exact-origin/segment parser for manifest, queue, evidence and transport."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import urlsplit

from .discovery_contracts import DiscoveryError, canonical
from .site_knowledge import _safe_route

UNSAFE_SEGMENTS = frozenset('new create add edit update delete remove save submit upload import logout sign-out approve reject send pay payment purchase transfer withdraw deposit confirm accept grant consent cancel reset clear close'.split())
GENERIC_ALIASES = {'docs': 'documents', 'documentation': 'documents', 'guide': 'help',
                   'guides': 'help', 'tutorial': 'help', 'tutorials': 'help',
                   'api': 'documents', 'faq': 'help', 'about': 'information'}


def origin(value):
    if type(value) is not str or any(ord(c) < 33 or c in '\\%' for c in value):
        raise DiscoveryError('unsafe_origin', '$.scope.origins')
    try:
        p = urlsplit(value)
        host = (p.hostname or '').encode('idna').decode('ascii').lower()
        port = p.port
        if (p.scheme != 'https' or p.username is not None or p.password is not None
                or port not in (None, 443) or not host or host.endswith('.')
                or p.path not in ('', '/') or p.query or p.fragment
                or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', host)):
            raise ValueError()
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal', '.invalid')) or '.' not in host:
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
        if any(not part or len(part) > 63 or part.startswith('-') or part.endswith('-') for part in host.split('.')):
            raise ValueError()
    except (ValueError, UnicodeError) as error:
        raise DiscoveryError('unsafe_origin', '$.scope.origins', 'Use an exact public HTTPS hostname on port 443; private/literal/ambiguous origins are unavailable') from error
    return 'https://' + host


def path(value, exclusion=False):
    if type(value) is not str or not value.startswith('/') or any(c in value for c in '%\\?#;:@'):
        raise DiscoveryError('unsafe_path', '$.scope', 'Encoded/traversal/parameter paths are unavailable in strict public v1')
    try:
        # Closed public-documentation aliases extend, not weaken, the existing
        # privacy vocabulary. They validate as generic words; URLs are never
        # rewritten and customer identifiers remain excluded.
        generic = '/'.join(GENERIC_ALIASES.get(segment, segment) for segment in value.split('/'))
        _safe_route(generic)
        checked = value
    except ValueError as error:
        raise DiscoveryError('privacy_path', '$.scope', 'Only installed generic navigation paths are retainable; customer/unknown identifiers require the existing approved ephemeral tools') from error
    parts = [p for p in checked.split('/') if p]
    if any(p.startswith('{') or p in UNSAFE_SEGMENTS and not exclusion for p in parts):
        raise DiscoveryError('consequential_path', '$.scope', 'Write-like or unresolved parameter routes cannot be autonomous reads')
    if any(count > 4 for count in Counter(parts).values()):
        raise DiscoveryError('route_trap', '$.scope')
    return checked


def matches(value, prefix):
    return prefix == '/' or value == prefix or value.startswith(prefix.rstrip('/') + '/')


@dataclass(frozen=True)
class ScopedURL:
    url: str
    origin: str
    host: str
    path: str


class Scope:
    def __init__(self, value):
        import hashlib
        self.origins = tuple(origin(o) for o in value['origins'])
        if len(set(self.origins)) != len(self.origins):
            raise DiscoveryError('duplicate_origin', '$.scope.origins')
        self.allow = tuple(path(p) for p in value['allow_paths'])
        self.exclude = tuple(path(p, exclusion=True) for p in value['exclude_paths'])
        if value['allow_private_network'] is not False or value['query_keys']:
            raise DiscoveryError('query_capability_unavailable', '$.scope', 'No query strings, private networks or secret URL values are accepted by this adapter')
        self.redirect_limit = min(5, value['redirect_limit'])
        self.identity = hashlib.sha256(canonical(value).encode()).hexdigest()

    def resolve(self, value):
        if type(value) is not str or len(value) > 2048 or value != value.strip():
            raise DiscoveryError('unsafe_url', '$.urls')
        try:
            p = urlsplit(value)
            if p.query or p.fragment or p.username is not None or p.password is not None:
                raise ValueError()
            o = origin(p.scheme + '://' + p.netloc)
            route = path(p.path or '/')
        except (ValueError, UnicodeError) as error:
            if isinstance(error, DiscoveryError):
                raise
            raise DiscoveryError('unsafe_url', '$.urls', 'Query strings, fragments and user information are unavailable') from error
        if o not in self.origins or not any(matches(route, a) for a in self.allow) or any(matches(route, e) for e in self.exclude):
            raise DiscoveryError('scope_mismatch', '$.urls', 'Destination is outside the exact locally approved origin/path scope')
        return ScopedURL(o + route, o, urlsplit(o).hostname, route)


def public_address(value):
    try:
        address = ipaddress.ip_address(value)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_global and not address.is_multicast and not address.is_reserved
    except ValueError:
        return False
