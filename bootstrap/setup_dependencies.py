"""Repeat-safe package setup. Scratch files only; agent knowledge stays on S:."""
from __future__ import annotations

from collections import deque
from importlib import metadata
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
import uuid


def folder(value):
    path = Path(str(value).strip().strip('"').strip("'")).expanduser()
    if not path.is_absolute() or path == Path(path.anchor):
        raise ValueError('Choose a full folder address, not just a drive letter.')
    return path


def probe(path):
    """Exercise the actual nested pip-unpack wheel-file pattern, not just mkdir."""
    path.mkdir(parents=True, exist_ok=True)
    child = path / ('pip-unpack-probe-' + uuid.uuid4().hex)
    child.mkdir()
    wheel = child / 'jsonschema-4.26.0-py3-none-any.whl'
    payload = b'copilot-setup-folder-check' * 2048
    try:
        with wheel.open('xb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if wheel.read_bytes() != payload:
            raise OSError('Setup folder could not read back its test file.')
    finally:
        # Only our uniquely owned probe is removed; existing files are retained.
        wheel.unlink(missing_ok=True)
        child.rmdir()


def shared_root(env):
    """Resolve only the actual S: mapping, with bounded provider fallbacks."""
    if os.name != 'nt':
        return None
    try:
        root = os.path.realpath('S:\\', strict=True)
        if root.startswith('\\\\?\\UNC\\'):
            root = '\\\\' + root[8:]
        if root.startswith('\\\\') and not root.startswith(('\\\\?\\', '\\\\.\\')):
            return Path(root)
    except (OSError, ValueError):
        pass
    # Constant commands, never interpolate environment values or path strings.
    script = r"""
$ErrorActionPreference = 'Stop'
$root = $null
try { $root = (Get-PSDrive -Name S -PSProvider FileSystem -ErrorAction Stop).DisplayRoot } catch { }
if (-not $root) { try { $root = (Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='S:'" -ErrorAction Stop).ProviderName } catch { } }
if (-not $root) { try { $root = @(Get-SmbMapping -LocalPath 'S:' -ErrorAction Stop)[0].RemotePath } catch { } }
if ($root) { ConvertTo-Json -Compress -InputObject ([string]$root) }
"""
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                env=env, capture_output=True, text=True, timeout=5)
        root = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else None
        if isinstance(root, str) and root.startswith('\\\\') and not root.startswith(('\\\\?\\', '\\\\.\\')):
            # Require a share identity, never accept a provider's drive-only value.
            if len([part for part in root.split('\\') if part]) >= 2:
                return Path(root)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def candidates(project, env):
    values = [env.get('COPILOT_SETUP_TEMP')]
    for key in ('TEMP', 'TMP', 'TMPDIR'):
        try:
            candidate = folder(env.get(key) or '')
            values.append(candidate)  # The nested write/read probe can create it.
        except (OSError, ValueError):
            pass
    values.extend([project / '.setup-cache' / 'temp', project / '.setup-cache' / 'temp-retry'])
    try:
        resolved = project.resolve()
        values.append(resolved / '.setup-cache' / 'temp')
        # S: and UNC are equivalent identities but distinct I/O spellings. Try
        # both when a current mapping proves the alias, never guess a share.
        if os.name == 'nt':
            share = Path(os.path.realpath('S:\\', strict=True))
            if str(share).startswith('\\\\'):
                values.append(Path('S:/') / resolved.relative_to(share) / '.setup-cache' / 'temp')
    except (OSError, ValueError):
        pass
    key = hashlib.sha256(str(project).casefold().encode()).hexdigest()[:12]
    if env.get('LOCALAPPDATA'):
        values.append(Path(env['LOCALAPPDATA']) / 'CopilotLocalAgent' / 'setup' / key / 'temp')
    if env.get('SystemRoot'):
        values.append(Path(env['SystemRoot']) / 'Temp' / 'CopilotLocalAgent' / key)
    seen = set()

    def unique(items):
        for value in items:
            if not value:
                continue
            try:
                path = folder(value)
            except ValueError:
                continue
            identity = os.path.normcase(str(path))
            if identity not in seen:
                seen.add(identity)
                yield path

    yield from unique(values)
    # Keep the established candidates first. Short scratch paths avoid long
    # redirected project paths. Provider lookup happens only if those fail.
    values = []
    root = shared_root(env)
    if root is not None:
        project_text = ntpath.normpath(str(project))
        root_text = ntpath.normpath(str(root))
        if ntpath.splitdrive(project_text)[0].casefold() == 's:':
            values.append(root / project_text[3:] / '.setup-cache' / 'temp')
        elif project_text.casefold().startswith(root_text.casefold().rstrip('\\') + '\\'):
            relative = project_text[len(root_text.rstrip('\\')) + 1:]
            values.append(Path('S:/') / relative / '.setup-cache' / 'temp')
        values.extend([Path('S:/') / '.copilot-setup' / key / 'temp',
                       root / '.copilot-setup' / key / 'temp'])
    elif os.name == 'nt' and ntpath.splitdrive(str(project))[0].casefold() == 's:':
        values.append(Path('S:/') / '.copilot-setup' / key / 'temp')
    if env.get('LOCALAPPDATA'):
        values.append(Path(env['LOCALAPPDATA']) / 'Temp' / 'CopilotLocalAgent' / key)
    yield from unique(values)


