"""Native attachment selection; call select_files using asyncio.to_thread.

The picker queues paths only. Existing approval, file-policy and upload checks
remain responsible for deciding whether each selected attachment can be sent.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .attachments import OFFICE_EXTENSIONS, SUPPORTED_EXTENSIONS, TEXT_EXTENSIONS as ATTACHMENT_TEXT_EXTENSIONS


DOCUMENT_EXTENSIONS = tuple(sorted(OFFICE_EXTENSIONS | {'.pdf'}))
CODE_EXTENSIONS = tuple(sorted(ATTACHMENT_TEXT_EXTENSIONS & {
    '.py', '.js', '.jsx', '.ts', '.tsx', '.html', '.htm', '.css', '.sql', '.sh', '.ps1', '.bat', '.cmd'}))
TEXT_EXTENSIONS = tuple(sorted(ATTACHMENT_TEXT_EXTENSIONS - set(CODE_EXTENSIONS)))
IMAGE_EXTENSIONS = tuple(sorted(SUPPORTED_EXTENSIONS - ATTACHMENT_TEXT_EXTENSIONS - set(DOCUMENT_EXTENSIONS)))


def _patterns(extensions):
    return ' '.join('*' + extension for extension in extensions)


FILE_TYPES = (
    ('Documents, code, text and images', _patterns(sorted(SUPPORTED_EXTENSIONS))),
    ('Documents', _patterns(DOCUMENT_EXTENSIONS)),
    ('Code', _patterns(CODE_EXTENSIONS)),
    ('Text', _patterns(TEXT_EXTENSIONS)),
    ('Images', _patterns(IMAGE_EXTENSIONS)),
)


def _native_picker(**options):
    if os.name != 'nt':
        raise RuntimeError('The native attachment picker requires an interactive Windows desktop.')
    root = None
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.update_idletasks()
        return filedialog.askopenfilenames(parent=root, **options)
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError('The native attachment picker is unavailable. Use an interactive Windows desktop with Tkinter installed.') from exc
    except Exception as exc:
        raise RuntimeError('The native attachment picker could not open on this Windows desktop. No files were selected.') from exc
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def select_files(initial_directory: str | Path | None = None, *, picker_backend: Callable | None = None) -> list[Path]:
    """Select several attachment paths, preserving order and removing aliases.

    Cancellation returns []. The optional backend receives the exact Tk dialog
    options, allowing deterministic tests without opening native windows. ZIPs
    are absent from every filter and rejected if entered manually.
    """
    options = {'title':'Choose files to attach to Copilot', 'filetypes':FILE_TYPES, 'multiple':True}
    if initial_directory is not None:
        options['initialdir'] = str(Path(initial_directory).expanduser().absolute())
    backend = picker_backend or _native_picker
    try:
        selected = backend(**options)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError('The attachment file picker failed. No files were selected.') from exc
    if not selected:
        return []
    if isinstance(selected, (str, Path)):
        selected = [selected]
    results, seen = [], set()
    try:
        for item in selected:
            path = Path(item).expanduser().absolute()
            if '\x00' in str(path):
                raise ValueError('Invalid file path')
            if path.suffix.casefold() == '.zip':
                raise RuntimeError('ZIP archives cannot be attached. Choose individual documents, code or text files.')
            key = os.path.normcase(os.path.normpath(str(path)))
            if key not in seen:
                results.append(path)
                seen.add(key)
    except (TypeError, ValueError) as exc:
        raise RuntimeError('The attachment picker returned an invalid file selection.') from exc
    return results
