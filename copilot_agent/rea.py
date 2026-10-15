"""Bounded, passive REA CLI capabilities owned by the existing ToolRegistry.

Inspected upstream: morluto/rea d7651b6, rea-agents 6.5.0 (MIT).
No model, MCP server, target executable or arbitrary command is launched here.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit
import uuid

from .logging_utils import now, redact
from .persistence import io_path, write_json
from .policy import PathPolicy, PolicyError, config_value, reject_path_redirection


def _schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


PATH = {'type': 'string', 'minLength': 1, 'maxLength': 4096}
REA_SPECS = {
    'rea.inspect_page': (_schema({
        'tab_id': {'type': 'string', 'minLength': 1, 'maxLength': 100},
        'observation_ms': {'type': 'integer', 'minimum': 0, 'maximum': 3000},
    }), 'read_only', 'Preferred broad technical research: passively inspect one already owned, approved website tab with REA. Returns redacted structural/network evidence, provenance and limitations. No navigation, login, page text, cookies, storage values, script sources or active requests.'),
    'rea.analyze_capture': (_schema({
        'path': PATH, 'format': {'type': 'string', 'enum': ['har', 'saz']},
    }, ('path', 'format')), 'read_only', 'Inspect an approved retained HAR or Fiddler Everywhere SAZ capture offline with REA. Never replay requests. Returns structural request/response evidence and source locations with headers, payload values and query strings omitted.'),
    'rea.analyze_artifact': (_schema({
        'path': PATH, 'kind': {'type': 'string', 'enum': ['managed', 'go', 'rust', 'javascript']},
    }, ('path', 'kind')), 'read_only', 'Statically inspect an approved .NET assembly, Go or Rust binary, or JavaScript/Electron directory/ASAR with REA. Never execute the target. Returns evidence, source locations and explicit coverage/unknowns. General native decompilation requires providers and is not exposed.'),
}

COMMANDS = {'managed': 'inspect-managed-artifact', 'go': 'inspect-go-binary',
            'rust': 'inspect-rust-binary', 'javascript': 'analyze-javascript-application'}
_SENSITIVE_KEYS = re.compile(r'(?i)(?:password|passwd|credential|cookie|authorization|token|api.?key|secret)')
_OMIT_KEYS = frozenset({'raw_result', 'reported', 'text', 'body', 'postData', 'post_data',
                        'content', 'content_base64', 'source_text', 'source_code',
                        'headers', 'request_headers', 'response_headers', 'query', 'queryString',
                        'numeric_literals', 'binary_fields', 'captured_output', 'console', 'storage'})


def _repository(config):
    configured = config_value(config, 'rea_repository', '')
    if configured:
        root = Path(configured).expanduser()
        if not root.is_absolute():
            raise ValueError('rea_repository must be an absolute trusted administrator path')
        return root
    project = Path(config_value(config, 'root', Path(__file__).resolve().parents[1])).resolve()
    return project.parent / 'Copilot Local Agent Research' / 'rea'


def rea_health(config):
    """Cheap availability only; never install packages or launch REA at startup."""
    base = {'interface': 'cli', 'capabilities': list(REA_SPECS),
            'runtime_requirement': 'Node ^22.19.0, ^24.11.0 or >=26; runtime checked by REA on invocation'}
    if not config_value(config, 'rea_enabled', True):
        return {**base, 'status': 'disabled', 'available': False, 'reason': 'REA disabled by administrator configuration'}
    try:
        root = _repository(config)
        reject_path_redirection(root)
        manifest = root / 'package.json'
        if not manifest.is_file() or manifest.stat().st_size > 100000:
            raise ValueError('REA package manifest unavailable')
        package = json.loads(manifest.read_text(encoding='utf-8'))
        if package.get('name') != 'rea-agents' or not re.fullmatch(r'6\.5\.\d+', str(package.get('version', ''))):
            raise ValueError('REA package must be a compatible rea-agents 6.5.x installation')
        files = ['scripts/rea.mjs', 'dist/cli-runtime/cli.js', 'dist/cli-runtime/cliOutput.js',
                 'dist/cli-runtime/cliResultOutput.js']
        for name in files:
            reject_path_redirection(root / name)
            if not (root / name).is_file():
                raise ValueError('REA compiled runtime missing; in its checkout run npm ci then npm run build:cached')
        if os.name == 'nt':
            native = root / 'native' / 'windows' / 'build'
            manifest_path = native / 'manifest.json'
            addon = native / 'rea-windows-x64.node'
            reject_path_redirection(manifest_path)
            reject_path_redirection(addon)
            if not manifest_path.is_file() or manifest_path.stat().st_size > 16384 or not addon.is_file():
                raise ValueError('REA Windows native controls missing; restore the exact matching published artifact and run npm run verify:windows-native:artifact')
            metadata = json.loads(manifest_path.read_text(encoding='utf-8'))
            if (metadata.get('packageVersion') != package['version'] or metadata.get('platform') != 'win32'
                    or metadata.get('architecture') != 'x64' or addon.stat().st_size > 16777216
                    or hashlib.sha256(addon.read_bytes()).hexdigest() != metadata.get('artifactSha256')):
                raise ValueError('REA Windows native artifact version/identity mismatch; run npm run verify:windows-native:artifact')
        selected = config_value(config, 'rea_node_executable', '')
        executable = str(Path(selected).expanduser()) if selected else shutil.which('node')
        if not executable or not Path(executable).is_absolute() or not Path(executable).is_file():
            raise ValueError('Node runtime unavailable; configure a trusted absolute rea_node_executable')
        reject_path_redirection(executable)
        if Path(executable).suffix.lower() in {'.cmd', '.bat', '.ps1'}:
            raise ValueError('REA Node runtime must be a native executable, not a shell wrapper')
        native = (root / 'native/windows/build/manifest.json').is_file() and (root / 'native/windows/build/rea-windows-x64.node').is_file()
        return {**base, 'status': 'available', 'available': True, 'version': package['version'],
                'repository': str(root.resolve()), 'node': executable,
                'windows_native_artifact_present': native if os.name == 'nt' else None,
                'warnings': ['Windows HAR/SAZ and JavaScript analysis need the exact-version packaged native addon; follow REA native/windows/README.md.'] if os.name == 'nt' and not native else []}
    except (OSError, ValueError, TypeError) as error:
        return {**base, 'status': 'unavailable', 'available': False, 'reason': str(error)}


def _bounded(config, name, default, minimum, maximum):
    value = config_value(config, name, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer from {minimum} to {maximum}')
    return value


def _file_identity(path, policy, limit):
    checked = policy.resolve(path, must_exist=True)
    if hasattr(policy, 'require_operation'):
        policy.require_operation(checked, 'read')
    if not checked.is_file() or checked.stat().st_size > limit:
        raise PolicyError('REA input must be an approved regular file within the configured size budget')
    digest = hashlib.sha256()
    count = 0
    with checked.open('rb') as stream:
        while block := stream.read(65536):
            count += len(block)
            if count > limit:
                raise PolicyError('REA input grew beyond its size budget')
            digest.update(block)
    return {'path': str(checked), 'sha256': digest.hexdigest(), 'bytes': count}


def _artifact_identity(path, kind, policy, limit):
    raw = str(path)
    if '\x00' in raw or '..' in Path(raw).parts:
        raise PolicyError('REA input must not contain traversal or NUL characters')
    checked = policy.resolve(path, must_exist=True)
    if not checked.is_dir():
        return _file_identity(checked, policy, limit)
    if kind != 'javascript':
        raise PolicyError('Only static JavaScript application analysis accepts a directory')
    # Admit every member, including credential exclusions, before REA can read it.
    files, total, visited = [], 0, 0
    pending = [checked]
    while pending:
        folder = pending.pop()
        for entry in folder.iterdir():
            visited += 1
            if visited > 2000:
                raise PolicyError('REA application inventory exceeds 2000 entries; select a smaller artifact')
            member = policy.resolve(entry, must_exist=True)
            if member.is_dir():
                pending.append(member)
            else:
                record = _file_identity(member, policy, limit - total)
                total += record['bytes']
                files.append({**record, 'path': str(member.relative_to(checked))})
    canonical = json.dumps(sorted(files, key=lambda item: item['path']), sort_keys=True).encode('utf-8')
    return {'path': str(checked), 'sha256': hashlib.sha256(canonical).hexdigest(), 'bytes': total,
            'file_count': len(files)}


def _fixed_local(path):
    """REA's Windows artifact admission requires a fixed local NTFS volume."""
    reject_path_redirection(path)
    if os.name != 'nt':
        return not str(path).startswith('\\\\')
    import ctypes
    volume = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetVolumePathNameW(str(path), volume, len(volume)):
        return False
    if ctypes.windll.kernel32.GetDriveTypeW(volume.value) != 3:
        return False
    filesystem = ctypes.create_unicode_buffer(64)
    if not ctypes.windll.kernel32.GetVolumeInformationW(volume.value, None, 0, None, None, None, filesystem, len(filesystem)):
        return False
    return filesystem.value.upper() == 'NTFS'


