"""Provision the pinned optional REA runtime without administrator rights.

Only installation scratch and runtime files are written; discovery data stays on S:.
No REA target operation or package lifecycle script is executed during installation.
"""
from __future__ import annotations

import argparse
from contextvars import ContextVar
from types import SimpleNamespace
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import uuid

# This helper also runs as a standalone script before the application starts.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copilot_agent.node_runtime import node_path_candidates, node_source_candidates
from copilot_agent.persistence import io_path, write_json

VERSION = '6.5.0'
ARCHIVE_URL = 'https://registry.npmjs.org/rea-agents/-/rea-agents-6.5.0.tgz'
INTEGRITY = 'C6BG7LyrAdR74mSjertM6PrxJkcNZ2bfQNOJornPo9erDEp2tyPRVYPnV5Yodr+1RqewCQla68WulXlVnveD+A=='
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
REQUIRED = ('scripts/rea.mjs', 'dist/cli-runtime/cli.js',
            'dist/cli-runtime/cliOutput.js', 'dist/cli-runtime/cliResultOutput.js')


# Each setup invocation retains bounded diagnostics with exact local paths.
# Credentials are removed; arbitrary environment values and payloads are not logged.
_DIAGNOSTICS = ContextVar('rea_setup_diagnostics', default=None)
_BUDGET = ContextVar('rea_setup_budget', default=None)


class SetupBudgetExpired(RuntimeError):
    pass


class SetupBudget:
    def __init__(self, seconds):
        self.seconds = float(seconds)
        self.deadline = time.monotonic() + self.seconds

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise SetupBudgetExpired(f'Node setup exhausted its shared {self.seconds:g}-second budget; no further install attempt started.')
        return remaining


def _remaining(default=180):
    diagnostics = _DIAGNOSTICS.get()
    if diagnostics and any(item.get('termination') == 'subtree_cleanup_unconfirmed' for item in diagnostics.records):
        raise RuntimeError('Node setup stopped: owned process subtree cleanup is unconfirmed; no additional probe or installation retry is safe.')
    budget = _BUDGET.get()
    return min(float(default), budget.remaining()) if budget else float(default)

_STAGES = frozenset({'node_probe', 'npm_probe', 'archive_acquire', 'archive_verify',
                     'archive_extract', 'dependency_install', 'native_verify', 'cli_smoke', 'publish'})


class SetupDiagnostics:
    def __init__(self, project, env):
        self.project, self.env, self.records = Path(project), env, []

    def safe(self, value):
        value = str(value or '')[:8192]
        value = re.sub(r'''(?im)(authorization|proxy-authorization|cookie|set-cookie)["']?\s*[:=]\s*[^\r\n]+''', r'\1=<redacted>', value)
        value = re.sub(r'''(?ix)([\"']?(?:[\w-]*token|password|passwd|secret|api[_-]?key)[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)''', r'\1<redacted>', value)
        value = re.sub(r'(?i)(https?://)[^/@\s]+:[^/@\s]+@', r'\1<redacted>@', value)
        return value[:2048]

    def record(self, stage, *, command=None, duration=0, timeout=None, returncode=None,
               stdout='', stderr='', termination='not_started', error=None):
        assert stage in _STAGES
        item = {'stage': stage, 'command': command or stage, 'duration_seconds': round(duration, 3),
                'timeout_seconds': timeout, 'returncode': returncode, 'stdout': self.safe(stdout),
                'stderr': self.safe(stderr), 'termination': termination}
        if error is not None:
            item.update(error_type=type(error).__name__, error=self.safe(error),
                        errno=getattr(error, 'errno', None), winerror=getattr(error, 'winerror', None))
        self.records.append(item)
        return item

    def call(self, stage, function, *args, **kwargs):
        started, before = time.monotonic(), len(self.records)
        try:
            result = function(*args, **kwargs)
        except Exception as error:
            if len(self.records) > before and self.records[-1]['stage'] == stage:
                self.records[-1].update(error_type=type(error).__name__, error=self.safe(error),
                                        errno=getattr(error, 'errno', None), winerror=getattr(error, 'winerror', None))
            elif len(self.records) == before or self.records[-1].get('termination') == 'completed':
                self.record(stage, duration=time.monotonic()-started, error=error, termination='failed')
            raise
        if len(self.records) == before or self.records[-1]['stage'] != stage:
            self.record(stage, duration=time.monotonic()-started, termination='completed')
        return result


