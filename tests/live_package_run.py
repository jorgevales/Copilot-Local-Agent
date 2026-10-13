"""Live Copilot ZIP-to-local-run proof in an isolated workspace.

Requires --live and a dedicated proof config. It downloads only the named
synthetic project, relies on the orchestrator's automatic ZIP review, and
uses conversation-scoped authorization for reviewed package revisions until
one passes, without replaying any exact archive that already started.
It never attaches to or operates inside a VDI session.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from types import SimpleNamespace
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copilot_agent.browser import (BrowserAdapter, SubmissionNotSentError,
                                   SubmissionAmbiguousError, CaptureTimeoutError)
from copilot_agent.config import Config
from copilot_agent.automation_packages import PackageError, PackageReviewError, inspect_package
from copilot_agent.app import choose_browser_endpoint
from copilot_agent.logging_utils import redact
from copilot_agent.orchestrator import Orchestrator
from copilot_agent.persistence import write_json
from copilot_agent.setup_resources import machine_key
from copilot_agent.state import SessionState, latest_committed_request_id, recoverable_capture_request_id
from copilot_agent.tools import ToolRegistry


PACKAGE_PREFIX = "transit-reliability-observatory-"
PACKAGE_NAME = "transit-reliability-observatory-1.0.0.zip"
DEFAULT_PROOF_REVISIONS = 4
SAFE_IMPORTS = {"csv", "json", "html", "statistics", "math", "datetime", "collections", "pathlib", "sys"}
EXPECTED_OUTPUTS = {
    "reports/route_day.csv",
    "reports/route_summary.json",
    "reports/dashboard.html",
    "reports/styles.css",
    "reports/quality_report.json",
}


def proof_import_scope_valid(manifest: dict) -> bool:
    """Allow only standard imports or hash-listed local modules in this proof package."""
    files = manifest.get("files", {})
    if not isinstance(files, dict):
        return False
    local_modules = {
        PurePosixPath(path).stem for path in files
        if isinstance(path, str) and path.casefold().endswith(".py")
        and PurePosixPath(path).stem.isidentifier()
        and PurePosixPath(path).stem not in sys.stdlib_module_names
    }
    allowed = SAFE_IMPORTS | local_modules
    stages = manifest.get("stages", [])
    capabilities = manifest.get("capabilities", {})
    dependencies = manifest.get("dependencies", {})
    return (set(capabilities.get("imports", [])) <= allowed
            and all(set(stage.get("imports", [])) <= allowed for stage in stages)
            and set(dependencies.get("modules", [])) <= allowed)


def proof_description_is_synthetic(manifest: dict) -> bool:
    """Conservatively screen wording; this check alone does not prove provenance."""
    description = manifest.get("description", "")
    if not isinstance(description, str):
        return False
    text = description.casefold()
    positive_claims = ("synthetic data", "invented data", "fictional data",
                       "entirely synthetic", "entirely invented", "fully synthetic",
                       "fully invented", "purely synthetic", "purely invented")
    conflicting_claim = re.compile(
        r"\b(?:no|not|never|without|avoid|exclude|don't|doesn't|didn't|can't|cannot|"
        r"shouldn't|wouldn't|couldn't|won't|mustn't)\b"
        r".{0,32}\b(?:synthetic|invented|fictional)\b"
        r"|\b(?:synthetic|invented|fictional)\s+data\b.{0,40}\b"
        r"(?:(?:is|are|was|were|do|does|did|should|would|could|will|shall|must)\s+(?:not|never)|"
        r"(?:is|are|was|were|do|does|did|should|would|could|will|shall|must)n['’]t|can't|cannot)\s+"
        r"(?:be\s+)?(?:used|included|present|generated|provided|created)\b"
        r"|\bnon[- ]?(?:synthetic|invented|fictional)\b"
        r"|\b(?:customer|client|passenger|live|production|historical?|operational|actual|"
        r"real(?:[- ]world)?|genuine|authentic|source|derived|account|feed|records?|"
        r"logs?|measurements?|observations?)\b")
    return (any(phrase in text for phrase in positive_claims)
            and not conflicting_claim.search(text))


def latest_package_run_was_denied(calls: dict) -> bool:
    """Tell a harness-only approval denial from a captured package-stage failure."""
    if not isinstance(calls, dict):
        return False
    for record in reversed(list(calls.values())):
        if not isinstance(record, dict) or record.get("request", {}).get("name") != "automation.run":
            continue
        result = record.get("result", {})
        return (isinstance(result, dict)
                and result.get("error", {}).get("code") in {
                    "approval_denied", "package_review_required", "package_review_failed"})
    return False


def should_recover_denied_run_plan(calls: dict, recovery_request_id: str | None,
                                   pending_submission: dict | None) -> bool:
    """Recover an old proof denial only when it is still the latest unresolved run."""
    return (recovery_request_id is None and pending_submission is None
            and latest_package_run_was_denied(calls))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def extract_call(preview: dict) -> tuple[dict, list[dict]]:
    plan = preview.get("complete_pending_plan", {})
    calls = plan.get("tool_requests", [])
    current = next((item for item in calls if item.get("call_id") == preview.get("current_call_id")), None)
    return current or {}, calls


def package_archive_was_executed(calls: dict, expected_hash: str) -> bool:
    """Return whether these immutable ZIP bytes already started a local run."""
    if not isinstance(calls, dict):
        return False
    for record in calls.values():
        if not isinstance(record, dict) or record.get("request", {}).get("name") != "automation.run":
            continue
        arguments = record.get("request", {}).get("arguments", {})
        if arguments.get("expected_sha256") != expected_hash:
            continue
        result = record.get("result", {})
        if isinstance(result, dict) and result.get("error", {}).get("code") in {
                "approval_denied", "package_review_required", "package_review_failed"}:
            continue
        run_result = result.get("result", {}) if isinstance(result, dict) else {}
        if isinstance(run_result, dict) and run_result.get("status") == "not_started":
            continue
        return True
    return False


def latest_failed_proof_run_state(workspace: Path) -> dict | None:
    """Recover the latest failed proof checkpoint without opening package files."""
    runs_root = (workspace / "runs").resolve()
    if not runs_root.is_dir():
        return None
    candidates = sorted((item / "state.json" for item in runs_root.iterdir()
                         if item.is_dir() and (item / "state.json").is_file()),
                        key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    path = candidates[0].resolve()
    try:
        path.relative_to(runs_root)
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if state.get("status") not in {"failed", "partial"}:
        return None
    stages = state.get("stages", {})
    if not isinstance(stages, dict) or not any(
            isinstance(record, dict) and record.get("status") == "failed"
            for record in stages.values()):
        return None
    return {"state_path": str(path), "archive_sha256": state.get("archive_sha256"),
            "run_id": state.get("run_id"), "status": state.get("status")}


def recover_denied_run_plan(config, acceptance_dir: Path, current_directory: Path) -> dict | None:
    """Recover the latest reviewed archive denied by the proof harness before it started."""
    delivery_root = (config.storage_dir / "deliveries").resolve()
    workspace_root = (config.workspace_dir / "live-package-proof").resolve()
    candidates = sorted((path for path in acceptance_dir.iterdir()
                         if path.is_dir() and path != current_directory
                         and path.name.startswith("package-run-") and (path / "report.json").is_file()),
                        key=lambda path: path.name, reverse=True)
    for path in candidates:
        try:
            previous = json.loads((path / "report.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        run_decisions = [item for item in previous.get("decisions", [])
                         if item.get("tool") == "automation.run"]
        if not run_decisions:
            continue
        # Never resurrect a denial from an older proof after a newer run was approved or executed.
        if run_decisions[-1].get("decision") != "deny":
            return None
        reviews = [item for item in previous.get("reviews", [])
                   if item.get("status") == "passed" and not item.get("failures")
                   and isinstance(item.get("archive_sha256"), str)]
        denied = [item for item in previous.get("all_calls", {}).values()
                  if item.get("request", {}).get("name") == "automation.run"
                  and item.get("result", {}).get("error", {}).get("code") == "approval_denied"]
        for record in reversed(denied):
            arguments = record.get("request", {}).get("arguments", {})
            archive = Path(arguments.get("archive_path", "")).expanduser().resolve()
            workspace = Path(arguments.get("workspace", "")).expanduser().resolve()
            expected = arguments.get("expected_sha256")
            if not isinstance(expected, str) or not any(item["archive_sha256"] == expected for item in reviews):
                continue
            try:
                archive.relative_to(delivery_root)
                workspace.relative_to(workspace_root)
            except ValueError:
                continue
            if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
                continue
            try:
                with zipfile.ZipFile(archive) as package:
                    manifest = json.loads(package.read("manifest.json").decode("utf-8"))
            except (OSError, KeyError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile):
                continue
            declared_outputs = manifest.get("expected_outputs", [])
            if not isinstance(declared_outputs, list) or not all(isinstance(item, str) for item in declared_outputs):
                continue
            return {"archive_path": archive, "archive_sha256": expected, "workspace": workspace,
                    "declared_outputs": declared_outputs,
                    "outputs_match_request": set(declared_outputs) == EXPECTED_OUTPUTS,
                    "prior_report": previous.get("directory")}
        # Older in-progress reports may not yet contain their final call/review tables.
        # Recover only a fresh, fully passing ZIP created after that report began.
        try:
            started_at = datetime.fromisoformat(str(previous.get("started_at", "")).replace("Z", "+00:00"))
            workspace = Path(previous.get("workspace", "")).expanduser().resolve()
            workspace.relative_to(workspace_root)
        except (TypeError, ValueError):
            return None
        for archive in sorted(delivery_root.rglob(PACKAGE_PREFIX + "*.zip"),
                              key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                archive.relative_to(delivery_root)
                if archive.stat().st_mtime < started_at.timestamp():
                    continue
                expected = hashlib.sha256(archive.read_bytes()).hexdigest()
                inspection = inspect_package(archive, expected)
                manifest = inspection.get("manifest", {})
                review = inspection.get("review", {})
                declared_outputs = manifest.get("expected_outputs", [])
                if (inspection.get("status") != "validated" or review.get("status") != "passed"
                        or review.get("failures") or not isinstance(declared_outputs, list)
                        or not all(isinstance(item, str) for item in declared_outputs)):
                    continue
                return {"archive_path": archive, "archive_sha256": expected, "workspace": workspace,
                        "declared_outputs": declared_outputs,
                        "outputs_match_request": set(declared_outputs) == EXPECTED_OUTPUTS,
                        "prior_report": previous.get("directory"),
                        "review_recovered_from_delivery": True}
            except (OSError, ValueError, PackageReviewError, PackageError, zipfile.BadZipFile):
                continue
        return None
    return None


def proof_retry_instruction(plan: dict) -> str:
    """Recover from a harness-generated denial with a fresh, package-portable revision."""
    if plan["outputs_match_request"]:
        return f"""Continue the local Transit Reliability Observatory proof. The earlier v8 automation.run denial was emitted by a local proof-harness allowlist bug; the user did not deny execution and had already authorized this scoped proof. No package stage started.