def _stage_input(prepared, kind, context, policy):
    """Copy approved bytes to owned local scratch; durable evidence stays put."""
    candidates = []
    if os.environ.get('LOCALAPPDATA'):
        candidates.append(Path(os.environ['LOCALAPPDATA']) / 'Copilot Local Agent' / 'rea-scratch')
    candidates.append(Path(tempfile.gettempdir()) / 'copilot-rea-scratch')
    errors = []
    source = Path(prepared['target'])
    limit = config_value(context.get('config', {}), 'rea_max_input_bytes', 20971520)
    for candidate in candidates:
        scratch = None
        try:
            candidate = candidate.absolute()
            reject_path_redirection(candidate)
            candidate.mkdir(parents=True, exist_ok=True)
            if not _fixed_local(candidate):
                raise OSError('Scratch candidate is not a supported fixed local filesystem')
            scratch = candidate / uuid.uuid4().hex
            context['rea_retained_scratch'] = str(scratch)
            scratch.mkdir()
            target = scratch / source.name
            if source.is_dir():
                target.mkdir()
                pending = [(source, target)]
                visited = 0
                remaining = limit
                while pending:
                    current, destination = pending.pop()
                    for child in current.iterdir():
                        visited += 1
                        if visited > 2000:
                            raise PolicyError('REA application changed beyond its inventory budget during staging')
                        checked = policy.resolve(child, must_exist=True)
                        output = destination / child.name
                        if checked.is_dir():
                            output.mkdir()
                            pending.append((checked, output))
                        else:
                            _file_identity(checked, policy, remaining)
                            remaining -= _copy_bounded(checked, output, remaining)
            else:
                _copy_bounded(policy.resolve(source, must_exist=True), target, limit)
            source_after = _artifact_identity(source, kind, policy, limit)
            staged = _artifact_identity(target, kind, PathPolicy([scratch]), limit)
            expected = prepared['input']
            if (source_after != expected or staged['sha256'] != expected['sha256']
                    or staged['bytes'] != expected['bytes']):
                raise PolicyError('REA source changed while its immutable local snapshot was being copied')
            return {'root': str(scratch), 'target': str(target), 'original': str(source),
                    'sha256': staged['sha256'], 'bytes': staged['bytes']}
        except OSError as error:
            errors.append(type(error).__name__)
            if scratch is not None:
                _clean_scratch(scratch)
                context.pop('rea_retained_scratch', None)
            context['rea_cleanup_confirmed'] = True
        except BaseException:
            if scratch is not None:
                _clean_scratch(scratch)
                context.pop('rea_retained_scratch', None)
            context['rea_cleanup_confirmed'] = True
            raise
    raise OSError('No writable fixed local REA scratch candidate succeeded: ' + ', '.join(errors))