def _stage(stage, function, *args, **kwargs):
    _remaining()
    diagnostics = _DIAGNOSTICS.get()
    return diagnostics.call(stage, function, *args, **kwargs) if diagnostics else function(*args, **kwargs)


def _terminate_owned(process):
    """Bounded subtree cleanup for the npm/CLI process this invocation owns."""
    if os.name == 'nt':
        killer = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'taskkill.exe'
        try:
            result = subprocess.run([str(killer), '/PID', str(process.pid), '/T', '/F'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            if result.returncode:
                process.kill()
                process.wait(timeout=3)
                return 'subtree_cleanup_unconfirmed'
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=3)
            return 'subtree_cleanup_unconfirmed'
    else:
        # Children inherit the private process group created below.
        import signal
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=3)
        return 'terminated_owned_subtree'
    except subprocess.TimeoutExpired:
        return 'subtree_cleanup_unconfirmed'


def _run_command(command, *, cwd=None, env=None, timeout=8, stage='cli_smoke', identity='rea --help'):
    """Spool output to verified setup scratch, retaining at most 2 KiB per stream."""
    diagnostics = _DIAGNOSTICS.get()
    timeout = _remaining(timeout)
    started = time.monotonic()
    process, termination, error = None, 'not_started', None
    scratch = (env or {}).get('TEMP') if (env or {}).get('TEMP') else None
    with tempfile.TemporaryFile(dir=scratch) as stdout, tempfile.TemporaryFile(dir=scratch) as stderr:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                                       **({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if os.name == 'nt'
                                          else {'start_new_session': True}))
            process.wait(timeout=timeout)
            termination = 'completed'
        except subprocess.TimeoutExpired as exc:
            error = exc
            termination = _terminate_owned(process)
        except OSError as exc:
            error = exc
        outputs = []
        for stream in (stdout, stderr):
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell()-2048))
            outputs.append(stream.read(2048).decode('utf-8', errors='replace'))
        result = SimpleNamespace(returncode=process.returncode if process else None, stdout=outputs[0], stderr=outputs[1])
        if diagnostics:
            diagnostics.record(stage, command=identity, duration=time.monotonic()-started, timeout=timeout,
                               returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
                               termination=termination, error=error)
            diagnostics.records[-1]['executable'] = diagnostics.safe(command[0])
        if error:
            raise error
        return result


def runtime_candidates(project, env):
    values = [Path(project) / '.runtime' / 'rea']
    if env.get('LOCALAPPDATA'):
        values.append(Path(env['LOCALAPPDATA']) / 'Copilot Local Agent' / 'runtimes' / 'rea' / VERSION)
    values.append(Path(tempfile.gettempdir()) / 'Copilot Local Agent' / 'runtimes' / 'rea' / VERSION)
    return list(dict.fromkeys(path.absolute() for path in values))


