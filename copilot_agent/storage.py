"""Per-user OneDrive storage discovery; never inspect Copilot Created folders."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import socket

from .persistence import write_json

APP_FOLDER = 'Copilot Agent'
SETTINGS_FILE = 'settings.json'
TESTING_SETTINGS_FILE = 'testing-settings.json'


@dataclass(frozen=True)
class OneDriveAccount:
    label: str
    path: Path


def _registry_paths() -> list[str]:
    if os.name != 'nt':
        return []
    import winreg
    paths = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\OneDrive\Accounts') as accounts:
            for index in range(32):
                try:
                    name = winreg.EnumKey(accounts, index)
                except OSError:
                    break
                try:
                    with winreg.OpenKey(accounts, name) as account:
                        value, _ = winreg.QueryValueEx(account, 'UserFolder')
                        if isinstance(value, str) and value:
                            paths.append(value)
                except OSError:
                    continue
    except OSError:
        pass
    return paths


def discover_onedrive_accounts(environ=None, registry_paths=None) -> list[OneDriveAccount]:
    """Read known account roots only, not account contents or Created folders."""
    environment = os.environ if environ is None else environ
    values = [environment.get(name, '') for name in ('OneDrive', 'OneDriveCommercial', 'OneDriveConsumer')]
    values.extend(_registry_paths() if registry_paths is None else registry_paths)
    accounts, seen = [], set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value).expanduser().resolve()
        key = str(path).casefold()
        if key in seen or not path.is_dir():
            continue
        seen.add(key)
        accounts.append(OneDriveAccount(path.name or 'OneDrive', path))
    return sorted(accounts, key=lambda account: (account.label.casefold(), str(account.path).casefold()))


def machine_key(hostname=None) -> str:
    name = socket.gethostname() if hostname is None else str(hostname)
    return 'vdi-' + hashlib.sha256(name.casefold().encode('utf-8')).hexdigest()[:16]


def default_storage(account: OneDriveAccount) -> Path:
    return account.path / APP_FOLDER


def profile_directory(storage_dir: Path, hostname=None) -> Path:
    return Path(storage_dir) / 'runtime' / 'edge-profiles' / machine_key(hostname)


def read_user_settings(storage_dir: Path, *, testing=False) -> dict:
    if type(testing) is not bool:
        raise ValueError('Testing preferences selector must be boolean')
    path = Path(storage_dir) / (TESTING_SETTINGS_FILE if testing else SETTINGS_FILE)
    if not path.is_file():
        # Testing may inherit live defaults in memory, never write them back.
        return read_user_settings(storage_dir) if testing else {}
    if path.stat().st_size > 65536:
        raise ValueError('Per-user settings exceed the bounded settings size')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict) or value.get('schema_version') != '1.0':
        raise ValueError('Unsupported per-user settings format')
    return value


def saved_storage_choice(accounts: list[OneDriveAccount], *, testing=False) -> Path | None:
    """Restore one recorded account; never guess between multiple choices."""
    selected = []
    for account in accounts:
        directory = default_storage(account)
        settings = read_user_settings(directory, testing=True) if testing else read_user_settings(directory)
        if settings.get('selected_account') is True:
            # Local mount/user paths may differ between VDIs. The settings live
            # in the selected account; derive its current local root safely.
            selected.append(directory)
    return selected[0] if len(selected) == 1 else None


def validate_storage_directory(path: Path, accounts: list[OneDriveAccount]) -> Path:
    target = Path(path).expanduser().resolve()
    if not any(target != account.path and target.is_relative_to(account.path) for account in accounts):
        raise ValueError('Storage must be a dedicated directory inside a discovered OneDrive account')
    return target


def save_user_settings(storage_dir: Path, settings: dict, *, testing=False) -> Path:
    if type(testing) is not bool:
        raise ValueError('Testing preferences selector must be boolean')
    directory = Path(storage_dir)
    directory.mkdir(parents=True, exist_ok=True)
    value = dict(settings, schema_version='1.0', selected_account=True, storage_dir=str(directory))
    path = directory / (TESTING_SETTINGS_FILE if testing else SETTINGS_FILE)
    write_json(path, value)
    return path


def shared_python_candidates(values, require_shared=True) -> list[str]:
    """Pure candidate normalization for the launcher's S-drive policy."""
    selected, seen = [], set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = PureWindowsPath(value.strip().strip('"'))
        if candidate.name.casefold() != 'python.exe' or not candidate.is_absolute():
            continue
        if require_shared and candidate.drive.upper() != 'S:':
            continue
        key = str(candidate).casefold()
        if key not in seen:
            seen.add(key)
            selected.append(str(candidate))
    return selected
