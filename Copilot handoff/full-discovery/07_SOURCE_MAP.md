# Source map

All paths below are relative to `Scripts and projects/Copilot Local Agent`.

## Primary runtime

| Path | Important symbols / role |
|---|---|
| `app.py` | Thin launcher to `copilot_agent.app.main`. |
| `copilot_agent/app.py` | `run`, `choose_browser_endpoint`, `start_new_session`, `main`; interactive lifecycle. |
| `copilot_agent/orchestrator.py` | `Orchestrator`; conversation, dispatch, approvals, retries, findings, terminal states. |
| `copilot_agent/browser.py` | `BrowserAdapter`; UI lifecycle, model selection, upload/send/capture/diagnostics. |
| `copilot_agent/reused_browser.py` | `find_edge_executable`, `validate_endpoint`, `validate_profile_ownership`, `launch_edge`, `connect_bounded`. |
| `copilot_agent/config.py` | `Config`, `documents_directory`; validated runtime settings. |
| `copilot_agent/protocol.py` | `parse_response`, `validate_schema`, `ProtocolError`, `correction_message`. |
| `copilot_agent/state.py` | `SessionState`, `canonical_hash`; state snapshots and hashes. |
| `copilot_agent/persistence.py` | `write_json`, `write_preserving`; atomic/versioned writes. |
| `copilot_agent/policy.py` | `PathPolicy`, `URLPolicy`, `PolicyError`, `config_value`. |
| `copilot_agent/tools.py` | `ToolRegistry`, `definitions`, `execute`, `configured_path_policy`; tool catalogue and effects. |
| `copilot_agent/approvals.py` | `ApprovalManager`; once/plan decisions and previews. |

## Context, files, and findings

| Path | Important symbols / role |
|---|---|
| `copilot_agent/prompts.py` | `PromptBuilder`; startup/context/correction prompts and reference manifest. |
| `copilot_agent/bundle.py` | `build_bundle`, `build_startup_attachments`, `read_bundle_components`; exact-byte grouping and verification. |
| `copilot_agent/attachments.py` | `AttachmentQueue`, `upload_name`; user-file validation and ten-file cap. |
| `copilot_agent/findings.py` | `Findings`; immediate filtering, deduplication, persistence, cumulative Markdown. |
| `copilot_agent/feedback.py` | `Feedback`, `public_preview`; attributed terminal output and safe previews. |
| `copilot_agent/logging_utils.py` | `redact`, `EventLog`; redacted event retention. |
| `copilot_agent/diagnostics.py` | `DiagnosticReports`; separate internal/sanitized bug reports and source-origin recommendations. |
| `copilot_agent/storage.py` | OneDrive discovery, machine keys, selected settings and shared Python candidates. |
| `copilot_agent/sync.py` | `CreatedSync`, `snapshot`; bounded stable-file polling. |
| `copilot_agent/file_picker.py` | `select_files`; native picker and supported file filters. |

## Execution, delivery, and desktop

| Path | Important symbols / role |
|---|---|
| `copilot_agent/code_runner.py` | `CodeRunner`; restricted subset, proposal normalization, hash binding. |
| `copilot_agent/local_python_runner.py` | `runtime_binding`, `ManagedProcessRegistry`, `execute_local_python`; bounded approved host process. |
| `copilot_agent/local_python_worker.py` | `main`, audit hooks, declared-scope enforcement, bounded worker. |
| `copilot_agent/delivery.py` | `DeliveryRequirements`, `detect_requirements`, retry/delivery instructions. |
| `copilot_agent/downloads.py` | `DownloadService`, `validate_download_args`; actual anchor/event/hash-bound downloads. |
| `copilot_agent/archives.py` | `ArchiveService`, `inspect_zip`, `verify_delivered_file`, `extract_zip`; safe archive processing. |
| `copilot_agent/desktop.py` | `enumerate_displays`, `capture_display`, `launch_viewers`, `inspect_windows`. |
| `copilot_agent/image_viewer.py` | Small managed image viewer entry point. |

## Contracts and operational files

| Path | Role |
|---|---|
| `schemas/response-v1.schema.json` | Response JSON schema. |
| `schemas/tool-catalogue-v1.json` | Machine-readable tool definitions and examples. |
| `guidance/01-copilot-orchestrator-contract.md` through `09-testing-acceptance.md` | Behavioral, protocol, security, recovery, memory, delivery, and acceptance contracts. |
| `Launcher.ps1` | Shared Python/environment/resource discovery and Setup/Start/Tests modes. |
| `requirements.txt`, `requirements.lock.txt` | Dependency declaration and exact lock. |
| `config.example.json` | Safe configuration template. |
| `docs/ARCHITECTURE.md`, `THREAT_MODEL.md`, `TEST_REPORT.md`, `VISUAL_ACCEPTANCE.md`, `KNOWN_LIMITATIONS.md` | Design, security, evidence, acceptance, and limits. |

## Tests

`tests/test_diagnostics.py` and `tests/test_bug_handoff.py` cover diagnostic safety and quiet session continuation. `tests/test_orchestrator.py`, `test_browser.py`, `test_protocol_state.py`, `test_code_runner.py`, `test_tools.py`, `test_attachments.py`, `test_bundle.py`, `test_downloads.py`, `test_delivery*.py`, `test_archives.py`, `test_edge_startup.py`, `test_launcher.py`, `test_storage.py`, `test_sync.py`, `test_feedback.py`, `test_setup_resources.py`, and `test_app_*.py` cover the primary contracts. `tests/live_*.py` and `inspect_download_settings.py` are manual/live harnesses, not ordinary offline proof.

