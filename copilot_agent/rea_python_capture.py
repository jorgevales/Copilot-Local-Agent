"""Passive, bounded capture analysis. No traffic is replayed and no values retained."""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urljoin, urlsplit
import zipfile

MAX_ENTRIES = 2000
MAX_EXPANDED = 20 * 1024 * 1024
MAX_MEMBER = 4 * 1024 * 1024
_STATIC = frozenset('api v1 v2 v3 graphql rest users user customers customer accounts account orders order items item products product login logout auth oauth callback status health search assets static js css images home index html json data app admin settings profile dashboard session sessions tenants tenant'.split())
_METHODS = frozenset('GET POST PUT PATCH DELETE OPTIONS HEAD CONNECT TRACE'.split())
_MIMES = frozenset('application/json application/xml text/xml text/html text/plain text/css text/javascript application/javascript application/octet-stream multipart/form-data application/x-www-form-urlencoded image/png image/jpeg image/svg+xml font/woff font/woff2'.split())


def _tick(budget):
    if callable(budget):
        budget()


def safe_url(value):
    """A route template, never query/fragment/userinfo or an arbitrary path value."""
    if not isinstance(value, str) or len(value) > 16384:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname:
            return None
        hostname = parsed.hostname.lower()
        # Do not accidentally echo encoded credentials or arbitrary strings as hosts.
        if not re.fullmatch(r'[a-z0-9.:-]{1,253}', hostname):
            return None
        hostname = '.'.join(label if len(label) <= 40 else 'redacted' for label in hostname.split('.'))
        if ':' in hostname:
            hostname = '[' + hostname + ']'
        port = parsed.port
        origin = parsed.scheme.lower() + '://' + hostname
        if port and port != (443 if parsed.scheme.lower() == 'https' else 80):
            origin += ':' + str(port)
        parts = []
        for segment in parsed.path.split('/')[:40]:
            if not segment:
                continue
            lower = segment.lower()
            # Unknown words can be customer names as well as identifiers.
            parts.append(lower if lower in _STATIC else ':segment')
        return origin + '/' + '/'.join(parts)
    except (ValueError, UnicodeError):
        return None


def _mime(value):
    value = str(value or '').split(';', 1)[0].strip().lower()
    return value if value in _MIMES else ('other' if value else 'unknown')


def _headers(value):
    return value if isinstance(value, list) else []


def _header(headers, name):
    for field in _headers(headers):
        if isinstance(field, dict) and str(field.get('name', '')).lower() == name:
            return str(field.get('value', ''))[:16384]
    return ''


def _http(data, request=False):
    # Parse only bounded HTTP metadata. Bodies never enter the result.
    head, separator, body = data.partition(b'\r\n\r\n')
    if not separator:
        head, separator, body = data.partition(b'\n\n')
    if len(head) > 65536 or not separator:
        raise ValueError('SAZ HTTP header block is malformed or oversized')
    lines = head.decode('iso-8859-1').splitlines()
    if not lines:
        raise ValueError('SAZ HTTP message is empty')
    headers = []
    for line in lines[1:]:
        if ':' not in line or line.startswith((' ', '\t')):
            raise ValueError('SAZ HTTP header syntax is unsupported')
        name, value = line.split(':', 1)
        if not re.fullmatch(r'[!#$%&\'*+.^_`|~0-9A-Za-z-]+', name):
            raise ValueError('SAZ HTTP header name is invalid')
        headers.append({'name': name, 'value': value.strip()})
    words = lines[0].split(' ')
    if request:
        if len(words) != 3 or words[0] not in _METHODS or not words[2].startswith('HTTP/'):
            raise ValueError('SAZ HTTP request line is malformed')
        target = words[1]
        if target.startswith('/'):
            hosts = [h['value'] for h in headers if h['name'].lower() == 'host']
            if len(hosts) != 1:
                raise ValueError('SAZ relative request requires one unambiguous Host header')
            target = 'http://' + hosts[0] + target
        return {'method': words[0], 'url': target, 'headers': headers,
                'postData': {'mimeType': _header(headers, 'content-type')} if body else {}}
    if len(words) < 2 or not words[0].startswith('HTTP/') or not re.fullmatch(r'[1-5][0-9]{2}', words[1]):
        raise ValueError('SAZ HTTP response line is malformed')
    return {'status': int(words[1]), 'headers': headers,
            'redirectURL': _header(headers, 'location'),
            'content': {'mimeType': _header(headers, 'content-type')}}