Do not replay or re-deliver v8 (SHA-256 {plan['archive_sha256']}). Create a fresh v9 ZIP from the reviewed project with the same 4 stages and exact outputs: {json.dumps(sorted(EXPECTED_OUTPUTS))}. Make the stage scripts self-contained: inline the small shared common.py helpers into their consuming stages and remove that local-module import. The local Python worker resolves declared imports from its approved runtime; this change avoids depending on package-folder import lookup. Preserve all previous fixes, hashes, no-network scope, output limits, and the exact synthetic-only dataset requirements. Exclude __pycache__ and bytecode from the ZIP.

Run the package tests in Copilot's cloud sandbox. Deliver the fresh ZIP through one clickable link and request its download. The local orchestrator will automatically inspect the new fingerprint, show all findings, and only after a passing review request one automation.run in the original isolated workspace {plan['workspace']}. The user's existing scoped authorization covers this proof; the corrected callback accepts each distinct passing revision once. Do not claim local results before the observed run."""
    return f"""Continue the already authorized local Transit Reliability Observatory proof. The package safety review passed, but its exact report locations did not match the requested reports/ paths: the archive declares {json.dumps(plan['declared_outputs'])}, while the request requires {json.dumps(sorted(EXPECTED_OUTPUTS))}. This is a deliverable mismatch; no package stage ran.

