"""Provision the pinned optional REA runtime without administrator rights.

Only installation scratch and runtime files are written; discovery data stays on S:.
No REA target operation or package lifecycle script is executed during installation.
"""
from __future__ import annotations

import argparse
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
            result = subprocess.run([str(path), '--version'], capture_output=True, text=True, timeout=5, env=env)
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
        except RuntimeError:
            if not ask_on_missing:
                raise
    ask = input_fn or input
    while True:
        try:
            value = ask('Paste Node node.exe, extracted portable folder or ZIP path (S: or UNC; Enter to use detected Node / cancel): ').strip()
        except EOFError as error:
            raise RuntimeError('No Node path input is available. Rerun Setup interactively or supply --node-path.') from error
        if not value:
            try:
                return find_node(env), True
            except RuntimeError as error:
                raise RuntimeError('Node path was not supplied; setup needs a compatible Node executable or portable ZIP. Rerun Setup to paste it.') from error
        try:
            return _operator_node(value, project, env), True
        except (OSError, ValueError, RuntimeError) as error:
            print('Node path was not accepted: ' + str(error) + ' Paste another path, or press Enter to stop.', flush=True)


def find_npm(node, env):
    candidates = [node.parent / 'node_modules' / 'npm' / 'bin' / 'npm-cli.js']
    executable = shutil.which('npm', path=env.get('PATH'))
    if executable:
        candidates.append(Path(executable).parent / 'node_modules' / 'npm' / 'bin' / 'npm-cli.js')
    if env.get('APPDATA'):
        candidates.append(Path(env['APPDATA']) / 'npm' / 'node_modules' / 'npm' / 'bin' / 'npm-cli.js')
    for path in candidates:
        if path.is_file():
            return path
    raise RuntimeError('npm CLI not found beside Node or in the user npm installation. Repair the Node LTS installation, '
                       'or reuse a complete offline REA installation via rea_repository in config.local.json.')


def validate_runtime(root, node, env, *, smoke=True):
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
    if smoke:
        result = subprocess.run([str(node), str(root / 'scripts' / 'rea.mjs'), '--help'],
                                cwd=root, env=env, capture_output=True, text=True, timeout=8)
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
        with urllib.request.urlopen(ARCHIVE_URL, timeout=25) as response:
            if not response.geturl().startswith('https://registry.npmjs.org/'):
                raise ValueError('unexpected REA archive redirect')
            payload = response.read(MAX_ARCHIVE + 1)
    if len(payload) > MAX_ARCHIVE or base64.b64encode(hashlib.sha512(payload).digest()).decode() != INTEGRITY:
        raise ValueError('REA archive integrity mismatch; expected the pinned npm rea-agents 6.5.0 distribution')
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


def provision(project, *, environ=None, deadline_seconds=90, offline=False, config_path=None,
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
    node, save_node = _select_node(project, env, node_path=node_path,
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
    # Interactive operator time and ZIP preparation do not consume the REA
    # dependency installation budget.
    deadline = time.monotonic() + deadline_seconds
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
            print(f'REA {VERSION}: ready at {root}', flush=True)
            return {'available': True, 'repository': str(root), 'reused': True}
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
            continue
    npm = find_npm(node, env)
    if offline and not env.get('COPILOT_REA_ARCHIVE'):
        raise RuntimeError('Offline repair needs COPILOT_REA_ARCHIVE pointing to the pinned 6.5.0 tarball and a populated npm cache.')
    payload = archive_bytes(env)
    failures = []
    for target in candidates:
        staging = target.parent / ('.rea-install-' + uuid.uuid4().hex)
        try:
            if time.monotonic() >= deadline:
                break
            staging.mkdir(parents=True)
            archive = staging / 'rea.tgz'
            archive.write_bytes(payload)
            root = staging / 'package'
            root.mkdir()
            extract_archive(archive, root)
            (root / '.copilot-rea-runtime.json').write_text(json.dumps({'version': VERSION}), encoding='utf-8')
            child_env = dict(env, TEMP=str(staging), TMP=str(staging), TMPDIR=str(staging),
                             npm_config_cache=str(staging / 'npm-cache'), PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD='1')
            command = [str(node), str(npm), 'install', '--omit=dev', '--omit=optional', '--ignore-scripts',
                       '--no-audit', '--no-fund', '--fetch-retries=0', '--fetch-timeout=20000',
                       '--registry=https://registry.npmjs.org']
            # Prefer the existing npm cache when it is useful in restricted VDIs;
            # a cache miss then gets one bounded online attempt.
            cache_env = dict(child_env)
            cache_env.pop('npm_config_cache', None)
            result = subprocess.run(command + ['--offline'], cwd=root, env=cache_env,
                                    capture_output=True, text=True, timeout=min(30, max(1, deadline-time.monotonic())))
            if result.returncode and not offline:
                result = subprocess.run(command, cwd=root, env=child_env, capture_output=True, text=True,
                                        timeout=min(60, max(1, deadline-time.monotonic())))
            if result.returncode:
                raise RuntimeError('npm could not obtain production dependencies (cache and registry attempted)')
            validate_runtime(root, node, child_env)
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
            root.rename(target)
            print(f'REA {VERSION}: installed and CLI verified at {target}', flush=True)
            return {'available': True, 'repository': str(target), 'reused': False}
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            failures.append(f'{target}: {type(error).__name__}: {error if isinstance(error, (RuntimeError, ValueError)) else "write, download or execution failure"}')
            print('REA runtime candidate failed; trying another verified installation location.', flush=True)
        finally:
            # Only our unique directory is removed; targets and prior installs
            # are outside it and are retained on every failure.
            if staging.name.startswith('.rea-install-') and staging.parent == target.parent:
                shutil.rmtree(staging, ignore_errors=True)
    raise RuntimeError('REA setup failed. ' + '; '.join(failures) +
                       '. Rerun bootstrap/setup_rea.py after repairing Node/npm or registry access; '
                       'use COPILOT_REA_ARCHIVE for the pinned offline tarball and a populated npm cache, '
                       'or set rea_repository to a complete existing installation. Python tools remain usable.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--config', type=Path, default=None)
    parser.add_argument('--timeout-seconds', type=int, default=90, choices=range(10, 181), metavar='10..180')
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