def _copy_bounded(source, target, limit):
    total = 0
    with source.open('rb') as incoming, target.open('xb') as outgoing:
        while block := incoming.read(65536):
            total += len(block)
            if total > limit:
                raise PolicyError('REA source grew beyond its staging byte budget')
            outgoing.write(block)
    return total


def _clean_scratch(path):
    path = Path(path)
    if not re.fullmatch('[a-f0-9]{32}', path.name) or path.parent.name not in {'rea-scratch', 'copilot-rea-scratch'}:
        raise PolicyError('REA cleanup refused a path outside its unique owned scratch')
    reject_path_redirection(path)
    for folder, directories, files in os.walk(path, followlinks=False):
        for name in [*directories, *files]:
            reject_path_redirection(Path(folder) / name)
    shutil.rmtree(path)


def _restore_source_paths(value, staging):
    if isinstance(value, str):
        for staged, original in ((staging['target'], staging['original']),
                                 (staging['target'].replace('\\', '/'), staging['original'].replace('\\', '/'))):
            if value == staged or value.startswith(staged + '\\') or value.startswith(staged + '/'):
                return original + value[len(staged):]
        return value
    if isinstance(value, list):
        return [_restore_source_paths(item, staging) for item in value]
    if isinstance(value, dict):
        return {key: _restore_source_paths(item, staging) for key, item in value.items()}
    return value


