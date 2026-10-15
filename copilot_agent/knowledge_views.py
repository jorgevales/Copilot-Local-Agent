"""Sanitized, bounded website views derived from the authoritative ledger."""
from __future__ import annotations

import hashlib
import getpass
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

from .persistence import io_path, write_preserving
from .policy import reject_path_redirection

_PRIVATE_KEY = re.compile(
    r'(?i)^(?:password|passwd|secret|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|'
    r'authorization|cookie|cookies|session[_ -]?(?:token|id)|credentials|'
    r'(?:customer|client|patient|person|account)[_ -]?(?:name|id|number|record)|'
    r'first[_ -]?name|last[_ -]?name|full[_ -]?name|email|phone|date[_ -]?of[_ -]?birth|ssn)$')
_PRIVATE_TEXT = re.compile(
    r'(?i)(?:-----BEGIN [^-]*PRIVATE KEY|\bBearer\s+[A-Za-z0-9._~+/-]{8,}|'
    r'\b(?:password|passwd|secret|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|'
    r'cookie|authorization)\s*[:=]\s*\S+|'
    r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b|'
    r'\b\d{3}-\d{2}-\d{4}\b|[\w.+-]+@[\w.-]+\.[a-z]{2,})')
_URL = re.compile(r'https?://[^\s<>\"\']+')


def reusable_value(value, depth=0):
    """Reject obvious secrets/records and remove ephemeral URL parameters.

    These checks supplement the model's sanitized-navigation contract. They do
    not claim to classify every possible personal detail in arbitrary prose.
    """
    if depth > 12:
        raise ValueError('Knowledge structure is too deeply nested')
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            if not isinstance(key, str) or _PRIVATE_KEY.fullmatch(key.strip()):
                raise ValueError('Knowledge must exclude credentials and identifiable records')
            output[key] = reusable_value(item, depth + 1)
        return output
    if isinstance(value, list):
        return [reusable_value(item, depth + 1) for item in value]
    if isinstance(value, str):
        if _PRIVATE_TEXT.search(value):
            raise ValueError('Knowledge must exclude credentials and identifiable records')
        def clean(match):
            parsed = urlsplit(match.group())
            if not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('Saved URLs must exclude credentials')
            # Route parameters describing identifiable records are templates.
            from .site_knowledge import _template_route
            origin = urlunsplit((parsed.scheme, parsed.netloc, '', '', ''))
            path = _template_route(parsed.path or '/', origin)
            return urlunsplit((parsed.scheme, parsed.netloc, path, '', ''))
        return _URL.sub(clean, value).strip()
    return value


