"""Bounded, interactive automatic/manual setup; never launches a resource."""
from pathlib import Path
from . import reused_browser as edge
from .storage import machine_key


async def choice(label, ask, emit):
    emit(label + ': 1. Automatic detection  2. Paste a path')
    for _ in range(5):
        answer = (await ask('Choose 1 or 2 [Enter for 1]: ')).strip()
        if answer in {'', '1', '2'}:
            return answer or '1'
        emit('Enter 1 for automatic detection or 2 to paste a path.')
    raise RuntimeError(label + ' selection stopped after five attempts.')


def pasted_path(text):
    value = text.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    if not value or not Path(value).is_absolute():
        raise ValueError('Paste the full absolute path, copied from File Explorer.')
    return Path(value).resolve()


async def choose_account(accounts, ask, emit):
    if not accounts:
        raise RuntimeError('No configured OneDrive account is available. Sign in to OneDrive and run setup again; no local-storage fallback is used.')
    emit('Choose OneDrive once for personal settings, sessions and delivered files.')
    mode = await choice('OneDrive account', ask, emit)
    if mode == '2':
        for _ in range(5):
            try:
                path = pasted_path(await ask('Paste the OneDrive account folder path: '))
                selected = next((account for account in accounts if path == account.path.resolve()), None)
                if selected is not None:
                    return selected
                emit('That path is not a registered OneDrive account root. Paste the account folder, not a workspace subfolder.')
            except (ValueError, OSError) as error:
                emit(str(error))
        raise RuntimeError('OneDrive path selection stopped after five attempts; no files were created.')
    for index, account in enumerate(accounts, 1):
        emit(f'{index}. {account.label}: {account.path}')
    for _ in range(5):
        answer = (await ask('Choose an account number' + (' [Enter for 1]' if len(accounts) == 1 else '') + ': ')).strip()
        if not answer and len(accounts) == 1:
            return accounts[0]
        if answer.isdigit() and 1 <= int(answer) <= len(accounts):
            return accounts[int(answer) - 1]
        emit('Choose a displayed account number.')
    raise RuntimeError('OneDrive selection stopped after five attempts; no files were created.')


async def choose_edge(config, settings, ask, emit, force=False):
    if config.attach_existing:
        return  # An authorized existing Edge session needs no executable launch.
    key = machine_key()
    saved = settings.get('edge_executables', {})
    if not isinstance(saved, dict):
        saved = {}
    explicit = config.edge_executable
    candidate = explicit or saved.get(key, '')
    selected = None
    if not force:
        try:
            selected = edge.find_edge_executable(candidate or None)
        except (FileNotFoundError, OSError):
            pass
    if selected is None:
        mode = await choice('Microsoft Edge', ask, emit)
        if mode == '1':
            try:
                selected = edge.find_edge_executable(candidate or None)
            except (FileNotFoundError, OSError):
                try:
                    selected = edge.find_edge_executable()
                except (FileNotFoundError, OSError):
                    emit('Edge was not found automatically. Paste its executable or installation folder.')
        if selected is None:
            for _ in range(5):
                try:
                    path = pasted_path(await ask('Paste the full msedge.exe path or its installation folder: '))
                    if path.is_dir():
                        path = path / 'msedge.exe'
                    if path.name.casefold() != 'msedge.exe' or not path.is_file():
                        raise ValueError('The path must identify an existing msedge.exe.')
                    selected = edge.find_edge_executable(str(path))
                    break
                except (ValueError, OSError) as error:
                    emit(str(error))
            if selected is None:
                raise RuntimeError('Edge path selection stopped after five attempts.')
    config.edge_executable = str(selected)
    saved[key] = str(selected)
    settings['edge_executables'] = saved
    emit('Using Microsoft Edge: ' + str(selected))
