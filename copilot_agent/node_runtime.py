"""Operator supplied portable Node paths, including live S:/UNC aliases."""
from __future__ import annotations

import ntpath
import os
from pathlib import Path


def normalize_node_path(value):
    if not isinstance(value, (str, Path)):
        raise ValueError('Paste an absolute Node executable, extracted folder or ZIP path.')
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    text = os.path.expandvars(text)
    if text.lower().startswith('\\\\?\\unc\\'):
        text = '\\\\' + text[8:]
    elif text.startswith('\\\\?\\'):
        text = text[4:]
    path = Path(text).expanduser()
    if not text or any(ord(char) < 32 for char in text) or not path.is_absolute():
        raise ValueError('Paste a full absolute Node path, not a command or drive-relative path.')
    return path


def _aliases(path):
    paths = [path]
    if os.name == 'nt' and ntpath.splitdrive(str(path))[0].casefold() == 's:':
        try:
            final = str(normalize_node_path(os.path.realpath(path, strict=True)))
            if final.startswith('\\\\'):
                paths.insert(0, Path(final))
        except (OSError, ValueError):
            pass
        if len(paths) == 1:
            try:
                from .policy import mapped_s_drive_root
                share = mapped_s_drive_root()
                relative = ntpath.relpath(str(path), 'S:\\')
                paths.insert(0, share / relative)
            except (OSError, ValueError):
                pass
    return list(dict.fromkeys(paths))


def node_source_candidates(value):
    """Keep file/folder/ZIP identities; never guess an unrelated share."""
    return _aliases(normalize_node_path(value))


def node_path_candidates(value):
    candidates = []
    for path in node_source_candidates(value):
        if path.is_dir():
            candidates.append(path / 'node.exe')
        elif path.suffix.lower() == '.zip' or path.suffix.lower() == '.exe' or path.name.lower() == 'node':
            candidates.append(path)
        else:
            candidates.append(path / 'node.exe')
    return list(dict.fromkeys(candidates))