def _endpoint(browser):
    value = getattr(browser, 'endpoint', '')
    if callable(value):
        value = value()
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', '::1'}
            or parsed.port is None or parsed.username or parsed.password
            or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
        raise PolicyError('REA requires the owned browser literal-loopback CDP endpoint')
    return value.rstrip('/')


def _page_scope(args, context):
    from .web_navigation import get_navigation_page
    page = get_navigation_page(context, args.get('tab_id'))
    config = context.get('config', {})
    domains = [*config_value(config, 'allowed_domains', []), *context.get('approved_domains', [])]
    # Deliberately use strict URLPolicy even in supervised fast mode.
    from .session_mode import ApprovedWebsitePolicy, fast_mode, website_policy
    scoped = (ApprovedWebsitePolicy(domains, config_value(config, '_session_approved_origins', ()))
              if fast_mode(config) else website_policy(config, domains))
    url = scoped.resolve(page.url)
    parsed = urlsplit(url)
    host = parsed.hostname
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    origin = urlunsplit((parsed.scheme, parsed.netloc, '', '', ''))
    if (address is not None and not address.is_global and host not in context.get('approved_domains', [])
            and origin not in config_value(config, '_session_approved_origins', [])):
        raise PolicyError('Private browser targets require an explicit session target grant')
    browser = context.get('browser')
    endpoint = _endpoint(browser)
    state = getattr(browser, '_navigation_state', {})
    tab = state.get('tabs', {}).get(args.get('tab_id') or 'tab-1', {})
    if tab.get('customer_key') is not None and tab.get('customer_key') != context.get('customer_key'):
        raise PolicyError('REA customer-bound tab requires its exact active customer context')
    if tab.get('task_id') is not None and tab.get('task_id') != context.get('task_id'):
        raise PolicyError('REA task-bound tab requires its exact active task context')
    return page, origin, endpoint


