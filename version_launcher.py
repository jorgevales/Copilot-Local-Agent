"""Local complete-copy testing versions. Requires neither Git nor extra packages."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone

EXCLUDED = {'.git', '.venv', '__pycache__', 'runtime', 'workspace', '.history',
            'Copilot proposals', 'Copilot testing environment', 'node_modules'}
PRIVATE = {'config.local.json', 'python-launcher.txt', '.venv-setup.lock'}


def source_files(root):
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = [name for name in folders if name not in EXCLUDED
                      and not name.startswith('.venv-')
                      and not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if name in PRIVATE or name.startswith('.env') or path.is_symlink():
                continue
            if path.suffix.lower() in {'.pyc', '.pem', '.pfx', '.key', '.log'}:
                continue
            yield path.relative_to(root), path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replacement_map(live, proposals):
    """Preserve relative paths; flat files must have one unambiguous destination."""
    originals = dict(source_files(live))
    changes = {}
    for relative, path in source_files(proposals):
        if relative not in originals and len(relative.parts) == 1:
            matches = [item for item in originals if item.name == relative.name]
            if len(matches) != 1:
                raise ValueError(f'{relative}: keep the original project-relative folder path; destination is ambiguous or new.')
            relative = matches[0]
        if relative in changes:
            raise ValueError(f'Duplicate replacement destination: {relative}')
        if relative.suffix.lower() == '.py':
            compile(path.read_bytes(), str(relative), 'exec')
        changes[relative] = path
    if not changes:
        raise ValueError('The selected folder contains no usable replacement files.')
    return changes


def create_version(live, proposals, previous=None):
    live, proposals = live.resolve(), proposals.resolve()
    if not proposals.is_dir() or proposals == live or live.is_relative_to(proposals):
        raise ValueError('Select a separate folder of Copilot replacement files.')
    changes = replacement_map(live, proposals)
    store = live / 'Copilot testing environment'
    if store.is_symlink():
        raise ValueError('Testing storage must be a regular directory.')
    identifier = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8]
    version = store / 'versions' / identifier
    source = version / 'source'
    source.mkdir(parents=True)
    base = previous or live
    base_hashes = {}
    for relative, path in source_files(base):
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        base_hashes[relative.as_posix()] = digest(path)
    records = []
    for relative, path in changes.items():
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        records.append({'path': relative.as_posix(), 'sha256': digest(destination),
                        'previous_sha256': base_hashes.get(relative.as_posix()),
                        'live_sha256': digest(live / relative) if (live / relative).is_file() else None})
    manifest = {'version': identifier, 'created_utc': datetime.now(timezone.utc).isoformat(),
                'base': str(base), 'live_root': str(live), 'proposal_folder': str(proposals),
                'base_hashes': base_hashes, 'replacements': records,
                'verification': 'Python syntax checked. Functional behavior requires testing.'}
    (version / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return source


def choose_source(live, ask=input, choice=None):
    if choice is None:
        print('Which version do you want to run?\n1. Live repository\n2. Copilot testing environment')
        choice = ask('Choose 1 or 2: ').strip()
    if choice == '1':
        return live
    if choice != '2':
        raise ValueError('Enter 1 or 2; no version was started.')
    versions = sorted((live / 'Copilot testing environment' / 'versions').glob('*/source'), reverse=True)
    previous = None
    if versions:
        print('Available testing versions (latest first):')
        for number, path in enumerate(versions, 1):
            print(f'{number}. {path.parent.name}')
        answer = ask('Choose a version number, or L to start from live [1]: ').strip() or '1'
        if answer.upper() != 'L':
            if not answer.isdigit() or not 1 <= int(answer) <= len(versions):
                raise ValueError('Invalid testing version number.')
            previous = versions[int(answer) - 1]
    value = ask('Folder of new Copilot files (Enter runs the selected testing version): ').strip().strip('"')
    if not value:
        if previous:
            return previous
        default = live / 'Copilot proposals'
        if not default.is_dir():
            raise ValueError('No testing version exists. Select a folder containing Copilot replacements.')
        proposals = default
    else:
        proposals = Path(value)
        if not proposals.is_absolute():
            proposals = live / proposals
    print('Copilot replacements are untrusted. Review them before running; a testing copy uses your normal account permissions.')
    return create_version(live, proposals, previous)


def main():
    live = Path(__file__).resolve().parent
    try:
        source = choose_source(live, choice=sys.argv[1] if len(sys.argv) > 1 else None)
        print(f'Running project version: {source}')
        flags = ['-B']
        if sys.flags.ignore_environment:
            flags.append('-E')
        if sys.flags.no_user_site:
            flags.append('-s')
        return subprocess.call([sys.executable, *flags, str(source / 'app.py')], cwd=source)
    except (ValueError, OSError, SyntaxError) as exc:
        print(f'Version selection stopped: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