def pins_from(path):
    pins = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9.+_-]*)', line)
        if not match:
            raise ValueError('Setup needs the unchanged pinned requirements.lock.txt file.')
        name, version = match.groups()
        name = re.sub(r'[-_.]+', '-', name).lower()
        if name in pins:
            raise ValueError('Duplicate package in requirements.lock.txt.')
        pins[name] = version
    if not pins:
        raise ValueError('The package list is empty.')
    return pins


def installed_versions():
    import sysconfig
    paths = {sysconfig.get_path('purelib'), sysconfig.get_path('platlib')}
    return {re.sub(r'[-_.]+', '-', dist.metadata['Name']).lower(): dist.version
            for dist in metadata.distributions(path=paths) if dist.metadata.get('Name')}


def run_python(args, env):
    flags = ['-B'] + (['-I'] if sys.flags.isolated else ['-s'] if sys.flags.no_user_site else [])
    command = [sys.executable, *flags, *args]
    if args == ['-m', 'pip', 'cache', 'dir']:
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
        return SimpleNamespace(returncode=result.returncode, output=result.stdout.strip())
    tail = deque(maxlen=60)
    with subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, errors='replace') as process:
        for line in process.stdout:
            print(line, end='', flush=True)
            tail.append(line)
        code = process.wait()
    return SimpleNamespace(returncode=code, output=''.join(tail))


def path_failure(output):
    return any(word in output.lower() for word in (
        'no such file or directory', 'cannot find the path', 'file not found',
        'winerror 2', 'winerror 3', 'error 2]', 'error 3]', 'error 112]',
        'winerror 206', 'file name too long', 'filename or extension is too long',
        'permission denied', 'access is denied', 'no space left', 'not enough space',
        'winerror 112', 'winerror 39', 'disk quota', 'quota exceeded',
        'network path was not found', 'network name is no longer available',
        'winerror 53', 'winerror 64',
        'invalid wheel', 'not a zip file', 'badzipfile'))


def failure_category(error):
    """Classify without echoing raw OS/pip messages that may contain secrets."""
    text = str(error).lower()
    code = getattr(error, 'winerror', None)
    if getattr(error, 'errno', None) in {28, 122} or code in {39, 112} or any(
            word in text for word in ('no space', 'not enough space', 'quota', 'error 112')):
        return 'space/quota reported (write probe or installer; not a free-space verdict)'
    if isinstance(error, PermissionError) or code == 5 or any(word in text for word in ('permission', 'access is denied')):
        return 'access denied'
    if code in {53, 64, 67} or 'network' in text:
        return 'network path unavailable'
    if any(word in text for word in ('cache', 'invalid wheel', 'not a zip file', 'badzipfile')):
        return 'cached archive unavailable or invalid'
    if code == 206 or 'too long' in text:
        return 'path too long'
    if isinstance(error, FileNotFoundError) or any(word in text for word in ('no such file', 'cannot find', 'file not found')):
        return 'path unavailable'
    return 'filesystem operation failed'


def diagnostic_path(path, project, env):
    value = str(path)
    for base, label in ((project, '<PROJECT>'), (env.get('LOCALAPPDATA'), '<LOCALAPPDATA>'),
                        (env.get('USERPROFILE'), '<USERPROFILE>'), (env.get('SystemRoot'), '<SystemRoot>')):
        if base and value.casefold().startswith(str(base).rstrip('/\\').casefold() + os.sep):
            value = label + value[len(str(base).rstrip('/\\')):]
            break
    value = re.sub(r'(?i)(https?://)[^/\s@]+@', r'\1<REDACTED>@', value)
    value = value.split('?', 1)[0].split('#', 1)[0]
    return ''.join(char if char.isprintable() else '?' for char in value)