def validate_rea(name, args, context, policy):
    if name not in REA_SPECS:
        raise ValueError('Unknown REA operation')
    # Registry validates too; this remains strict for direct internal callers.
    from .tools import validate
    validate(args, REA_SPECS[name][0])
    config = context.get('config', {})
    _bounded(config, 'rea_timeout_seconds', 45, 1, 180)
    _bounded(config, 'rea_max_output_bytes', 1048576, 16384, 8388608)
    _bounded(config, 'rea_max_parallel', 3, 1, 8)
    limit = _bounded(config, 'rea_max_input_bytes', 20971520, 1024, 104857600)
    if name == 'rea.inspect_page':
        page, origin, _ = _page_scope(args, context)
        parsed = urlsplit(page.url)
        target = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/', '', ''))
        return {'target': target, 'target_type': 'owned_browser', 'url': page.url}
    identity = _artifact_identity(args['path'], args.get('kind'), policy, limit)
    return {'target': identity['path'], 'target_type': args.get('format', args.get('kind')),
            'input': identity}


def _capture_metadata(value):
    """Project producer traffic into useful facts without exporting payloads."""
    if not isinstance(value, dict):
        return '[OMITTED]'
    result = {}
    for side in ('request', 'response'):
        record = value.get(side)
        if isinstance(record, dict):
            result[side] = {key: item for key, item in record.items()
                            if key in {'method', 'url', 'status', 'statusCode', 'httpVersion', 'member'}
                            and type(item) in {str, int}}
    for key in ('startedDateTime', 'time'):
        if type(value.get(key)) in {str, int, float}:
            result[key] = value[key]
    return result


