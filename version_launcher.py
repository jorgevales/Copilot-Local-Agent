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
DROP_FOLDER = Path('Copilot testing environment') / 'Updated files'


def prepare_drop_folder(live):
    inbox = live / DROP_FOLDER
    inbox.mkdir(parents=True, exist_ok=True)
    for relative, _ in source_files(live):
        (inbox / relative.parent).mkdir(parents=True, exist_ok=True)
    return inbox


def source_files(root):
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = [name for name in folders if name not in EXCLUDED
                      and not name.startswith('.venv-')
                      and not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if name in PRIVATE or name == '.gitkeep' or name.startswith('.env') or path.is_symlink():
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
    inbox = prepare_drop_folder(live)
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
            previous = versions[int(answer) - 1].resolve()
    print(f'Copilot replacement folder: {inbox}')
    if not any(source_files(inbox)):
        if previous:
            return previous
        raise ValueError(f'Drop Copilot files into {inbox}, matching their project-relative paths, then start again.')
    changes = replacement_map(live, inbox)
    if previous and all((previous / relative).is_file() and digest(previous / relative) == digest(path)
                        for relative, path in changes.items()):
        return previous
    print('Copilot replacements are untrusted. Review them before running; a testing copy uses your normal account permissions.')
    return create_version(live, inbox, previous)


def main():
    live = Path(__file__).resolve().parent
    try:
        arguments = sys.argv[1:]
        use_ui = '--ui' in arguments
        choices = [value for value in arguments if value != '--ui']
        if len(choices) > 1:
            raise ValueError('Provide one live/testing selection.')
        source = choose_source(live, choice=choices[0] if choices else None)
        print(f'Running project version: {source}')
        if use_ui and not (source / 'agent_ui' / 'runtime.py').is_file():
            raise ValueError('This saved testing version predates the UI launcher. Recreate it by dropping the Copilot files again, or choose the live project.')
        flags = ['-B']
        if sys.flags.ignore_environment:
            flags.append('-E')
        if sys.flags.no_user_site:
            flags.append('-s')
        environment = os.environ.copy()
        environment['COPILOT_AGENT_EXECUTION_MODE'] = 'testing' if source.is_relative_to(live / 'Copilot testing environment' / 'versions') else 'live'
        command = ([sys.executable, *flags, '-m', 'agent_ui.runtime'] if use_ui else
                   [sys.executable, *flags, str(source / 'app.py')])
        return subprocess.call(command, cwd=source, env=environment)
    except (ValueError, OSError, SyntaxError) as exc:
        print(f'Version selection stopped: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
