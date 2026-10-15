"""Portable delivery of an explicitly trusted, complete upstream REA runtime.

No install scripts run here. A portable archive is executable software: its digest
must come from the operator/build that supplied it, not from the archive itself.
The usual pinned npm installation remains available when no archive is supplied.
"""
from __future__ import annotations

import ctypes
import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import stat
import tempfile
import uuid
import zipfile

VERSION = '6.5.0'
NATIVE_SHA256 = '665c57ab90aef0712a6aafc423c7992a88bf608bea63b370cb30c695900f9aed'
MAX_ARCHIVE = 100 * 1024 * 1024
MAX_EXPANDED = 300 * 1024 * 1024
MAX_MEMBERS = 15000
MANIFEST = 'rea-runtime-manifest.json'
REQUIRED = ('scripts/rea.mjs', 'dist/cli-runtime/cli.js',
            'dist/cli-runtime/cliOutput.js', 'dist/cli-runtime/cliResultOutput.js')


def _shared(path):
    value = str(path)
    if value.startswith(('\\\\', '//')):
        return True
    if os.name == 'nt' and Path(path).anchor:
        try:
            return ctypes.windll.kernel32.GetDriveTypeW(str(Path(path).anchor)) == 4
        except (AttributeError, OSError):
            pass
    return False


def staging_candidates(project, env):
    """Prefer actual local storage for npm's many small files; retain all fallbacks."""
    raw = []
    for name in ('LOCALAPPDATA', 'TEMP', 'TMP'):
        if env.get(name):
            raw.append(Path(env[name]) / 'Copilot Local Agent' / 'rea-setup')
    raw.append(Path(tempfile.gettempdir()) / 'Copilot Local Agent' / 'rea-setup')
    raw.append(Path(project) / '.setup-cache' / 'rea-staging')
    unique = []
    for path in raw:
        if path.is_absolute() and str(path).casefold() not in {str(p).casefold() for p in unique}:
            unique.append(path)
    ordered = sorted(unique, key=_shared)
    if env.get('COPILOT_SETUP_TEMP'):
        explicit = Path(env['COPILOT_SETUP_TEMP'])
        if explicit.is_absolute():
            ordered.insert(0, explicit / 'Copilot Local Agent' / 'rea-setup')
    return ordered


def create_staging(project, env, *, remaining=None, excluded=()):
    """Verify write/read/delete, without trusting redirected-drive free-space reports."""
    failures = []
    for parent in staging_candidates(project, env):
        if str(parent).casefold() in {str(path).casefold() for path in excluded}:
            continue
        if remaining:
            remaining()
        owned = parent / ('rea-install-' + uuid.uuid4().hex)
        try:
            owned.mkdir(parents=True, exist_ok=False)
            probe = owned / '.write-probe'
            probe.write_bytes(b'copilot-rea-setup')
            if probe.read_bytes() != b'copilot-rea-setup':
                raise OSError('setup scratch readback mismatch')
            probe.unlink()
            return owned, failures
        except OSError as error:
            failures.append(f'{parent}: {error}')
            try:
                (owned / '.write-probe').unlink(missing_ok=True)
                owned.rmdir()
            except OSError:
                pass
    raise OSError('No writable REA setup scratch location: ' + '; '.join(failures))


