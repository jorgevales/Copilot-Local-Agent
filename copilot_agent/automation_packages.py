"""Validated, resumable automation ZIP packages and measurable task routing.

Package code is still untrusted. ZIP processing reuses ArchiveService, Python
stages use the fixed exact-plan Code Runner worker, and tool stages go through
the registered local ToolRegistry. This module is not an OS sandbox.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from .state import canonical_hash
from .policy import PathPolicy, PolicyError
from .archives import ArchiveError, ArchiveService, inspect_zip


DEFAULT_THRESHOLDS = {
    "package_score": 8,
    "minimum_steps": 4,
    "minimum_files": 3,
    "minimum_runtime_seconds": 120,
    "max_stages": 100,
    "max_parallel_stages": 4,
    "max_runtime_seconds": 1800,
    "max_output_chars": 65536,
}
_PATH_TOKEN = re.compile(r"(?<![\w.-])[\w.-]+\.(?:py|pyw|js|jsx|ts|tsx|html|css|json|ya?ml|toml|md|csv|xlsx?|docx|pptx)(?![\w.-])", re.I)
_LIST_ITEM = re.compile(r"(?m)^\s*(?:\d{1,2}[.)]|[-*])\s+")
_SEQUENCE = re.compile(r"\b(?:then|after(?:wards)?|next|once|before|finally|resume|retry|validate|verify)\b", re.I)
_MULTI_TOOL = re.compile(r"\b(?:browser|web|research|download|filesystem|file|desktop|Copilot|local tool)\b", re.I)
_CODE_TASK = re.compile(r"\b(?:implement|build|create|modify|full application|full app|codebase|design system|multi-file)\b", re.I)
_OUTPUT = re.compile(r"\b(?:report|application|app|dashboard|documentation|tests?|workbook|presentation|package|artifact|deliverable)\b", re.I)
_RECOVERY = re.compile(r"\b(?:checkpoint|resume|resumable|retry|recover|incremental|patch|cache|idempotent)\b", re.I)
_DEPENDENCY = re.compile(r"\b(?:dependency|dependencies|install|pip|npm|package manager|environment|library)\b", re.I)
_VALIDATION = re.compile(r"\b(?:test|validate|verify|check|regression)\b", re.I)
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)")
_PERMISSIONS = {"read_files", "create_files", "network"}


class PackageError(ValueError):
    """A package was incomplete, incompatible, unsafe or unverifiable."""


def _bounded_int(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise PackageError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def _relative(value, name="package path"):
    if not isinstance(value, str) or not value or len(value) > 240 or "\\" in value:
        raise PackageError(f"Invalid {name}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} or ":" in part for part in path.parts):
        raise PackageError(f"Unsafe {name}")
    return path.as_posix()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def estimate_task(description: str, thresholds: dict | None = None) -> dict:
    """Estimate workload from several observable structural and intent signals.

    No single term routes a task. The estimate is deterministic and its inputs
    are returned for review, tuning and tests.
    """
    if not isinstance(description, str) or not description.strip():
        raise ValueError("A non-empty task description is required")
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    text = description.strip()
    lines = len(_LIST_ITEM.findall(text))
    sequential = len(_SEQUENCE.findall(text))
    # Count semicolon-separated instructions only as another structural signal.
    clauses = len([part for part in re.split(r"[;\n]+", text) if len(part.strip()) >= 16])
    steps = max(1, lines, min(20, (sequential + 1 if sequential else 1)), min(20, clauses))
    file_names = {name.casefold() for name in _PATH_TOKEN.findall(text)}
    explicit_files = [int(n) for n in re.findall(r"\b(\d{1,3})\s+(?:files?|modules?|components?)\b", text, re.I)]
    files = max(len(file_names), min(100, max(explicit_files, default=0)))
    if re.search(r"\b(?:multi-file|multiple files|several files|full project|codebase)\b", text, re.I):
        files = max(files, 3)
    tool_mentions = {m.casefold() for m in _MULTI_TOOL.findall(text)}
    tools = len(tool_mentions)
    dependencies = len(_DEPENDENCY.findall(text))
    recovery = len(_RECOVERY.findall(text))
    validations = len(_VALIDATION.findall(text))
    outputs = len(_OUTPUT.findall(text))
    explicit_durations = [int(n) for n in re.findall(r"\b(\d{1,5})\s*(?:minutes?|mins?|hours?|hrs?)\b", text, re.I)]
    duration = max(explicit_durations, default=0) * (3600 if re.search(r"\b(?:hours?|hrs?)\b", text, re.I) else 60)
    duration = max(duration, steps * 15 + tools * 30 + files * 10 + dependencies * 20)
    code_change = bool(_CODE_TASK.search(text) and (files >= 2 or outputs >= 2 or re.search(r"\b(?:application|app|codebase|design system)\b", text, re.I)))
    multi_source = tools >= 3 and (steps >= 2 or validations > 0)
    needs_resume = recovery > 0 or steps >= int(limits["minimum_steps"]) or duration >= int(limits["minimum_runtime_seconds"])
    score = (min(5, steps) * 1.25 + min(4, files) * 1.25 + min(4, tools) * 1.25
             + min(3, dependencies) + min(3, recovery) * 1.5
             + min(3, validations) + min(4, outputs) * .75
             + (2 if duration >= int(limits["minimum_runtime_seconds"]) else 0)
             + (5 if code_change else 0) + (3 if multi_source else 0))
    package = (score >= float(limits["package_score"])
               or steps >= int(limits["minimum_steps"])
               or files >= int(limits["minimum_files"])
               or duration >= int(limits["minimum_runtime_seconds"])
               or code_change or multi_source or needs_resume and score >= float(limits["package_score"]) - 2)
    factors = {"estimated_steps": steps, "estimated_files": files,
               "estimated_tools": tools, "dependency_signals": dependencies,
               "estimated_duration_seconds": duration,
               "recovery_signals": recovery, "validation_signals": validations,
               "output_signals": outputs, "codebase_change": code_change,
               "multi_source_work": multi_source, "needs_resumability": needs_resume}
    return {"route": "package" if package else "direct", "score": round(score, 2),
            "threshold": limits["package_score"], "factors": factors}


def _check_object(value, fields, required, name):
    if not isinstance(value, dict) or set(value) - fields or required - set(value):
        raise PackageError(f"{name} has missing or unsupported fields")


def _topological(stages):
    by_id = {stage["id"]: stage for stage in stages}
    if len(by_id) != len(stages):
        raise PackageError("Stage IDs must be unique")
    for stage in stages:
        if stage["id"] in stage["depends_on"] or set(stage["depends_on"]) - set(by_id):
            raise PackageError("Stage dependency is missing or self-referential")
    remaining = {key: set(stage["depends_on"]) for key, stage in by_id.items()}
    order = []
    while remaining:
        ready = sorted(key for key, deps in remaining.items() if not deps)
        if not ready:
            raise PackageError("Stage graph contains a dependency cycle")
        order.extend(ready)
        for key in ready:
            remaining.pop(key)
        for deps in remaining.values():
            deps.difference_update(ready)
    return order


def validate_manifest(manifest: dict, archive_files: dict[str, bytes], registry=None,
                      *, limits=None, python_version=None) -> dict:
    limits = {**DEFAULT_THRESHOLDS, **(limits or {})}
    top = {"schema_version", "package_id", "package_version", "task_id", "correlation_id", "description",
           "entrypoint", "files", "dependencies", "tools", "capabilities", "stages", "validation",
           "expected_outputs", "result_contract", "rollback", "compatibility"}
    required = {"schema_version", "package_id", "package_version", "task_id", "correlation_id", "description",
                "entrypoint", "files", "dependencies", "tools", "capabilities", "stages", "validation",
                "expected_outputs", "result_contract"}
    _check_object(manifest, top, required, "Manifest")
    if manifest["schema_version"] != "1.0":
        raise PackageError("Unsupported package manifest version")
    for field in ("package_id", "task_id", "correlation_id", "description", "entrypoint"):
        if not isinstance(manifest[field], str) or not manifest[field] or len(manifest[field]) > 4000:
            raise PackageError(f"Invalid manifest {field}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", manifest["package_id"]):
        raise PackageError("Invalid package ID")
    if not isinstance(manifest["package_version"], str) or not _VERSION.match(manifest["package_version"]):
        raise PackageError("Invalid semantic package version")
    declared = manifest["files"]
    if not isinstance(declared, dict) or not declared or len(declared) > 1000:
        raise PackageError("Manifest files must be a bounded path-to-hash map")
    normalized_files = {}
    for name, digest in declared.items():
        path = _relative(name, "file path")
        if path in {"manifest.json", "README.md"} or path in normalized_files:
            raise PackageError("Payload files cannot replace the manifest, README or duplicate a path")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise PackageError("Each payload needs a lowercase SHA-256")
        data = archive_files.get(path)
        if data is None or _sha256(data) != digest:
            raise PackageError("Payload is missing or its SHA-256 does not match: " + path)
        normalized_files[path] = digest
    expected_archive_files = set(normalized_files) | {"manifest.json", "README.md"}
    if set(archive_files) != expected_archive_files:
        raise PackageError("ZIP members must match the manifest payload list plus manifest.json and README.md")
    if not isinstance(archive_files["README.md"], bytes) or len(archive_files["README.md"]) > 100_000:
        raise PackageError("Package README is missing or exceeds its limit")
    entrypoint = manifest["entrypoint"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", entrypoint):
        raise PackageError("Entrypoint must name a valid stage ID")

    dependencies = manifest["dependencies"]
    _check_object(dependencies, {"python_min", "modules"}, {"python_min", "modules"}, "Dependencies")
    if not isinstance(dependencies["python_min"], str) or not re.fullmatch(r"\d+\.\d+", dependencies["python_min"]):
        raise PackageError("python_min must be a major.minor version")
    py = python_version or sys.version_info[:2]
    min_py = tuple(int(part) for part in dependencies["python_min"].split("."))
    if tuple(py[:2]) < min_py:
        raise PackageError("Package requires a newer Python version")
    modules = dependencies["modules"]
    if (not isinstance(modules, list) or len(modules) > 100
            or not all(isinstance(module, str) for module in modules)
            or len(set(modules)) != len(modules)):
        raise PackageError("Invalid or duplicate dependencies")
    missing = []
    for module in modules:
        if not isinstance(module, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", module):
            raise PackageError("Invalid dependency name")
        try:
            if importlib.util.find_spec(module) is None:
                missing.append(module)
        except (ImportError, ModuleNotFoundError, ValueError):
            missing.append(module)
    if missing:
        raise PackageError("Missing declared dependency modules: " + ", ".join(sorted(missing)))

    caps = manifest["capabilities"]
    cap_fields = {"read_paths", "create_paths", "modify_paths", "network_destinations", "imports", "permissions",
                  "max_runtime_seconds", "max_output_chars", "max_concurrency"}
    _check_object(caps, cap_fields, cap_fields, "Capabilities")
    for field in ("read_paths", "create_paths", "modify_paths", "imports", "permissions", "network_destinations"):
        if (not isinstance(caps[field], list) or len(caps[field]) > 100
                or not all(isinstance(item, str) for item in caps[field])
                or len(set(caps[field])) != len(caps[field])):
            raise PackageError("Invalid or duplicate capability list: " + field)
    caps["read_paths"] = [_relative(item, "read path") for item in caps["read_paths"]]
    caps["create_paths"] = [_relative(item, "create path") for item in caps["create_paths"]]
    caps["modify_paths"] = [_relative(item, "modify path") for item in caps["modify_paths"]]
    if caps["modify_paths"]:
        raise PackageError("Package v1 supports create-only stage outputs; modifying existing files is not supported")
    if not set(caps["permissions"]) <= _PERMISSIONS:
        raise PackageError("Unsupported package permission")
    _bounded_int(caps["max_runtime_seconds"], "max_runtime_seconds", 1, int(limits["max_runtime_seconds"]))
    _bounded_int(caps["max_output_chars"], "max_output_chars", 1, int(limits["max_output_chars"]))
    _bounded_int(caps["max_concurrency"], "max_concurrency", 1, min(4, int(limits["max_parallel_stages"])))
    for host in caps["network_destinations"]:
        parsed = urlsplit(host)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise PackageError("Network capability must be an exact HTTPS host")

    if not isinstance(manifest["tools"], list) or len(manifest["tools"]) > 100:
        raise PackageError("Tool references must be a bounded list")
    tool_versions = {}
    for ref in manifest["tools"]:
        _check_object(ref, {"id", "version"}, {"id", "version"}, "Tool reference")
        if not all(isinstance(ref[key], str) and ref[key] for key in ("id", "version")) or ref["id"] in tool_versions:
            raise PackageError("Invalid or duplicate tool reference")
        if registry is None:
            raise PackageError("No local tool registry is available to resolve package references")
        try:
            definition = registry.definition(ref["id"])
        except (ValueError, KeyError) as error:
            raise PackageError("Package references an unavailable tool: " + ref["id"]) from error
        if definition["version"] != ref["version"]:
            raise PackageError("Package tool version is incompatible: " + ref["id"])
        if definition.get("approval_policy") != "read_only":
            raise PackageError("Package stages may use only registered read-only tools; local output writes belong to declared Python stage outputs")
        tool_versions[ref["id"]] = ref["version"]

    stage_fields = {"id", "kind", "script", "tool_id", "arguments", "depends_on", "inputs", "outputs",
                    "timeout_seconds", "retries", "idempotent", "checkpoint", "imports",
                    "network_destinations", "permissions", "arguments_list", "failure_policy"}
    stage_required = {"id", "kind", "depends_on", "inputs", "outputs", "timeout_seconds", "retries", "idempotent", "checkpoint"}
    stages = manifest["stages"]
    if not isinstance(stages, list) or not stages or len(stages) > int(limits["max_stages"]):
        raise PackageError("Package stages must be a non-empty bounded list")
    output_owners = {}
    for stage in stages:
        _check_object(stage, stage_fields, stage_required, "Stage")
        if not isinstance(stage["id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", stage["id"]):
            raise PackageError("Invalid stage ID")
        if stage["kind"] not in {"python", "tool"}:
            raise PackageError("Unsupported stage kind")
        stage["depends_on"] = list(stage["depends_on"])
        stage["inputs"] = [_relative(item, "stage input") for item in stage["inputs"]]
        stage["outputs"] = [_relative(item, "stage output") for item in stage["outputs"]]
        if len(set(stage["inputs"])) != len(stage["inputs"]) or len(set(stage["outputs"])) != len(stage["outputs"]):
            raise PackageError("Stage paths may not be duplicated")
        for output in stage["outputs"]:
            if output not in caps["create_paths"] or output in output_owners:
                raise PackageError("Stage outputs must be unique declared create paths")
            output_owners[output] = stage["id"]
        _bounded_int(stage["timeout_seconds"], "stage timeout", 1, caps["max_runtime_seconds"])
        _bounded_int(stage["retries"], "stage retries", 0, 3)
        if type(stage["idempotent"]) is not bool or type(stage["checkpoint"]) is not bool:
            raise PackageError("Stage idempotent and checkpoint values must be booleans")
        for inp in stage["inputs"]:
            if inp not in normalized_files and inp not in caps["create_paths"]:
                raise PackageError("Stage input is neither a packaged file nor a declared output")
        if stage["kind"] == "python":
            if set(stage) - (stage_required | {"script", "arguments_list", "imports", "network_destinations", "permissions"}) or "script" not in stage:
                raise PackageError("Python stage fields do not match a runnable script stage")
            script = _relative(stage["script"], "stage script")
            if script not in normalized_files or not script.endswith(".py"):
                raise PackageError("Python stage script must be a declared .py payload")
            source = archive_files[script].decode("utf-8", errors="strict")
            compile(source, script, "exec")
            imports = stage.get("imports", [])
            if not set(imports) <= set(caps["imports"]):
                raise PackageError("Stage imports exceed package capabilities")
            if not set(stage.get("permissions", [])) <= set(caps["permissions"]):
                raise PackageError("Stage permissions exceed package capabilities")
            if not set(stage.get("network_destinations", [])) <= set(caps["network_destinations"]):
                raise PackageError("Stage network destinations exceed package capabilities")
            if stage.get("network_destinations") and "network" not in stage.get("permissions", []):
                raise PackageError("Network destinations require the explicit network permission")
            if not {"read_files", "create_files"} <= set(stage.get("permissions", [])):
                raise PackageError("Python stages must explicitly declare read_files and create_files permissions")
            if not {script, *stage["inputs"]} <= set(caps["read_paths"]):
                raise PackageError("Python stage script and inputs must be declared in package read_paths")
            if not set(stage["outputs"]) <= set(caps["create_paths"]):
                raise PackageError("Python stage outputs must be declared in package create_paths")
            if not isinstance(stage.get("arguments_list", []), list) or len(stage.get("arguments_list", [])) > 100:
                raise PackageError("Invalid Python stage arguments")
        else:
            if set(stage) - (stage_required | {"tool_id", "arguments", "failure_policy"}) or "tool_id" not in stage or "arguments" not in stage:
                raise PackageError("Tool stage fields do not match a registered tool stage")
            if stage["tool_id"] not in tool_versions or not isinstance(stage["arguments"], dict):
                raise PackageError("Tool stage must call a versioned registered tool with object arguments")
            if stage["tool_id"] in {"automation.run", "automation.inspect", "automation.compare"}:
                raise PackageError("Automation packages cannot recursively invoke the package runtime")
            if stage.get("failure_policy", "stop") not in {"stop", "continue"}:
                raise PackageError("Unsupported tool-stage failure policy")
    order = _topological(stages)
    for stage in stages:
        if any(dep not in order[:order.index(stage["id"])] for dep in stage["depends_on"]):
            raise PackageError("Stage order cannot satisfy declared dependencies")
    if entrypoint not in {stage["id"] for stage in stages}:
        raise PackageError("Entrypoint must name a declared stage ID")
    expected = manifest["expected_outputs"]
    if not isinstance(expected, list) or len(expected) > 100 or not set(expected) <= set(output_owners):
        raise PackageError("Expected outputs must be a subset of stage-declared outputs")
    if not isinstance(manifest["validation"], list) or len(manifest["validation"]) > 100:
        raise PackageError("Validation rules must be a bounded list")
    for rule in manifest["validation"]:
        _check_object(rule, {"kind", "path", "sha256"}, {"kind", "path"}, "Validation rule")
        rule["path"] = _relative(rule["path"], "validation path")
        if rule["kind"] not in {"exists", "sha256", "python_syntax"}:
            raise PackageError("Unsupported validation rule")
        if rule["kind"] == "sha256" and (not isinstance(rule.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", rule["sha256"])):
            raise PackageError("SHA-256 validation requires an expected lowercase digest")
    _check_object(manifest["result_contract"], {"status", "summary"}, {"status", "summary"}, "Result contract")
    if manifest["result_contract"]["status"] not in {"complete", "partial", "blocked", "failed"} or not isinstance(manifest["result_contract"]["summary"], str):
        raise PackageError("Invalid structured result contract")
    result = dict(manifest)
    result["files"] = normalized_files
    result["stage_order"] = order
    result["tool_versions"] = tool_versions
    result["manifest_sha256"] = canonical_hash(manifest)
    result["missing_dependencies"] = []
    return result


def inspect_package(path: Path, expected_sha256: str | None = None, registry=None,
                    *, limits=None, python_version=None) -> dict:
    path = Path(path)
    inspected = inspect_zip(path)
    if expected_sha256 is not None and inspected["archive_sha256"] != expected_sha256:
        raise PackageError("Package ZIP SHA-256 differs from the reviewed artifact")
    if inspected.get("office"):
        raise PackageError("An Office archive is not an automation package")
    file_names = {item["path"] for item in inspected["entries"] if not item["directory"]}
    if not {"manifest.json", "README.md"} <= file_names:
        raise PackageError("Package ZIP must contain manifest.json and README.md")
    if len(file_names) > 1002:
        raise PackageError("Package has too many files")
    with zipfile.ZipFile(path) as archive:
        payloads = {name: archive.read(name) for name in file_names}
    try:
        manifest = json.loads(payloads["manifest.json"].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PackageError("Manifest is not valid UTF-8 JSON") from error
    normalized = validate_manifest(manifest, payloads, registry, limits=limits, python_version=python_version)
    return {"status": "validated", "archive": str(path), "archive_sha256": inspected["archive_sha256"],
            "archive_bytes": inspected["archive_bytes"], "manifest": normalized,
            "manifest_sha256": normalized["manifest_sha256"], "file_count": len(payloads),
            "stages": [{"id": stage["id"], "kind": stage["kind"], "depends_on": stage["depends_on"],
                        "timeout_seconds": stage["timeout_seconds"], "retries": stage["retries"],
                        "outputs": stage["outputs"], "tool_id": stage.get("tool_id"),
                        "script_sha256": normalized["files"].get(stage.get("script"))}
                       for stage in normalized["stages"]],
            "capabilities": normalized["capabilities"], "expected_outputs": normalized["expected_outputs"]}


def plan_patch(previous: dict, current: dict) -> dict:
    """Compare compatible manifests and invalidate only changed descendants."""
    old, new = previous.get("manifest"), current.get("manifest")
    if not isinstance(old, dict) or not isinstance(new, dict):
        return {"mode": "full_rebuild", "reason": "missing_manifest", "reusable_stages": [], "rebuild_stages": []}
    if old.get("schema_version") != new.get("schema_version") or old.get("package_id") != new.get("package_id"):
        return {"mode": "full_rebuild", "reason": "incompatible_package_lineage", "reusable_stages": [],
                "rebuild_stages": [stage["id"] for stage in new.get("stages", [])]}
    old_stages = {stage["id"]: stage for stage in old.get("stages", [])}
    new_stages = {stage["id"]: stage for stage in new.get("stages", [])}
    old_files, new_files = old.get("files", {}), new.get("files", {})
    changed = {key for key in old_stages.keys() | new_stages.keys()
               if old_stages.get(key) != new_stages.get(key)}
    for key in old_stages.keys() & new_stages.keys():
        old_stage, new_stage = old_stages[key], new_stages[key]
        watched = set(old_stage.get("inputs", [])) | set(new_stage.get("inputs", []))
        for field in ("script",):
            if old_stage.get(field): watched.update((old_stage[field], new_stage.get(field, "")))
        if any(old_files.get(name) != new_files.get(name) for name in watched):
            changed.add(key)
    invalidated = set(changed)
    progress = True
    while progress:
        progress = False
        for stage in new.get("stages", []):
            if stage["id"] not in invalidated and set(stage.get("depends_on", [])) & invalidated:
                invalidated.add(stage["id"]); progress = True
    reusable = sorted(set(new_stages) - invalidated)
    return {"mode": "patch" if reusable and invalidated else "reuse" if reusable else "full_rebuild",
            "reason": "stage_fingerprint_diff", "reusable_stages": reusable,
            "rebuild_stages": [key for key in (new["stage_order"] if "stage_order" in new else list(new_stages)) if key in invalidated]}


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def _load_state(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _save_state(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
    try:
        with temp.open("xb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        try: temp.unlink()
        except FileNotFoundError: pass


def _assert_workspace(path: Path, policy: PathPolicy) -> Path:
    resolved = policy.resolve(path)
    if resolved == Path(resolved.anchor) or resolved in {root.resolve() for root in policy.roots}:
        raise PolicyError("Package workspace must be a dedicated subdirectory within an allowed root")
    return resolved


def prepare_package_run(args: dict, context: dict, registry) -> dict:
    if not isinstance(args, dict) or set(args) - {"archive_path", "expected_sha256", "workspace", "resume_run_id", "prior_run_id"} or not {"archive_path", "expected_sha256", "workspace"} <= set(args):
        raise PackageError("automation.run requires archive_path, expected_sha256 and workspace")
    policy = context.get("path_policy")
    if not isinstance(policy, PathPolicy):
        raise PackageError("Package execution needs the current local path policy")
    archive = policy.resolve(args["archive_path"], must_exist=True)
    workspace = _assert_workspace(Path(args["workspace"]).expanduser(), policy)
    inspection = inspect_package(archive, args["expected_sha256"], registry,
                                 limits={"max_runtime_seconds": getattr(context.get("config"), "automation_max_runtime_seconds", 1800),
                                         "max_stages": getattr(context.get("config"), "automation_max_stages", 100),
                                         "max_parallel_stages": getattr(context.get("config"), "automation_max_parallel_stages", 4),
                                         "max_output_chars": getattr(context.get("config"), "automation_max_output_chars", 65536)})
    manifest = inspection["manifest"]
    for stage in manifest["stages"]:
        if stage["kind"] == "tool":
            registry.validate_input(stage["tool_id"], stage["arguments"])
    if inspection["archive_bytes"] > 50 * 1024 * 1024:
        raise PackageError("Package exceeds the archive size limit")
    prepared = {"inspection": inspection, "archive_path": str(archive), "workspace": str(workspace),
            "package_id": manifest["package_id"], "task_id": manifest["task_id"],
            "resume_run_id": args.get("resume_run_id"), "prior_run_id": args.get("prior_run_id"),
            "resource_limits": {"max_runtime_seconds": getattr(context.get("config"), "automation_max_runtime_seconds", 1800),
                                "max_stages": getattr(context.get("config"), "automation_max_stages", 100),
                                "max_parallel_stages": getattr(context.get("config"), "automation_max_parallel_stages", 4),
                                "max_output_chars": getattr(context.get("config"), "automation_max_output_chars", 65536)},
            "archive_sha256": inspection["archive_sha256"], "manifest_sha256": inspection["manifest_sha256"],
            "tool_stages": [{"stage": s["id"], "tool": s["tool_id"], "version": manifest["tool_versions"][s["tool_id"]],
                             "arguments": s["arguments"]} for s in manifest["stages"] if s["kind"] == "tool"],
            "python_stages": [{"stage": s["id"], "script": s["script"], "sha256": manifest["files"][s["script"]],
                               "permissions": s.get("permissions", []), "network_destinations": s.get("network_destinations", [])}
                              for s in manifest["stages"] if s["kind"] == "python"],
            "capabilities": manifest["capabilities"], "expected_outputs": manifest["expected_outputs"],
            "approval_scope": "This exact package revision, tool set, workspace and declared capability/resource scope"}
    prepared["approval_scope_type"] = "automation_package"
    prepared["package_plan_hash"] = canonical_hash({key: prepared[key] for key in
        ("archive_sha256", "manifest_sha256", "workspace", "package_id", "task_id", "tool_stages",
         "python_stages", "capabilities", "expected_outputs", "resume_run_id", "prior_run_id", "resource_limits")})
    return prepared


async def execute_package(args: dict, context: dict, registry, *, code_runner_factory) -> dict:
    """Run a pre-approved package in a dedicated workspace with durable evidence."""
    prepared = prepare_package_run(args, context, registry)
    approved = (context.get("approved") is True
                and context.get("approved_hash") == prepared["package_plan_hash"]
                and context.get("package_plan_hash") == prepared["package_plan_hash"])
    if not approved:
        raise PolicyError("Automation package execution requires approval bound to the exact archive and scope")
    inspection = prepared["inspection"]
    manifest = inspection["manifest"]
    archive = Path(prepared["archive_path"])
    workspace = Path(prepared["workspace"])
    package_dir = workspace / "packages" / inspection["archive_sha256"]
    if not package_dir.exists():
        workspace.mkdir(parents=True, exist_ok=True)
        extraction = ArchiveService(context["path_policy"], context["session_dir"]).extract(
            {"path": str(archive), "destination": str(package_dir),
             "expected_sha256": inspection["archive_sha256"], "expected_files": list(manifest["files"]) + ["manifest.json", "README.md"]},
            approved=True)
        if extraction["status"] != "verified":
            raise PackageError("Safe package extraction did not verify every file: " + extraction["status"])
    else:
        # A cache hit still requires exact retained file hashes.
        for name, digest in manifest["files"].items():
            target = package_dir.joinpath(*PurePosixPath(name).parts)
            if not target.is_file() or _file_hash(target) != digest:
                raise PackageError("Cached package payload differs from the approved manifest")
    resume_id = args.get("resume_run_id")
    prior_id = args.get("prior_run_id")
    if resume_id is not None and (not isinstance(resume_id, str) or not re.fullmatch(r"[a-f0-9]{32}", resume_id)):
        raise PackageError("Invalid resume run ID")
    if prior_id is not None and (not isinstance(prior_id, str) or not re.fullmatch(r"[a-f0-9]{32}", prior_id)):
        raise PackageError("Invalid prior run ID")
    run_id = resume_id or uuid.uuid4().hex
    run_dir = workspace / "runs" / run_id
    if run_dir.exists() and resume_id is None:
        raise PackageError("Run directory already exists; select its run ID to resume")
    run_dir.mkdir(parents=True, exist_ok=True)
    output_root = run_dir / "outputs"
    output_root.mkdir(parents=True, exist_ok=True)
    state_path = run_dir / "state.json"
    previous = _load_state(state_path) if resume_id else {}
    if resume_id and previous.get("archive_sha256") != inspection["archive_sha256"]:
        raise PackageError("Resume package hash differs from the original run; use prior_run_id for an incremental patch")
    if previous.get("status") == "completed":
        return {"status": "completed", "package_id": manifest["package_id"], "run_id": run_id,
                "archive_sha256": inspection["archive_sha256"], "resumed": True,
                "cache_hits": list(previous.get("stages", {})), "outputs": previous.get("outputs", []),
                "summary": "The exact package run was already verified; no stage was repeated."}
    prior = {}
    patch = {"mode": "full_rebuild", "reason": "no_prior_run", "reusable_stages": [],
             "rebuild_stages": manifest["stage_order"]}
    if prior_id:
        prior_dir = workspace / "runs" / prior_id
        prior = _load_state(prior_dir / "state.json")
        if prior.get("status") not in {"completed", "partial", "failed", "cancelled"}:
            raise PackageError("Prior run state is unavailable")
        patch = plan_patch(prior, {"manifest": manifest})
        if patch["mode"] != "full_rebuild":
            for stage_id in patch["reusable_stages"]:
                record = prior.get("stages", {}).get(stage_id, {})
                if record.get("status") != "completed":
                    patch["rebuild_stages"].append(stage_id)
                    patch["reusable_stages"].remove(stage_id)
                    continue
                valid = True
                for rel, digest in record.get("output_hashes", {}).items():
                    src = prior_dir / "outputs" / rel
                    if not src.is_file() or _file_hash(src) != digest:
                        valid = False; break
                stage = next(item for item in manifest["stages"] if item["id"] == stage_id)
                expected_fingerprint = canonical_hash({"stage": stage,
                    "payload": manifest["files"].get(stage.get("script")),
                    "inputs": {name: _sha256((package_dir / name).read_bytes()) for name in stage["inputs"] if (package_dir / name).is_file()},
                    "dependencies": {dep: prior.get("stages", {}).get(dep, {}).get("output_hashes", {}) for dep in stage["depends_on"]},
                    "tool_version": manifest["tool_versions"].get(stage.get("tool_id")),
                    "python": list(sys.version_info[:3])})
                valid = valid and record.get("fingerprint") == expected_fingerprint
                if valid:
                    for rel in record.get("output_hashes", {}):
                        src, dest = prior_dir / "outputs" / rel, output_root / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(src, dest)
                        if _file_hash(dest) != record["output_hashes"][rel]:
                            raise PackageError("Cached output copy failed verification")
                else:
                    patch["rebuild_stages"].append(stage_id)
                    patch["reusable_stages"].remove(stage_id)
    stages = {stage["id"]: stage for stage in manifest["stages"]}
    stage_records = {}
    if resume_id:
        for stage_id, record in previous.get("stages", {}).items():
            stage = next((item for item in manifest["stages"] if item["id"] == stage_id), None)
            if stage is None or record.get("status") not in {"completed", "cached"}:
                continue
            valid = all((output_root / rel).is_file() and _file_hash(output_root / rel) == digest
                        for rel, digest in record.get("output_hashes", {}).items())
            if valid:
                stage_records[stage_id] = dict(record, status="cached", cache_source=run_id)
    for stage_id in patch["reusable_stages"]:
        if stage_id in prior.get("stages", {}):
            record = prior["stages"][stage_id]
            stage_records[stage_id] = dict(record, status="cached", cache_source=prior_id)
    old_stages = previous.get("stages", {})
    state = {"schema_version": "1.0", "manifest": manifest,
             "run_id": run_id, "package_id": manifest["package_id"],
             "package_version": manifest["package_version"], "task_id": manifest["task_id"],
             "archive_sha256": inspection["archive_sha256"], "manifest_sha256": inspection["manifest_sha256"],
             "status": "running", "patch_decision": patch, "stages": stage_records,
             "created_at": previous.get("created_at", time.time()), "updated_at": time.time()}
    _save_state(state_path, state)
    progress = context.get("automation_progress")
    cancel = context.get("cancelled", lambda: False)
    completed = set(stage_records)
    failures = []
    elapsed = 0.0
    concurrency = min(manifest["capabilities"]["max_concurrency"], int(getattr(context.get("config"), "automation_max_parallel_stages", 4)))

    async def _await_stage(coroutine, timeout_seconds):
        task = asyncio.create_task(coroutine)
        deadline = time.monotonic() + timeout_seconds
        try:
            while True:
                if cancel():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise asyncio.CancelledError()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise asyncio.TimeoutError()
                done, _ = await asyncio.wait({task}, timeout=min(.2, remaining))
                if done:
                    return task.result()
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            raise

    async def run_stage(stage):
        nonlocal elapsed
        if cancel():
            raise asyncio.CancelledError()
        sid = stage["id"]
        start = time.monotonic()
        fingerprint = canonical_hash({"stage": stage, "payload": manifest["files"].get(stage.get("script")),
                                      "inputs": {name: _sha256((package_dir / name).read_bytes()) for name in stage["inputs"] if (package_dir / name).is_file()},
                                      "dependencies": {dep: state["stages"].get(dep, {}).get("output_hashes", {}) for dep in stage["depends_on"]},
                                      "tool_version": manifest["tool_versions"].get(stage.get("tool_id")),
                                      "python": list(sys.version_info[:3])})
        outputs = {}
        outcome = None
        max_attempts = stage["retries"] + 1 if stage["idempotent"] else 1
        for attempt in range(1, max_attempts + 1):
            try:
                if stage["kind"] == "tool":
                    subcontext = dict(context)
                    subcontext.update(approved=True, approved_hash=context["package_plan_hash"],
                                      package_stage=True, source_request_id=manifest["correlation_id"])
                    outcome = await _await_stage(registry.execute(stage["tool_id"], stage["arguments"], subcontext),
                                                 stage["timeout_seconds"])
                    if not outcome.get("ok"):
                        if attempt < max_attempts and outcome.get("result", {}).get("side_effects_uncertain") is False:
                            continue
                        break
                else:
                    script_path = package_dir.joinpath(*PurePosixPath(stage["script"]).parts)
                    expected = [str(output_root.joinpath(*PurePosixPath(path).parts)) for path in stage["outputs"]]
                    for target in expected:
                        Path(target).parent.mkdir(parents=True, exist_ok=True)
                    read_paths = [str(script_path)]
                    for rel in stage["inputs"]:
                        source = package_dir / rel if (package_dir / rel).is_file() else output_root / rel
                        if source.exists(): read_paths.append(str(source))
                    permissions = list(stage.get("permissions", []))
                    code_args = {"script": script_path.read_text(encoding="utf-8"), "purpose": manifest["description"][:4000],
                                 "language": "local_python", "working_directory": str(package_dir), "read_paths": read_paths,
                                 "create_paths": expected, "expected_outputs": expected, "commands": [],
                                 "network_destinations": stage.get("network_destinations", []), "permissions": permissions,
                                 "risk_summary": "Execute this exact package stage under its reviewed manifest scope.",
                                 "recovery_notes": "Resume from the verified package checkpoint; do not repeat uncertain effects.",
                                 "interpreter": sys.executable, "arguments": list(stage.get("arguments_list", [])) + [str(output_root)],
                                 "imports": list(stage.get("imports", [])), "modify_paths": [], "timeout_seconds": stage["timeout_seconds"],
                                 "max_output_chars": min(manifest["capabilities"]["max_output_chars"], 12000),
                                 "expected_effects": ["create declared outputs"], "viewer_windows": [],
                                 "source_path": str(script_path), "source_sha256": manifest["files"][stage["script"]]}
                    runner = code_runner_factory(context["path_policy"], context["session_dir"], stage["timeout_seconds"],
                                                 min(manifest["capabilities"]["max_output_chars"], 12000))
                    proposed = runner.prepare(code_args)
                    outcome = await _await_stage(runner.run_async(code_args, proposed["proposal_hash"], process_registry=context.get("process_registry")),
                                                 stage["timeout_seconds"])
                    if outcome.get("status") != "completed":
                        safe_retry = (outcome.get("side_effects_uncertain") is False
                                      and not any(Path(path).exists() for path in expected))
                        if attempt < max_attempts and safe_retry:
                            continue
                        break
                break
            except asyncio.CancelledError:
                raise
            except Exception as error:
                outcome = {"ok": False, "status": "failed", "error": str(error)[:1000], "side_effects_uncertain": True}
                break
        if stage["kind"] == "python" and outcome and outcome.get("status") == "completed":
            outputs = {rel: _file_hash(output_root / rel) for rel in stage["outputs"]}
        elif stage["kind"] == "tool" and outcome and outcome.get("ok"):
            outputs = {}
        success = outcome is not None and (outcome.get("ok", True) if stage["kind"] == "tool" else outcome.get("status") == "completed")
        record = {"status": "completed" if success else "failed", "fingerprint": fingerprint,
                  "attempts": attempt, "duration_seconds": round(time.monotonic() - start, 4),
                  "output_hashes": outputs, "tool_id": stage.get("tool_id"),
                  "tool_version": manifest["tool_versions"].get(stage.get("tool_id")),
                  "result": outcome if stage["kind"] == "tool" else {key: outcome.get(key) for key in ("status", "exit_code", "stdout", "stderr", "audit_path", "side_effects_uncertain", "error") if key in outcome}}
        elapsed += record["duration_seconds"]
        if elapsed > manifest["capabilities"]["max_runtime_seconds"]:
            record["status"] = "failed"; record["error"] = "Package runtime budget expired"
        state["stages"][sid] = record
        state["updated_at"] = time.time()
        _save_state(state_path, state)
        if progress:
            progress({"event": "package_stage", "stage_id": sid, "status": record["status"],
                      "completed": len([r for r in state["stages"].values() if r.get("status") in {"completed", "cached"}]),
                      "total": len(stages), "attempts": record["attempts"]})
        if not success:
            failures.append(sid)
        return record

    if resume_id:
        for stage in manifest["stages"]:
            if stage["id"] not in stage_records and any((output_root / rel).exists() for rel in stage["outputs"]):
                raise PackageError("An interrupted stage left output files; resume into a fresh run directory to preserve them")
    try:
        pending = set(manifest["stage_order"]) - completed
        while pending:
            if cancel():
                raise asyncio.CancelledError()
            ready = [stages[sid] for sid in manifest["stage_order"]
                     if sid in pending and set(stages[sid]["depends_on"]) <= completed]
            if not ready:
                raise PackageError("No runnable stage remains; dependency state is inconsistent")
            wave = ready[:concurrency]
            # Do not overlap tool effects with one another. Python stages have
            # disjoint declared create paths, so independent waves may run safely.
            if any(stage["kind"] == "tool" for stage in wave):
                wave = [wave[0]]
            results = await asyncio.gather(*(run_stage(stage) for stage in wave), return_exceptions=True)
            for stage, result in zip(wave, results):
                pending.remove(stage["id"])
                if isinstance(result, asyncio.CancelledError):
                    raise result
                if isinstance(result, BaseException):
                    failures.append(stage["id"])
                    state["stages"][stage["id"]] = {"status": "failed", "error": str(result)[:1000]}
                    _save_state(state_path, state)
                elif result.get("status") in {"completed", "cached"}:
                    completed.add(stage["id"])
                elif stage.get("failure_policy", "stop") != "continue":
                    pending.clear(); break
        if failures:
            state["status"] = "partial" if completed else "failed"
        else:
            state["status"] = "completed"
    except asyncio.CancelledError:
        state["status"] = "cancelled"
        _save_state(state_path, state)
        return {"status": "cancelled", "package_id": manifest["package_id"], "run_id": run_id,
                "archive_sha256": inspection["archive_sha256"], "patch_decision": patch,
                "completed_stages": sorted(completed), "failed_stages": failures,
                "summary": "Package execution was cancelled at a retained checkpoint."}

    validation = _validate_outputs(manifest, package_dir, output_root)
    if not validation["ok"] and state["status"] == "completed":
        state["status"] = "partial"
        failures.extend(validation["errors"])
    output_evidence = []
    for rel in manifest["expected_outputs"]:
        path = output_root / rel
        if path.is_file(): output_evidence.append({"path": str(path), "size": path.stat().st_size, "sha256": _file_hash(path), "verified": True})
    state["outputs"] = output_evidence
    state["validation"] = validation
    state["updated_at"] = time.time()
    _save_state(state_path, state)
    result = {"status": state["status"], "package_id": manifest["package_id"],
              "package_version": manifest["package_version"], "task_id": manifest["task_id"],
              "run_id": run_id, "archive_sha256": inspection["archive_sha256"],
              "manifest_sha256": inspection["manifest_sha256"], "workspace": str(workspace),
              "package_path": str(package_dir), "output_root": str(output_root),
              "completed_stages": sorted(completed), "failed_stages": failures,
              "patch_decision": patch, "validation": validation, "outputs": output_evidence,
              "state_path": str(state_path), "summary": manifest["result_contract"]["summary"]}
    if context.get("session_state"):
        context["session_state"].event("automation_package_completed", package_id=manifest["package_id"],
                                         run_id=run_id, status=state["status"], archive_sha256=inspection["archive_sha256"],
                                         patch_mode=patch["mode"], completed_stages=sorted(completed))
    if progress:
        progress({"event": "package_completed", "run_id": run_id, "status": state["status"], "outputs": output_evidence})
    return result


def _validate_outputs(manifest, package_dir, output_root):
    errors = []
    expected = manifest["expected_outputs"]
    for rel in expected:
        target = output_root.joinpath(*PurePosixPath(rel).parts)
        if not target.is_file(): errors.append("Missing expected output: " + rel)
    for rule in manifest["validation"]:
        target = output_root / rule["path"]
        if rule["path"] not in expected:
            target = package_dir / rule["path"]
        try:
            if rule["kind"] == "exists" and not target.is_file(): errors.append("Validation file missing: " + rule["path"])
            elif rule["kind"] == "sha256" and (not target.is_file() or _file_hash(target) != rule["sha256"]): errors.append("Validation SHA-256 mismatch: " + rule["path"])
            elif rule["kind"] == "python_syntax": compile(target.read_text(encoding="utf-8"), str(target), "exec")
        except (OSError, SyntaxError, UnicodeError):
            errors.append("Validation could not verify: " + rule["path"])
    return {"ok": not errors, "checked": len(expected) + len(manifest["validation"]), "errors": errors}