Update the stage scripts, output declarations, capabilities and validations together so all five report files are written at the exact requested reports/ paths, without a project/ prefix: {json.dumps(sorted(EXPECTED_OUTPUTS))}. Keep package source files under their project/ folder and the README and manifest at the ZIP root. Run package tests in Copilot's cloud sandbox, create a fresh ZIP with updated payload hashes and request a download. The local orchestrator will inspect that revision and return every finding. After it passes, request one automation.run in the original isolated workspace {plan['workspace']}. Do not reuse the mismatched archive or claim unobserved results."""


def load_proof_config(path: Path) -> Config:
    """Accept the proof harness settings wrapper or a plain Config JSON file."""
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("config"), dict):
        config = Config.load(path)
        config._automation_test_mode = True
        config._s_storage_verified = False
        return config
    storage_dir = Path(payload.get("storage_dir", "")).expanduser().resolve()
    require(storage_dir.is_dir(), "The proof settings point to a missing isolated storage folder.")
    config = Config.load(storage_override=storage_dir)
    for name, value in payload["config"].items():
        if hasattr(config, name):
            setattr(config, name, value)
    key = machine_key()
    edge_executables = payload.get("edge_executables", {})
    debug_ports = payload.get("debug_ports", {})
    require(isinstance(edge_executables, dict) and isinstance(debug_ports, dict),
            "The proof settings have invalid per-machine Edge mappings.")
    executable = edge_executables.get(key)
    port = debug_ports.get(key)
    if executable is None and len(edge_executables) == 1:
        executable = next(iter(edge_executables.values()))
    if port is None and len(debug_ports) == 1:
        port = next(iter(debug_ports.values()))
    require(isinstance(executable, str) and Path(executable).is_file(),
            "The proof settings do not identify an available Edge executable for this machine.")
    require(type(port) is int and 1024 <= port <= 65535,
            "The proof settings do not identify a valid Edge debugging port for this machine.")
    config.edge_executable = executable
    config.debug_port = port
    config.attach_existing = False
    config.visible = True
    config._automation_test_mode = True
    config._s_storage_verified = False
    config.validate()
    return config


def proof_revision_allowed(limit: int | None, completed: int) -> bool:
    """The synthetic proof alone may request unlimited distinct ZIP revisions."""
    return limit is None or completed < limit


def parse_proof_revision_limit(value: str) -> int | None:
    if value.casefold() == "unlimited":
        return None
    try:
        limit = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("max-revisions must be positive or 'unlimited'") from error
    if limit < 1:
        raise argparse.ArgumentTypeError("max-revisions must be positive or 'unlimited'")
    return limit


def require_dedicated_existing_profile(config: Config, port: int) -> None:
    """An explicit proof port may attach only to the previously verified profile."""
    profile = Path(config.profile_dir).resolve()
    expected = (config.runtime_dir / "acceptance" /
                "package-run-20261013T111348Z-7f22f7bf" / "edge-profile").resolve()
    require(config.attach_existing and config.debug_port == port,
            "The requested dedicated Edge listener was not verified; no fallback port may be used.")
    try:
        in_proof = profile.samefile(expected)
    except OSError:
        in_proof = False
    require(in_proof,
            "The Edge listener is not the previously verified dedicated proof profile; refusing to attach.")