def find_node(env):
    values = [env.get('COPILOT_REA_NODE'), shutil.which('node', path=env.get('PATH'))]
    for key in ('ProgramFiles', 'ProgramW6432', 'LOCALAPPDATA'):
        if env.get(key):
            base = Path(env[key])
            values.extend([base / 'nodejs' / 'node.exe', base / 'Programs' / 'nodejs' / 'node.exe'])
    if env.get('COPILOT_REA_NODE'):
        values = [env['COPILOT_REA_NODE']]
    paths = []
    for value in values:
        if not value:
            continue
        try:
            paths.extend(node_path_candidates(value))
        except ValueError:
            continue
    for path in dict.fromkeys(paths):
        if not path.is_absolute() or not path.is_file() or path.suffix.lower() in {'.cmd', '.bat', '.ps1'}:
            continue
        try:
            result = _run_command([str(path), '--version'], timeout=_remaining(), env=env,
                                  stage='node_probe', identity='node --version')
            version = tuple(int(item) for item in re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)\s*', result.stdout).groups())
            if result.returncode == 0 and (version[0] >= 26 or version[0] == 24 and version >= (24, 11, 0)
                                           or version[0] == 22 and version >= (22, 19, 0)):
                return path
        except (OSError, AttributeError, ValueError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError('Compatible native Node not found. Install Node 24.11+ LTS (or 22.19+/26+) and reopen Setup; '
                       'or paste the absolute node.exe, extracted portable folder or portable ZIP path when asked.')


def _operator_node(value, project, env):
    sources = node_source_candidates(value)
    if sources[0].suffix.lower() == '.zip':
        from copilot_agent.portable_node import extract_portable_node
        failures = []
        for source in sources:
            try:
                selected = extract_portable_node(source, project, environ=env)
                return find_node(dict(env, COPILOT_REA_NODE=str(selected)))
            except (OSError, ValueError, RuntimeError) as error:
                failures.append(str(error))
        raise RuntimeError('Portable Node ZIP could not be prepared: ' + '; '.join(failures))
    return find_node(dict(env, COPILOT_REA_NODE=str(value)))


def _select_node(project, env, *, node_path=None, prompt_for_node=False,
                 ask_on_missing=False, input_fn=None):
    if node_path is not None:
        return _operator_node(node_path, project, env), True
    if not prompt_for_node:
        try:
            return find_node(env), bool(env.get('COPILOT_REA_NODE'))
        except SetupBudgetExpired:
            raise
        except RuntimeError:
            if not ask_on_missing:
                raise
            _remaining()
    ask = input_fn or input
    while True:
        try:
            prompt_started = time.monotonic()
            value = ask('Paste Node node.exe, extracted portable folder or ZIP path (S: or UNC; Enter to use detected Node / cancel): ').strip()
            budget = _BUDGET.get()
            if budget:
                budget.deadline += time.monotonic() - prompt_started
        except EOFError as error:
            raise RuntimeError('No Node path input is available. Rerun Setup interactively or supply --node-path.') from error
        if not value:
            try:
                return find_node(env), True
            except RuntimeError as error:
                raise RuntimeError('Node path was not supplied; setup needs a compatible Node executable or portable ZIP. Rerun Setup to paste it.') from error
        try:
            return _operator_node(value, project, env), True
        except SetupBudgetExpired:
            raise
        except (OSError, ValueError, RuntimeError) as error:
            diagnostics = _DIAGNOSTICS.get()
            detail = diagnostics.safe(error) if diagnostics else type(error).__name__
            print('Node path was not accepted: ' + detail + ' Paste another path, or press Enter to stop.', flush=True)


def find_npm(node, env):
    candidates = [node.parent / 'node_modules' / 'npm' / 'bin' / 'npm-cli.js']
    executable = shutil.which('npm', path=env.get('PATH'))
    if executable:
        candidates.append(Path(executable).parent / 'node_modules' / 'npm' / 'bin' / 'npm-cli.js')
    if env.get('APPDATA'):
        candidates.append(Path(env['APPDATA']) / 'npm' / 'node_modules' / 'npm' / 'bin' / 'npm-cli.js')
    for path in candidates:
        if path.is_file():
            result = _run_command([str(node), str(path), '--version'], env=env, timeout=_remaining(),
                                  stage='npm_probe', identity='node npm --version')
            if result.returncode == 0 and re.fullmatch(r'\d+\.\d+\.\d+\s*', result.stdout):
                return path
    raise RuntimeError('npm CLI not found beside Node or in the user npm installation. Repair the Node LTS installation, '
                       'or reuse a complete offline REA installation via rea_repository in config.local.json.')


def _validate_runtime_files(root):
    package = json.loads((root / 'package.json').read_text(encoding='utf-8'))
    if (not isinstance(package, dict) or package.get('name') != 'rea-agents'
            or not re.fullmatch(r'6\.5\.\d+', str(package.get('version', '')))):
        raise ValueError('wrong REA package identity/version')
    if not all((root / name).is_file() for name in REQUIRED):
        raise ValueError('compiled CLI runtime missing')
    if not (root / 'node_modules' / 'zod' / 'package.json').is_file():
        raise ValueError('production Node dependencies missing')
    if os.name == 'nt':
        native = root / 'native' / 'windows' / 'build'
        metadata = json.loads((native / 'manifest.json').read_text(encoding='utf-8'))
        addon = native / 'rea-windows-x64.node'
        if (metadata.get('packageVersion') != package['version'] or metadata.get('platform') != 'win32'
                or metadata.get('architecture') != 'x64' or addon.stat().st_size > 16777216
                or hashlib.sha256(addon.read_bytes()).hexdigest() != metadata.get('artifactSha256')):
            raise ValueError('Windows native artifact identity mismatch')
    return True


def validate_runtime(root, node, env, *, smoke=True):
    _stage('native_verify', _validate_runtime_files, root)
    if smoke:
        result = _run_command([str(node), str(root / 'scripts' / 'rea.mjs'), '--help'],
                              cwd=root, env=env, timeout=_remaining(), stage='cli_smoke', identity='node rea --help')
        if result.returncode:
            raise ValueError('REA CLI could not load its production dependencies; rerun runtime repair')
    return True


def archive_bytes(env):
    """An offline archive is accepted only when it matches the pinned registry digest."""
    supplied = env.get('COPILOT_REA_ARCHIVE')
    if supplied:
        path = Path(supplied).expanduser()
        if not path.is_absolute() or path.stat().st_size > MAX_ARCHIVE:
            raise ValueError('COPILOT_REA_ARCHIVE must be a bounded absolute archive path')
        payload = path.read_bytes()
    else:
        with urllib.request.urlopen(ARCHIVE_URL, timeout=_remaining()) as response:
            if not response.geturl().startswith('https://registry.npmjs.org/'):
                raise ValueError('unexpected REA archive redirect')
            payload = response.read(MAX_ARCHIVE + 1)
    def verify():
        if len(payload) > MAX_ARCHIVE or base64.b64encode(hashlib.sha512(payload).digest()).decode() != INTEGRITY:
            raise ValueError('REA archive integrity mismatch; expected the pinned npm rea-agents 6.5.0 distribution')
    _stage('archive_verify', verify)
    return payload


def extract_archive(archive, destination):
    """No links, devices, traversal, duplicate members or unbounded expansion."""
    total, seen = 0, set()
    with tarfile.open(archive, 'r:gz') as source:
        members = source.getmembers()
        if len(members) > 4000:
            raise ValueError('REA archive member limit exceeded')
        for member in members:
            name = PurePosixPath(member.name)
            if (not name.parts or name.parts[0] != 'package' or name.is_absolute()
                    or '..' in name.parts or '\\' in member.name or ':' in member.name
                    or member.name in seen or not (member.isfile() or member.isdir())):
                raise ValueError('unsafe REA archive member')
            seen.add(member.name)
            total += member.size
            if total > MAX_EXPANDED:
                raise ValueError('REA archive expanded size limit exceeded')
            relative = Path(*name.parts[1:])
            output = destination / relative
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as incoming, output.open('xb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing)


def _install_node(project, *, environ=None, deadline_seconds=180, offline=False, config_path=None,
              node_path=None, prompt_for_node=False, ask_on_missing=False, input_fn=None):
    project = Path(project).resolve()
    env = dict(os.environ if environ is None else environ)
    settings_file = Path(config_path) if config_path else project / 'config.local.json'
    settings = json.loads(settings_file.read_text(encoding='utf-8-sig')) if settings_file.is_file() else {}
    if not isinstance(settings, dict):
        raise ValueError('REA configuration must be a JSON object: ' + str(settings_file))
    if settings.get('rea_enabled') is False:
        print('REA runtime disabled in local configuration; setup skipped.', flush=True)
        return {'available': False, 'disabled': True}
    if settings.get('rea_node_executable'):
        env['COPILOT_REA_NODE'] = settings['rea_node_executable']
    node, save_node = _stage('node_probe', _select_node, project, env, node_path=node_path,
        prompt_for_node=prompt_for_node, ask_on_missing=ask_on_missing, input_fn=input_fn)
    env['COPILOT_REA_NODE'] = str(node)
    if save_node:
        current = json.loads(io_path(settings_file).read_text(encoding='utf-8-sig')) if settings_file.exists() else {}
        if current != settings:
            raise RuntimeError('Local configuration changed while selecting Node; rerun setup to preserve those changes.')
        settings['rea_node_executable'] = str(node)
        write_json(settings_file, settings)
        if json.loads(io_path(settings_file).read_text(encoding='utf-8-sig')) != settings:
            raise RuntimeError('Saved Node configuration did not read back correctly; setup stopped.')
        print('Node path validated and saved. Continuing the remaining setup automatically.', flush=True)
    # One budget covers selection, portable preparation, every probe and all
    # installation candidates. Only time spent waiting for operator input is paused.
    deadline = _BUDGET.get().deadline
    candidates = runtime_candidates(project, env)
    if settings.get('rea_repository'):
        selected = Path(settings['rea_repository']).expanduser()
        if not selected.is_absolute() or selected == Path(selected.anchor):
            raise ValueError('rea_repository must be an absolute runtime folder, not a drive root')
        candidates = [selected]
    # A complete offline/developer installation is useful without copying its
    # potentially large dependency tree or modifying it.
    existing = candidates + ([] if settings.get('rea_repository') else [project.parent / 'Copilot Local Agent Research' / 'rea'])
    for root in existing:
        try:
            if time.monotonic() >= deadline:
                break
            validate_runtime(root, node, env)
            print(f'REA {VERSION}: verified existing Node runtime.', flush=True)
            return {'available': True, 'repository': str(root), 'reused': True}
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
            continue
    npm = _stage('npm_probe', find_npm, node, env)
    if offline and not env.get('COPILOT_REA_ARCHIVE'):
        raise RuntimeError('Offline repair needs COPILOT_REA_ARCHIVE pointing to the pinned 6.5.0 tarball and a populated npm cache.')
    payload = _stage('archive_acquire', archive_bytes, env)
    failures = []
    for target in candidates:
        staging = target.parent / ('.rea-install-' + uuid.uuid4().hex)
        stage = 'archive_extract'
        try:
            if time.monotonic() >= deadline:
                break
            staging.mkdir(parents=True)
            archive = staging / 'rea.tgz'
            archive.write_bytes(payload)
            root = staging / 'package'
            root.mkdir()
            _stage('archive_extract', extract_archive, archive, root)
            (root / '.copilot-rea-runtime.json').write_text(json.dumps({'version': VERSION}), encoding='utf-8')
            child_env = dict(env, TEMP=str(staging), TMP=str(staging), TMPDIR=str(staging),
                             npm_config_cache=str(staging / 'npm-cache'), PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD='1')
            child_env.pop('NPM_CONFIG_CACHE', None)
            _verify_scratch(Path(child_env['npm_config_cache']))
            command = [str(node), str(npm), 'install', '--omit=dev', '--omit=optional', '--ignore-scripts',
                       '--no-audit', '--no-fund', '--fetch-retries=0', '--fetch-timeout=20000',
                       '--registry=https://registry.npmjs.org']
            # Prefer the existing npm cache when it is useful in restricted VDIs;
            # a cache miss then gets one bounded online attempt.
            cache_env = dict(child_env)
            # An explicitly supplied cache is kept only after a write/read probe.
            # Never let npm silently select the full C: user cache.
            cache = env.get('npm_config_cache') or env.get('NPM_CONFIG_CACHE')
            if cache:
                try:
                    _verify_scratch(Path(cache))
                    cache_env['npm_config_cache'] = str(cache)
                except OSError as error:
                    diagnostics = _DIAGNOSTICS.get()
                    if diagnostics:
                        diagnostics.record('dependency_install', command='npm cache write/read probe', error=error, termination='failed')
            stage = 'dependency_install'
            result = _run_command(command + ['--offline'], cwd=root, env=cache_env,
                                  timeout=_remaining(),
                                  stage='dependency_install', identity='node npm install --offline --ignore-scripts')
            if result.returncode and not offline:
                result = _run_command(command, cwd=root, env=child_env,
                                      timeout=_remaining(),
                                      stage='dependency_install', identity='node npm install --ignore-scripts')
            if result.returncode:
                raise RuntimeError('npm could not obtain production dependencies (cache and registry attempted)')
            stage = 'native_verify'
            validate_runtime(root, node, child_env)
            stage = 'publish'
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                try:
                    prior_package = json.loads((target / 'package.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    prior_package = {}
                if prior_package.get('name') != 'rea-agents' and not (target / '.copilot-rea-runtime.json').is_file():
                    raise ValueError('installation target contains unrelated files; choose a dedicated REA folder')
                # Preserve a previous partial runtime for diagnosis; never merge
                # new files into an old or potentially inconsistent installation.
                target.rename(target.with_name('rea-incomplete-' + uuid.uuid4().hex))
            _stage('publish', root.rename, target)
            print(f'REA {VERSION}: installed and CLI verified.', flush=True)
            return {'available': True, 'repository': str(target), 'reused': False}
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            diagnostics = _DIAGNOSTICS.get()
            if diagnostics:
                if (not diagnostics.records or diagnostics.records[-1].get('stage') != stage
                        and diagnostics.records[-1].get('stage') != 'cli_smoke'):
                    diagnostics.record(stage, error=error, termination='failed')
                else:
                    diagnostics.records[-1].update(error_type=type(error).__name__, error=diagnostics.safe(error),
                                                   errno=getattr(error, 'errno', None), winerror=getattr(error, 'winerror', None))
                failures.append(json.dumps(diagnostics.records[-1], sort_keys=True))
            else:
                failures.append(type(error).__name__)
            if diagnostics and diagnostics.records[-1].get('termination') == 'subtree_cleanup_unconfirmed':
                raise RuntimeError('Node setup stopped: owned process subtree cleanup is unconfirmed; no installation retry is safe.') from error
            print('REA runtime candidate failed; trying another verified installation location.', flush=True)
        finally:
            # Only our unique directory is removed; targets and prior installs
            # are outside it and are retained on every failure.
            diagnostics = _DIAGNOSTICS.get()
            uncertain = bool(diagnostics and diagnostics.records and
                             diagnostics.records[-1].get('termination') == 'subtree_cleanup_unconfirmed')
            if uncertain:
                diagnostics.records[-1]['staging_retained'] = True
            elif staging.name.startswith('.rea-install-') and staging.parent == target.parent:
                shutil.rmtree(staging, ignore_errors=True)
    raise RuntimeError('REA setup failed. ' + '; '.join(failures) +
                       '. Rerun bootstrap/setup_rea.py after repairing Node/npm or registry access; '
                       'use COPILOT_REA_ARCHIVE for the pinned offline tarball and a populated npm cache, '
                       'or set rea_repository to a complete existing installation. The Python REA backend remains available when its local health check succeeds.')


def _provision_node(project, *, environ=None, deadline_seconds=180, offline=False, config_path=None,
                    node_path=None, prompt_for_node=False, ask_on_missing=False, input_fn=None):
    token = _BUDGET.set(SetupBudget(deadline_seconds))
    try:
        return _install_node(project, environ=environ, deadline_seconds=deadline_seconds, offline=offline,
                             config_path=config_path, node_path=node_path, prompt_for_node=prompt_for_node,
                             ask_on_missing=ask_on_missing, input_fn=input_fn)
    finally:
        _BUDGET.reset(token)


def _verify_scratch(path):
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ('.rea-cache-probe-' + uuid.uuid4().hex)
    try:
        probe.write_bytes(b'rea-cache-probe')
        if probe.read_bytes() != b'rea-cache-probe':
            raise OSError('npm cache write/read verification failed')
    finally:
        probe.unlink(missing_ok=True)


def provision(project, *, environ=None, deadline_seconds=180, offline=False, config_path=None,
              node_path=None, prompt_for_node=False, ask_on_missing=False, input_fn=None):
    """Setup may repair Node; Python-only mode never discovers or installs it."""
    project = Path(project).resolve()
    env = dict(os.environ if environ is None else environ)
    diagnostics = SetupDiagnostics(project, env)
    token = _DIAGNOSTICS.set(diagnostics)
    settings = {}
    settings_file = Path(config_path) if config_path else project / 'config.local.json'
    try:
        loaded = json.loads(settings_file.read_text(encoding='utf-8-sig')) if settings_file.is_file() else {}
        if not isinstance(loaded, dict):
            raise ValueError('REA configuration must be a JSON object')
        settings = loaded
        if settings.get('rea_backend', 'auto') == 'python_native' and settings.get('rea_enabled', True):
            from copilot_agent.rea import rea_health
            health = rea_health(dict(settings, root=project))
            if not health.get('available'):
                raise RuntimeError('Python REA backend validation failed; run Setup.cmd to repair project dependencies.')
            print('REA setup: Python backend checked; no Node/npm discovery or installation.', flush=True)
            return dict(health, diagnostics=diagnostics.records)
        result = _provision_node(project, environ=env, deadline_seconds=deadline_seconds, offline=offline,
                                 config_path=config_path, node_path=node_path, prompt_for_node=prompt_for_node,
                                 ask_on_missing=ask_on_missing, input_fn=input_fn)
        return dict(result, backend='node_cli', diagnostics=diagnostics.records)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        if settings.get('rea_backend', 'auto') == 'auto' and settings.get('rea_enabled', True):
            from copilot_agent.rea import rea_health
            health = rea_health(dict(settings, root=project, rea_backend='python_native'))
            if health.get('available'):
                print('Node setup did not finish; verified Python REA backend is ready. ' +
                      json.dumps(diagnostics.records[-1:] or [{'stage': 'node_probe', 'error': diagnostics.safe(error)}]), flush=True)
                return dict(health, node_repair_failed=True,
                            node_repair_cleanup_uncertain=any(item.get('termination') == 'subtree_cleanup_unconfirmed'
                                                             for item in diagnostics.records),
                            diagnostics=diagnostics.records)
        safe = diagnostics.safe(error)
        if diagnostics.records:
            safe += ' Diagnostic: ' + json.dumps(diagnostics.records[-1], sort_keys=True)
        raise RuntimeError(safe) from None
    finally:
        try:
            write_json(project / '.setup-cache' / 'rea-setup-diagnostics.json',
                       {'schema_version': 1, 'stages': diagnostics.records[-100:]})
        except (OSError, ValueError):
            pass
        _DIAGNOSTICS.reset(token)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--config', type=Path, default=None)
    parser.add_argument('--timeout-seconds', type=int, default=180, choices=range(10, 181), metavar='10..180')
    parser.add_argument('--offline', action='store_true', help='Use only COPILOT_REA_ARCHIVE and the existing npm cache.')
    parser.add_argument('--node-path', help='Absolute node.exe, extracted portable folder or Windows Node ZIP; accepts S:/UNC paths.')
    parser.add_argument('--prompt-node-path', action='store_true', help='Paste a Node path before continuing setup automatically.')
    parser.add_argument('--non-interactive', action='store_true', help='Never prompt for a missing Node path.')
    args = parser.parse_args()
    try:
        provision(args.project, deadline_seconds=args.timeout_seconds, offline=args.offline, config_path=args.config,
                  node_path=args.node_path, prompt_for_node=args.prompt_node_path and not args.non_interactive,
                  ask_on_missing=not args.non_interactive and sys.stdin.isatty())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print('REA setup: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
