"""Separate restricted and allowlisted external bug reports."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import sysconfig
import traceback
import uuid

from .config import PROJECT_ROOT
from .logging_utils import redact

SCHEMA_VERSION = "1.0"
try:
    RETENTION_DAYS = int(os.environ.get("COPILOT_AGENT_DIAGNOSTIC_RETENTION_DAYS", "30"))
except ValueError:
    RETENTION_DAYS = 30
if not 1 <= RETENTION_DAYS <= 3650:
    RETENTION_DAYS = 30

_SECRET = re.compile(r"(?i)(bearer\s+[\w.\-]+|(?:[\"']?[A-Z0-9_.-]*(?:password|passwd|secret|token|api[_ -]?key|authorization|cookie|credential|private[_ -]?key|recovery[_ -]?code)[A-Z0-9_.-]*[\"']?)\s*[:=]\s*[\"']?[^\s,;\"']+|(?:sk-|ghp_)[A-Za-z0-9_-]{12,}|eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)")
_AUTH_HEADER = re.compile(r"(?i)(?:authorization|proxy-authorization)\s*[:=]\s*(?:bearer\s+)?[^\s,;]+")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_ABS_PATH = re.compile(r"(?i)(?:[A-Z]:\\|\\\\)[^\s\"']+")
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)")
_EXTERNAL_FIELDS = frozenset({
    "classification", "schema_version", "report_id", "correlation_id", "timestamp_utc",
    "application", "runtime", "execution_mode", "error_category", "exception_type",
    "summary", "error_code", "severity", "origin", "exception_chain", "candidate_files",
    "sanitization", "integrity",
})
_EXTERNAL_SAFE = re.compile(r"^[A-Za-z0-9 _.,:;()\[\]{}+\-/<>?=]+$")
_SAFE_EXCEPTION_SUMMARIES = {
    "TimeoutError": "A local operation exceeded its time limit.",
    "FileNotFoundError": "A required local file or resource was not found.",
    "PermissionError": "The operating system denied a local operation.",
    "ConnectionError": "A local connection failed.",
    "UnicodeError": "Text could not be decoded using the expected encoding.",
    "JSONDecodeError": "Structured input could not be parsed as JSON.",
    "ValueError": "A supplied or returned value failed validation.",
    "TypeError": "An operation received a value of an unexpected type.",
    "KeyError": "A required data field was missing.",
    "AssertionError": "An internal consistency check failed.",
    "RuntimeError": "An application operation could not complete.",
}


def _safe_text(value: object, limit: int = 1000) -> str:
    text = _AUTH_HEADER.sub("[REDACTED_SECRET]", str(value))
    text = _SECRET.sub("[REDACTED_SECRET]", text)
    text = _PRIVATE_KEY.sub("[REDACTED_SECRET]", text)
    text = _EMAIL.sub("[REDACTED_PERSONAL_DATA]", text)
    text = _PHONE.sub("[REDACTED_PERSONAL_DATA]", text)
    text = _ABS_PATH.sub("[REDACTED_PATH]", text)
    text = re.sub(r"(?i)https?://\S+", "[REDACTED_URL]", text)
    text = re.sub(r"\b\d{8,}\b", "[REDACTED_IDENTIFIER]", text)
    return str(redact(text))[:limit]


def _frames(exc: BaseException) -> list[dict]:
    result = []
    for frame in traceback.extract_tb(exc.__traceback__)[-40:]:
        path = Path(frame.filename)
        try:
            relative = path.resolve().relative_to(PROJECT_ROOT).as_posix()
            ownership = _ownership(path, relative)
        except (OSError, ValueError):
            relative, ownership = path.name, _ownership(path)
        result.append({"path": _safe_text(relative, 300), "function": _safe_text(frame.name, 120),
                       "line": frame.lineno, "column": getattr(frame, "colno", None), "ownership": ownership})
    return result


def _ownership(path: Path, relative: str | None = None) -> str:
    parts = {part.casefold() for part in path.parts}
    if relative and relative.casefold().startswith("tests/"): return "test"
    if parts & {"runtime", ".tools", "build", "dist", "__pycache__", "generated"}: return "generated"
    if parts & {"vendor", "vendored", "third_party", "third-party"}: return "vendor"
    if "site-packages" in parts or "dist-packages" in parts or ".venv" in parts: return "dependency"
    if relative is not None: return "project"
    resolved = path.resolve()
    try:
        if any(resolved.is_relative_to(Path(root).resolve()) for root in sysconfig.get_paths().values() if root):
            return "system"
    except (OSError, ValueError):
        pass
    return "dependency"


def _caught_frame() -> dict | None:
    for frame in reversed(traceback.extract_stack(limit=30)[:-1]):
        path = Path(frame.filename)
        try:
            relative = path.resolve().relative_to(PROJECT_ROOT).as_posix()
            ownership = _ownership(path, relative)
        except (OSError, ValueError):
            relative, ownership = path.name, _ownership(path)
        if relative != "copilot_agent/diagnostics.py" and frame.name != "_record_bug_fix":
            return {"path": _safe_text(relative, 300), "function": _safe_text(frame.name, 120),
                    "line": frame.lineno, "column": getattr(frame, "colno", None), "ownership": ownership}
    return None


def _category(exc: BaseException) -> str:
    name = type(exc).__name__.casefold()
    if "timeout" in name: return "timeout"
    if "protocol" in name: return "protocol"
    if "policy" in name: return "policy"
    if isinstance(exc, OSError): return "operating_system"
    return "application"


def _write_private(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if os.name != "nt":
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        handle_context = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
    else:
        handle_context = path.open("x", encoding="utf-8", newline="\n")
    with handle_context as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def validate_external(data: dict) -> None:
    if set(data) != _EXTERNAL_FIELDS or data.get("classification") != "EXTERNAL_SANITIZED":
        raise ValueError("External diagnostic schema validation failed")
    encoded = json.dumps(data, ensure_ascii=False)
    if _SECRET.search(encoded) or _EMAIL.search(encoded) or _ABS_PATH.search(encoded) or "http://" in encoded.casefold() or "https://" in encoded.casefold():
        raise ValueError("External diagnostic contains a prohibited value")
    def check(value):
        if isinstance(value, str) and not _EXTERNAL_SAFE.fullmatch(value):
            raise ValueError("External diagnostic contains a value outside its safe character set")
        if isinstance(value, dict):
            for item in value.values(): check(item)
        if isinstance(value, list):
            for item in value: check(item)
    check(data)


class DiagnosticReports:
    def __init__(self, storage_root: Path, session_id: str, execution_mode: str = "live"):
        self.root = Path(storage_root) / "runtime" / "diagnostics"
        self.session_id = session_id
        self.execution_mode = execution_mode if execution_mode in {"live", "testing"} else "unknown"

    def _expire(self, directory: Path) -> None:
        cutoff = datetime.now(timezone.utc).timestamp() - RETENTION_DAYS * 86400
        for path in directory.glob("*_bug_report_*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass

    def create(self, exc: BaseException, *, operation: str, stage: str,
               events: list[dict] | None = None) -> dict:
        report_id, correlation_id = uuid.uuid4().hex, uuid.uuid4().hex
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        frames = _frames(exc)
        origin = next((frame for frame in reversed(frames) if frame["ownership"] == "project"), None)
        first = origin or (frames[-1] if frames else None)
        message = _safe_text(exc)
        internal = {
            "FILES TO PROVIDE TO AUTHORIZED COPILOT": _recommend(first),
            "classification": "INTERNAL_RESTRICTED", "schema_version": SCHEMA_VERSION,
            "report_id": report_id, "correlation_id": correlation_id, "session_id": _safe_text(self.session_id, 100),
            "timestamp_utc": stamp, "application": {"name": "Copilot Local Agent", "version": "unknown", "component": first["path"] if first else "unknown"},
            "runtime": {"python": f"{sys.version_info.major}.{sys.version_info.minor}", "os": sys.platform},
            "execution_mode": self.execution_mode, "error_category": _category(exc),
            "exception_type": type(exc).__name__, "summary": message, "error_message": message,
            "error_code": _safe_text(exc.code) if getattr(exc, "code", None) is not None else None,
            "severity": "error", "reproducible": None,
            "operation": _safe_text(operation), "processing_stage": _safe_text(stage),
            "origin": origin, "raised_at": origin, "caught_at": _caught_frame(), "frames": frames,
            "exception_chain": [{"type": type(item).__name__, "message": _safe_text(item)}
                                for item in _exception_chain(exc)],
            "preceding_events": [{"event": _safe_text(item.get("event", "unknown"), 100),
                                  "timestamp": _safe_text(item.get("timestamp", "unknown"), 50)}
                                 for item in (events or [])[-20:]],
            "resources": [], "tool_or_command": None, "command_arguments": None, "exit_code": None,
            "stderr_summary": None, "expected_behavior": None, "observed_behavior": message,
            "probable_cause": None, "alternative_causes": [], "remediation": [],
            "candidate_files": _recommend(first), "related_tests": [item["related_test"] for item in _recommend(first) if item["related_test"]], "configuration_context": None,
            "dependency_context": None, "sanitization": {"secrets_filtered": True, "personal_data_filtered": True},
            "integrity": {"validated": True, "external_report_validated": True},
        }
        external = self._external(internal, first, frames, report_id, correlation_id, stamp, type(exc).__name__)
        validate_external(external)
        internal_dir, external_dir = self.root / "internal", self.root / "external_review"
        self._expire(internal_dir); self._expire(external_dir)
        internal_path = internal_dir / f"internal_bug_report_{report_id}.json"
        external_path = external_dir / f"sanitized_bug_report_{report_id}.json"
        _write_private(internal_path, internal)
        _write_private(external_path, external)
        return {"internal_path": internal_path, "external_path": external_path,
                "internal": internal, "external": external}

    def _external(self, internal, origin, frames, report_id, correlation_id, stamp, exception_type):
        alias_by_path = {}
        safe_frames = []
        for index, frame in enumerate(frames, 1):
            path = frame["path"]
            alias = alias_by_path.setdefault(path, f"FILE_{len(alias_by_path)+1:03d}")
            safe_frames.append({"file": alias, "function": f"FUNCTION_{index:03d}", "line": frame["line"],
                                "ownership": "application" if frame["ownership"] == "project" else "runtime"})
        first_alias = next((item["file"] for item in safe_frames if item["ownership"] == "application"), None)
        files = ([{"file": first_alias, "lines": origin["line"], "whole_file_needed": False}]
                 if first_alias and origin else [])
        safe_type = exception_type if exception_type in _SAFE_EXCEPTION_SUMMARIES else "ApplicationError"
        return {
            "classification": "EXTERNAL_SANITIZED", "schema_version": SCHEMA_VERSION,
            "report_id": report_id, "correlation_id": correlation_id, "timestamp_utc": stamp,
            "application": "Local desktop application", "runtime": f"Python {sys.version_info.major}.{sys.version_info.minor} on {('Windows' if os.name == 'nt' else 'Unix-like')}",
            "execution_mode": self.execution_mode, "error_category": internal["error_category"],
            "exception_type": safe_type,
            "summary": _SAFE_EXCEPTION_SUMMARIES.get(safe_type, "The application stopped during a local operation."),
            "error_code": internal["error_category"], "severity": "error",
            "origin": {"file": first_alias,
                       "function": next((item["function"] for item in safe_frames if item["file"] == first_alias), None),
                       "line": origin["line"] if origin else None, "frames": safe_frames},
            "exception_chain": ["ApplicationError"],
            "candidate_files": {"section": "FILES OR CODE EXCERPTS NEEDED FOR EXTERNAL REVIEW", "files": files},
            "sanitization": "Strict field allowlist; paths, messages, identifiers, and user data omitted.",
            "integrity": "Validated against the external report allowlist.",
        }


def _exception_chain(exc):
    chain, seen, current = [], set(), exc
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current)); chain.append(current)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return chain


def _recommend(origin):
    if not origin or origin["ownership"] != "project": return []
    path = Path(origin["path"])
    test = PROJECT_ROOT / "tests" / ("test_" + path.stem + ".py")
    related_test = test.relative_to(PROJECT_ROOT).as_posix() if test.is_file() else None
    return [{"priority": 1, "location": origin["path"], "file_name": Path(origin["path"]).name,
             "repository_relative_path": origin["path"], "why": "Contains the deepest project-owned frame associated with this failure.",
             "symbol": origin["function"], "line": origin["line"], "whole_file_needed": False,
             "related_file": None, "related_test": related_test, "sensitivity_warning": "Review for sensitive content before upload.",
             "manual_review_required": True}]