def _regular(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('Portable REA delivery cannot contain links or reparse points: ' + str(path))
    return stat.S_ISREG(info.st_mode)


def _sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_delivery(root):
    """Check upstream package and every declared direct production dependency."""
    root = Path(root)
    package = json.loads((root / 'package.json').read_text(encoding='utf-8'))
    if not isinstance(package, dict) or package.get('name') != 'rea-agents' or package.get('version') != VERSION:
        raise ValueError('Portable runtime must be upstream rea-agents ' + VERSION)
    if not all((root / name).is_file() for name in REQUIRED):
        raise ValueError('Portable runtime is missing compiled upstream CLI files')
    dependencies = package.get('dependencies', {})
    if not isinstance(dependencies, dict) or not 1 <= len(dependencies) <= 200:
        raise ValueError('Portable runtime production dependency declarations are invalid')
    for name, version in dependencies.items():
        if (not isinstance(name, str) or not re.fullmatch(r'(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+', name)
                or name in ('.', '..') or not isinstance(version, str)
                or not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', version)):
            raise ValueError('Portable runtime production dependency declaration is unsafe or unpinned')
        dependency = root / 'node_modules' / name / 'package.json'
        actual = json.loads(dependency.read_text(encoding='utf-8'))
        if not isinstance(actual, dict) or actual.get('version') != version:
            raise ValueError('Portable runtime has a missing or wrong production dependency: ' + name)
    if 'zod' not in package.get('dependencies', {}):
        raise ValueError('Portable upstream runtime must declare zod')
    native = root / 'native' / 'windows' / 'build'
    metadata = json.loads((native / 'manifest.json').read_text(encoding='utf-8'))
    if (not isinstance(metadata, dict) or metadata.get('packageVersion') != VERSION or metadata.get('architecture') != 'x64'
            or metadata.get('platform') != 'win32' or metadata.get('artifactSha256') != NATIVE_SHA256
            or _sha(native / 'rea-windows-x64.node') != NATIVE_SHA256):
        raise ValueError('Portable upstream Windows native artifact identity mismatch')
    return package


def export_runtime(root, archive):
    """Build an operator-transferable archive; return the digest to transmit separately."""
    root, archive = Path(root).resolve(), Path(archive).resolve()
    if archive.is_relative_to(root):
        raise ValueError('Portable runtime archive output must be outside its source tree')
    package = validate_delivery(root)
    published = package.get('files')
    if not isinstance(published, list) or not published or len(published) > 500:
        raise ValueError('Portable upstream runtime must declare bounded published files')
    allowed = {'package.json', 'package-lock.json', 'node_modules'}
    for entry in published:
        if not isinstance(entry, str) or any(character in entry for character in '*?[]!'):
            raise ValueError('Portable upstream published file declaration must be a safe literal path')
        allowed.add(_relative(entry).as_posix())
    files, total = {}, 0
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts
        if not any(relative == entry or relative.startswith(entry + '/') for entry in allowed):
            continue
        if any(part.lower().startswith('.env') or part.lower() in ('.npmrc', 'config.local.json')
               or Path(part).suffix.lower() in ('.pem', '.key', '.pfx') for part in parts):
            continue
        if any(part in ('.bin', '.git') for part in parts):
            continue
        if _regular(path):
            total += path.stat().st_size
            if total > MAX_EXPANDED or len(files) >= MAX_MEMBERS:
                raise ValueError('Portable runtime exceeds delivery bounds')
            files[relative] = {'size': path.stat().st_size, 'sha256': _sha(path)}
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open('xb') as output, zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(MANIFEST, json.dumps({'format': 1, 'name': 'rea-agents', 'version': VERSION,
            'source': 'https://registry.npmjs.org/rea-agents/-/rea-agents-6.5.0.tgz',
            'files': files}, sort_keys=True))
        for name in files:
            bundle.write(root / name, 'runtime/' + name)
    if archive.stat().st_size > MAX_ARCHIVE:
        raise ValueError('Portable runtime archive exceeds compressed size limit')
    return _sha(archive)


def _relative(name):
    path = PurePosixPath(name)
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
    if (not isinstance(name, str) or not path.parts or path.is_absolute() or '\\' in name or ':' in name
            or any(part in ('', '.', '..') for part in name.split('/'))
            or any(part in ('', '.', '..') or part.endswith((' ', '.'))
                   or part.split('.')[0].upper() in reserved for part in path.parts)):
        raise ValueError('Unsafe portable REA archive member')
    return path


def extract_runtime_archive(archive, destination, *, expected_sha256, remaining=None):
    """Extract a digest-approved bundle into a new/empty owned directory, no execution."""
    archive, destination = Path(archive), Path(destination)
    if (not isinstance(expected_sha256, str) or len(expected_sha256) != 64
            or any(c not in '0123456789abcdefABCDEF' for c in expected_sha256)):
        raise ValueError('Portable REA requires a trusted SHA256 supplied separately from its archive')
    if archive.stat().st_size > MAX_ARCHIVE or _sha(archive) != expected_sha256.lower():
        raise ValueError('Portable REA archive digest mismatch or size limit exceeded')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Portable runtime destination must be empty')
    if destination.exists():
        _regular(destination)  # Reject an empty destination that redirects elsewhere.
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        if len(infos) > MAX_MEMBERS + 1 or sum(i.file_size for i in infos) > MAX_EXPANDED + 4 * 1024 * 1024:
            raise ValueError('Portable REA archive expanded bounds exceeded')
        seen = set()
        for info in infos:
            _relative(info.filename)
            if info.filename.casefold() in seen or info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('Duplicate or nonregular portable REA archive member')
            seen.add(info.filename.casefold())
        if bundle.getinfo(MANIFEST).file_size > 4 * 1024 * 1024:
            raise ValueError('Portable REA manifest exceeds bounds')
        manifest = json.loads(bundle.read(MANIFEST))
        if not isinstance(manifest, dict):
            raise ValueError('Portable REA manifest must be an object')
        files = manifest.get('files', {})
        if (manifest.get('format') != 1 or manifest.get('name') != 'rea-agents'
                or manifest.get('version') != VERSION or not isinstance(files, dict)
                or set(i.filename for i in infos) != {MANIFEST, *('runtime/' + n for n in files)}):
            raise ValueError('Portable REA manifest identity or file membership mismatch')
        destination.mkdir(parents=True, exist_ok=True)
        for name, identity in files.items():
            if remaining:
                remaining()
            relative = _relative(name)
            info = bundle.getinfo('runtime/' + name)
            if not isinstance(identity, dict) or info.file_size != identity.get('size'):
                raise ValueError('Portable REA member size mismatch')
            path = destination.joinpath(*relative.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as incoming, path.open('xb') as outgoing:
                digest = hashlib.sha256()
                while chunk := incoming.read(1024 * 1024):
                    outgoing.write(chunk)
                    digest.update(chunk)
            if digest.hexdigest() != identity.get('sha256'):
                raise ValueError('Portable REA member integrity mismatch')
    validate_delivery(destination)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description='Export a complete real upstream REA runtime for trusted offline transfer.')
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    arguments = parser.parse_args(argv)
    digest = export_runtime(arguments.source, arguments.output)
    print('Archive: ' + str(arguments.output.resolve()))
    print('SHA256: ' + digest)
    print('Transfer this digest through a trusted channel separately from the archive.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
