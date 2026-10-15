"""Bounded, passive REA CLI capabilities owned by the existing ToolRegistry.

Inspected upstream: morluto/rea d7651b6, rea-agents 6.5.0 (MIT).
No model, MCP server, target executable or arbitrary command is launched here.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
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


class _AvailabilityError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def rea_repository_candidates(config):
    """Deterministic trusted install locations; explicit administrator config wins."""
    configured = config_value(config, 'rea_repository', '')
    if configured:
        root = Path(configured).expanduser()
        if not root.is_absolute():
            raise _AvailabilityError('repository_not_absolute', 'rea_repository must be an absolute trusted administrator path')
        return [root]
    project = Path(config_value(config, 'root', Path(__file__).resolve().parents[1])).resolve()
    candidates = [project / '.runtime' / 'rea']
    if os.environ.get('LOCALAPPDATA'):
        candidates.append(Path(os.environ['LOCALAPPDATA']) / 'Copilot Local Agent' / 'runtimes' / 'rea' / '6.5.0')
    candidates.extend([Path(tempfile.gettempdir()) / 'Copilot Local Agent' / 'runtimes' / 'rea' / '6.5.0',
                       project.parent / 'Copilot Local Agent Research' / 'rea'])
    return list(dict.fromkeys(candidates))


def _repository(config):
    # Compatibility helper; actual selection is validated by rea_health.
    return rea_repository_candidates(config)[0]


def _node_candidates(config):
    selected = config_value(config, 'rea_node_executable', '')
    if selected:
        from .node_runtime import node_path_candidates
        try:
            return node_path_candidates(selected)
        except ValueError:
            return [Path(selected).expanduser()]
    candidates = []
    detected = shutil.which('node')
    if detected:
        candidates.append(Path(detected))
    for variable, relative in (('ProgramFiles', 'nodejs/node.exe'),
                               ('ProgramW6432', 'nodejs/node.exe'),
                               ('LOCALAPPDATA', 'Programs/nodejs/node.exe')):
        if os.environ.get(variable):
            candidates.append(Path(os.environ[variable]) / relative)
    return list(dict.fromkeys(candidates))


def _check_repository(root):
    reject_path_redirection(root)
    manifest = root / 'package.json'
    try:
        manifest_stat = manifest.stat()
    except FileNotFoundError as error:
        raise _AvailabilityError('manifest_missing', f'REA package manifest missing: {manifest}') from error
    if not stat.S_ISREG(manifest_stat.st_mode):
        raise _AvailabilityError('manifest_not_file', f'REA package manifest is not a regular file: {manifest}')
    if manifest_stat.st_size > 100000:
        raise _AvailabilityError('manifest_oversized', f'REA package manifest exceeds 100000 bytes: {manifest}')
    try:
        package = json.loads(manifest.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise _AvailabilityError('manifest_invalid_json', f'REA package manifest invalid JSON: {manifest}') from error
    if not isinstance(package, dict) or package.get('name') != 'rea-agents' or not re.fullmatch(r'6\.5\.\d+', str(package.get('version', ''))):
        raise _AvailabilityError('manifest_incompatible', f'REA package must be a compatible rea-agents 6.5.x installation: {manifest}')
    files = ['scripts/rea.mjs', 'dist/cli-runtime/cli.js', 'dist/cli-runtime/cliOutput.js',
             'dist/cli-runtime/cliResultOutput.js']
    for name in files:
        reject_path_redirection(root / name)
        if not (root / name).is_file():
            raise _AvailabilityError('compiled_runtime_missing', f'REA compiled runtime missing: {root / name}; run bootstrap/setup_rea.py')
    dependencies = package.get('dependencies', {})
    if not isinstance(dependencies, dict) or len(dependencies) > 100:
        raise _AvailabilityError('manifest_dependencies_invalid', f'REA package dependency manifest invalid: {manifest}')
    for dependency in dict.fromkeys(['zod', *dependencies]):
        if not isinstance(dependency, str) or not re.fullmatch(r'(?:@[a-zA-Z0-9_.-]+/)?[a-zA-Z0-9_.-]+', dependency):
            raise _AvailabilityError('manifest_dependencies_invalid', f'REA package dependency name invalid: {manifest}')
        dependency_manifest = root / 'node_modules' / dependency / 'package.json'
        reject_path_redirection(dependency_manifest)
        if not dependency_manifest.is_file():
            raise _AvailabilityError('runtime_dependency_missing', f'REA runtime dependency missing: {dependency_manifest}; run bootstrap/setup_rea.py')
    if os.name == 'nt':
        native = root / 'native' / 'windows' / 'build'
        manifest_path = native / 'manifest.json'
        addon = native / 'rea-windows-x64.node'
        reject_path_redirection(manifest_path)
        reject_path_redirection(addon)
        if not manifest_path.is_file() or manifest_path.stat().st_size > 16384 or not addon.is_file():
            raise _AvailabilityError('native_artifact_missing', f'REA Windows native controls missing: {native}; restore exact matching published artifact with bootstrap/setup_rea.py')
        try:
            metadata = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, UnicodeError) as error:
            raise _AvailabilityError('native_manifest_invalid', f'REA Windows native manifest invalid JSON: {manifest_path}') from error
        if (not isinstance(metadata, dict) or metadata.get('packageVersion') != package['version']
                or metadata.get('platform') != 'win32' or metadata.get('architecture') != 'x64'
                or addon.stat().st_size > 16777216
                or hashlib.sha256(addon.read_bytes()).hexdigest() != metadata.get('artifactSha256')):
            raise _AvailabilityError('native_identity_mismatch', f'REA Windows native artifact version/identity mismatch: {native}; run npm run verify:windows-native:artifact')
    return package


def _check_node(executable, timeout=180):
    if not executable.is_absolute() or not executable.is_file():
        raise _AvailabilityError('node_missing', f'Node runtime unavailable: {executable}; configure a trusted absolute rea_node_executable')
    reject_path_redirection(executable)
    if executable.suffix.lower() in {'.cmd', '.bat', '.ps1'}:
        raise _AvailabilityError('node_shell_wrapper', f'REA Node runtime must be a native executable, not a shell wrapper: {executable}')
    from .rea_readiness import native_probe
    result = native_probe([str(executable), '--version'], timeout=timeout, output_limit=4096)
    if result.get('cleanup_uncertain'):
        raise _AvailabilityError('node_probe_cleanup_uncertain', f'Node version check cleanup is uncertain: {executable}')
    if result.get('error'):
        raise _AvailabilityError('node_probe_' + result['error'], f'Node version check {result["error"]} within the shared readiness budget: {executable}')
    version = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)\s*', result.get('stdout', '')[:256]) if result.get('returncode') == 0 else None
    if version is None:
        raise _AvailabilityError('node_probe_invalid', f'Node --version failed or returned an invalid version: {executable}')
    major, minor, patch = map(int, version.groups())
    if not (major >= 26 or major == 24 and minor >= 11 or major == 22 and minor >= 19):
        raise _AvailabilityError('node_version_unsupported', f'Node {major}.{minor}.{patch} is unsupported; need ^22.19.0, ^24.11.0 or >=26')
    return f'{major}.{minor}.{patch}'


def _node_cli_probe(root, executable, timeout=180):
    """Verify actual fixed CLI loading with bounded output and owned cleanup."""
    from .rea_readiness import native_probe
    result = native_probe([str(executable), str(root / 'scripts/rea.mjs'), '--help'],
                          cwd=root, timeout=timeout)
    if result.get('cleanup_uncertain'):
        return 'cli_smoke_cleanup_uncertain'
    if result.get('error'):
        return 'cli_smoke_' + result['error']
    required = ['inspect-web-page', 'inspect-web-network-capture', *COMMANDS.values()]
    if result.get('returncode') != 0 or not all(command in result.get('stdout', '') for command in required):
        return 'cli_smoke_failed_or_capabilities_missing'
    return None


def _node_health_identity(config):
    from .rea_readiness import file_stamp, source_tree_stamp
    roots = rea_repository_candidates(config)
    identities = []
    for root in roots:
        members = [file_stamp(root, include_parents=True), file_stamp(root / 'package.json'),
                   file_stamp(root / 'native/windows/build/manifest.json'),
                   file_stamp(root / 'native/windows/build/rea-windows-x64.node')]
        members.extend(source_tree_stamp(root / 'scripts'))
        members.extend(source_tree_stamp(root / 'dist'))
        dependencies = ['zod']
        try:
            manifest = root / 'package.json'
            if manifest.stat().st_size <= 100000:
                package = json.loads(manifest.read_text(encoding='utf-8'))
                declared = package.get('dependencies', {}) if isinstance(package, dict) else {}
                if isinstance(declared, dict) and len(declared) <= 100:
                    dependencies.extend(name for name in declared if isinstance(name, str)
                                        and re.fullmatch(r'(?:@[a-zA-Z0-9_.-]+/)?[a-zA-Z0-9_.-]+', name))
        except (OSError, ValueError, TypeError):
            pass
        for name in sorted(set(dependencies)):
            members.extend([file_stamp(root / 'node_modules' / name),
                            file_stamp(root / 'node_modules' / name / 'package.json')])
        identities.append(tuple(members))
    return ('node', config_value(config, 'rea_enabled', True),
            config_value(config, 'rea_node_readiness_timeout_seconds', 180),
            tuple(identities), tuple(file_stamp(path, include_parents=True) for path in _node_candidates(config)),
            id(_check_node), id(_node_cli_probe), file_stamp(Path(__file__)))


def _node_health(config):
    """Reuse verified runtime/source identity across catalog and execution calls."""
    from .rea_readiness import cached_health, UNCERTAIN_NODE_PROBES
    selection = (str(config_value(config, 'root', '')), str(config_value(config, 'rea_repository', '')),
                 str(config_value(config, 'rea_node_executable', '')))
    if UNCERTAIN_NODE_PROBES:
        return copy.deepcopy(next(iter(UNCERTAIN_NODE_PROBES.values())))
    try:
        identity = _node_health_identity(config)
    except (OSError, ValueError, TypeError):
        return _node_health_uncached(config)
    result = cached_health(identity, lambda: _node_health_uncached(config),
                           failure_seconds=_bounded(config, 'rea_node_readiness_timeout_seconds', 180, 1, 180))
    if result.get('cleanup_uncertain'):
        UNCERTAIN_NODE_PROBES[selection] = copy.deepcopy(result)
    return result


def _node_health_uncached(config):
    """One shared readiness deadline: local version/help only, never install."""
    allowance = _bounded(config, 'rea_node_readiness_timeout_seconds', 180, 1, 180)
    deadline = time.monotonic() + allowance
    diagnostics = {'manifest_filename': 'package.json', 'repository_candidates': [], 'node_candidates': [],
                   'required_files': ['scripts/rea.mjs', 'dist/cli-runtime/cli.js', 'dist/cli-runtime/cliOutput.js', 'dist/cli-runtime/cliResultOutput.js'],
                   'capability_commands': {'rea.inspect_page': ['inspect-web-page'], 'rea.analyze_capture': ['inspect-web-network-capture'], 'rea.analyze_artifact': list(COMMANDS.values())},
                   'runtime_dependencies': 'Declared production dependency manifests plus zod must exist.',
                   'capability_detection': 'Pinned rea-agents 6.5.x compiled entry points, Windows native integrity and fixed CLI --help capabilities verified.',
                   'readiness_timeout_seconds': allowance,
                   'remediation': ['Run the normal launcher dependency setup to provision pinned REA into a managed runtime folder.',
                                   'Run .venv\\Scripts\\python.exe bootstrap\\setup_rea.py to repair or provision the managed runtime.',
                                   'For an existing built trusted installation set absolute rea_repository and, if required, rea_node_executable, then start a new session.']}
    base = {'interface': 'cli', 'capabilities': list(REA_SPECS),
            'runtime_requirement': 'Node ^22.19.0, ^24.11.0 or >=26; version checked locally at availability assessment',
            'diagnostics': diagnostics}
    if not config_value(config, 'rea_enabled', True):
        return {**base, 'status': 'disabled', 'available': False, 'reason': 'REA disabled by administrator configuration'}
    selected_root, package, selected_node, node_version = None, None, None, None
    try:
        roots = rea_repository_candidates(config)
    except (OSError, ValueError, TypeError) as error:
        roots = []
        diagnostics['repository_candidates'].append({'path': str(config_value(config, 'rea_repository', '')), 'manifest': str(Path(str(config_value(config, 'rea_repository', ''))) / 'package.json'),
            'available': False, 'code': getattr(error, 'code', 'repository_unreadable'), 'reason': str(error)})
    for root in roots:
        attempt = {'path': str(root), 'manifest': str(root / 'package.json'), 'available': False}
        diagnostics['repository_candidates'].append(attempt)
        try:
            package = _check_repository(root)
            attempt.update(available=True, code='ready', version=package['version'])
            selected_root = root
            break
        except (OSError, ValueError, TypeError) as error:
            attempt.update(code=getattr(error, 'code', 'repository_unreadable'), reason=str(error))
    for executable in _node_candidates(config):
        attempt = {'path': str(executable), 'available': False}
        diagnostics['node_candidates'].append(attempt)
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _AvailabilityError('node_probe_timeout', 'Node shared readiness budget exhausted')
            node_version = _check_node(executable, timeout=remaining)
            selected_node = executable
            attempt.update(available=True, code='ready', version=node_version)
            break
        except (OSError, ValueError, TypeError) as error:
            attempt.update(code=getattr(error, 'code', 'node_unreadable'), reason=str(error))
            if getattr(error, 'code', '') == 'node_probe_cleanup_uncertain':
                return {**base, 'status': 'unavailable', 'available': False, 'failure_stage': 'node',
                        'reason': str(error), 'cleanup_uncertain': True}
    if selected_root is None or selected_node is None:
        stage = 'repository' if selected_root is None else 'node'
        attempts = diagnostics[stage + '_candidates']
        reason = attempts[0].get('reason', 'No candidate configured or detected') if attempts else 'No candidate configured or detected'
        if len(attempts) > 1:
            reason += f'; {len(attempts)} {stage} candidates checked; see diagnostics'
        return {**base, 'status': 'unavailable', 'available': False, 'failure_stage': stage, 'reason': reason}
    remaining = deadline - time.monotonic()
    smoke = _node_cli_probe(selected_root, selected_node, timeout=remaining) if remaining > 0 else 'cli_smoke_timeout'
    if smoke:
        return {**base, 'status': 'unavailable', 'available': False, 'failure_stage': 'cli_smoke',
                'reason': smoke, 'cleanup_uncertain': smoke == 'cli_smoke_cleanup_uncertain'}
    return {**base, 'status': 'available', 'available': True, 'version': package['version'],
            'repository': str(selected_root.resolve()), 'node': str(selected_node.resolve()), 'node_version': node_version,
            'windows_native_artifact_present': True if os.name == 'nt' else None, 'warnings': []}


def _public_diagnostic(value):
    """Retain useful runtime coordinates while excluding credential carriers."""
    return _safe(value)


def rea_health(config):
    """Select verified bundled Python when optional Node is unhealthy; no install."""
    from .rea_backends import NodeCliREABackend, PythonNativeREABackend
    mode = config_value(config, 'rea_backend', 'auto')
    base = {'interface': 'analysis_backend', 'capabilities': list(REA_SPECS),
            'backend_policy': mode, 'runtime_requirement': 'Bundled Python; Node is an optional verified backend.'}
    if not config_value(config, 'rea_enabled', True):
        return {**base, 'status': 'disabled', 'available': False, 'selected_backend': None,
                'reason': 'REA disabled by administrator configuration'}
    if mode not in {'auto', 'node_cli', 'python_native'}:
        return {**base, 'status': 'unavailable', 'available': False, 'selected_backend': None,
                'reason': 'Invalid rea_backend configuration'}
    python = PythonNativeREABackend(config).health()
    node = {'status': 'not_checked', 'available': False, 'reason': 'Python-only selection performs no Node discovery.'}
    if mode != 'python_native':
        try:
            node = NodeCliREABackend(config).health()
        except (OSError, ValueError, RuntimeError, TypeError) as error:
            node = {'status': 'unavailable', 'available': False,
                    'reason': 'Node validation failed: ' + type(error).__name__, 'errno': getattr(error, 'errno', None)}
    selected = ('node_cli' if mode != 'python_native' and node.get('available') else
                'python_native' if mode != 'node_cli' and python.get('available') else None)
    chosen = node if selected == 'node_cli' else python
    return {**base, 'status': 'available' if selected else 'unavailable', 'available': selected is not None,
            'selected_backend': selected, 'backend': selected,
            'version': chosen.get('version') if selected else None,
            'backends': {'node_cli': _public_diagnostic(node), 'python_native': python},
            **({'execution_blocked': 'Node health probe cleanup is uncertain.'} if node.get('cleanup_uncertain') else {}),
            **({'reason': 'No selected REA backend passed validation.'} if not selected else {})}


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


def _stage_input(prepared, kind, context, policy, *, require_fixed=True):
    """Copy approved bytes to owned local scratch; durable evidence stays put."""
    candidates = []
    if os.environ.get('LOCALAPPDATA'):
        candidates.append(Path(os.environ['LOCALAPPDATA']) / 'Copilot Local Agent' / 'rea-scratch')
    candidates.append(Path(tempfile.gettempdir()) / 'copilot-rea-scratch')
    if not require_fixed:
        candidates.append(Path(config_value(context.get('config', {}), 'root', Path(__file__).resolve().parents[1])) / '.runtime' / 'rea-scratch')
    errors = []
    source = Path(prepared['target'])
    limit = config_value(context.get('config', {}), 'rea_max_input_bytes', 20971520)
    for candidate in candidates:
        scratch = None
        try:
            candidate = candidate.absolute()
            reject_path_redirection(candidate)
            candidate.mkdir(parents=True, exist_ok=True)
            if require_fixed and not _fixed_local(candidate):
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
            value = value.replace(staged, original)
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


def observation_usable(result):
    """A successful bounded observation may still have explicit coverage gaps."""
    if (result.get('side_effects_uncertain') or result.get('error')
            or result.get('observation_verified') is False):
        return False
    if result.get('status') == 'completed':
        return True
    return (result.get('status') == 'partial' and result.get('observation_verified') is True
            and isinstance(result.get('findings'), dict) and bool(result['findings']))


def _observation_flags(result):
    verified = (result.get('status') in {'completed', 'partial'}
                and result.get('observation_verified') is not False
                and not result.get('side_effects_uncertain') and not result.get('error')
                and isinstance(result.get('findings'), dict) and bool(result['findings']))
    result.update(observation_verified=verified,
                  coverage_complete=verified and result.get('status') == 'completed')
    return result


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
    result = _safe(result)
    result.pop('evidence_path', None)
    result.pop('evidence_sha256', None)
    original = result.get('target', '')
    result.setdefault('target_identity_sha256', hashlib.sha256(original.encode('utf-8')).hexdigest())
    session = Path(context['session_dir']).resolve()
    reject_path_redirection(session)
    path = session / 'rea' / (result['execution_id'] + '.json')
    reject_path_redirection(path)
    limit = config_value(context.get('config', {}), 'rea_max_output_bytes', 1048576)
    complete_size = len(json.dumps(dict(result, evidence_path=str(path), evidence_sha256='0' * 64),
                                   ensure_ascii=True).encode('utf-8'))
    if complete_size > limit:
        status = result.get('status', 'failed')
        result = {key: item for key, item in result.items() if key in {
            'execution_id', 'backend', 'tool', 'target', 'target_type', 'target_identity_sha256',
            'started_at', 'finished_at', 'execution_started', 'side_effects_uncertain', 'provenance', 'retained_scratch'}}
        result.update(status='output_limit' if status in {'completed', 'partial'} else status,
                      observation_verified=False, coverage_complete=False,
                      limitations=['Complete evidence with original source coordinates exceeded the configured output budget; no complete observation is claimed.'])
    write_json(path, _safe(result))
    content = io_path(path).read_bytes()
    result['evidence_path'] = str(path)
    result['evidence_sha256'] = hashlib.sha256(content).hexdigest()
    return result


async def _execute_python(name, args, context, policy):
    from .rea_backends import PythonNativeREABackend
    context['rea_execution_started'] = False
    context['rea_cleanup_confirmed'] = True
    prepared = validate_rea(name, args, context, policy)
    prepared.update(_name=name, _arguments=args)
    config = context.get('config', {})
    timeout = config_value(config, 'rea_timeout_seconds', 45)
    output_limit = config_value(config, 'rea_max_output_bytes', 1048576)
    base = {'execution_id': uuid.uuid4().hex, 'backend': 'python_native', 'tool': name,
            'target': prepared['target'], 'target_type': prepared['target_type'],
            'started_at': now(), 'side_effects_uncertain': False, 'execution_started': False,
            'provenance': {'interface': 'bundled Python analysis', 'version': '1',
                           'input': prepared.get('input'), 'request_id': context.get('source_request_id')}}
    runtime = context.setdefault('_rea_runtime', {})
    loop = asyncio.get_running_loop()
    if runtime.get('loop') is not loop or runtime.get('semaphore') is None:
        runtime.update(loop=loop, semaphore=asyncio.Semaphore(config_value(config, 'rea_max_parallel', 3)))
    staging = None
    result = None
    async with runtime['semaphore']:
        try:
            cancelled = context.get('cancelled')
            if callable(cancelled) and cancelled():
                raise asyncio.CancelledError()
            if name == 'rea.inspect_page':
                page, _, _ = _page_scope(args, context)
                deadline = time.monotonic() + timeout
                def budget():
                    if callable(cancelled) and cancelled():
                        raise asyncio.CancelledError()
                    if time.monotonic() > deadline:
                        raise TimeoutError()
                analysis = await asyncio.wait_for(PythonNativeREABackend().inspect_page(prepared,
                    {**context, '_rea_owned_page': page, '_rea_budget': budget}), timeout)
                context['rea_execution_started'] = True
                if page.url != prepared['url']:
                    analysis.update(status='partial', observation_verified=False)
                    analysis.setdefault('limitations', []).append('Owned page changed during passive observation; evidence is a bounded snapshot.')
                _page_scope(args, context)
            else:
                staging = _stage_input(prepared, args.get('kind'), context, policy, require_fixed=False)
                operation = 'capture' if name == 'rea.analyze_capture' else 'artifact'
                command = [sys.executable, '-B', '-E', '-s', '-m', 'copilot_agent.rea_python_worker',
                           operation, args.get('format', args.get('kind')), staging['target'], str(timeout),
                           str(config_value(config, 'rea_max_input_bytes', 20971520)), str(output_limit)]
                run = await _run(command, cwd=str(Path(__file__).resolve().parents[1]), timeout=timeout,
                                 output_limit=output_limit, context=context)
                if run.get('status'):
                    analysis = {key: run[key] for key in ('status', 'side_effects_uncertain')}
                elif run['returncode'] != 0:
                    analysis = {'status': 'failed', 'error': {'code': 'analysis_worker_failed', 'message': 'The bounded Python worker rejected the analysis.'}}
                else:
                    analysis = _json_object(run['stdout'])
                after = validate_rea(name, args, context, policy)
                if after['input'] != prepared['input'] and not analysis.get('side_effects_uncertain'):
                    analysis.update(status='partial', observation_verified=False)
                    analysis.setdefault('limitations', []).append('Input changed; current-byte identity is not verified.')
            if analysis.get('status') not in {'completed', 'partial', 'failed', 'unavailable', 'cancelled', 'timeout', 'output_limit', 'uncertain'}:
                raise ValueError('Unsupported Python analysis status')
            result = {**base, **_safe(analysis), 'execution_started': context.get('rea_execution_started', False)}
            result.setdefault('confidence', 'observed')
            result.setdefault('unknowns', [])
            result.setdefault('limitations', [])
            if result.get('findings') is not None:
                result['evidence'] = {'evidence_id': 'ev_' + hashlib.sha256(json.dumps(result['findings'], sort_keys=True).encode()).hexdigest(),
                    'provider': {'id': 'python_native', 'version': '1'}, 'locations': result.get('locations', [])}
            if len(json.dumps(result, ensure_ascii=True).encode()) + 300 > output_limit:
                result = {**base, 'status': 'output_limit', 'limitations': ['The complete analysis exceeded the configured output budget.']}
        except asyncio.CancelledError:
            uncertain = context.get('rea_cleanup_confirmed') is False
            result = {**base, 'status': 'uncertain' if uncertain else 'cancelled', 'side_effects_uncertain': uncertain}
        except (asyncio.TimeoutError, TimeoutError):
            result = {**base, 'status': 'timeout'}
        except (OSError, ValueError, RuntimeError, TypeError, RecursionError) as error:
            uncertain = context.get('rea_cleanup_confirmed') is False or 'cleanup could not be confirmed' in str(error)
            result = {**base, 'status': 'uncertain' if uncertain else 'failed', 'side_effects_uncertain': uncertain,
                      'error': {'code': 'python_analysis_failed', 'message': type(error).__name__}}
        finally:
            if staging is not None:
                result = _restore_source_paths(result, staging)
                if result.get('side_effects_uncertain'):
                    result['retained_scratch'] = staging['root']
                else:
                    try:
                        _clean_scratch(staging['root'])
                        context.pop('rea_retained_scratch', None)
                    except (OSError, ValueError):
                        result.update(status='uncertain', side_effects_uncertain=True, retained_scratch=staging['root'])
                        context['rea_cleanup_confirmed'] = False
        _observation_flags(result)
        result['finished_at'] = now()
        try:
            return _save(result, context)
        except (OSError, ValueError, TypeError, RecursionError):
            context['rea_cleanup_confirmed'] = False
            return {**base, 'status': 'uncertain', 'side_effects_uncertain': True,
                    'finished_at': now(), 'provenance': {'interface': 'bundled Python analysis'},
                    'error': {'code': 'evidence_storage_failed', 'message': 'Evidence persistence could not be confirmed.'}}


async def execute_rea(name, args, context, policy):
    from .rea_backends import NodeCliREABackend
    validated = validate_rea(name, args, context, policy)
    config = context.get('config', {})
    health = rea_health(config)
    if not health['available']:
        return {'backend': None, 'execution_id': uuid.uuid4().hex, 'status': 'unavailable',
                'target': validated['target'], 'target_type': validated['target_type'],
                'started_at': now(), 'finished_at': now(), 'side_effects_uncertain': False,
                'execution_started': False, 'diagnostic': health}
    if health.get('execution_blocked'):
        context['rea_cleanup_confirmed'] = False
        return {'backend': health['selected_backend'], 'execution_id': uuid.uuid4().hex, 'status': 'uncertain',
                'target': validated['target'], 'target_type': validated['target_type'],
                'started_at': now(), 'finished_at': now(), 'side_effects_uncertain': True,
                'execution_started': False, 'diagnostic': health}
    if health['selected_backend'] == 'python_native':
        return await _execute_python(name, args, context, policy)
    began = time.monotonic()  # Readiness has a separate allowance from analysis.
    prepared = {'_name': name, '_arguments': args}
    method = name.split('.')[1]
    automatic = config_value(config, 'rea_backend', 'auto') == 'auto'
    total_timeout = config_value(config, 'rea_timeout_seconds', 45)
    def limited(seconds):
        selected = copy.copy(config)
        if isinstance(selected, dict):
            selected['rea_timeout_seconds'] = max(1, int(seconds))
        else:
            selected.rea_timeout_seconds = max(1, int(seconds))
        return {**context, 'config': selected, '_rea_runtime': context.setdefault('_rea_runtime', {})}
    node_context = limited(total_timeout // 2) if automatic else context
    result = await getattr(NodeCliREABackend(config, policy), method)(prepared, node_context)
    for key in ('rea_execution_started', 'rea_cleanup_confirmed', 'rea_retained_scratch'):
        if key in node_context:
            context[key] = node_context[key]
    if (automatic and result.get('status') in {'unavailable', 'failed', 'timeout', 'output_limit'}
            and not result.get('side_effects_uncertain')):
        remaining = total_timeout - (time.monotonic() - began)
        if remaining < 1:
            return result
        fallback_context = limited(remaining)
        fallback = await _execute_python(name, args, fallback_context, policy)
        for key in ('rea_execution_started', 'rea_cleanup_confirmed', 'rea_retained_scratch'):
            if key in fallback_context:
                context[key] = fallback_context[key]
        fallback['prior_backend_attempt'] = {'backend': 'node_cli', 'status': result['status'],
                                             'execution_id': result['execution_id']}
        # Retain fallback provenance in its hashed evidence as well as the result.
        return _save(fallback, context)
    if 'diagnostic' in result:
        result['diagnostic'] = _public_diagnostic(result['diagnostic'])
    return result


async def _execute_node(name, args, context, policy):
    context['rea_execution_started'] = False
    context['rea_cleanup_confirmed'] = True
    context.pop('rea_retained_scratch', None)
    prepared = validate_rea(name, args, context, policy)
    config = context.get('config', {})
    health = _node_health(config)
    base = {'execution_id': uuid.uuid4().hex, 'backend': 'node_cli', 'tool': name, 'target': prepared['target'],
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
                result.update(status='partial', observation_verified=False, limitations=['Owned page navigated during passive inspection; inspect its new state before reuse.'])
            if page is None:
                after = validate_rea(name, args, context, policy)
                if after['input'] != prepared['input'] and not result.get('side_effects_uncertain'):
                    result.update(status='partial', observation_verified=False, limitations=['Input changed during analysis; findings are not a verified observation of current bytes.'])
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
        _observation_flags(result)
        result['finished_at'] = now()
        try:
            return _save(result, context)
        except (OSError, ValueError, TypeError, RecursionError) as error:
            return {**base, 'status': 'uncertain', 'finished_at': now(), 'side_effects_uncertain': True,
                    'error': {'code': 'evidence_storage_failed', 'message': type(error).__name__},
                    'recovery': ['Repair session evidence storage and inspect retained state before retry.']}