def _saz(path, budget):
    entries, total, names, sessions = [], 0, set(), {}
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > MAX_ENTRIES * 3 + 50:
            raise ValueError('SAZ member limit exceeded')
        for member in members:
            _tick(budget)
            name = member.filename
            pure = PurePosixPath(name)
            canonical = str(pure).casefold()
            if ('\\' in name or pure.is_absolute() or ':' in name or
                    any(part in ('..', '.') for part in name.rstrip('/').split('/')) or
                    canonical in names or member.flag_bits & 1 or
                    (member.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('SAZ archive contains unsafe, encrypted or ambiguous members')
            names.add(canonical)
            total += member.file_size
            if member.file_size > MAX_MEMBER or total > MAX_EXPANDED:
                raise ValueError('SAZ expanded size limit exceeded')
            if member.is_dir():
                continue
            match = re.fullmatch(r'raw/([1-9][0-9]*)_([cs])\.txt', name, re.I)
            if match:
                number, side = int(match.group(1)), match.group(2).lower()
                if number > MAX_ENTRIES * 1000 or len(sessions) >= MAX_ENTRIES and number not in sessions:
                    raise ValueError('SAZ session limit exceeded')
                with archive.open(member) as stream:
                    data = stream.read(MAX_MEMBER + 1)
                if len(data) != member.file_size or len(data) > MAX_MEMBER:
                    raise ValueError('SAZ member size is inconsistent')
                sessions.setdefault(number, {})[side] = _http(data, side == 'c')
        if not sessions:
            raise ValueError('SAZ contains no supported HTTP sessions')
        for number, session in sorted(sessions.items()):
            _tick(budget)
            if set(session) != {'c', 's'}:
                raise ValueError('SAZ contains incomplete HTTP session pairs')
            entries.append({'request': session['c'], 'response': session['s'], '_location': 'raw/' + str(number) + '_c.txt'})
    return entries


def analyze_capture(path: Path, format: str, budget=None) -> dict:
    """Read an already admitted immutable HAR/SAZ input; emit value-free structure."""
    _tick(budget)
    if format == 'har':
        with Path(path).open('rb') as stream:
            data = stream.read(MAX_EXPANDED + 1)
        if len(data) > MAX_EXPANDED:
            raise ValueError('HAR input size limit exceeded')
        root = json.loads(data)
        if not isinstance(root, dict) or not isinstance(root.get('log'), dict) or not isinstance(root['log'].get('entries'), list):
            raise ValueError('HAR requires a log.entries array')
        entries = root['log']['entries']
    elif format == 'saz':
        entries = _saz(path, budget)
    else:
        raise ValueError('Unsupported capture format')
    hosts, routes, methods, statuses, mimes, shapes = (Counter() for _ in range(6))
    timings, redirects, apis, locations = [], [], [], []
    sensitive_headers = payloads = queries = malformed = 0
    observed = []
    for index, entry in enumerate(entries[:MAX_ENTRIES]):
        _tick(budget)
        if not isinstance(entry, dict) or not isinstance(entry.get('request'), dict) or not isinstance(entry.get('response'), dict):
            malformed += 1
            continue
        request, response = entry['request'], entry['response']
        if (any(record.get('headers') is not None and not isinstance(record['headers'], list) for record in (request, response)) or
                response.get('content') is not None and not isinstance(response['content'], dict) or
                request.get('postData') is not None and not isinstance(request['postData'], dict)):
            malformed += 1
        route = safe_url(request.get('url'))
        if not route:
            malformed += 1
            continue
        method = str(request.get('method', '')).upper()
        method = method if method in _METHODS else 'OTHER'
        status = response.get('status')
        status_class = str(status // 100) + 'xx' if isinstance(status, int) and 100 <= status <= 599 else 'unknown'
        content = response.get('content') if isinstance(response.get('content'), dict) else {}
        mime = _mime(content.get('mimeType') or _header(response.get('headers'), 'content-type'))
        location = entry.get('_location') or 'log.entries[' + str(index) + ']'
        hosts[urlsplit(route).netloc] += 1
        routes[route] += 1
        methods[method] += 1
        statuses[status_class] += 1
        mimes[mime] += 1
        post = request.get('postData')
        payload = isinstance(post, dict) and bool(post)
        payloads += bool(payload)
        queries += bool(urlsplit(request['url']).query or request.get('queryString'))
        for header in _headers(request.get('headers')) + _headers(response.get('headers')):
            if isinstance(header, dict) and str(header.get('name', '')).lower() in ('authorization', 'proxy-authorization', 'cookie', 'set-cookie', 'x-api-key'):
                sensitive_headers += 1
        shapes[(method, route, _mime(post.get('mimeType')) if payload else 'none')] += 1
        duration = entry.get('time')
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and 0 <= duration <= 86400000:
            timings.append(duration)
        target = None
        if isinstance(response.get('redirectURL'), str) and response.get('redirectURL'):
            try:
                target = safe_url(urljoin(request['url'], response['redirectURL']))
            except ValueError:
                malformed += 1
        if target and status_class == '3xx':
            redirects.append({'from': route, 'to': target, 'location': location})
        if mime == 'application/json' or '/api/' in route or '/graphql' in route:
            apis.append({'method': method, 'route': route, 'status_class': status_class, 'mime_type': mime, 'location': location})
        locations.append(location)
        observed.append(route)
    # Chains describe explicit recorded Location edges; do not infer temporal pairing.
    chains = []
    edges = {item['from']: item['to'] for item in redirects}
    for edge in redirects[:100]:
        chain, seen = [edge['from'], edge['to']], {edge['from'], edge['to']}
        while len(chain) < 10 and chain[-1] in edges and edges[chain[-1]] not in seen:
            chain.append(edges[chain[-1]])
            seen.add(chain[-1])
        if chain not in chains:
            chains.append(chain)
    unknowns = ['Encrypted content and server implementation are not inferred.']
    if not timings:
        unknowns.append('No usable request timing samples were present.')
    if malformed:
        unknowns.append('Malformed or unsupported entries or metadata fields were omitted: ' + str(malformed))
    truncated = len(entries) > MAX_ENTRIES
    if truncated:
        unknowns.append('Entry analysis truncated at ' + str(MAX_ENTRIES))
    return {'status': 'partial' if truncated or malformed or not observed else 'completed',
            'confidence': 'observed', 'findings': {
                'format': format, 'entry_count': len(entries), 'analyzed_request_count': len(observed),
                'hosts': dict(hosts), 'route_templates': dict(routes), 'methods': dict(methods),
                'status_classes': dict(statuses), 'content_types': dict(mimes),
                'timing_ms': {'samples': len(timings), 'min': min(timings), 'max': max(timings), 'mean': round(sum(timings) / len(timings), 3)} if timings else {'samples': 0},
                'redirect_edges': redirects[:100], 'redirect_chains': chains,
                'api_candidates': apis[:200],
                'repeated_request_shapes': [{'method': key[0], 'route': key[1], 'request_mime_type': key[2], 'count': count} for key, count in shapes.items() if count > 1][:200],
                'redaction': {'sensitive_header_fields_omitted': sensitive_headers, 'payloads_omitted': payloads, 'queries_omitted': queries, 'all_header_values_omitted': True}},
            'unknowns': unknowns, 'limitations': ['Route segments are conservatively templated; distinct identifiers can share a template.', 'No headers, cookies, payload values, queries, traffic replay or response bodies are returned.', 'Redirect chains link recorded templates and cannot establish a unique client journey.'],
            'locations': locations[:200]}
