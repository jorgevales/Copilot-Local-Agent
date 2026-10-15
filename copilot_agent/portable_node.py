"""Bounded extraction of official portable Windows Node ZIP distributions."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import uuid
import zipfile


MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_EXTRACTED_BYTES = 400 * 1024 * 1024
MAX_ENTRIES = 12_000
_MARKER = ".copilot-node-archive.json"
_REQUIRED = ("node.exe", "node_modules/npm/bin/npm-cli.js")
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            size += len(chunk)
            if size > MAX_ARCHIVE_BYTES:
                raise ValueError("Portable Node ZIP exceeds the compressed size limit")
            result.update(chunk)
    return result.hexdigest()


def _members(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, Path]]:
    infos = archive.infolist()
    if not infos or len(infos) > MAX_ENTRIES:
        raise ValueError("Portable Node ZIP has an invalid or excessive entry count")
    if sum(item.file_size for item in infos) > MAX_EXTRACTED_BYTES:
        raise ValueError("Portable Node ZIP exceeds the extracted size limit")
    if sum(item.compress_size for item in infos) > MAX_ARCHIVE_BYTES:
        raise ValueError("Portable Node ZIP exceeds the compressed size limit")
    seen: set[str] = set()
    directories: set[str] = set()
    files: set[str] = set()
    roots: set[str] = set()
    result = []
    for info in infos:
        name = info.filename
        if "\\" in name or name.startswith("/") or ":" in name or "\x00" in name:
            raise ValueError("Portable Node ZIP contains an unsafe path")
        parts = name.rstrip("/").split("/")
        if any(not part or part in (".", "..") or part.endswith((".", " "))
               or any(c in part for c in '<>"|?*') or _RESERVED.match(part)
               or any(ord(c) < 32 for c in part) for part in parts):
            raise ValueError("Portable Node ZIP contains an unsafe Windows path")
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or info.external_attr & 0x400:
            raise ValueError("Portable Node ZIP contains a link or special file")
        if info.flag_bits & 1:
            raise ValueError("Encrypted portable Node ZIPs are unsupported")
        key = "/".join(parts).casefold()
        if key in seen:
            raise ValueError("Portable Node ZIP contains colliding paths")
        seen.add(key)
        roots.add(parts[0])
        ancestors = ["/".join(parts[:index]).casefold() for index in range(1, len(parts))]
        if any(parent in files for parent in ancestors) or (not info.is_dir() and key in directories):
            raise ValueError("Portable Node ZIP contains file/directory collisions")
        directories.update(ancestors)
        (directories if info.is_dir() else files).add(key)
        if len(parts) == 1:
            if not info.is_dir():
                raise ValueError("Portable Node ZIP must contain one distribution folder")
            continue
        result.append((info, Path(*parts[1:])))
    if len(roots) != 1:
        raise ValueError("Portable Node ZIP must contain one distribution folder")
    names = {str(relative).replace("\\", "/") for info, relative in result if not info.is_dir()}
    if not all(required in names for required in _REQUIRED):
        raise ValueError("Portable Node ZIP must include node.exe and node_modules/npm/bin/npm-cli.js")
    if _MARKER.casefold() in {name.casefold() for name in names}:
        raise ValueError("Portable Node ZIP uses a reserved installation marker")
    return result


def _reusable(root: Path, digest: str) -> bool:
    try:
        marker = root / _MARKER
        if marker.stat().st_size > 4096 or json.loads(marker.read_text(encoding="utf-8")) != {"sha256": digest}:
            return False
        return all((root / name).is_file() and (root / name).stat().st_size > 0 for name in _REQUIRED)
    except (OSError, ValueError):
        return False


def _clean_stage(stage: Path, parent: Path, name: str) -> None:
    # Only remove the exact UUID-owned staging directory created by this call.
    try:
        if stage.name != name or stage.is_symlink() or getattr(stage, "is_junction", lambda: False)():
            return
        if stage.parent.resolve() != parent.resolve() or stage.resolve().parent != parent.resolve():
            return
        shutil.rmtree(stage)
    except OSError:
        pass


def extract_portable_node(archive: Path, project: Path, *, environ=None) -> Path:
    """Extract an immutable ZIP to a verified writable cache and return node.exe.

    Normal pathlib reads preserve mapped-drive and UNC support. No npm scripts or
    executables are run here; the caller verifies the selected runtime version.
    """
    archive = Path(archive).absolute()
    project = Path(project).absolute()
    env = os.environ if environ is None else environ
    before = archive.stat()
    if before.st_size <= 0 or before.st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Portable Node ZIP exceeds the compressed size limit or is empty")
    digest = _digest(archive)
    key = digest[:24]
    candidates = []
    if env.get("LOCALAPPDATA"):
        candidates.append(Path(env["LOCALAPPDATA"]) / "Copilot Local Agent" / "runtimes" / "node")
    candidates.extend((project / ".runtime" / "node", Path(tempfile.gettempdir()) / "Copilot Local Agent" / "runtimes" / "node"))
    errors = []
    visited = set()
    try:
        source_zip = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("Portable Node ZIP cannot be read as a ZIP archive") from exc
    with source_zip:
        members = _members(source_zip)
        for candidate in candidates:
            normalized = str(candidate.absolute()).casefold()
            if normalized in visited:
                continue
            visited.add(normalized)
            stage_name = f".{key}.{uuid.uuid4().hex}.stage"
            stage = candidate / stage_name
            destination = candidate / key
            try:
                if destination.exists():
                    if _reusable(destination, digest) and _digest(archive) == digest:
                        return destination / "node.exe"
                    raise OSError("Existing runtime cache failed identity/layout validation")
                candidate.mkdir(parents=True, exist_ok=True)
                stage.mkdir()
                probe = stage / ".write-probe"
                probe.write_bytes(b"portable-node-write-readback")
                if probe.read_bytes() != b"portable-node-write-readback":
                    raise OSError("Runtime staging write/readback failed")
                probe.unlink()
                total = 0
                for info, relative in members:
                    target = stage / relative
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    count = 0
                    with source_zip.open(info) as incoming, target.open("xb") as outgoing:
                        for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                            count += len(chunk)
                            total += len(chunk)
                            if count > info.file_size or total > MAX_EXTRACTED_BYTES:
                                raise ValueError("Portable Node ZIP exceeded its declared size")
                            outgoing.write(chunk)
                    if count != info.file_size:
                        raise ValueError("Portable Node ZIP entry was truncated")
                after = archive.stat()
                if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns) or _digest(archive) != digest:
                    raise ValueError("Portable Node ZIP changed during installation; select it again")
                (stage / _MARKER).write_text(json.dumps({"sha256": digest}), encoding="utf-8")
                if not _reusable(stage, digest):
                    raise ValueError("Extracted portable Node layout is incomplete")
                try:
                    os.replace(stage, destination)
                except OSError:
                    if not _reusable(destination, digest):
                        raise
                return destination / "node.exe"
            except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
                errors.append(f"{candidate}: {type(exc).__name__}: {str(exc)[:220]}")
            finally:
                _clean_stage(stage, candidate, stage_name)
    raise RuntimeError("Unable to install portable Node in any writable runtime location: " + "; ".join(errors))