def health_check(pins):
    if 'crawl4ai' in pins:
        from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy
        if not LXMLWebScrapingStrategy().scrap('https://example.com', '<html><body>setup check</body></html>').success:
            raise RuntimeError('The installed exploration tools could not start.')
    if 'playwright' in pins:
        import playwright.sync_api


def install(requirements, prefix, *, versions=installed_versions, run=run_python,
            health=None, environ=None, probe_folder=probe, ask=input):
    pins = pins_from(requirements)
    project = requirements.parent
    env = dict(os.environ if environ is None else environ)
    health = health or (lambda: health_check(pins))

    def missing():
        current = versions()
        return [name+'=='+version for name,version in pins.items() if current.get(name)!=version]

    def verify():
        if missing():
            raise RuntimeError('Some needed packages are still missing. Existing files were retained.')
        if run(['-m','pip','check'], env).returncode:
            raise RuntimeError('The installed packages do not work together. Existing files were retained.')
        health()

    if not missing():
        print('All required packages are already installed. Checking them without downloading anything.', flush=True)
        verify()
        return

    cache = None
    try:
        result = run(['-m','pip','cache','dir'], env)
    except (OSError, subprocess.TimeoutExpired):
        result = SimpleNamespace(returncode=1, output='')
    for value in [env.get('PIP_CACHE_DIR'), result.output if result.returncode==0 else None,
                  project/'.setup-cache'/'pip-cache']:
        if value:
            try:
                cache = folder(value)
                probe_folder(cache)
                break
            except (OSError, ValueError):
                cache = None
    locations = iter(candidates(project, env))
    failed_installs = 0
    failures = []
    while True:
        path = next(locations, None)
        if path is None:
            details = '; '.join(f'{diagnostic_path(location, project, env)} [{stage}: {category}]'
                                for location, stage, category in failures)
            raise RuntimeError('Setup exhausted its automatic unpacking folders. ' + details +
                               '. Check share connectivity, write permissions or quota; '
                               'set COPILOT_SETUP_TEMP to a writable absolute scratch folder and rerun Setup. '
                               'Existing files were retained; durable knowledge remains on S:.')
        try:
            probe_folder(path)
        except OSError as error:
            failures.append((path, 'write/read probe', failure_category(error)))
            print('That unpacking folder is unavailable. Trying another folder.', flush=True)
            continue
        pending = missing()
        if not pending:
            verify()
            return
        child_env = dict(env, TEMP=str(path), TMP=str(path), TMPDIR=str(path))
        args = ['-m','pip','install','--disable-pip-version-check','--no-user',
                '--prefix',str(prefix),'--no-deps','--prefer-binary','--no-compile']
        args += ['--cache-dir',str(cache)] if cache else ['--no-cache-dir']
        print(f'Keeping {len(pins)-len(pending)} installed packages; setting up {len(pending)} missing or changed packages.', flush=True)
        result = run(args + pending, child_env)
        if result.returncode==0:
            verify()
            return
        if not path_failure(result.output):
            raise RuntimeError('Setup could not obtain packages from the configured package source. '
                               'See the message above; existing files were retained.')
        print('A download could not be unpacked. Retrying the remaining packages in another folder.', flush=True)
        failures.append((path, 'installer', failure_category(result.output)))
        failed_installs += 1
        # Retain verified cached downloads for the first ordinary temp failure.
        # A cache error or repeated failure gets a fresh uncached read instead.
        if failed_installs >= 2 or any(word in result.output.lower() for word in ('cache', 'invalid wheel', 'not a zip file', 'badzipfile')):
            cache = None


def main():
    if len(sys.argv)!=4 or sys.argv[1]!='install':
        raise ValueError('Use setup_dependencies.py install REQUIREMENTS ENVIRONMENT.')
    prefix = folder(sys.argv[3])
    if sys.prefix==sys.base_prefix or not os.path.samefile(prefix, sys.prefix):
        raise ValueError('Setup must use the verified project Python environment.')
    install(Path(sys.argv[2]), prefix)
    project = Path(sys.argv[2]).resolve().parent
    if (project / 'bootstrap' / 'setup_rea.py').is_file():
        from setup_rea import provision
        try:
            provision(project, prompt_for_node=sys.stdin.isatty())
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            print('REA OPTIONAL RUNTIME NOT READY: ' + str(error), file=sys.stderr, flush=True)
            print('Python setup completed. Run .venv\\Scripts\\python.exe bootstrap\\setup_rea.py to repair REA.',
                  file=sys.stderr, flush=True)


if __name__=='__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        print('Setup: '+str(error), file=sys.stderr)
        sys.exit(1)