def validate_output_files(output_root: Path) -> dict:
    required = {output_root / name for name in EXPECTED_OUTPUTS}
    missing = sorted(str(path) for path in required if not path.is_file())
    require(not missing, "The live run did not create all five named dashboard outputs: " + ", ".join(missing))
    with (output_root / "reports/route_day.csv").open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) == 1008, f"The route-day file contains {len(rows)} records; expected 1,008.")
    keys = {(row.get("route_id"), row.get("service_date")) for row in rows}
    require(len(keys) == 1008, "The route-day file contains duplicate or incomplete route/date pairs.")
    require(len({key[0] for key in keys}) == 12, "The synthetic dataset does not contain exactly 12 routes.")
    require(len({key[1] for key in keys}) == 84, "The synthetic dataset does not contain exactly 84 service dates.")
    required_columns = {"route_id", "service_date", "scheduled_trips", "completed_trips",
                        "on_time_trips", "cancelled_trips", "average_delay_minutes"}
    require(required_columns <= set(rows[0]), "The route-day file is missing one or more agreed measures.")
    summary = json.loads((output_root / "reports/route_summary.json").read_text(encoding="utf-8"))
    require(summary.get("route_count") == 12 and summary.get("day_count") == 84
            and summary.get("route_day_rows") == 1008,
            "The summary does not report the expected route, date and row totals.")
    dashboard = (output_root / "reports/dashboard.html").read_text(encoding="utf-8")
    require("Transit Reliability Observatory" in dashboard and "route_day.csv" in dashboard,
            "The dashboard is missing its title or data reference.")
    styles = (output_root / "reports/styles.css").read_text(encoding="utf-8")
    require(bool(styles.strip()), "The dashboard stylesheet is empty.")
    quality = json.loads((output_root / "reports/quality_report.json").read_text(encoding="utf-8"))
    require(quality.get("status") == "passed", "The package's own quality report did not pass.")
    return {"status": "passed", "route_day_rows": len(rows), "unique_route_days": len(keys),
            "routes": 12, "service_dates": 84, "required_outputs": sorted(str(path) for path in required),
            "summary_totals": {"route_count": summary["route_count"], "day_count": summary["day_count"],
                               "route_day_rows": summary["route_day_rows"]},
            "package_quality_report": quality.get("status")}