def canonical_site_origin(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Website storage requires an HTTP(S) origin without credentials')
    host = parsed.hostname.lower().rstrip('.')
    if ':' in host:
        host = '[' + host + ']'
    port = parsed.port
    if port is not None and port != (443 if parsed.scheme == 'https' else 80):
        host += ':' + str(port)
    return parsed.scheme.lower() + '://' + host


def site_folder(context, site_origin, *, root=None):
    """One stable folder per exact origin; app/tenant namespaces live inside."""
    from .site_knowledge import knowledge_directory
    checked = canonical_site_origin(site_origin)
    host = re.sub('[^a-z0-9.-]', '-', urlsplit(checked).netloc.lower())[:80]
    key = hashlib.sha256(checked.encode()).hexdigest()[:16]
    selected = knowledge_directory(context) if root is None else Path(root)
    result = selected / 'sites' / (host + '-' + key)
    reject_path_redirection(result)
    return result


def website_storage_root(legacy_websites_root):
    """The historical websites subtree and new sites tree share one root."""
    selected = Path(legacy_websites_root)
    return selected.parent if selected.name == 'websites' else selected


def evidence_namespace(context, site_origin):
    """Share explicit app/tenant scope while keeping origin default deterministic."""
    from .site_knowledge import _hash, _session, _digest, SCHEMA_VERSION
    checked = canonical_site_origin(site_origin)
    binding = context.get('site_knowledge_bindings', {}).get(checked)
    if binding is not None:
        if (not isinstance(binding, dict) or binding.get('session') != _session(context)
                or not _digest(binding.get('approval_hash')) or not _digest(binding.get('review_sha256'))
                or not isinstance(binding.get('scope'), dict) or binding['scope'].get('origin') != checked):
            raise ValueError('Refresh the explicit website namespace before saving task evidence')
        return _hash(binding['scope'])
    return _hash({'origin': checked, 'tenant': 'signed-in-account',
                  'user_scope': 'local-' + _hash(getpass.getuser())[:24],
                  'environment': 'session', 'schema_version': SCHEMA_VERSION})


def evidence_folder(context, site_url, collector, *, root):
    if collector not in {'crawl4ai', 'browser'}:
        raise ValueError('Use a registered website evidence collector')
    origin = canonical_site_origin(site_url)
    folder = site_folder(context, origin, root=root) / 'namespaces' / evidence_namespace(context, origin) / 'evidence' / collector
    reject_path_redirection(folder)
    return folder


def method_identity(method):
    payload = {key: item for key, item in method.items()
               if key not in {'source_call_ids', 'duration_ms', 'label'}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def recommended_methods(methods):
    groups = {}
    for method in methods:
        groups.setdefault((method['path'], method['purpose']), []).append(method)
    selected = []
    for key in sorted(groups):
        selected.append(min(groups[key], key=lambda method: (
            method.get('duration_ms', float('inf')), len(method['steps']), method_identity(method))))
    return selected


def _write_view(path, text):
    reject_path_redirection(path)
    if io_path(path).is_file() and io_path(path).read_text(encoding='utf-8') == text:
        return
    write_preserving(path, text)
    if io_path(path).read_text(encoding='utf-8') != text:
        raise OSError('Knowledge view readback failed')


def publish_site_view(context, scope, namespace, record, history=()):
    """Publish readable current hints and labeled methods after ledger commit."""
    root = site_folder(context, scope['origin'])
    folder = root / 'namespaces' / namespace
    knowledge = record['knowledge']
    # History stays in SQLite. The intake file contains only the current state;
    # previous methods have a separate bounded view to avoid slowing retrieval.
    intake = dict(knowledge)
    if intake.get('navigation_methods'):
        intake['navigation_methods'] = recommended_methods(intake['navigation_methods'])
    summary = {'origin': scope['origin'], 'namespace_id': namespace,
               'revision': record['revision'], 'payload_sha256': record['payload_sha256'],
               'expires_at': record['expires_at'], 'invalidated_at': record['invalidated_at'],
               'knowledge': intake}
    current = ('# Website navigation knowledge\n\n'
               'Derived from discovery-v1/ledger.sqlite3; verify current page before reuse.\n\n'
               + json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2) + '\n')
    _write_view(folder / 'current.md', current)
    methods = {}
    for revision in list(history) + [record]:
        for method in revision.get('knowledge', {}).get('navigation_methods', []):
            key = method_identity(method)
            methods[key] = dict(method, method_id=key, revision=revision['revision'])
    groups = {}
    for method in methods.values():
        groups.setdefault((method['path'], method['purpose']), []).append(method)
    organized = []
    for key in sorted(groups):
        candidates = sorted(groups[key], key=lambda method: (
            method.get('duration_ms', float('inf')), len(method['steps']), -method['revision']))
        for index, method in enumerate(candidates[:8]):
            organized.append(dict(method, status='recommended_verified' if index == 0 else 'previous_verified'))
    text = ('# Verified navigation methods\n\n'
            'Older methods remain labeled; the fastest measured method is recommended. '
            'Without comparable timing, fewer steps are preferred. Historical revisions remain in the ledger.\n\n'
            + json.dumps(organized[:40], ensure_ascii=True, sort_keys=True, indent=2) + '\n')
    _write_view(folder / 'methods.md', text)
    return {'status': 'verified', 'site_folder': str(root), 'current_path': str(folder / 'current.md'),
            'methods_path': str(folder / 'methods.md'), 'authoritative_store': 'discovery-v1/ledger.sqlite3'}


def publish_discovery_view(context, partition, record):
    """Keep public static-map summaries under the same canonical site folder."""
    folder = site_folder(context, record['origin']) / 'namespaces' / partition
    summary = {key: record[key] for key in ('origin', 'revision', 'scope_identity', 'last_verified')}
    summary['routes'] = [{key: route[key] for key in ('url', 'purpose', 'status', 'last_verified')}
                         for route in record['routes']]
    summary['actions'] = record['actions']
    text = ('# Public static navigation map\n\n'
            'Derived from the ledger. Public GET evidence does not prove a rendered browser transition.\n\n'
            + json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2) + '\n')
    _write_view(folder / 'public-static-map.md', text)
    return {'status': 'verified', 'path': str(folder / 'public-static-map.md')}
