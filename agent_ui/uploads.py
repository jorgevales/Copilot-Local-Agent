"""Session-scoped ingestion for files uploaded through the local workspace UI.

Browser filenames and MIME types are untrusted metadata. The store accepts only
bounded bytes, assigns opaque server-side identities, and never exposes its
private staging paths in public records.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import os
import re
import shutil
import stat
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path, PureWindowsPath

from copilot_agent.attachments import (
    MAX_FILE_BYTES,
    NATIVE_UPLOAD_EXTENSIONS,
    OFFICE_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    TEXT_EXTENSIONS,
    upload_name,
)
from copilot_agent.logging_utils import SENSITIVE

MAX_MESSAGE_ATTACHMENTS = 20
MAX_SESSION_ATTACHMENTS = 200
MAX_SESSION_ATTACHMENT_BYTES = 1024 * 1024 * 1024
MAX_ENCODED_FILE_BYTES = ((MAX_FILE_BYTES + 2) // 3) * 4
MAX_UPLOAD_REQUEST_BYTES = MAX_ENCODED_FILE_BYTES + 32 * 1024
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_:-]{1,128}$")
_WINDOWS_RESERVED = re.compile(r"(?i)^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$")


class UploadError(ValueError):
    """A user-visible but path-free upload validation error."""


def _safe_name(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 255:
        raise UploadError("Choose a file with a valid filename")
    # Browsers should send a basename. Reject all path-like forms rather than
    # silently taking a basename from a potentially hostile Windows path.
    if value in {".", ".."} or any(ch in value for ch in ("/", "\\", ":", "\x00")):
        raise UploadError("The uploaded filename must not contain a path")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise UploadError("The uploaded filename contains unsupported characters")
    if value.endswith((".", " ")) or _WINDOWS_RESERVED.fullmatch(value):
        raise UploadError("Choose a filename supported by Windows")
    if PureWindowsPath(value).name != value:
        raise UploadError("The uploaded filename must not contain a path")
    extension = Path(value).suffix.casefold()
    if extension == ".zip":
        raise UploadError("ZIP files cannot be attached; select supported files inside the archive")
    if extension not in SUPPORTED_EXTENSIONS:
        raise UploadError("Unsupported attachment type")
    return value


def _validate_content(name: str, content: bytes) -> dict:
    extension = Path(name).suffix.casefold()
    if not content or len(content) > MAX_FILE_BYTES:
        raise UploadError("Attachment must be between 1 byte and 20 MiB")
    if extension in TEXT_EXTENSIONS:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeError as exc:
            raise UploadError("Text and code attachments must be readable UTF-8") from exc
        quoted_credentials = re.search(
            r"(?i)[\"'](?:password|passwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret)[\"']\s*[:=]\s*[\"']?[^\s,;}]+",
            text,
        )
        if "\x00" in text:
            raise UploadError("Text attachment contains binary data")
        if SENSITIVE.search(text) or quoted_credentials or "PRIVATE KEY-----" in text:
            raise UploadError("Credential-like text cannot be attached")
    if zipfile.is_zipfile(io.BytesIO(content)):
        if extension not in OFFICE_EXTENSIONS:
            raise UploadError("ZIP content cannot be attached under another extension")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
        except (OSError, zipfile.BadZipFile) as exc:
            raise UploadError("Office attachment is not a valid native Office container") from exc
        main = {".docx": "word/document.xml", ".xlsx": "xl/workbook.xml", ".pptx": "ppt/presentation.xml"}[extension]
        if not {"[Content_Types].xml", main}.issubset(names):
            raise UploadError("Office attachment is not a valid native Office container")
    elif extension in OFFICE_EXTENSIONS:
        raise UploadError("Office attachment is not a valid native Office container")
    kind = "code" if extension == ".py" else "text" if extension in TEXT_EXTENSIONS else (
        "document" if extension in OFFICE_EXTENSIONS or extension == ".pdf" else "image"
    )
    return {"kind": kind, "upload_name": upload_name(name),
            "requires_text_conversion": extension not in NATIVE_UPLOAD_EXTENSIONS,
            "executable": False}


class UploadStore:
    """Validate and stage browser-provided file bytes for one UI process.

    Staged files use opaque names and live only for this store's lifetime.
    Public records never contain filesystem paths or file contents.
    """

    def __init__(self, session_directory: str | os.PathLike | None = None):
        if session_directory is None:
            self._directory = Path(tempfile.mkdtemp(prefix="copilot-agent-upload-"))
            self._owns_directory = True
        else:
            self._directory = Path(session_directory).resolve()
            self._directory.mkdir(parents=True, exist_ok=True)
            self._owns_directory = False
        self._lock = threading.RLock()
        self._records: dict[str, dict] = {}
        self._requests: dict[str, tuple[str, str, str]] = {}
        self._request_receipts: dict[str, dict] = {}
        self._group_counts: dict[str | None, int] = {}
        self._total_uploads = 0
        self._total_uploaded_bytes = 0
        self._closed = False

    @property
    def storage_root(self) -> Path:
        """Private staging root for the attachment validator only; never expose in UI data."""
        return self._directory

    def add(self, *, name, content_type="", declared_size, content_base64,
            client_message_id=None) -> dict:
        safe_name = _safe_name(name)
        if not isinstance(content_type, str) or len(content_type) > 255 or any(ord(ch) < 32 for ch in content_type):
            raise UploadError("Invalid uploaded file type metadata")
        if type(declared_size) is not int or not 1 <= declared_size <= MAX_FILE_BYTES:
            raise UploadError("Attachment must be between 1 byte and 20 MiB")
        if not isinstance(content_base64, str) or len(content_base64) > MAX_ENCODED_FILE_BYTES:
            raise UploadError("Attachment exceeds the 20 MiB size limit")
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise UploadError("Attachment data is not valid base64") from exc
        if len(content) != declared_size:
            raise UploadError("Attachment size did not match its uploaded bytes")
        digest = hashlib.sha256(content).hexdigest()
        details = _validate_content(safe_name, content)
        if client_message_id is not None and (
            not isinstance(client_message_id, str) or not _SAFE_REQUEST_ID.fullmatch(client_message_id)
        ):
            raise UploadError("Invalid upload request identity")
        with self._lock:
            if self._closed:
                raise UploadError("The upload session is closed")
            if client_message_id is not None and client_message_id in self._requests:
                existing_id, existing_digest, existing_name = self._requests[client_message_id]
                if existing_digest != digest or existing_name != safe_name:
                    raise UploadError("Upload request identity was reused for different bytes")
                existing = self._records.get(existing_id)
                return self._public(existing) if existing is not None else dict(self._request_receipts[client_message_id])
            group_id = (client_message_id.rsplit(":", 1)[0]
                        if client_message_id is not None and client_message_id.rsplit(":", 1)[-1].isdigit()
                        else client_message_id)
            group_count = self._group_counts.get(group_id, 0)
            if group_count >= MAX_MESSAGE_ATTACHMENTS:
                raise UploadError("At most 20 files may be uploaded for one message")
            if self._total_uploads >= MAX_SESSION_ATTACHMENTS:
                raise UploadError("This workspace has reached its 200-file staging limit; close and reopen it after finishing current work")
            if self._total_uploaded_bytes + len(content) > MAX_SESSION_ATTACHMENT_BYTES:
                raise UploadError("This workspace has reached its 1 GiB attachment staging limit")
            attachment_id = uuid.uuid4().hex
            staged_directory = self._directory / attachment_id
            staged_directory.mkdir(mode=0o700)
            staged_path = staged_directory / safe_name
            try:
                with staged_path.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                info = staged_path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_size != len(content):
                    raise UploadError("The attachment could not be staged safely")
            except Exception:
                try:
                    staged_path.unlink(missing_ok=True)
                    staged_directory.rmdir()
                except OSError:
                    pass
                raise
            record = {
                "attachment_id": attachment_id,
                "name": safe_name,
                "size": len(content),
                "sha256": digest,
                "kind": details["kind"],
                "upload_name": details["upload_name"],
                "requires_text_conversion": details["requires_text_conversion"],
                "executable": False,
                "provenance": "local_workspace_upload",
                "client_message_id": client_message_id,
                "_group_id": group_id,
                "_path": staged_path,
            }
            self._records[attachment_id] = record
            self._group_counts[group_id] = group_count + 1
            self._total_uploads += 1
            self._total_uploaded_bytes += len(content)
            if client_message_id is not None:
                self._requests[client_message_id] = (attachment_id, digest, safe_name)
                self._request_receipts[client_message_id] = self._public(record)
            return self._public(record)

    @staticmethod
    def _public(record: dict) -> dict:
        return {key: record[key] for key in (
            "attachment_id", "name", "size", "sha256", "kind", "upload_name",
            "requires_text_conversion", "executable", "provenance", "client_message_id",
        )}

    def resolve_paths(self, attachment_ids) -> list[Path]:
        if not isinstance(attachment_ids, list) or len(attachment_ids) > MAX_MESSAGE_ATTACHMENTS:
            raise UploadError("A message can contain at most 20 uploaded files")
        if any(not isinstance(item, str) for item in attachment_ids):
            raise UploadError("Invalid attachment reference")
        if len(set(attachment_ids)) != len(attachment_ids):
            raise UploadError("The same attachment cannot be included more than once")
        with self._lock:
            if self._closed:
                raise UploadError("The upload session is closed")
            records = []
            for attachment_id in attachment_ids:
                record = self._records.get(attachment_id)
                if record is None:
                    raise UploadError("An uploaded attachment is unavailable; upload it again")
                path = record["_path"]
                try:
                    info = path.lstat()
                except OSError as exc:
                    raise UploadError("An uploaded attachment is unavailable; upload it again") from exc
                if not stat.S_ISREG(info.st_mode) or info.st_size != record["size"]:
                    raise UploadError("An uploaded attachment changed before submission")
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(65536), b""):
                        digest.update(block)
                if digest.hexdigest() != record["sha256"]:
                    raise UploadError("An uploaded attachment changed before submission")
                records.append(path)
            return records

    def records(self, attachment_ids=None) -> list[dict]:
        with self._lock:
            ids = list(self._records) if attachment_ids is None else list(attachment_ids)
            return [self._public(self._records[item]) for item in ids if item in self._records]

    def discard(self, attachment_ids) -> None:
        with self._lock:
            for attachment_id in attachment_ids:
                record = self._records.pop(attachment_id, None)
                if record is None:
                    continue
                try:
                    record["_path"].unlink(missing_ok=True)
                    record["_path"].parent.rmdir()
                except OSError:
                    pass

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._owns_directory:
                shutil.rmtree(self._directory, ignore_errors=True)
            else:
                for record in self._records.values():
                    try:
                        record["_path"].unlink(missing_ok=True)
                        record["_path"].parent.rmdir()
                    except OSError:
                        pass
            self._records.clear()
            self._requests.clear()
            self._request_receipts.clear()
            self._group_counts.clear()
