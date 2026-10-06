"""Atomic writes with retained prior versions; no filesystem deletion."""
from __future__ import annotations
import json
import os
from pathlib import Path
import time
import uuid


def write_preserving(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        history = path.parent / '.history' / path.name
        history.mkdir(parents=True, exist_ok=True)
        backup = history / (str(time.time_ns()) + '-' + uuid.uuid4().hex + '.bak')
        with path.open('rb') as source, backup.open('xb') as target:
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.pending')
    with temporary.open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    for attempt in range(12):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 11:
                raise
            time.sleep(min(.05 * (attempt + 1), .5))


def write_json(path: Path, value: object) -> None:
    write_preserving(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')