async def run(args) -> int:
    if not args.live:
        raise SystemExit("Explicit --live is required; this harness opens the real Copilot UI and runs one scoped synthetic ZIP.")
    config = load_proof_config(args.config)
    if args.existing_edge_port is not None:
        require(1024 <= args.existing_edge_port <= 65535,
                "The requested existing Edge port must be a valid local debugging port.")
        config.debug_port = args.existing_edge_port
    require(config.storage_dir is not None, "A dedicated isolated proof storage folder is required.")
    require("proof-runs" in {part.casefold() for part in config.storage_dir.parts},
            "The selected storage folder is not inside runtime/proof-runs.")
    require(not config.created_sync_enabled, "Created-folder synchronization must remain disabled for this proof.")
    config._automation_test_mode = True

    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    directory = config.runtime_dir / "acceptance" / ("package-run-" + token)
    directory.mkdir(parents=True, exist_ok=False)
    report_path = directory / "report.json"
    session_dir = (args.resume_session.expanduser().resolve() if args.resume_session
                   else directory / "session")
    if args.resume_session:
        require(session_dir.is_relative_to(config.runtime_dir.resolve()),
                "The recovery session must remain inside the isolated proof runtime.")
    workspace = config.workspace_dir / "live-package-proof" / token
    deliveries = (config.storage_dir / "deliveries").resolve()
    report = {"status": "incomplete", "started_at": datetime.now(timezone.utc).isoformat(),
              "mode": "real Copilot UI; local synthetic package review and run; outside VDI",
              "directory": str(directory), "requested_package": PACKAGE_NAME,
              "workspace": str(workspace),
              "model_requested": args.model or config.model, "package_run_started": False,
              "authorization": "User-authorized scoped proof: one synthetic package, exact passing ZIP review, no network, no existing-file changes, outputs only under this isolated workspace.",
              "limits": {"max_downloads": args.max_revisions, "max_stages": 8, "max_stage_seconds": 30,
                         "safe_imports": sorted(SAFE_IMPORTS)},
              "decisions": [], "reviews": [], "steps": [], "limitations": [
                  "No VDI or S: live environment was accessed or tested.",
                  "Package execution is through the installed local Python worker and its declared file permissions; no shell or subprocess capability is authorized."]}

    def save() -> None:
        write_json(report_path, redact(report))

    def display(message) -> None:
        print(redact(str(message)), flush=True)

    proof_settings = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    browser = None
    state = None
    engine = None
    download_count = 0
    run_count = 0
    approved_archive: dict | None = None

    def archive_already_ran(expected_hash: str) -> bool:
        """Permit a failed proof to continue with a fresh reviewed ZIP, never replay the same bytes."""
        return bool(state and package_archive_was_executed(state.data.get("calls", {}), expected_hash))

    async def decide(preview: dict) -> str:
        nonlocal download_count, run_count, approved_archive
        call, calls = extract_call(preview)
        prepared = preview.get("prepared_code") or {}
        accepted = False
        reason = "Outside the isolated package proof scope"
        if (len(calls) == 1 and call.get("name") == "copilot.download"
                and proof_revision_allowed(args.max_revisions, download_count)):
            arguments = call.get("arguments", {})
            name = arguments.get("expected_name")
            destination = Path(prepared.get("destination", "")).resolve()
            try:
                destination.relative_to(deliveries)
                in_delivery = True
            except ValueError:
                in_delivery = False
            if (isinstance(name, str) and name.startswith(PACKAGE_PREFIX) and name.endswith(".zip")
                    and Path(name).name == name and in_delivery):
                accepted = True
                download_count += 1
                reason = "One actual Copilot ZIP link downloaded to the isolated proof deliveries folder"
        elif (len(calls) == 1 and call.get("name") == "automation.run"
              and proof_revision_allowed(args.max_revisions, run_count)):
            arguments = call.get("arguments", {})
            inspection = prepared.get("inspection", {})
            review = inspection.get("review", {})
            manifest = inspection.get("manifest", {})
            capabilities = manifest.get("capabilities", {})
            stages = manifest.get("stages", [])
            archive_path = Path(arguments.get("archive_path", "")).resolve()
            expected_hash = arguments.get("expected_sha256")
            not_previously_run = isinstance(expected_hash, str) and not archive_already_ran(expected_hash)
            try:
                archive_path.relative_to(deliveries)
                in_delivery = True
            except ValueError:
                in_delivery = False
            imports_ok = proof_import_scope_valid(manifest)
            stages_ok = (4 <= len(stages) <= 8
                         and all(stage.get("kind") == "python"
                                 and stage.get("timeout_seconds", 999) <= 30
                                 and stage.get("retries", 999) <= 1
                                 and stage.get("network_destinations", []) == []
                                 and set(stage.get("permissions", [])) <= {"read_files", "create_files"}
                                 for stage in stages))
            declared_scope_ok = (capabilities.get("network_destinations", []) == []
                                 and capabilities.get("modify_paths", []) == []
                                 and set(capabilities.get("permissions", [])) <= {"read_files", "create_files"}
                                 and manifest.get("tools", []) == []
                                 and manifest.get("package_id", "").casefold().startswith("transit")
                                 and proof_description_is_synthetic(manifest))
            limits_ok = (capabilities.get("max_runtime_seconds", 999999) <= 180
                         and capabilities.get("max_output_chars", 999999) <= 12000
                         and capabilities.get("max_concurrency", 999) <= 4
                         and len(manifest.get("expected_outputs", [])) <= 20)
            if (inspection.get("status") == "validated" and review.get("status") == "passed"
                    and not review.get("failures") and expected_hash == inspection.get("archive_sha256")
                    and in_delivery and archive_path.is_file()
                    and archive_path == Path(inspection.get("archive", "")).resolve()
                    and Path(arguments.get("workspace", "")).resolve() == workspace.resolve()
                    and not_previously_run
                    and imports_ok and stages_ok and declared_scope_ok and limits_ok
                    and EXPECTED_OUTPUTS <= set(manifest.get("expected_outputs", []))):
                accepted = True
                run_count += 1
                approved_archive = {"path": str(archive_path), "sha256": expected_hash,
                                    "package_id": manifest["package_id"], "stage_count": len(stages)}
                report["package_run_started"] = True
                reason = "Scoped one-time authorization: exact passing ZIP, synthetic package only, no network, create-only outputs in the isolated workspace"
            else:
                reason = ("Denied: this exact ZIP already ran; a fresh reviewed revision is required"
                          if not not_previously_run else
                          "Denied: package review or isolated synthetic-only scope did not match the proof authorization")
        decision_record = {"tool": call.get("name"), "decision": "once" if accepted else "deny",
                           "reason": reason, "current_call_id": preview.get("current_call_id")}
        if call.get("name") == "automation.run":
            arguments = call.get("arguments", {})
            inspection = prepared.get("inspection", {})
            review = inspection.get("review", {}) if isinstance(inspection, dict) else {}
            decision_record.update({
                "archive_path": arguments.get("archive_path"),
                "archive_sha256": arguments.get("expected_sha256"),
                "workspace": arguments.get("workspace"),
                "review_status": review.get("status") if isinstance(review, dict) else None,
                "review_failures": review.get("failures", []) if isinstance(review, dict) else [],
                "expected_outputs": inspection.get("manifest", {}).get("expected_outputs", [])
                if isinstance(inspection, dict) else [],
            })
        report["decisions"].append(decision_record)
        save()
        return "once" if accepted else "deny"

    try:
        await choose_browser_endpoint(
            config, SimpleNamespace(port=args.existing_edge_port or config.debug_port), proof_settings)
        if args.existing_edge_port is not None:
            require_dedicated_existing_profile(config, args.existing_edge_port)
            config._proof_exact_edge_endpoint = (args.existing_edge_port,
                                                 str(Path(config.profile_dir).resolve()))
        report["edge_endpoint"] = {"port": config.debug_port,
                                   "attached_to_verified_session": config.attach_existing,
                                   "profile": str(config.profile_dir)}
        browser = BrowserAdapter(config)
        state = SessionState(session_dir, resume=bool(args.resume_session))
        resume_existing = bool(args.resume_session)
        pending_submission = state.data.get("pending_submission") if resume_existing else None
        stored_workspace = state.data.get("proof_package_workspace") if resume_existing else None
        if stored_workspace:
            workspace = Path(stored_workspace).expanduser().resolve()
            workspace_root = (config.workspace_dir / "live-package-proof").resolve()
            try:
                workspace.relative_to(workspace_root)
            except ValueError as error:
                raise RuntimeError("The saved proof workspace is outside the isolated proof directory.") from error
            report["workspace"] = str(workspace)
        recovery_request_id = (recoverable_capture_request_id(state)
                               if resume_existing and not pending_submission else None)
        if (resume_existing and state.data.get("package_run_failure_call_id")
                and not state.data.get("package_run_failure_state_path")):
            recovered_state = latest_failed_proof_run_state(workspace)
            if recovered_state:
                state.data["package_run_failure_state_path"] = recovered_state["state_path"]
                state.data["package_run_failure_archive_sha256"] = recovered_state["archive_sha256"]
                state.save()
        package_failure_pending = bool(state.data.get("package_run_failure_state_path"))
        prior_run_plan = (recover_denied_run_plan(config, config.runtime_dir / "acceptance", directory)
                          if resume_existing and should_recover_denied_run_plan(
                              state.data.get("calls", {}), recovery_request_id, pending_submission) else None)
        if prior_run_plan and not recovery_request_id:
            workspace = prior_run_plan["workspace"]
            report["workspace"] = str(workspace)
            state.data["proof_package_workspace"] = str(workspace)
            state.save()
        resume_package_turn = bool(resume_existing and (
            state.message_count > 1
            or isinstance(pending_submission, dict) and pending_submission.get("ordinal", 0) > 2))
        if resume_existing:
            require(recovery_request_id is not None or isinstance(pending_submission, dict)
                    or prior_run_plan is not None or package_failure_pending,
                    "The requested recovery session has no safely recoverable response, pending draft, or reviewed proof retry.")
        save()
        await browser.start(resume_request_id=(recovery_request_id or
                                               latest_committed_request_id(state) if resume_existing else None))
        models = await browser.discover_models()
        enabled = [item for item in models if item.get("enabled", True)]
        model = args.model or config.model
        if not any(item["label"] == model for item in enabled):
            from copilot_agent.browser import model_rank
            ranked = model_rank(enabled)
            require(bool(ranked), "No enabled Copilot model is available in this account.")
            model = ranked[0]["label"]
        report["models_discovered"] = models
        report["model_selected"] = model
        await browser.select_model(model)
        config._proof_file_workspace = str(workspace.resolve())
        engine = Orchestrator(config, browser, ToolRegistry(), state,
                              approval_decider=decide, display=display)
        engine.initialized = resume_existing
        engine.prompts.verify_guidance()
        report["startup_documents"] = [{"name": path.name,
                                         "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest()}
                                        for path in engine.prompts.initial_attachments()]
        recovered_final = None
        if prior_run_plan:
            display("Continuing after fixing the saved proof workspace mismatch. The previously reviewed ZIP remains unchanged.")
            if prior_run_plan["outputs_match_request"]:
                display("The archive also declares the exact five requested report paths; continuing with the same reviewed ZIP.")
                retry_instruction = f"""Continue the already authorized local Transit Reliability Observatory proof. The prior ZIP passed all local inspection checks, but the local run was denied because the resumed proof harness compared Copilot's original workspace with a newly generated one. The harness now uses the exact original workspace again. No package stage ran, and no ZIP or review needs to be rebuilt.

Request exactly one automation.run for this exact archive path: {prior_run_plan['archive_path']}
Use SHA-256 {prior_run_plan['archive_sha256']} and workspace {prior_run_plan['workspace']}.
All other scope remains unchanged: execute only the exact reviewed synthetic package once and report its real results. Do not download, rebuild or claim unobserved results."""
            else:
                report["proof_checks"] = [{"name": "Requested report file locations", "status": "failed",
                                           "expected": sorted(EXPECTED_OUTPUTS),
                                           "found": sorted(prior_run_plan["declared_outputs"]),
                                           "explanation": "The package safety review passed, but this package writes reports under a project/ folder instead of the exact reports/ locations requested."}]
                save()
                display("The ZIP passed its safety review, but the requested report files were nested under project/ instead of reports/. No package code ran; asking Copilot to correct those five output locations before a new download and review.")
                retry_instruction = f"""Continue the already authorized Transit Reliability Observatory proof. The local package safety review passed, but the proof-specific output-location check failed: the ZIP declares {json.dumps(prior_run_plan['declared_outputs'])}, while the request requires exactly {json.dumps(sorted(EXPECTED_OUTPUTS))} relative to the run's outputs folder. This is a deliverable mismatch, not a safety failure. No local package stage ran.

Update the stage scripts, output declarations, capabilities and validations together so all five report files are written at the exact requested reports/ paths, without a project/ prefix: {json.dumps(sorted(EXPECTED_OUTPUTS))}. Keep package source files safely under their project/ folder and keep the README and manifest at the ZIP root. Run the package tests in your cloud sandbox, then create a fresh ZIP with updated payload hashes and request one download. The local orchestrator will inspect that exact new revision and return every finding. After it passes, request one automation.run in the original isolated workspace {prior_run_plan['workspace']}. Do not reuse the mismatched archive, and do not claim local results until they are observed."""
            recovered_final = await engine.turn(proof_retry_instruction(prior_run_plan))
            initialized = {"completion_status": "complete"}
        elif pending_submission:
            pending_id = pending_submission.get("request_id")
            pending_hash = pending_submission.get("text_hash")
            draft = await browser.read_reconciled_draft(pending_id, pending_hash)
            state.reconcile_submission(False)
            state.data["status"] = "ready"
            state.save()
            display("Confirmed the exact pending Copilot follow-up was still an unsent draft. Reusing that draft once.")
            state.begin_submission(pending_id, draft)
            state.data["status"] = "submitting"
            state.save()

            def commit_reconciled_draft():
                state.confirm_submission(pending_id)

            try:
                raw = await browser.exchange(draft, pending_id, on_submitted=commit_reconciled_draft)
            except SubmissionNotSentError:
                state.reconcile_submission(False)
                state.data["status"] = "blocked"
                state.save()
                raise
            except SubmissionAmbiguousError:
                state.data["status"] = "submission_uncertain"
                state.event("submission_uncertain", request_id=pending_id)
                state.save()
                raise
            except CaptureTimeoutError:
                state.data["status"] = "capture_failed"
                state.event("capture_failed", request_id=pending_id)
                state.save()
                raise
            state.event("committed_response_recovered", request_id=pending_id,
                        response_length=len(raw), capture_method="verified_unsent_draft")
            recovered_final = await engine.turn(
                "Continue from the response to the exact already committed Copilot instruction. Do not resend the original package task.",
                recovered_response=(raw, pending_id))
            initialized = {"completion_status": "complete"}
        elif resume_existing and package_failure_pending and not recovery_request_id:
            failed_package = engine._recovered_package_run_failure()
            require(failed_package is not None,
                    "The retained package-run failure could not be verified inside the proof workspace.")
            repair = engine._package_run_repair_instruction([failed_package])
            require(bool(repair), "The retained package-run failure has no actionable stage details.")
            if "WinError 267" in repair:
                repair += ("\n\nThe local runner's Windows long-path startup issue has now been corrected and its focused regression passed. "
                           "To continue this proof without changing the package's behavior, create a fresh ZIP revision from the same tested project, update only the package version and integrity hashes, and deliver that ZIP. "
                           "The local orchestrator will review and run the new fingerprint in the same isolated workspace.")
            display("Returning the retained local run failure to Copilot automatically; the original package request will not be resent.")
            recovered_final = await engine.turn(
                "Continue the active package-delivery workflow using the retained local run failure below. Do not ask the user to inspect files or write a repair request.\n\n" + repair)
            initialized = {"completion_status": "complete"}
        elif resume_existing:
            display("Recovering the committed Copilot response from the existing chat without resending it.")
            recovered_final = await engine.recover_capture_failed_turn()
            initialized = {"completion_status": "complete"}
        else:
            initialized = await engine.initialize()
        require(initialized.get("completion_status") == "complete" and state.message_count >= 1,
                "The Copilot response could not be recovered cleanly.")
        report["steps"].append({"name": "Copilot UI initialization", "status": "passed"})

        request = f"""Build a complete, polished synthetic Transit Reliability Observatory as one downloadable automation package ZIP named {PACKAGE_NAME}. The project must be substantial enough to exercise the package workflow: include at least 8 useful project files, at least 4 dependency-ordered Python stages with checkpoints, a README, exact SHA-256 hashes for every payload file, the required manifest, explicit output/capability declarations, bounded resource limits, and a structured result contract.

Use entirely invented data. Generate exactly 1,008 unique route-day records for 12 fictional routes over 84 service dates. Produce these five local outputs with these exact relative paths: reports/route_day.csv, reports/route_summary.json, reports/dashboard.html, reports/styles.css, and reports/quality_report.json. The CSV must have route_id, service_date, scheduled_trips, completed_trips, on_time_trips, cancelled_trips, and average_delay_minutes. The JSON summary must report route_count=12, day_count=84, and route_day_rows=1008. The HTML must be titled Transit Reliability Observatory and reference the route-day dataset. The quality report must have status=passed after checking row count, unique route/date pairs, 12 routes, and 84 dates.

Use only ordinary, explicitly declared Python standard-library imports. Do not use dunder/reflection tricks to obtain imports or paths. For every Python stage, the local runner passes the run-specific approved output folder as the final stage argument: `output_root = Path(sys.argv[-1])`. Construct every declared output from that exact folder, including nested reports/ paths. Do not infer outputs from the working directory, package extraction directory, or folders that happen to exist, and do not inspect sibling run folders. Keep each stage at or below 30 seconds and the whole package within a 180-second runtime budget. No external network, customer or live data, credentials, shell commands, subprocesses, deletion, or changes to existing files. Keep all package-owned intermediate and final outputs within the approved output folder, with every stage output declared in the manifest. Run relevant build and package tests in Copilot's cloud sandbox, then report what passed. No live environment test is needed.

In `manifest.capabilities.read_paths`, list every package file that any stage reads or imports; every stage input must be included there. Prefer self-contained stage scripts that import only standard-library modules, so package-local helpers do not become undeclared inputs. Cloud tests may create `__pycache__` and `.pyc` files: exclude them from the archive and verify that the ZIP contains only `manifest.json` and payload files explicitly listed and hash-bound by that manifest.

First response: include one actual clickable ZIP download link after the END marker and request exactly one copilot.download for that same link. Do not request local extraction, local file creation, or automation.run yet. The local orchestrator automatically inspects the downloaded ZIP and will return every check and any failures together. Fix all findings in one rebuilt ZIP. Once the local inspection has passed, request exactly one automation.run using the actual archive path and SHA-256 from the review result, with workspace {workspace}. After the actual local run, report its real stage and validation results. Do not request a duplicate review or download after a passing review."""
        if prior_run_plan:
            final = recovered_final
        elif resume_package_turn:
            display("Continuing from the already submitted package request; it will not be sent again.")
            final = recovered_final
        else:
            final = await engine.turn(request)
        report["task_response"] = final
        calls = list(state.data.get("calls", {}).values())
        for record in calls:
            call_name = record.get("request", {}).get("name")
            result = record.get("result", {})
            payload = result.get("result", {}) if isinstance(result, dict) else {}
            if call_name == "automation.inspect":
                review = payload.get("review", {})
                report["reviews"].append({"status": review.get("status", payload.get("status")),
                                          "summary": review.get("summary"),
                                          "archive_sha256": review.get("archive_sha256") or payload.get("archive_sha256"),
                                          "checks": review.get("checks", []),
                                          "failures": review.get("failures", []),
                                          "not_checked_count": review.get("not_checked_count")})
            elif call_name == "automation.run":
                report["package_run"] = redact(result)
            elif call_name == "copilot.download":
                report.setdefault("downloads", []).append(redact(payload))

        run_result = report.get("package_run", {}).get("result", {})
        require(run_result.get("status") == "completed", "Copilot did not complete one locally approved package run.")
        require(run_result.get("archive_sha256") == (approved_archive or {}).get("sha256"),
                "The executed ZIP does not match the exact authorized review fingerprint.")
        require(run_result.get("validation", {}).get("ok") is True,
                "The package runner's output validation did not pass.")
        require(not run_result.get("failed_stages"), "One or more package stages failed.")
        acceptance = validate_output_files(Path(run_result["output_root"]))
        require(final.get("completion_status") == "complete", "Copilot did not acknowledge the observed successful package run.")
        report["steps"].extend([
            {"name": "automatic local ZIP inspection", "status": "passed",
             "review_revisions": len(report["reviews"])},
            {"name": "exact reviewed package run", "status": "passed",
             "archive_sha256": run_result["archive_sha256"],
             "completed_stages": run_result.get("completed_stages"),
             "validation": run_result.get("validation")},
            {"name": "local synthetic dashboard output inspection", "status": "passed", **acceptance},
        ])
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "blocked"
        report["steps"].append({"name": "live package proof", "status": "blocked", "error": str(error)})
        print("LIVE_PACKAGE_RUN_BLOCKED: " + redact(str(error)), flush=True)
    finally:
        if state is not None:
            report["message_count"] = state.message_count
            report["all_calls"] = redact(state.data.get("calls", {}))
            report["session_status"] = state.data.get("status")
        try:
            if browser and browser.page and not browser.page.is_closed():
                screenshot = directory / "masked-final.png"
                await browser.page.screenshot(
                    path=str(screenshot), full_page=False, timeout=10000,
                    mask=[browser.page.locator('nav,aside,header,[role="navigation"],[data-testid*="sidebar" i],button[aria-label*="account" i]')])
                report["masked_screenshot"] = str(screenshot)
        except Exception as error:
            report.setdefault("limitations", []).append("Masked screenshot unavailable: " + str(error))
        try:
            if engine is not None:
                await engine.close()
            elif browser is not None:
                await browser.close()
        except Exception as error:
            report.setdefault("limitations", []).append("Owned browser cleanup failed: " + str(error))
            report["status"] = "blocked"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
        print("LIVE_PACKAGE_RUN_REPORT: " + str(report_path), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model", help="Exact enabled UI model; otherwise use the configured model or highest ranked enabled model")
    parser.add_argument("--max-revisions", type=parse_proof_revision_limit, default=DEFAULT_PROOF_REVISIONS,
                        help="Synthetic proof only: positive revision limit or 'unlimited'; default 4")
    parser.add_argument("--existing-edge-port", type=int,
                        help="Attach only after the local Edge listener and its dedicated profile are verified")
    parser.add_argument("--resume-session", type=Path,
                        help="Recover an existing committed turn inside the isolated proof runtime without resending it")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))