def _safe(value, depth=0):
    """Retain structural evidence; strip raw capture/credential carriers everywhere."""
    if depth > 64:
        raise ValueError('REA output nesting exceeds 64')
    if isinstance(value, dict):
        # Header name/value pairs need semantic handling, regardless of spelling.
        if isinstance(value.get('name'), str) and _SENSITIVE_KEYS.search(value['name']):
            return {'name': '[REDACTED]', 'value': '[REDACTED]'}
        return {key: _safe(_capture_metadata(item), depth + 1) if key == 'reported'
                else '[OMITTED]' if key in {'value', 'literal'} and isinstance(item, str)
                else _safe(item, depth + 1) if key == 'source' and value.get('kind') in {'source-range', 'artifact-path', 'file-offset', 'file-offset-range'}
                else '[OMITTED]' if key == 'source'
                else '[OMITTED]' if _SENSITIVE_KEYS.search(key) or key in _OMIT_KEYS
                else _safe(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe(item, depth + 1) for item in value]
    if isinstance(value, str):
        # Strip all URL queries/fragments, including unrecognized secret names.
        def clean_url(match):
            try:
                parsed = urlsplit(match.group(0))
                host = parsed.hostname or ''
                if ':' in host:
                    host = '[' + host + ']'
                if parsed.port:
                    host += ':' + str(parsed.port)
                return urlunsplit((parsed.scheme, host, parsed.path, '', ''))
            except ValueError:
                return '[REDACTED_URL]'
        return redact(re.sub(r'https?://[^\s<>"\x00-\x1f]+', clean_url, value))
    return value


def _json_object(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field in REA output')
            result[key] = value
        return result
    value = json.loads(data.decode('utf-8', errors='strict'), object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON value')))
    if type(value) is not dict:
        raise ValueError('REA output must be one JSON object')
    # Incur --full-output wraps a successful result; ordinary output may be bare.
    if value.get('ok') is True and isinstance(value.get('data'), dict):
        value = value['data']
    return value


def _normalize(data, returncode):
    value = _json_object(data)
    if value.get('ok') is False and isinstance(value.get('error'), dict):
        value = value['error']
    failure = value.get('error') or value.get('code') or value.get('ok') is False
    if failure or returncode != 0:
        code = value.get('code', 'operation_failed')
        details = value.get('details', {})
        uncertain = code == 'cleanup_incomplete'
        partial = isinstance(details, dict) and details.get('partial_observation') is not None
        status = ('uncertain' if uncertain else 'partial' if partial else 'cancelled' if code == 'cancelled'
                  else 'timeout' if code == 'timeout' else 'unavailable'
                  if code in {'capability_unavailable', 'provider_unavailable'} else 'failed')
        return {'status': status,
                'side_effects_uncertain': uncertain, 'error': _safe(value),
                'findings': _safe(details.get('partial_observation')) if partial else None,
                'limitations': ['REA did not produce a verified complete observation.']}
    if (not isinstance(value.get('evidence_id'), str) or not isinstance(value.get('provider'), dict)
            or 'normalized_result' not in value
            or value.get('confidence') not in {'observed', 'derived', 'inferred'}
            or not isinstance(value.get('operation'), str)):
        raise ValueError('REA returned an unsupported or ambiguous Evidence object')
    safe = _safe(value)
    findings = safe['normalized_result']
    incomplete = _incomplete(findings)
    return {'status': 'partial' if incomplete else 'completed', 'side_effects_uncertain': False,
            'findings': findings, 'evidence': safe, 'confidence': value['confidence'],
            'limitations': safe.get('limitations', []), 'unknowns': safe.get('unknowns', []),
            'redactions': ['Raw payloads, headers, credential carriers, URL queries and fragments omitted.']}


def _incomplete(value):
    if isinstance(value, dict):
        coverage = value.get('coverage')
        if (value.get('complete') is False
                or value.get('status') in {'partial', 'incomplete', 'failed', 'cancelled', 'uncertain'}
                or isinstance(coverage, dict) and coverage.get('status') in {'partial', 'unknown', 'unavailable'}):
            return True
        return any(_incomplete(item) for item in value.values())
    return isinstance(value, list) and any(_incomplete(item) for item in value)


async def _run(command, *, cwd, timeout, output_limit, context):
    from .local_python_runner import _read_bounded, _terminate_pid
    allowed = {'SYSTEMROOT', 'WINDIR', 'PATH', 'PATHEXT', 'TEMP', 'TMP', 'LANG', 'LC_ALL', 'USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA'}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env['REA_LOG_LEVEL'] = 'silent'
    options = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)} if os.name == 'nt' else {'start_new_session': True}
    context['rea_cleanup_confirmed'] = False
    try:
        process = await asyncio.create_subprocess_exec(*command, cwd=cwd, env=env,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, **options)
    except OSError:
        context['rea_cleanup_confirmed'] = True
        raise
    context['rea_execution_started'] = True
    readers = [asyncio.create_task(_read_bounded(process.stdout, output_limit)),
               asyncio.create_task(_read_bounded(process.stderr, min(output_limit, 65536)))]
    waiter = asyncio.create_task(process.wait())
    deadline = time.monotonic() + timeout
    try:
        while not all(task.done() for task in [*readers, waiter]):
            for task in readers:
                if task.done():
                    task.result()
            cancelled = context.get('cancelled')
            if callable(cancelled) and cancelled():
                raise asyncio.CancelledError()
            if time.monotonic() >= deadline:
                raise asyncio.TimeoutError()
            await asyncio.wait([task for task in [*readers, waiter] if not task.done()], timeout=.1,
                               return_when=asyncio.FIRST_COMPLETED)
        context['rea_cleanup_confirmed'] = True
        return {'stdout': readers[0].result(), 'stderr': readers[1].result(), 'returncode': process.returncode}
    except (asyncio.CancelledError, Exception) as error:
        # Reuse the project's owned-process termination primitive. Never kill a
        # PID once this child's exit has been observed, when it could be reused.
        stopped = (all(task.done() for task in readers) if process.returncode is not None
                   else await asyncio.shield(asyncio.to_thread(_terminate_pid, process.pid)))
        try:
            await asyncio.wait_for(asyncio.shield(waiter), 3)
        except asyncio.TimeoutError:
            stopped = False
        status = ('cancelled' if isinstance(error, asyncio.CancelledError) else 'timeout'
                  if isinstance(error, asyncio.TimeoutError) else 'output_limit'
                  if isinstance(error, PolicyError) else 'failed')
        context['rea_cleanup_confirmed'] = stopped
        return {'stdout': b'', 'stderr': b'', 'returncode': process.returncode,
                'status': status if stopped else 'uncertain', 'side_effects_uncertain': not stopped}
    finally:
        for task in [*readers, waiter]:
            if not task.done():
                task.cancel()
        await asyncio.gather(*readers, waiter, return_exceptions=True)


def _save(result, context):
    session = Path(context['session_dir']).resolve()
    reject_path_redirection(session)
    path = session / 'rea' / (result['execution_id'] + '.json')
    reject_path_redirection(path)
    write_json(path, _safe(result))
    content = io_path(path).read_bytes()
    result['evidence_path'] = str(path)
    result['evidence_sha256'] = hashlib.sha256(content).hexdigest()
    return result


async def execute_rea(name, args, context, policy):
    context['rea_execution_started'] = False
    context['rea_cleanup_confirmed'] = True
    context.pop('rea_retained_scratch', None)
    prepared = validate_rea(name, args, context, policy)
    config = context.get('config', {})
    health = rea_health(config)
    base = {'execution_id': uuid.uuid4().hex, 'tool': name, 'target': prepared['target'],
            'target_type': prepared['target_type'], 'started_at': now(),
            'side_effects_uncertain': False, 'execution_started': False,
            'provenance': {'interface': 'REA fixed CLI', 'version': health.get('version'),
                           'input': prepared.get('input'), 'request_id': context.get('source_request_id')},
            'recovery': ['Use operation.list/operation.call for a known API operation, Crawl4AI for content, or a specialized registered inspection tool.']}
    if not health['available']:
        return {**base, 'status': 'unavailable', 'finished_at': now(), 'diagnostic': health}
    slots = _bounded(config, 'rea_max_parallel', 3, 1, 8)
    # Context is session-owned; reset when a later test/runtime uses a new loop.
    loop = asyncio.get_running_loop()
    runtime = context.setdefault('_rea_runtime', {})
    semaphore = runtime.get('semaphore')
    if semaphore is None or runtime.get('loop') is not loop:
        semaphore = runtime['semaphore'] = asyncio.Semaphore(slots)
        runtime['loop'] = loop
    async with semaphore:
        command = [health['node'], '--max-old-space-size=384', str(Path(health['repository']) / 'scripts/rea.mjs')]
        page = None
        staging = None
        if name != 'rea.inspect_page':
            try:
                context['rea_cleanup_confirmed'] = False
                staging = _stage_input(prepared, args.get('kind'), context, policy)
                context['rea_cleanup_confirmed'] = True
            except OSError as error:
                uncertain = context.get('rea_cleanup_confirmed') is False
                return {**base, 'status': 'uncertain' if uncertain else 'unavailable',
                        'side_effects_uncertain': uncertain, 'finished_at': now(),
                        **({'retained_scratch': context['rea_retained_scratch']} if context.get('rea_retained_scratch') else {}),
                        'diagnostic': {'code': 'local_scratch_unavailable', 'message': str(error)},
                        'limitations': ['No REA process started. Retained original input and existing research tools remain available.']}
            base['provenance']['staging'] = {'sha256': staging['sha256'], 'bytes': staging['bytes'],
                                           'input_snapshot': 'verified immutable local copy; source coordinates restored in returned evidence'}
        if name == 'rea.inspect_page':
            page, origin, endpoint = _page_scope(args, context)
            context['rea_cleanup_confirmed'] = False
            session = await page.context.new_cdp_session(page)
            try:
                info = await session.send('Target.getTargetInfo')
                target = info['targetInfo']
                if target.get('type') != 'page' or target.get('url') != page.url:
                    raise PolicyError('Owned browser target identity changed before REA inspection')
                command += ['inspect-web-page', endpoint, target['targetId'], '--allowed-origins', origin,
                            '--observation-ms', str(args.get('observation_ms', 500))]
            finally:
                await session.detach()
                context['rea_cleanup_confirmed'] = True
        elif name == 'rea.analyze_capture':
            command += ['inspect-web-network-capture', staging['target'], args['format']]
        else:
            command += [COMMANDS[args['kind']], staging['target']]
            if args['kind'] == 'javascript':
                command += ['--max-heap-mb', '256', '--max-semantic-nodes', '10000',
                            '--max-semantic-nodes-per-file', '3000', '--analysis-timeout-ms',
                            str(config_value(config, 'rea_timeout_seconds', 45) * 1000)]
        command += ['--json', '--full-output']
        base['operation'] = command[3]
        try:
            run = await _run(command, cwd=health['repository'],
                timeout=config_value(config, 'rea_timeout_seconds', 45),
                output_limit=config_value(config, 'rea_max_output_bytes', 1048576), context=context)
            base['execution_started'] = context.get('rea_execution_started', False)
            if run.get('status'):
                result = {**base, 'status': run['status'], 'side_effects_uncertain': run['side_effects_uncertain'],
                          'limitations': ['REA output was not accepted; no complete observation is claimed.']}
            else:
                result = {**base, **_normalize(run['stdout'], run['returncode']), 'exit_status': run['returncode'],
                          'stdout_bytes': len(run['stdout']), 'stderr_bytes': len(run['stderr'])}
                if result.get('side_effects_uncertain'):
                    context['rea_cleanup_confirmed'] = False
            if page is not None and page.url != prepared['url']:
                result.update(status='partial', limitations=['Owned page navigated during passive inspection; inspect its new state before reuse.'])
            if page is None:
                after = validate_rea(name, args, context, policy)
                if after['input'] != prepared['input'] and not result.get('side_effects_uncertain'):
                    result.update(status='partial', limitations=['Input changed during analysis; findings are not a verified observation of current bytes.'])
        except asyncio.CancelledError:
            base['execution_started'] = context.get('rea_execution_started', False)
            result = {**base, 'status': 'uncertain', 'side_effects_uncertain': True,
                      'error': {'code': 'cancelled', 'message': 'Cancellation interrupted REA process startup; inspect owned resources before retry.'}}
        except (ValueError, UnicodeError, RecursionError) as error:
            result = {**base, 'status': 'failed', 'error': {'code': 'invalid_output', 'message': str(error)},
                      'limitations': ['No valid complete REA Evidence object was accepted.']}
            if 'run' in locals():
                result.update(exit_status=run.get('returncode'), stdout_bytes=len(run.get('stdout', b'')),
                              stderr_bytes=len(run.get('stderr', b'')))
        except OSError as error:
            result = {**base, 'status': 'failed', 'error': {'code': 'unavailable', 'message': type(error).__name__},
                      'limitations': ['REA process or input became unavailable.']}
        if staging is not None:
            result = _restore_source_paths(result, staging)
            if result.get('side_effects_uncertain'):
                result['retained_scratch'] = staging['root']
            else:
                try:
                    _clean_scratch(staging['root'])
                    context.pop('rea_retained_scratch', None)
                except (OSError, PolicyError):
                    context['rea_cleanup_confirmed'] = False
                    result.update(status='uncertain', side_effects_uncertain=True,
                                  retained_scratch=staging['root'],
                                  cleanup='Local input snapshot cleanup could not be verified; inspect before retry.')
        result['finished_at'] = now()
        try:
            return _save(result, context)
        except (OSError, ValueError, TypeError, RecursionError) as error:
            return {**base, 'status': 'uncertain', 'finished_at': now(), 'side_effects_uncertain': True,
                    'error': {'code': 'evidence_storage_failed', 'message': type(error).__name__},
                    'recovery': ['Repair session evidence storage and inspect retained state before retry.']}
