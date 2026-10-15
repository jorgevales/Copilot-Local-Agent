# Code, interfaces, and relationship index

## Python source and symbol catalogue

This is a static AST inventory of the current source, not a verbatim code package. It lists source paths, direct imports, public top-level classes/functions, and public methods on key classes. Private implementation bodies are summarized rather than embedded.

### `agent_ui/runtime.py`

- Role: Thread-safe bridge from the local workspace to the existing agent runtime.
- Direct imports: `__future__`, `asyncio`, `collections`, `queue`, `re`, `threading`, `time`, `types`, `uuid`
- Public symbols: `class AgentRuntime; method names: __init__, _start_agent, _run_agent, submit, take_submitted_attachments, active_run_id, steer, complete_steering, poll_steering, _cancel_pending_steering_locked, _cancel_pending_steering, permission_context, permission_snapshot, manage_permission, action, _dispatch_actions, _emit, close`; `class PromptBroker; method names: __init__, ask, submit, submit_if_waiting, close`; `create_runtime(emit, request_approval)`; `main()`

### `agent_ui/tests/test_launch_ui.py`

- Role: Local Edge checks with a fake runtime; never starts Copilot or real tools.
- Direct imports: `agent_ui.workspace`, `http.server`, `pathlib`, `playwright.sync_api`, `secrets`, `threading`, `unittest`
- Public symbols: `class LaunchUITests(unittest.TestCase); 12 public methods`

### `agent_ui/tests/test_runtime.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `agent_ui.runtime`, `collections`, `threading`, `time`, `unittest`
- Public symbols: `class PromptBrokerTests(unittest.TestCase); 2 public methods`; `class RuntimeCancellationTests(unittest.TestCase); 1 public methods`

### `agent_ui/tests/test_uploads.py`

- Role: Local byte-ingestion tests; no browser, model, or Copilot connection.
- Direct imports: `agent_ui.uploads`, `base64`, `copilot_agent.attachments`, `pathlib`, `tempfile`, `unittest`
- Public symbols: `class UploadStoreTests(unittest.TestCase); 10 public methods`; `payload(name='review.py', content=b"print('safe review only')\n", **overrides)`

### `agent_ui/tests/test_workspace.py`

- Role: Synthetic local tests only; no real agent, browser automation or model call.
- Direct imports: `base64`, `http.client`, `http.server`, `importlib.util`, `json`, `pathlib`, `secrets`, `sys`, `tempfile`, `threading`, `time`, `unittest`, `unittest.mock`
- Public symbols: `class HTTPTests(unittest.TestCase); 12 public methods`; `class WorkspaceTests(unittest.TestCase); 9 public methods`

### `agent_ui/uploads.py`

- Role: Session-scoped ingestion for files uploaded through the local workspace UI.
- Direct imports: `__future__`, `base64`, `binascii`, `copilot_agent.attachments`, `copilot_agent.logging_utils`, `hashlib`, `io`, `os`, `pathlib`, `re`, `shutil`, `stat`, `tempfile`, `threading`, `uuid`, `zipfile`
- Public symbols: `_safe_name(value: object) -> str [private helper]`; `_validate_content(name: str, content: bytes) -> dict [private helper]`; `class UploadError(ValueError)`; `class UploadStore; 8 public methods`

### `agent_ui/workspace.py`

- Role: Local authenticated workspace. No model API, telemetry, or execution bypass.
- Direct imports: `__future__`, `agent_ui.uploads`, `argparse`, `hashlib`, `http.server`, `importlib`, `json`, `os`, `pathlib`, `secrets`, `threading`, `time`, `urllib.parse`, `uuid`, `webbrowser`
- Public symbols: `_public_file_metadata(value, in_file_collection=False) [private helper]`; `class Handler(BaseHTTPRequestHandler); method names: log_message, headers_common, reply, valid_host, authorized, do_GET, do_POST`; `class Workspace; method names: __init__, emit, request_approval, decide, snapshot, submit, steer, _message_digest, _existing_message_locked, upload, close`; `main()`

### `app.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `copilot_agent.app`

### `bootstrap/setup_dependencies.py`

- Role: Repeat-safe package setup. Scratch files only; agent knowledge stays on S:.
- Direct imports: `__future__`, `collections`, `hashlib`, `importlib`, `os`, `pathlib`, `re`, `subprocess`, `sys`, `types`, `uuid`
- Public symbols: `candidates(project, env)`; `folder(value)`; `health_check(pins)`; `install(requirements, prefix, *, versions=installed_versions, run=run_python, health=None, environ=None, probe_folder=probe, ask=input)`; `installed_versions()`; `main()`; `path_failure(output)`; `pins_from(path)`; `probe(path)`; `run_python(args, env)`

### `copilot_agent/__init__.py`

- Role: Local, policy-controlled Copilot web UI agent.

### `copilot_agent/app.py`

- Role: Interactive setup, visible browser and continuous policy-controlled conversation.
- Direct imports: `.`, `.attachments`, `.browser`, `.config`, `.diagnostics`, `.feedback`, `.file_picker`, `.knowledge_health`, `.orchestrator`, `.policy`, `.protocol`, `.setup_resources`, `.state`, `.storage`, `.temp_storage`, `.tools`, `__future__`, `argparse`, `asyncio`, `dataclasses`, `json`, `os`, `pathlib`, `socket`, `sys`, `uuid`
- Public symbols: `_actionable(exc) [private helper]`; `_choose_existing_endpoint(endpoints, prompt) [private helper]`; `_recent_events(state) [private helper]`; `_record_bug_fix(state, config, exc, operation, stage, report_index=None) [private helper]`; `_record_turn_error(state, exc) [private helper]`; `_show_bug_handoff(reports) [private helper]`; `_terminal_approval_decider(_preview) [private helper]`; `ask(prompt: str) -> str`; `choose_browser_endpoint(config, args, settings, *, interactive=False, prompt=ask, force_new=False)`; `configure_isolated_test_workspace(config, requested_path, *, resume_session=None)`; `configure_local_knowledge_test(config, requested_path)`; `error(message)`; `main()`; `persist_runtime_settings(config, settings)`; `read_runtime_settings(config)`; `run(args)`; `start_new_session(config, previous, model_label, registry=None)`; `system(message)`

### `copilot_agent/approvals.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `.feedback`, `.persistence`, `.presentation`, `.state`, `__future__`, `asyncio`, `json`, `pathlib`, `time`
- Public symbols: `class ApprovalManager; method names: __init__, revoke_session_grants, _show, request`

### `copilot_agent/archives.py`

- Role: Bounded, create-only ZIP inspection/extraction with retained verification evidence.
- Direct imports: `.policy`, `__future__`, `ast`, `hashlib`, `json`, `math`, `pathlib`, `re`, `stat`, `unicodedata`, `uuid`, `xml.etree`, `zipfile`
- Public symbols: `_digest(path) [private helper]`; `_entries(archive, limits) [private helper]`; `_limits(values) [private helper]`; `_office(archive, entries, limits) [private helper]`; `_reject_links(path) [private helper]`; `_relative(name, limits) [private helper]`; `_target(root, relative) [private helper]`; `_verify(path, limits) [private helper]`; `class ArchiveError(ValueError)`; `class ArchiveService; method names: __init__, inspect, extract`; `extract_zip(path, destination, expected_files=(), limits=None)`; `inspect_zip(path, limits=None)`; `verify_delivered_file(path, limits=None)`

### `copilot_agent/attachments.py`

- Role: Explicitly selected user-file queue, separate from local tool file roots.
- Direct imports: `.logging_utils`, `.policy`, `__future__`, `hashlib`, `io`, `os`, `pathlib`, `re`, `stat`, `zipfile`
- Public symbols: `class AttachmentError(PolicyError)`; `class AttachmentQueue; method names: __init__, _key, _resolve, _resolve_source, _record, add, records, paths, remove, clear, verify`; `upload_name(path)`

### `copilot_agent/automation_packages.py`

- Role: Validated, resumable automation ZIP packages and measurable task routing.
- Direct imports: `.archives`, `.policy`, `.session_mode`, `.state`, `__future__`, `asyncio`, `hashlib`, `importlib.util`, `ipaddress`, `json`, `os`, `pathlib`, `re`, `shutil`, `stat`, `sys`, `time`, `urllib.parse`, `uuid`, `zipfile`
- Public symbols: `_approved_output_path(output_root: Path, relative_path: str) -> Path [private helper]`; `_assert_workspace(path: Path, policy: PathPolicy) -> Path [private helper]`; `_binding_placeholder(value, binding_map) [private helper]`; `_binding_schema_placeholders(value, schema, binding_map) [private helper]`; `_bounded_int(value, name, minimum, maximum) [private helper]`; `_check_object(value, fields, required, name) [private helper]`; `_cleanup_stage_scratch(scratch_root: Path, output_root: Path) -> None [private helper]`; `_file_hash(path: Path) -> str [private helper]`; `_find_binding_references(value, path='$', found=None) [private helper]`; `_load_state(path: Path) -> dict [private helper]`; `_package_requires_fresh_confirmation(manifest: dict) -> bool [private helper]`; `_package_review_report(checks, archive=None, digest=None) [private helper]`; `_parallel_read_tab_ids(wave, tool_results, binding_declarations, registry, context, package_approved_domains, source_request_id) [private helper]`; `_preflight_package_review(manifest, archive_files, checks, registry, limits, python_version) [private helper]`; `_reject_ambiguous_numeric_host(hostname: str) -> None [private helper]`; `_reject_unavailable_patch_bindings(manifest: dict, prior: dict, patch: dict) -> None [private helper]`; `_relative(value, name='package path') [private helper]`; `_remove_unverified_stage_outputs(paths, output_root: Path, absent_before) -> list[str] [private helper]`; `_require_browser_host(hostname: str) -> None [private helper]`; `_resolve_result_bindings(value, tool_results, binding_map) [private helper]`; `_review_check(checks, item, status, detail=None, next_step=None) [private helper]`; `_run_summary(manifest: dict, state: dict, completed: set[str], validation: dict) -> str [private helper]`; `_save_state(path: Path, value: dict) -> None [private helper]`; `_schema_example(schema) [private helper]`; `_sha256(data: bytes) -> str [private helper]`; `_topological(stages) [private helper]`; `_validate_outputs(manifest, package_dir, output_root) [private helper]`; `_verify_stage_scratch(scratch_root: Path, output_root: Path) -> dict [private helper]`; `_within_declared_path(value: str, declarations) -> bool [private helper]`; `class PackageError(ValueError)`; `class PackageReviewError(PackageError); 1 public methods`; `estimate_task(description: str, thresholds: dict | None=None) -> dict`; `execute_package(args: dict, context: dict, registry, *, code_runner_factory) -> dict`; `inspect_package(path: Path, expected_sha256: str | None=None, registry=None, *, limits=None, python_version=None, review_enabled=True) -> dict`; `load_package_without_review(path, expected_sha256=None, registry=None, *, limits=None, python_version=None)`; `plan_patch(previous: dict, current: dict) -> dict`; `prepare_package_run(args: dict, context: dict, registry) -> dict`; `validate_manifest(manifest: dict, archive_files: dict[str, bytes], registry=None, *, limits=None, python_version=None, quality_review=True) -> dict`

### `copilot_agent/browser.py`

- Role: Visible Edge/Copilot UI adapter with bounded waits and owned-page isolation.
- Direct imports: `.`, `.protocol`, `__future__`, `asyncio`, `collections`, `hashlib`, `inspect`, `json`, `os`, `pathlib`, `re`, `time`, `urllib.parse`, `uuid`
- Public symbols: `class BrowserAdapter; method names: __init__, set_feedback, _feedback, endpoint, _acquire_controller, _navigate_copilot, _claim_chat_page, _claim_committed_request_page, _connect_running_edge_fallback, _connect_direct_edge_fallback, _authentication_required, start, _evaluate, _configure_tool_context, new_tool_page, focus_chat, authorize_tool_domain, _safe_url, _visible, _editor, _open_picker, _providers, _open_provider, discover_models, discover_models_on_auxiliary_page, select_model, _stop_present, _generation_state, attach_files, _attachment_signature, _attachment_signatures, _attachment_identities, _remove_preloaded_attachments, _reconcile_preloaded_attachments, preload_attachments, composer_character_limit, _composer_limit_from_editor, _editor_text, _expand_response_code, _response_code_groups, _copy_response_code, _safe_dom_code_response, _prepare_submission, preload_exchange, _consume_preloaded_exchange, verify_interaction_ready, read_reconciled_draft, _verified_unsent_retry_control, capture_committed_response, exchange, diagnostics, close`; `class BrowserUIError(RuntimeError)`; `class CaptureTimeoutError(BrowserUIError)`; `class ExistingEdgeUnavailable(BrowserUIError)`; `class ModelAccessError(BrowserUIError)`; `class ModelUnavailableError(BrowserUIError)`; `class SubmissionAmbiguousError(BrowserUIError)`; `class SubmissionNotSentError(BrowserUIError)`; `composer_comparison(expected: str, actual: str) -> dict`; `copied_code_response(text: str, request_id: str) -> str`; `fresh_assistant(messages: list[dict], baseline: dict, user_key, request_id: str) -> str`; `model_access_exhausted(text)`; `model_rank(models: list[dict]) -> list[dict]`; `public_progress(messages: list[dict], user_key, request_id: str) -> list[dict]`; `response_envelope_closed(text: str) -> bool`; `upload_alert_is_error(text: str) -> bool`; `uploads_verified(snapshot: dict, names: list[str], send_enabled: bool) -> bool`

### `copilot_agent/browser_inspection.py`

- Role: Paired structural/visual evidence and explicit JavaScript on owned website tabs.
- Direct imports: `.persistence`, `.policy`, `.web_navigation`, `__future__`, `asyncio`, `hashlib`, `pathlib`, `time`, `uuid`
- Public symbols: `_schema(properties, required=()) [private helper]`; `execute_inspection(name, args, context)`

### `copilot_agent/bundle.py`

- Role: Lossless, readable Markdown reference bundling; no ZIP, summary or deletion.
- Direct imports: `.persistence`, `__future__`, `hashlib`, `json`, `pathlib`, `re`
- Public symbols: `_build_reference(paths, manifest, destination, max_bytes, *, preamble=_PREAMBLE, write_output=True) -> dict [private helper]`; `_check_component_names(names: list[str]) -> None [private helper]`; `_check_reference_names(names: list[str]) -> None [private helper]`; `_hash(data: bytes) -> str [private helper]`; `_manifest_prefix(components: list[dict], preamble: str) -> bytes [private helper]`; `_read_bounded(path: Path, limit: int) -> bytes [private helper]`; `_write_verified_reference(target: Path, content: bytes, max_bytes: int) -> None [private helper]`; `build_bundle(paths, manifest, destination, max_bytes=MAX_BUNDLE_BYTES) -> dict`; `build_startup_attachments(paths, manifest, directory, max_bytes=MAX_BUNDLE_BYTES) -> dict`; `read_bundle_components(path, record) -> dict[str, bytes]`

### `copilot_agent/code_runner.py`

- Role: A constrained Python interpreter, never host exec or an OS sandbox claim.
- Direct imports: `.policy`, `ast`, `codecs`, `hashlib`, `io`, `json`, `math`, `operator`, `os`, `pathlib`, `re`, `stat`, `sys`, `time`, `tokenize`, `urllib.parse`
- Public symbols: `class CodeRunner; method names: __init__, _authorize_package_scratch_root, _plan, _local_plan, _verify_source, validate, prepare, run, run_async, _result, _tick, _bound, _statement, _eval, _call`

### `copilot_agent/config.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `.policy`, `.storage`, `__future__`, `dataclasses`, `json`, `os`, `pathlib`
- Public symbols: `class Config; method names: runtime_dir, workspace_dir, select_storage, load, validate, as_dict`; `documents_directory() -> Path`

### `copilot_agent/crawl4ai_adapter.py`

- Role: Crawl4AI extraction without browser networking, caches, credentials or LLMs.
- Direct imports: `.discovery_contracts`, `.discovery_http`, `__future__`, `functools`, `html`, `urllib.parse`
- Public symbols: `extract_links(url, document, scope, limit=500)`; `strategy_type()`

### `copilot_agent/delivery.py`

- Role: Pure generated-artifact intent hints; policy/observed UI still authorize delivery.
- Direct imports: `__future__`, `dataclasses`, `re`, `typing`
- Public symbols: `_expected_names(text: str) -> tuple[str, ...] [private helper]`; `_without_negated_clauses(text: str) -> str [private helper]`; `class DeliveryRequirements; method names: as_dict`; `delivery_instruction(user_text: str) -> str`; `delivery_requirements(user_text: str) -> dict`; `detect_requirements(user_text: str) -> DeliveryRequirements`; `retry_message(reason: str, attempt: int, max_attempts: int=3, office: bool=False) -> str`

### `copilot_agent/desktop.py`

- Role: Approved Windows display capture and independent viewer verification helpers.
- Direct imports: `__future__`, `ctypes`, `math`, `os`, `pathlib`, `re`, `struct`, `subprocess`, `sys`, `time`, `zlib`
- Public symbols: `_png_chunk(kind: bytes, payload: bytes) -> bytes [private helper]`; `_require_windows() -> None [private helper]`; `_tile_bounds(display: dict, count: int) -> list[dict] [private helper]`; `capture_display(display_index: int, output_path: str | os.PathLike) -> dict`; `class _MonitorInfo(ctypes.Structure)`; `enumerate_displays() -> list[dict]`; `inspect_windows(expected: list[dict], wait_seconds: float=8.0) -> dict`; `launch_viewers(viewers: list[dict], interpreter: str) -> list[dict]`

### `copilot_agent/diagnostics.py`

- Role: Separate restricted and allowlisted external bug reports.
- Direct imports: `.config`, `.logging_utils`, `__future__`, `datetime`, `json`, `os`, `pathlib`, `re`, `sys`, `sysconfig`, `traceback`, `uuid`
- Public symbols: `_category(exc: BaseException) -> str [private helper]`; `_caught_frame() -> dict | None [private helper]`; `_exception_chain(exc) [private helper]`; `_frames(exc: BaseException) -> list[dict] [private helper]`; `_ownership(path: Path, relative: str | None=None) -> str [private helper]`; `_recommend(origin) [private helper]`; `_safe_text(value: object, limit: int=1000) -> str [private helper]`; `_write_private(path: Path, data: dict) -> None [private helper]`; `class DiagnosticReports; 4 public methods`; `validate_external(data: dict) -> None`

### `copilot_agent/discovery_contracts.py`

- Role: Strict package contracts and a capability-checked, immutable graph compiler.
- Direct imports: `__future__`, `copy`, `dataclasses`, `datetime`, `functools`, `json`, `math`, `pathlib`, `re`, `urllib.parse`
- Public symbols: `_pairs(items) [private helper]`; `_schema(kind) [private helper]`; `bounded_shape(value, depth=0)`; `canonical(value)`; `class CompiledGraph; 1 public methods`; `class DiscoveryError(ValueError); 2 public methods`; `compile_manifest(value, request_id=None)`; `format_valid(value, name)`; `parse_contract(raw)`; `schema(kind)`; `validate_budgets(b)`; `validate_contract(value, kind, request_id=None)`

### `copilot_agent/discovery_engine.py`

- Role: Installed bounded public-read manifest dispatch, local fan-in and safe evidence.
- Direct imports: `.discovery_contracts`, `.discovery_http`, `.discovery_scope`, `.discovery_store`, `.policy`, `__future__`, `asyncio`, `collections`, `copy`, `datetime`, `hashlib`, `html.parser`, `os`, `time`, `urllib.parse`, `uuid`
- Public symbols: `cancelled(context)`; `class Engine; 14 public methods`; `class StructureParser(HTMLParser); 3 public methods`; `correlation(context)`; `enabled(context, flag)`; `execute_discovery(name, args, context)`; `extract(response, scope, extractor='structure')`; `input_object(properties)`; `prepare_discovery(args, context)`; `project_result(result, budget)`; `testing_gate(context, flag)`; `validate_discovery(name, args, context=None)`

### `copilot_agent/discovery_http.py`

- Role: Credential-free pinned HTTPS transport; no browser, proxy, cookie or code lane.
- Direct imports: `.discovery_contracts`, `.discovery_scope`, `__future__`, `asyncio`, `dataclasses`, `datetime`, `email.utils`, `ipaddress`, `re`, `socket`, `ssl`, `time`, `urllib.parse`
- Public symbols: `class PublicReader; 12 public methods`; `class ReadFailure(DiscoveryError); 1 public methods`; `class Response`; `class TLSStream; 7 public methods`; `retry_after(value, now=None)`

### `copilot_agent/discovery_knowledge.py`

- Role: Bound evidence/CAS knowledge and locally compiled static read-only intents.
- Direct imports: `.discovery_contracts`, `.discovery_engine`, `.discovery_scope`, `.discovery_store`, `.site_knowledge`, `__future__`, `copy`, `datetime`, `heapq`, `json`, `math`, `pathlib`, `time`, `urllib.parse`
- Public symbols: `_proofs(store, knowledge, partition) [private helper]`; `_purpose(url) [private helper]`; `_run(context, run_id, site_origin) [private helper]`; `candidate(context, args, store)`; `check_plan(plan, knowledge)`; `compile_intent(args, context)`; `execute_intent(args, context, reviewed)`; `execute_knowledge_tool(name, args, context)`; `lookup(context, site_origin, scope=None)`; `namespace(context, site_origin)`; `prepare_knowledge_tool(name, args, context)`; `reliable_route(knowledge, start, target, now=None)`; `semantics(value, scope, now=None)`; `stamp(value)`; `validate_knowledge_tool(name, args, context=None)`

### `copilot_agent/discovery_scope.py`

- Role: One exact-origin/segment parser for manifest, queue, evidence and transport.
- Direct imports: `.discovery_contracts`, `.site_knowledge`, `__future__`, `collections`, `dataclasses`, `ipaddress`, `re`, `urllib.parse`
- Public symbols: `class Scope; 2 public methods`; `class ScopedURL`; `matches(value, prefix)`; `origin(value)`; `path(value, exclusion=False)`; `public_address(value)`

### `copilot_agent/discovery_store.py`

- Role: Versioned local SQLite ledger; no synced session/customer data or auth state.
- Direct imports: `.discovery_contracts`, `.persistence`, `.policy`, `.site_knowledge`, `__future__`, `contextlib`, `datetime`, `hashlib`, `json`, `os`, `pathlib`, `threading`, `time`
- Public symbols: `alias(value)`; `class Store; 39 public methods`; `digest(value)`; `directory(context)`

### `copilot_agent/document_catalogue.py`

- Role: Session-scoped file references and bounded, on-demand attachment selection.
- Direct imports: `.logging_utils`, `.policy`, `__future__`, `hashlib`, `json`, `pathlib`, `re`, `time`, `urllib.parse`, `uuid`
- Public symbols: `_catalogue(context, catalogue_id) [private helper]`; `_compact(record) [private helper]`; `_obj(properties, required=()) [private helper]`; `bounded_hash(path, cap)`; `build_catalogue(files, context, policy)`; `current_scope(context)`; `execute_catalogue(name, args, context, policy)`; `export_catalogue(catalogue, context, policy)`; `rank_records(records, query='', requested_paths=(), active_paths=(), references=())`

### `copilot_agent/downloads.py`

- Role: Approved downloads from real links in the current Copilot assistant reply.
- Direct imports: `.archives`, `.policy`, `__future__`, `asyncio`, `base64`, `copy`, `dataclasses`, `hashlib`, `inspect`, `json`, `os`, `pathlib`, `re`, `time`, `urllib.parse`, `uuid`
- Public symbols: `_canonical(value) [private helper]`; `_download_path_identity(policy, path, *, must_exist=False) [private helper]`; `_wait_for_completed_file(path, timeout, *, stable_samples=3, poll_interval=0.1) [private helper]`; `class _Ticket`; `class DownloadError(RuntimeError); method names: __init__`; `class DownloadService; method names: __init__, _config, _source, _url, _notify, _links, _settings, prepare, _download_same_origin_blob, download`; `validate_download_args(args)`

### `copilot_agent/edge_native_probe.py`

- Role: Bounded child-only Windows ownership queries; never run agent actions.
- Direct imports: `json`, `os`, `pathlib`, `sys`
- Public symbols: `main()`; `suppress_fault_dialogs()`

### `copilot_agent/edge_owner.py`

- Role: Keep a Playwright-launched Edge profile alive while agent sessions attach over CDP.
- Direct imports: `__future__`, `argparse`, `asyncio`, `pathlib`, `sys`
- Public symbols: `main() -> None`; `own_edge(port: int, profile: Path, executable: Path) -> None`

### `copilot_agent/feedback.py`

- Role: Public live reply previews and clearly attributed local activity.
- Direct imports: `.logging_utils`, `.presentation`, `.protocol`, `json`, `os`, `re`, `sys`
- Public symbols: `_actor_style(actor: str) -> str [private helper]`; `_enable_colour(stream) -> bool [private helper]`; `_terminal_text(value, preserve_markup=False) -> str [private helper]`; `class Feedback; 5 public methods`; `public_preview(raw, session_id, request_id)`

### `copilot_agent/file_picker.py`

- Role: Native attachment selection; call select_files using asyncio.to_thread.
- Direct imports: `.attachments`, `__future__`, `os`, `pathlib`, `typing`
- Public symbols: `_native_picker(**options) [private helper]`; `_patterns(extensions) [private helper]`; `select_files(initial_directory: str | Path | None=None, *, picker_backend: Callable | None=None) -> list[Path]`

### `copilot_agent/findings.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `.logging_utils`, `.persistence`, `__future__`, `hashlib`, `json`, `pathlib`, `re`
- Public symbols: `class Findings; 5 public methods`

### `copilot_agent/image_viewer.py`

- Role: Minimal persistent image viewer launched only by an approved Code Runner plan.
- Direct imports: `__future__`, `pathlib`, `sys`
- Public symbols: `main() -> int`

### `copilot_agent/knowledge_health.py`

- Role: Bounded startup storage probe. Returned diagnostics never contain paths/data.
- Direct imports: `.discovery_store`, `.site_knowledge`, `__future__`, `errno`, `hashlib`, `os`, `pathlib`, `sqlite3`, `uuid`
- Public symbols: `check_knowledge_health(context)`

### `copilot_agent/knowledge_notes.py`

- Role: Immutable, verified Discoveries artifacts independent of site schemas.
- Direct imports: `.policy`, `.site_knowledge`, `hashlib`, `json`, `os`, `re`, `uuid`
- Public symbols: `_bytes(value) [private helper]`; `execute_note(name, args, context)`

### `copilot_agent/local_crawler.py`

- Role: Local Crawl4AI, using owned tabs in the already connected Edge session.
- Direct imports: `.persistence`, `.policy`, `__future__`, `asyncio`, `collections`, `contextlib`, `hashlib`, `json`, `os`, `pathlib`, `re`, `time`, `urllib.parse`, `uuid`
- Public symbols: `crawl_websites(args, context, *, factory=None)`; `crawler_factory(browser, scratch, page_timeout)`; `knowledge_root(config)`; `open_login_page(browser, url)`; `read_knowledge(args, context)`; `saved_html(document)`; `website_url(value)`

### `copilot_agent/local_navigation.py`

- Role: Session-only local navigation authority and path-free filesystem diagnostics.
- Direct imports: `.policy`, `dataclasses`, `errno`, `ntpath`, `os`, `pathlib`
- Public symbols: `class FilesystemAccessError(PolicyError); 1 public methods`; `class SessionFileAccessPolicy(PathPolicy); 2 public methods`; `class SessionNavigationGrant; 2 public methods`; `class SessionPathExtensionPolicy(PathPolicy); 6 public methods`; `class SessionPathPolicy(PathPolicy); 2 public methods`; `filesystem_diagnostic(error)`; `prepare_session_path_extension(args, context)`

### `copilot_agent/local_python_runner.py`

- Role: Bounded host-process execution for an exact, explicitly approved local-Python plan.
- Direct imports: `.desktop`, `.policy`, `__future__`, `asyncio`, `hashlib`, `json`, `os`, `pathlib`, `signal`, `subprocess`, `sys`, `time`, `uuid`
- Public symbols: `_children(path: Path, plan: dict) -> list[dict] [private helper]`; `_hash_file(path: Path, maximum: int=MAX_EVIDENCE_BYTES) -> tuple[str, int] [private helper]`; `_ledger_records(path: Path) -> list[dict] [private helper]`; `_pid_running(pid: int) -> bool [private helper]`; `_preflight_imports(interpreter: Path, application_root: Path, imports: list[str]) -> dict [private helper]`; `_read_bounded(stream, limit: int) -> bytes [private helper]`; `_safe_environment(working: Path, create_roots=()) -> dict[str, str] [private helper]`; `_terminate_main(process) -> None [private helper]`; `_terminate_pid(pid: int) -> bool [private helper]`; `class ManagedProcessRegistry; method names: __init__, register, _save, cleanup, cleanup_all`; `execute_local_python(plan: dict, prepared: dict, session_dir: Path, process_registry: ManagedProcessRegistry | None=None) -> dict`; `runtime_binding(plan: dict) -> dict`

### `copilot_agent/local_python_worker.py`

- Role: Fixed worker for an explicitly approved local-Python plan.
- Direct imports: `__future__`, `_io`, `ast`, `builtins`, `hashlib`, `io`, `json`, `os`, `pathlib`, `socket`, `subprocess`, `sys`, `traceback`, `urllib.parse`
- Public symbols: `_normalized_executable(value: str) -> str [private helper]`; `_within(path: Path, scopes: list[Path]) -> bool [private helper]`; `_write_event(stream, event: str, **details) -> None [private helper]`; `main() -> int`

### `copilot_agent/logging_utils.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `__future__`, `datetime`, `json`, `pathlib`, `re`, `urllib.parse`
- Public symbols: `class EventLog; 2 public methods`; `now() -> str`; `redact(value)`

### `copilot_agent/orchestrator.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `.approvals`, `.attachments`, `.browser`, `.code_runner`, `.feedback`, `.findings`, `.local_python_runner`, `.logging_utils`, `.policy`, `.presentation`, `.prompts`, `.protocol`, `.reconciliation`, `.research_permissions`, `.state`, `.sync`, `__future__`, `asyncio`, `copy`, `hashlib`, `json`, `pathlib`, `re`, `threading`, `time`, `uuid`
- Public symbols: `class Orchestrator; method names: __init__, _display_s_path, _code_runner, _parallel_readonly_group, _live_feedback, _action_text, _emit_validated_response, _emit_tool_result, _package_run_stage_details, _package_run_repair_instruction, _latest_failed_package_run, _recovered_package_run_failure, _package_review_repair_instruction, _package_local_build_rejection, _routing_description, _route_for_turn, _review_passed, _record_package_delivery, _prior_package_review, _ensure_package_review, _local_archive_sha256, _queue_reviewed_package_run, _inspect_downloaded_package, _download_recovery_instruction, _attachment_record, attachment_queue, _bounded_hash, _direction_independent_attachments, prepare_pending_attachments, _schedule_next_turn_preparation, _finish_next_turn_preparation, _stage_approved, _send, _record_raw_response, _pack_outbound_response, prepare_initialization, _validated_exchange, _preflight, initialize, recover_capture_failed_turn, _recover_uncertain_knowledge, turn, _turn, _prepare_user_attachments, _take_steering, _browser_preparation, _delivery_result, _delivery_verified, close`

### `copilot_agent/outbound_results.py`

- Role: Lossless, sectioned attachments for oversized Copilot composer messages.
- Direct imports: `.persistence`, `.policy`, `__future__`, `collections`, `hashlib`, `json`, `pathlib`
- Public symbols: `composer_characters(text)`; `pack_outbound(text, attachments, directory, *, composer_limit=16000, max_file_bytes=MAX_RESULT_FILE_BYTES)`

### `copilot_agent/persistence.py`

- Role: Atomic writes with retained prior versions; no filesystem deletion.
- Direct imports: `__future__`, `json`, `os`, `pathlib`, `time`, `uuid`
- Public symbols: `io_path(path: Path) -> Path`; `write_json(path: Path, value: object) -> None`; `write_preserving(path: Path, text: str) -> None`

### `copilot_agent/policy.py`

- Role: Resolved-path and navigation boundaries shared by all local capabilities.
- Direct imports: `ntpath`, `os`, `pathlib`, `stat`, `urllib.parse`
- Public symbols: `_final_s_path(value) [private helper]`; `_mapped_s_provider_root() [private helper]`; `class PathPolicy; method names: __init__, resolve`; `class PolicyError(ValueError)`; `class URLPolicy; method names: __init__, resolve, website_domain`; `config_value(config, key, default=None)`; `is_s_drive_path(path) -> bool`; `mapped_s_drive_root()`; `reject_path_redirection(path)`; `resolve_s_drive_output(path, excluded_roots=(), *, must_exist=False)`

### `copilot_agent/presentation.py`

- Role: Human-readable terminal summaries; execution contracts remain exact JSON.
- Public symbols: `call_summary(call)`; `exchange_summary(kind, content)`; `readable(value, indent=0)`

### `copilot_agent/prompts.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `.bundle`, `.persistence`, `__future__`, `copy`, `hashlib`, `json`, `pathlib`, `sys`
- Public symbols: `class PromptBuilder; 5 public methods`

### `copilot_agent/protocol.py`

- Role: Strict JSON envelope parser and validator for the published schema vocabulary.
- Direct imports: `__future__`, `json`, `math`, `pathlib`, `re`
- Public symbols: `_object_pairs(pairs) [private helper]`; `class ProtocolError(ValueError); method names: __init__`; `correction_message(exc: ProtocolError) -> str`; `parse_response(raw: str, session_id: str, request_id: str, registry=None, seen_response_ids=()) -> dict`; `validate_schema(value, schema: dict, root=None, path='$') -> list[str]`

### `copilot_agent/reconciliation.py`

- Role: Fresh, model-requested reconciliation of navigation-only browser effects.
- Direct imports: `.logging_utils`, `.policy`, `.session_mode`, `__future__`, `asyncio`, `hashlib`, `urllib.parse`, `uuid`
- Public symbols: `_binding(browser) [private helper]`; `_hash(value: str) -> str [private helper]`; `_navigation_only(request: dict) -> bool [private helper]`; `_origin(url: str) -> str [private helper]`; `_owned_page(browser, request) [private helper]`; `_query_free(url) [private helper]`; `abandon_uncertain_browser_call(state, browser, call_id: str, checkpoint_url: str)`; `browser_diagnostics(state, browser)`; `capture_baseline(browser, request)`; `class ReconciliationRequired(RuntimeError); 1 public methods`; `close_quarantined_tabs(browser)`; `navigation_scope_allows(request, browser, domains, expected_binding=None)`; `reconcile_browser_call(state, browser, call_id: str, outcome: str, observed_url: str, observed_title: str='')`; `recover_missing_navigation(state, browser)`

### `copilot_agent/research_permissions.py`

- Role: Independent per-user consent store and bounded, locally enforced research tools.
- Direct imports: `.logging_utils`, `.persistence`, `.policy`, `.protocol`, `.site_knowledge`, `.web_navigation`, `__future__`, `asyncio`, `copy`, `datetime`, `getpass`, `hashlib`, `json`, `os`, `pathlib`, `re`, `threading`, `urllib.parse`
- Public symbols: `active(context, grant_id)`; `audit(context, event, grant_id, **details)`; `bind_namespace(context, record)`; `bound(maximum)`; `collection(page, strategy, context)`; `directory(context)`; `execute_permissions(name, args, context)`; `guard_customer_read(context, capability='structured_summaries')`; `list_grants(context)`; `load(context, grant_id)`; `manage(context, grant_id, action)`; `obj(properties, required=None)`; `perform(args, context)`; `prepare_permissions(name, args, context)`; `save(context, record)`; `user_identity(context)`; `verify_scope(context, record, tab_id=None)`

### `copilot_agent/reused_browser.py`

- Role: Narrow, provenance-recorded Edge helpers, with no CDD engine import.
- Direct imports: `__future__`, `asyncio`, `json`, `os`, `pathlib`, `re`, `shutil`, `socket`, `subprocess`, `sys`, `time`, `urllib.parse`, `urllib.request`
- Public symbols: `_decode_process_command(buffer, returned) [private helper]`; `_edge_listener_process(port: int) -> dict [private helper]`; `_hidden_command(command: list[str], timeout=8) -> str [private helper]`; `_loopback_listener_pid_native(port: int) -> int | None [private helper]`; `_native_probe(kind, identifier) [private helper]`; `_profile_argument(command_line: str) -> Path | None [private helper]`; `_windows_process_details(pid: int) -> dict [private helper]`; `_windows_process_details_native(pid: int) -> dict [private helper]`; `cdp_endpoint(port: int) -> str`; `class EndpointError(RuntimeError)`; `connect_bounded(playwright, endpoint: str, timeout: float, process=None, initial_payload=None, endpoint_validator=None, endpoint_wait_timeout=None)`; `direct_profile_candidates(profile)`; `discover_edge_debugging_endpoints() -> list[dict]`; `find_edge_executable(explicit_path=None) -> Path`; `get_cdp_version(endpoint: str, timeout: float=0.75) -> dict | None`; `launch_edge(edge_path: Path, port: int, profile: Path) -> subprocess.Popen`; `launch_edge_direct(edge_path, port, profile, *, software_graphics=False)`; `loopback_listener_pid(port: int) -> int | None`; `port_listening(port: int) -> bool`; `profile_in_use(profile: Path) -> bool`; `remote_debugging_blocked() -> bool`; `stop_launched_edge(process: subprocess.Popen | None) -> None`; `validate_edge_listener(port: int, profile: Path | None=None) -> Path | None`; `validate_endpoint(endpoint: str, payload: dict) -> str`; `validate_launched_endpoint(port: int, profile: Path, process: subprocess.Popen | None) -> None`; `validate_profile_ownership(port: int, profile: Path) -> None`

### `copilot_agent/session_mode.py`

- Role: One ephemeral, permissive session choice; never restored from saved state.
- Direct imports: `.policy`, `urllib.parse`
- Public symbols: `class OpenWebsitePolicy(URLPolicy); 3 public methods`; `configure_session(config, allowed)`; `fast_mode(config)`; `website_policy(config, domains=())`

### `copilot_agent/session_setup.py`

- Role: Plain-language, session-only package and website discovery choices.
- Direct imports: `.local_crawler`, `__future__`, `asyncio`, `contextlib`, `threading`
- Public symbols: `_watch_stop(cancel_event, stop, task) [private helper]`; `choose_package_mode(config, ask, report, *, supplied=None)`; `guided_discovery(config, browser, session_dir, ask, report, cancel_event=None)`

### `copilot_agent/setup_resources.py`

- Role: Bounded, interactive automatic/manual setup; never launches a resource.
- Direct imports: `.`, `.storage`, `pathlib`
- Public symbols: `choice(label, ask, emit)`; `choose_edge(config, settings, ask, emit, force=False)`; `pasted_path(text)`

### `copilot_agent/site_knowledge.py`

- Role: Consent-bound, per-device navigation memory; no customer observations.
- Direct imports: `.policy`, `.protocol`, `__future__`, `copy`, `datetime`, `getpass`, `hashlib`, `json`, `ntpath`, `pathlib`, `re`, `urllib.parse`, `uuid`
- Public symbols: `_approval(name, args, context) [private helper]`; `_canonical(value) [private helper]`; `_current_origin(context) [private helper]`; `_digest(value) [private helper]`; `_enum(values) [private helper]`; `_fingerprint(scope) [private helper]`; `_hash(value) [private helper]`; `_json_pairs(pairs) [private helper]`; `_now(context) [private helper]`; `_object(properties, required=None) [private helper]`; `_origin(value) [private helper]`; `_read(context, scope) [private helper]`; `_record_path(context, scope) [private helper]`; `_reject_json_constant(value) [private helper]`; `_retrieve(context, scope) [private helper]`; `_safe_label(value) [private helper]`; `_safe_locator(item) [private helper]`; `_safe_route(value) [private helper]`; `_sanitize_knowledge(args) [private helper]`; `_scope(name, args, context) [private helper]`; `_session(context) [private helper]`; `_sources(scope, knowledge) [private helper]`; `_string(length=160) [private helper]`; `_template_route(value, origin) [private helper]`; `_timestamp(value) [private helper]`; `_verified_write(context, scope, value) [private helper]`; `_write(context, scope, value) [private helper]`; `class _KnowledgeStageError(OSError); 1 public methods`; `class KnowledgeStorageError(PolicyError); 1 public methods`; `class KnowledgeValidationError(ValueError); 1 public methods`; `class KnowledgeWriteError(RuntimeError); 1 public methods`; `execute_knowledge(name, args, context, policy=None)`; `knowledge_directory(context)`; `prepare_knowledge(args, context, name=None)`; `quarantine_knowledge_record(context, namespace_id)`; `reconcile_knowledge_call(state, context, call_id)`; `reconciliation_baseline(args, context, prepared)`; `safe_proposal(args)`; `storage_error_code(error)`; `validate_knowledge(name, args, context, policy=None)`

### `copilot_agent/state.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `.logging_utils`, `.persistence`, `__future__`, `copy`, `hashlib`, `json`, `pathlib`, `re`, `uuid`
- Public symbols: `canonical_hash(value) -> str`; `class SessionState; method names: __init__, session_id, message_count, save, event, message, begin_submission, confirm_submission, reconcile_submission, begin_call, quarantine_call, abandon_browser_uncertainty, finish_call, fail_active_turn, approve_domain, quarantine_missing_navigation, reconcile_call, grant, context`; `latest_committed_request_id(state) -> str | None`; `operation_domains(name: str) -> frozenset[str]`; `recoverable_capture_request_id(state) -> str | None`

### `copilot_agent/storage.py`

- Role: S: project-sibling persistence and operator-selected storage helpers.
- Direct imports: `.persistence`, `__future__`, `hashlib`, `json`, `ntpath`, `os`, `pathlib`, `socket`
- Public symbols: `default_local_storage(environ=None) -> Path`; `discoveries_storage(project_root: Path) -> Path`; `discoveries_storage_paths(project_root: Path) -> dict[str, str]`; `machine_key(hostname=None) -> str`; `profile_directory(storage_dir: Path, hostname=None) -> Path`; `read_user_settings(storage_dir: Path, *, testing=False) -> dict`; `save_user_settings(storage_dir: Path, settings: dict, *, testing=False) -> Path`; `shared_python_candidates(values, require_shared=True) -> list[str]`; `validate_user_storage_directory(path: Path) -> Path`

### `copilot_agent/sync.py`

- Role: Observe new local outputs without treating cloud previews as delivery.
- Direct imports: `asyncio`, `fnmatch`, `pathlib`, `time`
- Public symbols: `class CreatedSync; 3 public methods`; `snapshot(directory)`

### `copilot_agent/temp_storage.py`

- Role: Probe retry locations under S: without trusting free-space metadata.
- Direct imports: `__future__`, `hashlib`, `os`, `pathlib`, `tempfile`, `uuid`
- Public symbols: `_candidate_directories(environ=None, *, storage_root=None, home=None, platform=None) -> list[Path] [private helper]`; `_probe_directory(directory: Path) -> None [private helper]`; `configure_temp_directory(storage_root, environ=None, *, home=None, platform=None, probe=_probe_directory) -> Path`; `select_temp_directory(environ=None, *, storage_root=None, home=None, platform=None, probe=_probe_directory) -> Path`

### `copilot_agent/terminal_input.py`

- Role: Single-reader terminal input broker for live run steering and local files.
- Direct imports: `__future__`, `asyncio`, `collections`, `pathlib`, `queue`, `re`, `threading`, `time`, `uuid`
- Public symbols: `class TerminalInputBroker; 10 public methods`

### `copilot_agent/tools.py`

- Role: Versioned local capabilities. Browser tools use guarded owned Edge tabs.
- Direct imports: `.archives`, `.browser_inspection`, `.code_runner`, `.discovery_contracts`, `.discovery_engine`, `.discovery_knowledge`, `.downloads`, `.local_navigation`, `.logging_utils`, `.policy`, `.reconciliation`, `.research_permissions`, `.session_mode`, `.site_knowledge`, `.sync`, `.web_documents`, `.web_navigation`, `.web_operations`, `asyncio`, `ctypes`, `hashlib`, `importlib.metadata`, `json`, `os`, `pathlib`, `platform`, `re`, `shutil`, `sys`, `urllib.parse`, `uuid`
- Public symbols: `_approved_write_target(name, args, policy, context) [private helper]`; `_atomic_replace(path, payload, expected_sha256, context, policy, *, operation_name='files.replace') [private helper]`; `_require_extended_read(path, policy) [private helper]`; `_swap_replacement_file(path, temp) [private helper]`; `_write_target(name, args, policy, context) [private helper]`; `class ToolRegistry; method names: definitions, definition, validate_input, validate_call, _limit, execute, _execute`; `configured_path_policy(config, session_dir)`; `definitions()`; `execute(name, args, context)`; `obj(properties, required=None)`; `schema_example(schema)`; `tool_path_policy(name, context)`; `validate(value, schema)`

### `copilot_agent/web_documents.py`

- Role: Observed website document links, approved bounded downloads and upload staging.
- Direct imports: `.archives`, `.attachments`, `.document_catalogue`, `.policy`, `.session_mode`, `__future__`, `asyncio`, `hashlib`, `json`, `mimetypes`, `pathlib`, `re`, `time`, `unicodedata`, `urllib.parse`, `uuid`, `zipfile`
- Public symbols: `_bound(item, context, browser) [private helper]`; `_discover(args, context) [private helper]`; `_download_batch(args, context, policy) [private helper]`; `_hash(path, cap) [private helper]`; `_integrity(path, expected_mime=None, observed_mime=None) [private helper]`; `_name(raw, url) [private helper]`; `_obj(properties, required=()) [private helper]`; `_origin(value) [private helper]`; `_page(context, tab_id=None) [private helper]`; `_safe_url(value) [private helper]`; `_scope(context, browser, page) [private helper]`; `_transfer(args, context, policy) [private helper]`; `_urls(context, browser) [private helper]`; `_validate_shape(value, schema) [private helper]`; `execute_documents(name, args, context, policy)`; `validate_documents(name, args, context=None, policy=None)`

### `copilot_agent/web_navigation.py`

- Role: Bounded semantic website discovery and verified plans in owned Edge tabs.
- Direct imports: `.policy`, `.session_mode`, `asyncio`, `hashlib`, `json`, `re`, `time`, `urllib.parse`, `uuid`
- Public symbols: `_assertion(page, assertion, context, wait_ms=0) [private helper]`; `_boundary(page, context) [private helper]`; `_candidates(page, strategy, context) [private helper]`; `_check_cancelled(context) [private helper]`; `_close_tab(tab_id, context, task_id=None, customer_key=None) [private helper]`; `_compact_recon(snapshot, context) [private helper]`; `_consequential_control(locator, op) [private helper]`; `_execute_plan(args, context) [private helper]`; `_fingerprint(page) [private helper]`; `_identity(page, identities, context) [private helper]`; `_install_origin_guard(page, context, reference) [private helper]`; `_object(properties, required=()) [private helper]`; `_open_tab(args, context, reference) [private helper]`; `_origin(url) [private helper]`; `_reset_tabs(args, context) [private helper]`; `_resolve(page, strategy, context, retries=0, visible=True) [private helper]`; `_same_origin(url, reference, context) [private helper]`; `_scope(page, locator, context) [private helper]`; `_snapshot(page, context, max_elements=60, max_text_chars=1200) [private helper]`; `_state(context) [private helper]`; `_step_schema(depth=2) [private helper]`; `_stop_state(snapshot, url) [private helper]`; `_tab_list(context) [private helper]`; `_url_policy(context) [private helper]`; `_validate_assertion(assertion) [private helper]`; `_validate_locator(locator) [private helper]`; `_validate_schema(value, schema) [private helper]`; `_verify(page, assertions, context, timeout_ms=3000) [private helper]`; `class NavigationStop(Exception); 1 public methods`; `clear_navigation_state(browser)`; `execute_navigation(name, args, context, policy=None)`; `get_navigation_page(context, tab_id=None, task_id=None, customer_key=None)`; `get_primary_navigation_tab_id(context)`; `plan_hash(args)`; `read_business_field(locator)`; `safe_url(url)`; `validate_navigation(name, args, context=None)`

### `copilot_agent/web_operations.py`

- Role: Opt-in, public read-only website operations backed by the discovery ledger.
- Direct imports: `.discovery_contracts`, `.discovery_http`, `.discovery_scope`, `.discovery_store`, `.policy`, `__future__`, `asyncio`, `dataclasses`, `json`, `math`, `re`, `time`, `types`, `urllib.parse`, `uuid`
- Public symbols: `_call(args, context) [private helper]`; `_compact(value, limit=9000) [private helper]`; `_decode(response) [private helper]`; `_enabled(context) [private helper]`; `_entropy(value) [private helper]`; `_extract(value, response) [private helper]`; `_failure_class(error) [private helper]`; `_graph(site_origin, query_keys) [private helper]`; `_infer(args) [private helper]`; `_invalid_constant(value) [private helper]`; `_learn(args, context) [private helper]`; `_list(args, context) [private helper]`; `_materialize(site_origin, template, arguments) [private helper]`; `_obj(properties, required=None) [private helper]`; `_one_call(site_origin, call, context) [private helper]`; `_partition(site_origin) [private helper]`; `_parts(url, site_origin) [private helper]`; `_request(context, site_origin, url, query_keys) [private helper]`; `_safe_arguments(value, field='arguments') [private helper]`; `_shape(value, depth=0) [private helper]`; `_unique_pairs(items) [private helper]`; `class _OperationScope; 2 public methods`; `class _URL`; `execute_operation(name, args, context)`; `validate_operation(name, args, context=None)`

### `copilot_agent/web_privacy.py`

- Role: Keep website task content in memory; persist only operational audit evidence.
- Direct imports: `__future__`, `hashlib`, `json`, `re`
- Public symbols: `_snapshot_evidence(value) [private helper]`; `audit_evidence(value)`; `private_id(value)`; `private_session_snapshot(data)`

### `tests/discovery_fixtures.py`

- Role: Synthetic, deterministic fixtures for FUTURE tests; not observed site evidence.
- Direct imports: `contextlib`, `copilot_agent.discovery_contracts`, `copilot_agent.site_knowledge`, `pathlib`, `tempfile`, `threading`, `types`
- Public symbols: `budgets()`; `intent(scope, purpose='documents')`; `manifest()`; `task(i, worker, parents=(), refs=(), urls=(), accept='usable', expand=False)`; `workspace()`

### `tests/inspect_download_settings.py`

- Role: Explicit read-only inspection of this authorized Edge profile's download UI.
- Direct imports: `argparse`, `asyncio`, `copilot_agent.browser`, `copilot_agent.config`, `copilot_agent.persistence`, `datetime`, `json`, `pathlib`, `sys`, `uuid`
- Public symbols: `run(args)`

### `tests/live_acceptance.py`

- Role: Explicit real visible acceptance; never auto-approve generated scripts.
- Direct imports: `__future__`, `argparse`, `asyncio`, `copilot_agent.browser`, `copilot_agent.config`, `copilot_agent.logging_utils`, `copilot_agent.orchestrator`, `copilot_agent.persistence`, `copilot_agent.state`, `copilot_agent.sync`, `copilot_agent.tools`, `datetime`, `json`, `pathlib`, `sys`, `time`, `uuid`
- Public symbols: `class InjectedCaptureBrowser; 3 public methods`; `require(condition, message)`; `run(args)`

### `tests/live_attachments.py`

- Role: Opt-in real Copilot upload/readback acceptance; never execute delivered code.
- Direct imports: `__future__`, `argparse`, `asyncio`, `copilot_agent.attachments`, `copilot_agent.browser`, `copilot_agent.config`, `copilot_agent.file_picker`, `copilot_agent.logging_utils`, `copilot_agent.orchestrator`, `copilot_agent.persistence`, `copilot_agent.policy`, `copilot_agent.state`, `copilot_agent.tools`, `datetime`, `hashlib`, `json`, `pathlib`, `re`, `sys`, `uuid`
- Public symbols: `class RecordedBrowser; 3 public methods`; `file_record(path, cap)`; `require(condition, message)`; `run(args)`

### `tests/live_delivery.py`

- Role: Explicit real UI delivery acceptance; harmless retained artifacts, never code execution.
- Direct imports: `argparse`, `asyncio`, `copilot_agent.browser`, `copilot_agent.config`, `copilot_agent.orchestrator`, `copilot_agent.persistence`, `copilot_agent.state`, `copilot_agent.tools`, `datetime`, `json`, `pathlib`, `sys`, `uuid`
- Public symbols: `run(args)`

### `tests/live_download_run.py`

- Role: Real UI download, then exact-byte Python-subset execution after user approval.
- Direct imports: `__future__`, `argparse`, `ast`, `asyncio`, `copilot_agent.archives`, `copilot_agent.browser`, `copilot_agent.code_runner`, `copilot_agent.config`, `copilot_agent.logging_utils`, `copilot_agent.orchestrator`, `copilot_agent.persistence`, `copilot_agent.policy`, `copilot_agent.state`, `copilot_agent.tools`, `datetime`, `hashlib`, `json`, `pathlib`, `sys`, `time`, `uuid`
- Public symbols: `read_approval(path, expected)`; `require(condition, message)`; `run(args)`; `validate_print_only(script)`; `wait_for_approval(path, expected, timeout, report, save)`

### `tests/live_new_session.py`

- Role: Explicit visible test of :new's production lifecycle; synthetic no-tool turns.
- Direct imports: `argparse`, `asyncio`, `copilot_agent.app`, `copilot_agent.browser`, `copilot_agent.config`, `copilot_agent.orchestrator`, `copilot_agent.persistence`, `copilot_agent.state`, `copilot_agent.tools`, `datetime`, `json`, `pathlib`, `sys`, `uuid`
- Public symbols: `run(args)`

### `tests/live_package_run.py`

- Role: Live Copilot ZIP-to-local-run proof in an isolated workspace.
- Direct imports: `__future__`, `argparse`, `asyncio`, `copilot_agent.app`, `copilot_agent.automation_packages`, `copilot_agent.browser`, `copilot_agent.config`, `copilot_agent.logging_utils`, `copilot_agent.orchestrator`, `copilot_agent.persistence`, `copilot_agent.setup_resources`, `copilot_agent.state`, `copilot_agent.tools`, `csv`, `datetime`, `hashlib`, `json`, `pathlib`, `re`, `sys`, `types`, `uuid`, `zipfile`
- Public symbols: `extract_call(preview: dict) -> tuple[dict, list[dict]]`; `latest_failed_proof_run_state(workspace: Path) -> dict | None`; `latest_package_run_was_denied(calls: dict) -> bool`; `load_proof_config(path: Path) -> Config`; `package_archive_was_executed(calls: dict, expected_hash: str) -> bool`; `parse_proof_revision_limit(value: str) -> int | None`; `proof_description_is_synthetic(manifest: dict) -> bool`; `proof_import_scope_valid(manifest: dict) -> bool`; `proof_retry_instruction(plan: dict) -> str`; `proof_revision_allowed(limit: int | None, completed: int) -> bool`; `recover_denied_run_plan(config, acceptance_dir: Path, current_directory: Path) -> dict | None`; `require(condition: bool, message: str) -> None`; `require_dedicated_existing_profile(config: Config, port: int) -> None`; `run(args) -> int`; `should_recover_denied_run_plan(calls: dict, recovery_request_id: str | None, pending_submission: dict | None) -> bool`; `validate_output_files(output_root: Path) -> dict`

### `tests/live_probe.py`

- Role: Explicitly gated visible picker-only probe: no uploads or chat sends.
- Direct imports: `__future__`, `argparse`, `asyncio`, `copilot_agent.browser`, `copilot_agent.config`, `copilot_agent.reused_browser`, `datetime`, `json`, `pathlib`, `sys`, `uuid`
- Public symbols: `main()`; `run(args)`

### `tests/live_verify_completed_run.py`

- Role: Read-only verification/reporting recovery for an already completed execution.
- Direct imports: `__future__`, `argparse`, `ast`, `asyncio`, `copilot_agent.browser`, `copilot_agent.config`, `copilot_agent.logging_utils`, `copilot_agent.orchestrator`, `copilot_agent.persistence`, `copilot_agent.policy`, `copilot_agent.state`, `copilot_agent.tools`, `datetime`, `hashlib`, `json`, `pathlib`, `sys`, `uuid`
- Public symbols: `bounded_bytes(policy, path, cap=20 * 1024 * 1024)`; `class NoExecutionRegistry(ToolRegistry); 1 public methods`; `load_json(policy, path)`; `require(condition, message)`; `run(args)`; `verify_completed_report(config, path)`

### `tests/manual_live_copy_probe.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `asyncio`, `json`, `pathlib`, `playwright.async_api`, `uuid`
- Public symbols: `main()`

### `tests/test_agent_ui_runtime.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `agent_ui.runtime`, `agent_ui.workspace`, `collections`, `threading`, `time`, `unittest`, `unittest.mock`
- Public symbols: `class PromptBrokerTests(unittest.TestCase); 1 public methods`; `class SteeringQueueTests(unittest.TestCase); 4 public methods`; `class WorkspaceSteeringTests(unittest.TestCase); 5 public methods`

### `tests/test_app_ports.py`

- Role: Endpoint-choice tests with mocked sockets/CDP; no live ports or profiles.
- Direct imports: `copilot_agent.app`, `copilot_agent.reused_browser`, `pathlib`, `threading`, `types`, `unittest`, `unittest.mock`
- Public symbols: `class BrowserEndpointTests(unittest.IsolatedAsyncioTestCase); 19 public methods`; `class FakeSockets; 2 public methods`

### `tests/test_app_sessions.py`

- Role: Independent session lifecycle, without real UI messages or deletion.
- Direct imports: `copilot_agent.app`, `copilot_agent.orchestrator`, `json`, `tests.test_orchestrator`, `tests.test_protocol_state`, `unittest`, `unittest.mock`
- Public symbols: `class NewSessionTests(unittest.IsolatedAsyncioTestCase); 6 public methods`; `class SessionBrowser(MockBrowser); 7 public methods`

### `tests/test_app_startup_flow.py`

- Role: Startup latency contracts without launching Edge or sending Copilot messages.
- Direct imports: `copilot_agent.app`, `copilot_agent.config`, `copilot_agent.state`, `os`, `pathlib`, `tempfile`, `tests.test_protocol_state`, `types`, `unittest`, `unittest.mock`
- Public symbols: `class LocalKnowledgeTestStoreTests(unittest.TestCase); 2 public methods`; `class StartupBrowser; 8 public methods`; `class StartupFlowTests(unittest.IsolatedAsyncioTestCase); 9 public methods`; `class StartupOrchestrator; 7 public methods`

### `tests/test_archives.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `copilot_agent.archives`, `copilot_agent.policy`, `hashlib`, `io`, `pathlib`, `stat`, `tempfile`, `unittest`, `zipfile`
- Public symbols: `class ArchiveTests(unittest.TestCase); 24 public methods`

### `tests/test_attachment_capacity.py`

- Role: Offline assembled attachment boundary, using actual prompt and send logic.
- Direct imports: `copilot_agent.orchestrator`, `copilot_agent.policy`, `hashlib`, `json`, `pathlib`, `tests.test_orchestrator`, `tests.test_protocol_state`, `unittest`, `unittest.mock`
- Public symbols: `class AssembledCapacityTests(unittest.IsolatedAsyncioTestCase); 3 public methods`

### `tests/test_attachments.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `copilot_agent.attachments`, `copilot_agent.policy`, `hashlib`, `io`, `os`, `pathlib`, `tempfile`, `types`, `unittest`, `unittest.mock`, `zipfile`
- Public symbols: `class AttachmentTests(unittest.TestCase); 10 public methods`

### `tests/test_automation_approval.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `asyncio`, `copilot_agent.approvals`, `copilot_agent.state`, `hashlib`, `tempfile`, `time`, `unittest`
- Public symbols: `class AutomationApprovalTests(unittest.TestCase); 7 public methods`; `class QuietFeedback; 3 public methods`; `class RecordingFeedback(QuietFeedback); 2 public methods`

### `tests/test_automation_packages.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `asyncio`, `copilot_agent.automation_packages`, `copilot_agent.policy`, `copilot_agent.protocol`, `copilot_agent.state`, `copilot_agent.tools`, `datetime`, `hashlib`, `json`, `os`, `pathlib`, `tempfile`, `types`, `unittest`, `unittest.mock`, `zipfile`
- Public symbols: `class AutomationPackageTests(unittest.TestCase); 36 public methods`; `class FakeRunner; 3 public methods`; `class PreflightFailureRunner(FakeRunner); 2 public methods`; `execute_test_package(root, archive, runner=None, *, cancelled=lambda: False, config_parallelism=2)`; `package_bytes(script="print('ok')", version='1.0.0')`; `write_python_package(path, script, outputs=('result.txt',), imports=('os', 'pathlib', 'sys'), *, network_destinations=(), permissions=('read_files', 'create_files'), max_concurrency=1)`; `write_tool_package(path, registry, stages, *, package_id='tool-stage-test')`

### `tests/test_browser.py`

- Role: Offline contract tests; no browser, file deletion, network, or Copilot send.
- Direct imports: `asyncio`, `copilot_agent`, `copilot_agent.browser`, `copilot_agent.protocol`, `copilot_agent.reused_browser`, `hashlib`, `json`, `pathlib`, `sys`, `tempfile`, `types`, `unittest`, `unittest.mock`
- Public symbols: `class CodeExpansionTests(unittest.IsolatedAsyncioTestCase); 2 public methods`; `class CorrelationTests(unittest.TestCase); 3 public methods`; `class ExchangeTests(unittest.IsolatedAsyncioTestCase); 16 public methods`; `class FakeButton; 3 public methods`; `class FakeEditor; 3 public methods`; `class InteractionReadinessTests(unittest.IsolatedAsyncioTestCase); 3 public methods`; `class OfflineAdapter(BrowserAdapter); 12 public methods`; `class PreloadedOfflineAdapter(OfflineAdapter); 3 public methods`; `class ReadinessAdapter(BrowserAdapter); 7 public methods`; `class ReadinessControl; 1 public methods`; `class RemainingCorrelationTests(unittest.TestCase); 14 public methods`; `class StartupRecoveryTests(unittest.IsolatedAsyncioTestCase); 9 public methods`; `class ToolContextTests(unittest.IsolatedAsyncioTestCase); 10 public methods`

### `tests/test_browser_inspection.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `asyncio`, `copilot_agent.browser_inspection`, `copilot_agent.policy`, `copilot_agent.tools`, `hashlib`, `json`, `pathlib`, `tempfile`, `tests`, `types`, `unittest`, `unittest.mock`
- Public symbols: `class InspectionBrowserTests(unittest.IsolatedAsyncioTestCase); 3 public methods`; `class InspectionConcurrencyTests(unittest.IsolatedAsyncioTestCase); 1 public methods`

### `tests/test_browser_plan_extensions.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `copilot_agent.approvals`, `copilot_agent.orchestrator`, `copilot_agent.tools`, `pathlib`, `tempfile`, `types`, `unittest`
- Public symbols: `class BrowserPlanExtensionTests(unittest.TestCase); 5 public methods`; `class QuietFeedback; 3 public methods`

### `tests/test_bug_handoff.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `copilot_agent.app`, `copilot_agent.config`, `copilot_agent.state`, `pathlib`, `tempfile`, `unittest`, `unittest.mock`
- Public symbols: `class BugHandoffTests(unittest.TestCase); 1 public methods`

### `tests/test_bundle.py`

- Role: Lossless bundle tests with retained local fixtures; no ZIP/network/browser.
- Direct imports: `copilot_agent.bundle`, `copilot_agent.config`, `copy`, `hashlib`, `json`, `os`, `pathlib`, `tempfile`, `unittest`
- Public symbols: `class BundleTests(unittest.TestCase); 17 public methods`

### `tests/test_business_data_work.py`

- Role: Customer/company data is usable; effects and record identity remain checked.
- Direct imports: `copilot_agent.automation_packages`, `copilot_agent.policy`, `copilot_agent.reconciliation`, `copilot_agent.tools`, `json`, `pathlib`, `tempfile`, `types`, `unittest`, `unittest.mock`
- Public symbols: `class BusinessDataTests(unittest.IsolatedAsyncioTestCase); 6 public methods`

### `tests/test_code_runner.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `asyncio`, `copilot_agent.code_runner`, `copilot_agent.local_python_runner`, `copilot_agent.policy`, `copilot_agent.tools`, `hashlib`, `json`, `os`, `pathlib`, `subprocess`, `sys`, `tempfile`, `time`, `unittest`, `unittest.mock`
- Public symbols: `class CodeRunnerTests(unittest.TestCase); 20 public methods`; `class LocalPythonRunnerTests(unittest.TestCase); 21 public methods`

### `tests/test_crawl4ai_discovery.py`

- Role: Real offline Crawl4AI + synthetic pinned transport; no VDI/shared-drive proof.
- Direct imports: `asyncio`, `copilot_agent.discovery_contracts`, `copilot_agent.discovery_engine`, `copilot_agent.discovery_http`, `copilot_agent.discovery_knowledge`, `copilot_agent.discovery_scope`, `json`, `tests.discovery_fixtures`, `unittest`, `unittest.mock`
- Public symbols: `class Crawl4AITests(unittest.IsolatedAsyncioTestCase); 6 public methods`; `class SharedMappingTests(unittest.TestCase); 3 public methods`

### `tests/test_delivery.py`

- Role: Pure intent/instruction tests: no browser, files, network or execution.
- Direct imports: `copilot_agent.delivery`, `unittest`
- Public symbols: `class DeliveryRequirementTests(unittest.TestCase); 17 public methods`; `class DeliveryRetryTests(unittest.TestCase); 4 public methods`

### `tests/test_delivery_integration.py`

- Role: Delivery evidence, immutable observed-artifact approval and log redaction.
- Direct imports: `asyncio`, `copilot_agent.approvals`, `copilot_agent.logging_utils`, `copilot_agent.orchestrator`, `copilot_agent.policy`, `hashlib`, `json`, `pathlib`, `tests.test_orchestrator`, `tests.test_protocol_state`, `unittest`, `unittest.mock`, `zipfile`
- Public symbols: `class DeliveryIntegrationTests(unittest.IsolatedAsyncioTestCase); 14 public methods`; `class ExtractionLocationTests(unittest.IsolatedAsyncioTestCase); 1 public methods`; `class SignedLinkTests(unittest.TestCase); 3 public methods`

### `tests/test_diagnostics.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `copilot_agent.config`, `copilot_agent.diagnostics`, `copilot_agent.feedback`, `json`, `os`, `pathlib`, `tempfile`, `unittest`
- Public symbols: `class DiagnosticReportTests(unittest.TestCase); 4 public methods`

### `tests/test_discovery_contracts.py`

- Role: NOT RUN in static staging. Contract/policy tests for a later authorised phase.
- Direct imports: `copilot_agent.discovery_contracts`, `copilot_agent.discovery_http`, `copilot_agent.discovery_scope`, `copilot_agent.protocol`, `copy`, `json`, `tests.discovery_fixtures`, `unittest`
- Public symbols: `class ContractTests(unittest.TestCase); 20 public methods`

### `tests/test_discovery_engine.py`

- Role: NOT RUN. Future mocked scheduler/transport/store/privacy tests; no real egress.
- Direct imports: `asyncio`, `copilot_agent.discovery_contracts`, `copilot_agent.discovery_engine`, `copilot_agent.discovery_http`, `copilot_agent.discovery_store`, `copilot_agent.tools`, `copy`, `json`, `os`, `tests.discovery_fixtures`, `unittest`, `unittest.mock`
- Public symbols: `class EngineTests(unittest.IsolatedAsyncioTestCase); 13 public methods`; `static_response(reader, url, deadline, method='GET')`

### `tests/test_discovery_knowledge.py`

- Role: NOT RUN. Future consent/CAS/independent-proof/static-intent tests, mocked egress.
- Direct imports: `copilot_agent.discovery_contracts`, `copilot_agent.discovery_engine`, `copilot_agent.discovery_knowledge`, `copy`, `os`, `tests.discovery_fixtures`, `tests.test_discovery_engine`, `unittest`, `unittest.mock`
- Public symbols: `class KnowledgeTests(unittest.IsolatedAsyncioTestCase); 9 public methods`

### `tests/test_discovery_transport.py`

- Role: NOT RUN. Future isolated transport accounting tests; no socket/network creation.
- Direct imports: `asyncio`, `copilot_agent.discovery_contracts`, `copilot_agent.discovery_http`, `copilot_agent.discovery_scope`, `copilot_agent.discovery_store`, `ssl`, `tests.discovery_fixtures`, `time`, `types`, `unittest`, `unittest.mock`
- Public symbols: `class FakeTLS; 5 public methods`; `class FakeTLSContext; 1 public methods`; `class TransportTests(unittest.IsolatedAsyncioTestCase); 6 public methods`

### `tests/test_document_catalogue.py`

- Role: Large authorised collections stay retrievable within the hard upload budget.
- Direct imports: `copilot_agent.policy`, `copilot_agent.web_documents`, `hashlib`, `json`, `pathlib`, `tempfile`, `unittest`
- Public symbols: `class CatalogueTests(unittest.IsolatedAsyncioTestCase); 14 public methods`

### `tests/test_downloads.py`

- Role: Offline event/approval contracts; retained fixtures, no cleanup or live UI.
- Direct imports: `asyncio`, `base64`, `copilot_agent.downloads`, `copilot_agent.policy`, `copy`, `hashlib`, `json`, `os`, `pathlib`, `types`, `unittest`, `unittest.mock`, `uuid`
- Public symbols: `class ArgumentsTests(unittest.TestCase); 1 public methods`; `class DownloadCompletionTests(unittest.IsolatedAsyncioTestCase); 1 public methods`; `class DownloadPathIdentityTests(unittest.TestCase); 1 public methods`; `class DownloadTests(unittest.IsolatedAsyncioTestCase); 30 public methods`; `class FakeAnchor; 3 public methods`; `class FakeContext; 2 public methods`; `class FakeDownload; 4 public methods`; `class FakeLocator; 3 public methods`; `class FakePage; 4 public methods`; `class FakeSettingsPage; 4 public methods`; `class Pending; 4 public methods`

### `tests/test_edge_native_safety.py`

- Role: Exercise actual Windows ownership inspection without unsafe pointer reads.
- Direct imports: `asyncio`, `copilot_agent`, `copilot_agent.browser`, `ctypes`, `json`, `os`, `pathlib`, `socket`, `subprocess`, `tempfile`, `types`, `unittest`, `unittest.mock`
- Public symbols: `class LaunchCrashRecoveryTests(unittest.IsolatedAsyncioTestCase); 4 public methods`; `class NativeInspectionSafetyTests(unittest.TestCase); 6 public methods`

### `tests/test_edge_startup.py`

- Role: Focused Edge startup and CDP failure tests; no real browser or user profile.
- Direct imports: `copilot_agent`, `copilot_agent.browser`, `json`, `os`, `pathlib`, `socket`, `tempfile`, `types`, `unittest`, `unittest.mock`, `urllib.request`
- Public symbols: `class EdgeHandshakeTests(unittest.IsolatedAsyncioTestCase); 11 public methods`; `class EdgeLaunchTests(unittest.TestCase); 13 public methods`; `class EdgeOwnerTests(unittest.IsolatedAsyncioTestCase); 1 public methods`

### `tests/test_feedback.py`

- Role: Public previews stay separate from validated execution authority.
- Direct imports: `copilot_agent.config`, `copilot_agent.feedback`, `copilot_agent.protocol`, `copilot_agent.tools`, `json`, `tests`, `unittest`, `unittest.mock`
- Public symbols: `class FeedbackIntegrationTests(unittest.IsolatedAsyncioTestCase); 3 public methods`; `class PreviewTests(unittest.TestCase); 9 public methods`

### `tests/test_file_picker.py`

- Role: Picker options and cancellation contracts without opening desktop windows.
- Direct imports: `copilot_agent.attachments`, `copilot_agent.file_picker`, `os`, `pathlib`, `unittest`, `unittest.mock`
- Public symbols: `class FilePickerTests(unittest.TestCase); 10 public methods`

### `tests/test_isolated_proof_mode.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `copilot_agent.app`, `copilot_agent.config`, `copilot_agent.policy`, `copilot_agent.tools`, `pathlib`, `sys`, `tempfile`, `tests.live_package_run`, `types`, `unittest`, `unittest.mock`
- Public symbols: `class IsolatedProofModeTests(unittest.TestCase); 14 public methods`

### `tests/test_knowledge_health.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `copilot_agent.discovery_contracts`, `copilot_agent.knowledge_health`, `json`, `pathlib`, `tempfile`, `unittest`, `unittest.mock`
- Public symbols: `class KnowledgeHealthTests(unittest.TestCase); 7 public methods`

### `tests/test_knowledge_repair.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `copilot_agent.discovery_store`, `copilot_agent.knowledge_health`, `copilot_agent.knowledge_notes`, `copilot_agent.orchestrator`, `copilot_agent.site_knowledge`, `copilot_agent.tools`, `json`, `os`, `tests.test_orchestrator`, `tests.test_protocol_state`, `unittest`, `unittest.mock`
- Public symbols: `class KnowledgeRepairTests(unittest.IsolatedAsyncioTestCase); 7 public methods`

### `tests/test_launcher.py`

- Role: Exercise the launcher's actual Python portability probe without private S:.
- Direct imports: `ast`, `os`, `pathlib`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `unittest`, `unittest.mock`
- Public symbols: `class PythonSetupChoiceTests(unittest.TestCase); 24 public methods`; `class SharedPathFallbackTests(unittest.TestCase); 1 public methods`; `class SharedRuntimeProbeTests(unittest.TestCase); 16 public methods`

### `tests/test_local_crawler.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `asyncio`, `copilot_agent.local_crawler`, `copilot_agent.session_setup`, `copilot_agent.tools`, `json`, `pathlib`, `tempfile`, `threading`, `types`, `unittest`, `unittest.mock`
- Public symbols: `class EdgeContext; 2 public methods`; `class LocalCrawlerTests(unittest.IsolatedAsyncioTestCase); 19 public methods`; `class Page; 5 public methods`

### `tests/test_local_navigation.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `asyncio`, `copilot_agent.local_navigation`, `copilot_agent.policy`, `copilot_agent.tools`, `errno`, `hashlib`, `pathlib`, `tempfile`, `types`, `unittest`, `unittest.mock`
- Public symbols: `class LocalNavigationTests(unittest.TestCase); 11 public methods`

### `tests/test_model_picker_dom.py`

- Role: Replay the changed picker structure in an isolated, offline Edge page.
- Direct imports: `copilot_agent.browser`, `types`, `unittest`, `unittest.mock`
- Public symbols: `class ModelPickerDOMTests(unittest.IsolatedAsyncioTestCase); 4 public methods`

### `tests/test_orchestrator.py`

- Role: Mock transport/registry tests; no browser, network or deletion.
- Direct imports: `asyncio`, `copilot_agent.browser`, `copilot_agent.orchestrator`, `copilot_agent.policy`, `copilot_agent.protocol`, `copilot_agent.state`, `copilot_agent.tools`, `copilot_agent.web_privacy`, `copy`, `hashlib`, `io`, `json`, `os`, `pathlib`, `sys`, `tests.test_protocol_state`, `threading`, `time`, `unittest`, `unittest.mock`, `zipfile`
- Public symbols: `class MockBrowser; 3 public methods`; `class OrchestratorTests(unittest.IsolatedAsyncioTestCase); 62 public methods`; `class PreloadingBrowser(MockBrowser); 3 public methods`; `final_response(message, **changes)`; `tool_response(message, call_id='read-one', name='synthetic.read', arguments=None)`

### `tests/test_outbound_results.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `copilot_agent.browser`, `copilot_agent.orchestrator`, `copilot_agent.outbound_results`, `copilot_agent.policy`, `copilot_agent.tools`, `json`, `pathlib`, `tempfile`, `tests.test_browser`, `tests.test_orchestrator`, `tests.test_protocol_state`, `unittest`, `unittest.mock`
- Public symbols: `class LimitedBrowser(MockBrowser); 1 public methods`; `class OutboundResultTests(unittest.IsolatedAsyncioTestCase); 4 public methods`; `class PackingTests(unittest.TestCase); 7 public methods`

### `tests/test_package_terminal_flow.py`

- Role: Real terminal routing and ZIP execution with an offline Copilot transport.
- Direct imports: `asyncio`, `copilot_agent`, `copilot_agent.orchestrator`, `copilot_agent.terminal_input`, `copilot_agent.tools`, `hashlib`, `pathlib`, `queue`, `tests.test_automation_packages`, `tests.test_orchestrator`, `tests.test_protocol_state`, `threading`, `unittest`, `unittest.mock`
- Public symbols: `class PackageTerminalFlowTests(unittest.IsolatedAsyncioTestCase); 1 public methods`

### `tests/test_permissive_mode.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `asyncio`, `copilot_agent.code_runner`, `copilot_agent.config`, `copilot_agent.local_navigation`, `copilot_agent.policy`, `copilot_agent.reconciliation`, `copilot_agent.session_mode`, `copilot_agent.site_knowledge`, `copilot_agent.tools`, `copilot_agent.web_navigation`, `hashlib`, `pathlib`, `sys`, `tempfile`, `types`, `unittest`, `unittest.mock`
- Public symbols: `class PermissiveModeTests(unittest.IsolatedAsyncioTestCase); 10 public methods`

### `tests/test_persistence.py`

- Role: Persistence on Windows shares with legacy path-length limits.
- Direct imports: `copilot_agent.persistence`, `errno`, `os`, `pathlib`, `tempfile`, `unittest`, `unittest.mock`
- Public symbols: `class PersistencePathTests(unittest.TestCase); 2 public methods`

### `tests/test_protocol_state.py`

- Role: Contract/state checks with retained artifacts and no external tools.
- Direct imports: `asyncio`, `copilot_agent.approvals`, `copilot_agent.config`, `copilot_agent.findings`, `copilot_agent.prompts`, `copilot_agent.protocol`, `copilot_agent.state`, `copy`, `json`, `os`, `pathlib`, `tempfile`, `unittest`, `unittest.mock`
- Public symbols: `class FixtureRegistry; 3 public methods`; `class ProtocolTests(unittest.TestCase); 8 public methods`; `class StateAndPromptTests(unittest.TestCase); 31 public methods`; `encoded(value)`; `envelope(session='session', request='request', **changes)`; `make_fixture(prefix='contract-')`; `retained_root(prefix)`

### `tests/test_reconciliation.py`

- Role: Automatic reconciliation uses the original owned tab and fresh page state.
- Direct imports: `copilot_agent.reconciliation`, `copilot_agent.state`, `copilot_agent.tools`, `pathlib`, `tempfile`, `unittest`
- Public symbols: `class Browser; 2 public methods`; `class Page; 5 public methods`; `class ReconciliationTests(unittest.IsolatedAsyncioTestCase); 21 public methods`; `class RecoveryOrchestrationTests(unittest.IsolatedAsyncioTestCase); 2 public methods`

### `tests/test_setup_dependencies.py`

- Role: Installer path/reuse regressions; simulated VDI error, actual offline pip proof.
- Direct imports: `importlib.util`, `os`, `pathlib`, `subprocess`, `sys`, `tempfile`, `types`, `unittest`, `zipfile`
- Public symbols: `class DependencySetupTests(unittest.TestCase); 9 public methods`

### `tests/test_setup_resources.py`

- Role: Exercise Edge resource choices without launching executables.
- Direct imports: `copilot_agent.config`, `copilot_agent.setup_resources`, `copilot_agent.storage`, `os`, `pathlib`, `tempfile`, `types`, `unittest`, `unittest.mock`
- Public symbols: `class ResourceSetupTests(unittest.IsolatedAsyncioTestCase); 7 public methods`

### `tests/test_site_knowledge.py`

- Role: Deterministic privacy, consent, freshness and namespace isolation tests.
- Direct imports: `copilot_agent.policy`, `copilot_agent.protocol`, `copilot_agent.site_knowledge`, `copilot_agent.state`, `copy`, `datetime`, `json`, `os`, `pathlib`, `tempfile`, `types`, `unittest`, `unittest.mock`
- Public symbols: `class SiteKnowledgeTests(unittest.TestCase); 38 public methods`

### `tests/test_storage.py`

- Role: Isolated storage selection checks; never scan an actual S: drive/account.
- Direct imports: `copilot_agent.config`, `copilot_agent.storage`, `json`, `os`, `pathlib`, `tempfile`, `unittest`, `unittest.mock`
- Public symbols: `class StorageTests(unittest.TestCase); 13 public methods`

### `tests/test_supervised_session.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `copilot_agent.approvals`, `copilot_agent.config`, `copilot_agent.policy`, `copilot_agent.state`, `copilot_agent.web_navigation`, `copy`, `pathlib`, `tempfile`, `tests`, `tests.test_orchestrator`, `tests.test_web_navigation`, `unittest`, `unittest.mock`
- Public symbols: `class SupervisedSessionTests(unittest.IsolatedAsyncioTestCase); 7 public methods`

### `tests/test_sync.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `asyncio`, `copilot_agent.sync`, `pathlib`, `tempfile`, `unittest`
- Public symbols: `class SyncTests(unittest.IsolatedAsyncioTestCase); 4 public methods`

### `tests/test_temp_storage.py`

- Role: Regression tests for startup temporary-storage recovery.
- Direct imports: `copilot_agent.temp_storage`, `errno`, `pathlib`, `tempfile`, `unittest`, `unittest.mock`
- Public symbols: `class TempStorageTests(unittest.TestCase); 5 public methods`

### `tests/test_terminal_input.py`

- Role: Synthetic terminal input routing tests; never access a real terminal.
- Direct imports: `asyncio`, `copilot_agent.terminal_input`, `queue`, `threading`, `time`, `unittest`
- Public symbols: `class TerminalInputTests(unittest.IsolatedAsyncioTestCase); 10 public methods`

### `tests/test_tools.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `asyncio`, `copilot_agent.approvals`, `copilot_agent.config`, `copilot_agent.policy`, `copilot_agent.state`, `copilot_agent.tools`, `hashlib`, `os`, `pathlib`, `tempfile`, `unittest`, `unittest.mock`
- Public symbols: `class ToolTests(unittest.TestCase); 39 public methods`

### `tests/test_version_launcher.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `importlib.util`, `pathlib`, `subprocess`, `sys`, `tempfile`, `unittest`, `unittest.mock`
- Public symbols: `class VersionTests(unittest.TestCase); 9 public methods`

### `tests/test_web_documents.py`

- Role: Native-browser document contracts with deterministic controlled artifacts.
- Direct imports: `asyncio`, `copilot_agent.policy`, `copilot_agent.web_documents`, `hashlib`, `json`, `pathlib`, `tempfile`, `unittest`
- Public symbols: `class DocumentTests(unittest.IsolatedAsyncioTestCase); 23 public methods`; `class FakeBrowser; 2 public methods`; `class FakeContext; 2 public methods`; `class FakeDownload; 4 public methods`; `class FakePage; 8 public methods`; `class Pending; 4 public methods`; `class Response; 2 public methods`; `class ShapeTests(unittest.TestCase); 2 public methods`

### `tests/test_web_navigation.py`

- Role: Executable headless browser fixtures; requests are fulfilled locally, never production.
- Direct imports: `asyncio`, `copilot_agent.policy`, `copilot_agent.web_navigation`, `copy`, `pathlib`, `tempfile`, `types`, `unittest`
- Public symbols: `class NavigationBrowserTests(unittest.IsolatedAsyncioTestCase); 29 public methods`; `class NavigationSchemaTests(unittest.TestCase); 3 public methods`; `search_plan()`

### `tests/test_web_operations.py`

- Role: Implementation module; responsibilities are identified by its public symbols and imports.
- Direct imports: `copilot_agent.discovery_contracts`, `copilot_agent.discovery_http`, `copilot_agent.discovery_store`, `copilot_agent.web_operations`, `json`, `pathlib`, `tempfile`, `threading`, `unittest`, `unittest.mock`, `urllib.parse`
- Public symbols: `class OperationTests(unittest.IsolatedAsyncioTestCase); 11 public methods`

### `tests/test_web_privacy.py`

- Role: Private live context, immutable reviews and durable audit never copy customer facts.
- Direct imports: `copilot_agent.approvals`, `copilot_agent.config`, `copilot_agent.feedback`, `copilot_agent.findings`, `copilot_agent.orchestrator`, `copilot_agent.prompts`, `copilot_agent.state`, `copilot_agent.web_privacy`, `copy`, `json`, `pathlib`, `tempfile`, `tests.test_orchestrator`, `tests.test_protocol_state`, `unittest`
- Public symbols: `class WebPrivacyTests(unittest.IsolatedAsyncioTestCase); 12 public methods`

### `tests/test_web_transport.py`

- Role: Shared website capabilities and reviewed file queues across actual orchestrator sends.
- Direct imports: `copilot_agent.browser`, `copilot_agent.orchestrator`, `copilot_agent.policy`, `copilot_agent.tools`, `hashlib`, `json`, `pathlib`, `tests.test_orchestrator`, `tests.test_protocol_state`, `tests.test_web_documents`, `threading`, `unittest`
- Public symbols: `class WebTransportTests(unittest.IsolatedAsyncioTestCase); 8 public methods`

### `tests/test_website_integration.py`

- Role: Real Edge on synthetic HTTPS routes; no live website or Copilot account.
- Direct imports: `asyncio`, `copilot_agent.browser`, `copilot_agent.policy`, `copilot_agent.site_knowledge`, `copilot_agent.tools`, `hashlib`, `json`, `pathlib`, `playwright.async_api`, `tempfile`, `time`, `types`, `unittest`
- Public symbols: `class WebsiteIntegrationTests(unittest.IsolatedAsyncioTestCase); 9 public methods`

### `version_launcher.py`

- Role: Local complete-copy testing versions. Requires neither Git nor extra packages.
- Direct imports: `__future__`, `datetime`, `hashlib`, `json`, `os`, `pathlib`, `shutil`, `subprocess`, `sys`, `uuid`
- Public symbols: `choose_source(live, ask=input, choice=None)`; `create_version(live, proposals, previous=None)`; `digest(path)`; `main()`; `prepare_drop_folder(live)`; `replacement_map(live, proposals)`; `source_files(root)`


## Graphify relationship evidence

Generated from the local Graphify code-only AST graph. The raw graph, cache, and Graphify report are not attachments; the statistics and selected relationships below preserve their useful navigation evidence.

- Graphify version: `0.9.79`
- Source revision analyzed: `unrecorded`
- Nodes / edges / hyperedges: 3099 / 9382 / 0
- Relationship counts: calls=3847, contains=977, imports=1418, imports_from=641, indirect_call=350, inherits=37, method=1412, rationale_for=319, references=90, uses=291
- Graph origin: Graphify AST extraction; inferred edges are hypotheses, not verified behavior.

### Highest-connectivity source symbols

- `PolicyError` — 197 graph links; `copilot_agent/policy.py` at `L9`.
- `Orchestrator` — 135 graph links; `copilot_agent/orchestrator.py` at `L29`.
- `ToolRegistry` — 119 graph links; `copilot_agent/tools.py` at `L367`.
- `tools.py` — 116 graph links; `copilot_agent/tools.py` at `L1`.
- `PathPolicy` — 115 graph links; `copilot_agent/policy.py` at `L42`.
- `DiscoveryError` — 113 graph links; `copilot_agent/discovery_contracts.py` at `L64`.
- `SessionState` — 99 graph links; `copilot_agent/state.py` at `L62`.
- `BrowserAdapter` — 97 graph links; `copilot_agent/browser.py` at `L324`.
- `orchestrator.py` — 92 graph links; `copilot_agent/orchestrator.py` at `L1`.
- `Store` — 87 graph links; `copilot_agent/discovery_store.py` at `L44`.
- `copilot_agent/app.py` — 86 graph links; `copilot_agent/app.py` at `L1`.
- `final_response()` — 84 graph links; `tests/test_orchestrator.py` at `L65`.
- `site_knowledge.py` — 73 graph links; `copilot_agent/site_knowledge.py` at `L1`.
- `Config` — 71 graph links; `copilot_agent/config.py` at `L26`.
- `OrchestratorTests` — 71 graph links; `tests/test_orchestrator.py` at `L77`.
- `automation_packages.py` — 70 graph links; `copilot_agent/automation_packages.py` at `L1`.
- `live_package_run.py` — 57 graph links; `tests/live_package_run.py` at `L1`.
- `policy.py` — 57 graph links; `copilot_agent/policy.py` at `L1`.

### Direct, source-derived relationships

Each row is an AST-extracted graph edge; source file and line come from the Graphify edge.

- `agent_ui/runtime.py:L113` `.__init__()` **calls** `._start_agent()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L150` `._run_agent()` **calls** `Feedback` in `copilot_agent/feedback.py`.
- `agent_ui/runtime.py:L206` `.submit()` **calls** `.steer()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L278` `.poll_steering()` **calls** `._cancel_pending_steering_locked()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L299` `._cancel_pending_steering()` **calls** `._cancel_pending_steering_locked()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L309` `.permission_snapshot()` **calls** `.permission_context()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L309` `.permission_snapshot()` **calls** `list_grants()` in `copilot_agent/research_permissions.py`.
- `agent_ui/runtime.py:L314` `.manage_permission()` **calls** `.permission_context()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L315` `.manage_permission()` **calls** `manage()` in `copilot_agent/research_permissions.py`.
- `agent_ui/runtime.py:L319` `.manage_permission()` **calls** `prepare_permissions()` in `copilot_agent/research_permissions.py`.
- `agent_ui/runtime.py:L322` `.manage_permission()` **calls** `canonical_hash()` in `copilot_agent/state.py`.
- `agent_ui/runtime.py:L328` `.manage_permission()` **calls** `execute_permissions()` in `copilot_agent/research_permissions.py`.
- `agent_ui/runtime.py:L333` `.action()` **calls** `._cancel_pending_steering()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L368` `.close()` **calls** `._cancel_pending_steering()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L373` `.close()` **calls** `.complete_steering()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L377` `create_runtime()` **calls** `AgentRuntime` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L384` `main()` **calls** `main()` in `agent_ui/workspace.py`.
- `agent_ui/runtime.py:L91` `.__init__()` **calls** `PromptBroker` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L121` `runtime.py` **imports** `Feedback` in `copilot_agent/feedback.py`.
- `agent_ui/runtime.py:L308` `runtime.py` **imports** `list_grants()` in `copilot_agent/research_permissions.py`.
- `agent_ui/runtime.py:L312` `runtime.py` **imports** `execute_permissions()` in `copilot_agent/research_permissions.py`.
- `agent_ui/runtime.py:L312` `runtime.py` **imports** `manage()` in `copilot_agent/research_permissions.py`.
- `agent_ui/runtime.py:L312` `runtime.py` **imports** `prepare_permissions()` in `copilot_agent/research_permissions.py`.
- `agent_ui/runtime.py:L313` `runtime.py` **imports** `canonical_hash()` in `copilot_agent/state.py`.
- `agent_ui/runtime.py:L381` `runtime.py` **imports** `main()` in `agent_ui/workspace.py`.
- `agent_ui/runtime.py:L120` `runtime.py` **imports_from** `copilot_agent/app.py` in `copilot_agent/app.py`.
- `agent_ui/runtime.py:L115` `AgentRuntime` **method** `._start_agent()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L119` `AgentRuntime` **method** `._run_agent()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L17` `PromptBroker` **method** `.__init__()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L181` `AgentRuntime` **method** `.submit()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L208` `AgentRuntime` **method** `.take_submitted_attachments()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L213` `AgentRuntime` **method** `.active_run_id()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L217` `AgentRuntime` **method** `.steer()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L259` `AgentRuntime` **method** `.complete_steering()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L26` `PromptBroker` **method** `.ask()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L274` `AgentRuntime` **method** `.poll_steering()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L284` `AgentRuntime` **method** `._cancel_pending_steering_locked()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L297` `AgentRuntime` **method** `._cancel_pending_steering()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L301` `AgentRuntime` **method** `.permission_context()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L307` `AgentRuntime` **method** `.permission_snapshot()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L311` `AgentRuntime` **method** `.manage_permission()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L330` `AgentRuntime` **method** `.action()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L345` `AgentRuntime` **method** `._dispatch_actions()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L358` `AgentRuntime` **method** `._emit()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L363` `AgentRuntime` **method** `.close()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L45` `PromptBroker` **method** `.submit()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L60` `PromptBroker` **method** `.submit_if_waiting()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L73` `PromptBroker` **method** `.close()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L88` `AgentRuntime` **method** `.__init__()` in `agent_ui/runtime.py`.
- `agent_ui/runtime.py:L150` `AgentRuntime` **uses** `Feedback` in `copilot_agent/feedback.py`.
- `agent_ui/workspace.py:L139` `.submit()` **calls** `._message_digest()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L143` `.submit()` **calls** `._existing_message_locked()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L157` `.submit()` **calls** `.steer()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L160` `.submit()` **calls** `.emit()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L173` `run()` **calls** `.emit()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L193` `.steer()` **calls** `._message_digest()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L202` `.steer()` **calls** `._existing_message_locked()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L216` `.steer()` **calls** `.emit()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L24` `_public_file_metadata()` **calls** `_public_file_metadata()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L247` `.upload()` **calls** `.emit()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L272` `.reply()` **calls** `.headers_common()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L281` `.authorized()` **calls** `.valid_host()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L284` `.do_GET()` **calls** `.valid_host()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L285` `.do_GET()` **calls** `.reply()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L288` `.do_GET()` **calls** `.authorized()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L300` `.do_GET()` **calls** `.headers_common()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L306` `.do_POST()` **calls** `.authorized()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L319` `.do_POST()` **calls** `.reply()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L376` `main()` **calls** `Workspace` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L40` `.__init__()` **calls** `UploadStore` in `agent_ui/uploads.py`.
- `agent_ui/workspace.py:L72` `.emit()` **calls** `_public_file_metadata()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L97` `.request_approval()` **calls** `_public_file_metadata()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L99` `.request_approval()` **calls** `.emit()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L16` `workspace.py` **imports** `UploadStore` in `agent_ui/uploads.py`.
- `agent_ui/workspace.py:L16` `workspace.py` **imports_from** `uploads.py` in `agent_ui/uploads.py`.
- `agent_ui/workspace.py:L106` `Workspace` **method** `.decide()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L120` `Workspace` **method** `.snapshot()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L128` `Workspace` **method** `.submit()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L182` `Workspace` **method** `.steer()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L225` `Workspace` **method** `._message_digest()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L230` `Workspace` **method** `._existing_message_locked()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L240` `Workspace` **method** `.upload()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L253` `Workspace` **method** `.close()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L261` `Handler` **method** `.log_message()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L264` `Handler` **method** `.headers_common()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L270` `Handler` **method** `.reply()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L276` `Handler` **method** `.valid_host()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L279` `Handler` **method** `.authorized()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L283` `Handler` **method** `.do_GET()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L304` `Handler` **method** `.do_POST()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L33` `Workspace` **method** `.__init__()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L62` `Workspace` **method** `.emit()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L88` `Workspace` **method** `.request_approval()` in `agent_ui/workspace.py`.
- `agent_ui/workspace.py:L40` `Workspace` **uses** `UploadStore` in `agent_ui/uploads.py`.
- `app.py:L1` `app.py` **imports** `main()` in `copilot_agent/app.py`.
- `app.py:L1` `app.py` **imports_from** `copilot_agent/app.py` in `copilot_agent/app.py`.
- `copilot_agent/app.py:L115` `_show_bug_handoff()` **calls** `system()` in `copilot_agent/app.py`.
- `copilot_agent/app.py:L169` `_choose_existing_endpoint()` **calls** `system()` in `copilot_agent/app.py`.
- `copilot_agent/app.py:L189` `choose_browser_endpoint()` **calls** `machine_key()` in `copilot_agent/storage.py`.
- `copilot_agent/app.py:L214` `choose_browser_endpoint()` **calls** `cdp_endpoint()` in `copilot_agent/reused_browser.py`.

### Inferred relationship examples

These are Graphify hypotheses and must be checked against source before relying on them.

- No inferred edges are present.


## Configuration and response contract summary

Sources: `config.example.json`, `copilot_agent/config.py`, `schemas/response-v1.schema.json`, `schemas/tool-catalogue-v1.json`.

### Example configuration keys

- `allowed_domains`: example value `["example.com"]`.
- `allowed_roots`: example value `["workspace", "deliveries"]`.
- `attach_existing`: example value `false`.
- `automation_max_output_chars`: example value `65536`.
- `automation_max_parallel_stages`: example value `4`.
- `automation_max_runtime_seconds`: example value `1800`.
- `automation_max_stages`: example value `100`.
- `automation_minimum_files`: example value `3`.
- `automation_minimum_runtime_seconds`: example value `120`.
- `automation_minimum_steps`: example value `4`.
- `automation_package_score`: example value `8`.
- `bounded_parallelism`: example value `true`.
- `copilot_download_hosts`: example value `["eu-prod.asyncgw.teams.microsoft.com", "m365.cloud.microsoft"]`.
- `created_dir`: example value `null`.
- `created_sync_enabled`: example value `false`.
- `customer_data_work`: example value `true`.
- `debug_port`: example value `9443`.
- `discovery_extractor`: example value `"crawl4ai"`.
- `download_timeout`: example value `90`.
- `knowledge_directory`: example value `null`.
- `knowledge_reuse`: example value `true`.
- `knowledge_write`: example value `true`.
- `local_recovery`: example value `true`.
- `manifest_path`: example value `true`.
- `max_corrections`: example value `12`.
- `max_delivery_retries`: example value `3`.
- `max_download_bytes`: example value `20971520`.
- `operation_reuse`: example value `false`.
- `persistent_graph`: example value `true`.
- `response_timeout`: example value `180`.
- `sync_timeout`: example value `120`.
- `targeted_repair`: example value `false`.
- `visible`: example value `true`.

### Structured Copilot response envelope

The JSON Schema requires: `protocol_version`, `session_id`, `request_id`, `response_id`, `response_type`, `user_response`, `task_interpretation`, `decision_summary`, `assumptions`, `action_plan`, `tools_required`, `tool_requests`, `approval_required`, `code_runner_proposal`, `risk_summary`, `continuation_state`, `clarification`, `useful_findings`, `completion_status`, `recoverable_errors`.
Declared response properties: `protocol_version`, `session_id`, `request_id`, `response_id`, `response_type`, `user_response`, `task_interpretation`, `decision_summary`, `assumptions`, `action_plan`, `tools_required`, `tool_requests`, `approval_required`, `code_runner_proposal`, `risk_summary`, `continuation_state`, `clarification`, `useful_findings`, `completion_status`, `recoverable_errors`.
The application also checks identity and cross-field invariants in code; schema validity alone does not authorize execution.

## Tool interface summary

Source: `schemas/tool-catalogue-v1.json`, schema version `1.0`. This generated table summarizes every catalogue operation; the full 333 KB catalogue is intentionally not repeated.

| Tool | Purpose | Risk | Approval | Required arguments | Side effects |
|---|---|---:|---|---|---|
| files.list | List up to 200 immediate children inside allowed roots. | low | read_only | path | none |
| files.exists | Check a path inside allowed roots. | low | read_only | path | none |
| files.read | Read bounded UTF-8 text; binary or oversized reads fail. | low | read_only | path | none |
| files.create | Create a new UTF-8 file exclusively. Never overwrite. | moderate | user_approval | path, text | filesystem creation or append |
| files.append | Append text to an existing file after explicit approval; preserves prior content. | moderate | user_approval | path, text | filesystem creation or append |
| files.copy | Copy one bounded file to a new exclusive destination. | moderate | user_approval | source, destination | filesystem creation or append |
| files.metadata | Read size, modification time and type. | low | read_only | path | none |
| files.hash | Calculate SHA-256 for a file up to 20 MB. | low | read_only | path | none |
| files.mkdir | Create a new directory with an existing allowed parent. | moderate | user_approval | path | filesystem creation or append |
| system.versions | Read the exact current Python executable/version, operating system version and selected package versions; no environment variables. | low | read_only | none | none |
| system.disk | Read filesystem capacity for an allowed path. | low | read_only | path | none |
| system.processes | Report this agent PID and the explicitly launched owned Edge PID when available; no wider process or command-line inventory. | low | read_only | none | none |
| browser.open | After explicit approval, open the HTTPS website in an owned tab of the same verified Edge profile, window and CDP port as Copilot. Returns its stable primary tab_id with the final URL and title for follow-up browser.tabs or browser.recon calls. Existing site sign-ins are shared. Dependency hosts require explicit approval; focus returns to Copilot after the tool. | moderate | user_approval | url | browser interaction or screenshot |
| browser.back | Navigate backward only if the target history URL passes policy. | moderate | user_approval | none | browser interaction or screenshot |
| browser.forward | Navigate forward only if the target history URL passes policy. | moderate | user_approval | none | browser interaction or screenshot |
| browser.info | Read tool-tab URL and title. | low | read_only | none | none |
| browser.read | Read bounded visible body text from the managed tab or one explicit iframe. | low | read_only | none | none |
| browser.structure | Read visible controls without input values from the managed tab or one explicit iframe. | low | read_only | none | none |
| browser.click | Click one unique selector in the managed tab or explicit iframe. May change third-party state. | moderate | user_approval | selector | browser interaction or screenshot |
| browser.fill | Fill one unique ordinary text field; password fields are forbidden. | moderate | user_approval | selector, text | browser interaction or screenshot |
| browser.wait | Wait for a selector to be visible, attached, hidden or detached; bounded to 15 seconds. | low | read_only | selector | none |
| browser.select | Select an option in one unique select control. | moderate | user_approval | selector, value | browser interaction or screenshot |
| browser.press | Press an allowlisted key on one unique non-password control; Enter may submit and is never retried automatically. | moderate | user_approval | selector, key | browser interaction or screenshot |
| browser.frames | List iframe selectors and query-free source URLs. | low | read_only | none | none |
| browser.scroll | Scroll the owned tool page. | moderate | user_approval | pixels | browser interaction or screenshot |
| browser.screenshot | Save a screenshot of the owned tool tab to a unique session file. | moderate | user_approval | none | browser interaction or screenshot |
| browser.errors | Report captured tool-page console errors if the browser adapter supplies them. | low | read_only | none | none |
| browser.downloads | Report observed tool-page download events; absence is not delivery proof. | low | read_only | none | none |
| ocr.image | Check a local image; OCR requires an explicitly available integrated image capability. | moderate | user_approval | path | browser interaction or screenshot |
| created.snapshot | When explicitly enabled, record a baseline of the configured OneDrive Copilot Created files. Otherwise report disabled without filesystem access. | low | read_only | none | none |
| created.wait | When explicitly enabled, wait for stable readable new or changed local OneDrive Created files. Report disabled without filesystem access otherwise. | low | read_only | none | none |
| copilot.download | Download one real clickable artifact link in this exact Copilot response. Set link_text to its exact visible label and expected_name to a plain basename. Set expected_sha256 only when independently known. Inspect Edge settings without changing them; use the approved staging path or verified browser download event. Plaintext and sandbox links are not delivery. | moderate | user_approval | expected_name, link_text | filesystem creation or append |
| archives.inspect | Inspect a bounded ZIP manifest, archive SHA-256 and native Office container type without extracting. | low | read_only | path | none |
| archives.extract | Extract a reviewed SHA-256-bound ZIP exclusively inside allowed roots; preflight paths and verify all files without executing code. Preserve original and partial outputs. | moderate | user_approval | path, destination, expected_sha256 | filesystem creation or append |
| code_runner | Run reviewed code. python_subset remains the default restricted evaluator. local_python is available only for an exact explicitly approved host-Python plan binding script bytes/hash, interpreter, arguments, imports, file/network/process/desktop scope, limits, effects and verification. | moderate | immutable_plan_approval | commands, create_paths, expected_outputs, language, network_destinations, permissions, purpose, read_paths, recovery_notes, risk_summary, script, working_directory | filesystem creation or append |
| browser.recon | Inspect one approved page in one bounded semantic snapshot; return a task-ranked ephemeral site map, controls, forms, tables, documents and security boundaries. No crawling or input values. | low | read_only | none | none |
| browser.route | Rank fresh routes actually observed by reconnaissance in this same origin/session. Missing or stale knowledge requires recon; guessed routes are never executable. | low | read_only | goal | none |
| browser.tabs | Manage at most six owned same-origin tabs with stable IDs and explicit task/customer contexts; preserve the primary page. Reset navigates that page to an approved safe URL before clearing prior task/customer bindings and ephemeral plans/maps. | moderate | user_approval | operation | browser interaction or screenshot |
| browser.plan | Execute one exact approved, bounded semantic action plan with branches/loops, assertions, cancellation and verified partials. Side effects run once, require checkpoints, and uncertain effects block automatic resume. Consequential effects require a separate exact local grant. | moderate | user_approval | task_id, steps, success | browser interaction or screenshot |
| browser.customer_summary | Verify supplied authorised identifiers exactly and uniquely before extracting only requested customer fields. Facts have sources; missing/ambiguous fields are explicit; no inference or persistence. | moderate | user_approval | task_id, customer_key, identity, fields | browser interaction or screenshot |
| browser.documents | Discover up to 100 visible same-origin document links. Returns ephemeral IDs and query-free metadata; does not navigate or download. | low | read_only | none | none |
| browser.download_batch | Download only previously observed same-origin documents in bounded owned tabs; preserve failures and return a SHA-256 manifest. Resume skips only exactly reverified prior outputs. | moderate | user_approval | documents, destination | browser interaction or screenshot |
| files.transfer_to_copilot | Rank up to 1000 reviewed file references, deduplicate exact content, and queue only the remaining message capacity (at most 10 document slots). Retain deferred catalogue references and an index; queued is not proof of UI upload. | moderate | user_approval | files | filesystem creation or append |
| documents.catalogue | Register explicitly selected local file references or import an explicitly reviewed SHA-bound catalogue manifest. Read bounded metadata/hashes, retain task-scoped references, and report exact duplicates and filename-similarity warnings without uploading. | low | read_only | none | none |
| documents.find | Search authorised session document metadata. Rank explicitly requested references and query matches; return concise IDs for on-demand retrieval. | low | read_only | catalogue_id | none |
| documents.retrieve | Resolve specific catalogue references and reverify current SHA-256 and path authority. Returns files for a separately approved transfer; never silently uploads. | low | read_only | catalogue_id, references | none |
| site_knowledge.bind | Select the current HTTPS site's exact tenant, user/sharing scope and environment through local approval. Scope labels are user-declared; never infer an authenticated identity. No website knowledge is saved. | moderate | user_approval | origin, tenant, user_scope, environment | browser interaction or screenshot |
| site_knowledge.retrieve | Retrieve unexpired approved navigation knowledge for the current locally selected site namespace; a namespace must first be bound by the user. | low | read_only | origin | none |
| site_knowledge.query | Filter approved fresh navigation knowledge by category and/or exact generic route template inside the selected namespace. | low | read_only | origin | none |
| site_knowledge.save | Ask the local user whether to save the exact approved categories of sanitized navigation knowledge on this Windows user/device. Declining leaves the current task usable. Customer data and secrets are rejected. Replaces the namespace's prior knowledge after approval. | moderate | user_approval | origin, categories, knowledge | browser interaction or screenshot |
| site_knowledge.invalidate | After local approval, mark the selected namespace's knowledge unusable. It remains on disk as an invalidated record; never automatically re-use it. | moderate | user_approval | origin | browser interaction or screenshot |
| site_knowledge.export | Return a bounded structured summary of fresh knowledge for the approved namespace through the tool result; no arbitrary file export. | low | read_only | origin | none |
| guidance.load | Load up to three relevant website workflow guides; use index to choose topics. | low | read_only | topics | none |
| operation.learn | Learn one public read-only GET from two observed URLs, validate it with unseen inputs, and promote a sanitized versioned operation. Performs exactly three public GETs; no cookies, headers, browser, writes, or automatic fallback. | moderate | user_approval | origin, name, intent, example_url, example_args, example2_url, example2_args, validation_args, response, expected_revision | three approved public HTTPS GET validations and a sanitized versioned operation record |
| operation.list | List compact current public operations retained for one exact origin. No network or browser use. | low | read_only | origin | none |
| operation.call | Execute up to eight retained public GET operations locally, deduplicating identical calls and using bounded concurrency. No Copilot UI or browser round trip; failures are classified and never trigger a write or blind replay. | low | read_only | origin, calls | none |
| browser.recover_uncertain | Quarantine one uncertain non-navigation browser action without crediting its outcome, open a fresh approved same-origin checkpoint, and resume the current run. Never replays the action. | moderate | user_approval | call_id, checkpoint_url | browser interaction or screenshot |

## Verbatim operational entrypoints and response schema

These compact files define how users launch the project and the top-level response structure. They are embedded as source text to let a receiving LLM inspect exact entrypoint behavior.


---

<!-- BEGIN VERBATIM SOURCE: config.example.json -->
## Source: `config.example.json` (verbatim text; line endings normalized to LF)

{
  "customer_data_work": true,
  "debug_port": 9443,
  "attach_existing": false,
  "knowledge_directory": null,
  "visible": true,
  "allowed_roots": [
    "workspace",
    "deliveries"
  ],
  "allowed_domains": [
    "example.com"
  ],
  "response_timeout": 180,
  "max_corrections": 12,
  "sync_timeout": 120,
  "created_dir": null,
  "created_sync_enabled": false,
  "download_timeout": 90,
  "max_download_bytes": 20971520,
  "max_delivery_retries": 3,
  "automation_max_runtime_seconds": 1800,
  "automation_max_stages": 100,
  "automation_max_parallel_stages": 4,
  "automation_max_output_chars": 65536,
  "automation_package_score": 8,
  "automation_minimum_steps": 4,
  "automation_minimum_files": 3,
  "automation_minimum_runtime_seconds": 120,
  "copilot_download_hosts": [
    "eu-prod.asyncgw.teams.microsoft.com",
    "m365.cloud.microsoft"
  ],
  "manifest_path": true,
  "persistent_graph": true,
  "bounded_parallelism": true,
  "local_recovery": true,
  "knowledge_write": true,
  "knowledge_reuse": true,
  "targeted_repair": false,
  "operation_reuse": false,
  "discovery_extractor": "crawl4ai"
}
<!-- END SOURCE: config.example.json -->



---

<!-- BEGIN VERBATIM SOURCE: Launcher.ps1 -->
## Source: `Launcher.ps1` (verbatim text; line endings normalized to LF)

param([ValidateSet('Setup','Start','UI','Tests')][string]$Mode = 'Start')
$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
$productionShare = ([System.IO.Path]::GetPathRoot($repoRoot) -ieq 'S:\')
$candidates = [System.Collections.Generic.List[string]]::new()
$seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

function Test-SharedPythonPath([string]$Value) {
    # Preserve direct S: acceptance; consult mapping providers only for UNC.
    if ([System.IO.Path]::GetPathRoot($Value) -ieq 'S:\') { return $true }
    if (-not $Value.StartsWith('\\') -or $Value.StartsWith('\\?\') -or $Value.StartsWith('\\.\')) { return $false }
    $aliases = [System.Collections.Generic.List[string]]::new()
    try {
        $drive = Get-PSDrive -Name S -PSProvider FileSystem -ErrorAction Stop
        if ($drive.DisplayRoot) { $aliases.Add([string]$drive.DisplayRoot) }
    } catch { }
    if ($aliases.Count -eq 0) {
        try {
            $disk = Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DeviceID='S:'" -ErrorAction Stop
            if ($disk.ProviderName) { $aliases.Add([string]$disk.ProviderName) }
        } catch { }
    }
    if ($aliases.Count -eq 0) {
        try {
            foreach ($mapping in @(Get-SmbMapping -LocalPath 'S:' -ErrorAction Stop)) {
                if ($mapping.RemotePath) { $aliases.Add([string]$mapping.RemotePath) }
            }
        } catch { }
    }
    foreach ($alias in $aliases) {
        $root = $alias.TrimEnd('\')
        if ($Value.Equals($root, [System.StringComparison]::OrdinalIgnoreCase) -or
            $Value.StartsWith($root + '\', [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

function Add-PythonCandidate([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return }
    $candidate = $Value.Trim().Trim('"').Trim("'")
    if ($candidate -notmatch '^(?:[A-Za-z]:\\|\\\\[^\\]+\\[^\\]+\\)') { return }
    if (Test-Path -LiteralPath $candidate -PathType Container) {
        Add-PythonCandidate (Join-Path $candidate 'python.exe')
        Add-PythonCandidate (Join-Path $candidate 'Scripts\python.exe')
        return
    }
    if ([System.IO.Path]::GetFileName($candidate) -ine 'python.exe') { return }
    if ($productionShare -and -not (Test-SharedPythonPath $candidate)) { return }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { return }
    $entry = Get-Item -LiteralPath $candidate -Force
    if (-not (Test-SafePythonEntry $entry)) { return }
    $parent = $entry.Directory
    while ($parent) {
        if (-not (Test-SafePythonEntry $parent)) { return }
        $parent = $parent.Parent
    }
    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    if ($productionShare -and -not (Test-SharedPythonPath $resolved)) { return }
    if ($seen.Add($resolved)) { $candidates.Add($resolved) }
}

function Test-AllowedCloudTag([uint64]$Tag) {
    return (-not $productionShare -and ($Tag -band 4294905855) -eq 2415919130 -and ($Tag -band 536870912) -eq 0)
}

function Test-SafePythonEntry($Entry) {
    if (($Entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) { return $true }
    if ($productionShare) { return $false }
    if (-not ('CopilotLauncher.ReparseMetadata' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
namespace CopilotLauncher {
 public static class ReparseMetadata {
  [StructLayout(LayoutKind.Sequential)] private struct TagInfo { public uint Attributes; public uint Tag; }
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] private static extern SafeFileHandle CreateFileW(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
  [DllImport("kernel32.dll", SetLastError=true)] private static extern bool GetFileInformationByHandleEx(SafeFileHandle handle, int infoClass, out TagInfo info, uint size);
  public static uint ReadTag(string path) {
   using (var handle = CreateFileW(path,0,7,IntPtr.Zero,3,0x02200000,IntPtr.Zero)) {
    if (handle.IsInvalid) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
    TagInfo info;
    if (!GetFileInformationByHandleEx(handle,9,out info,8)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
    return info.Tag;
   }
  }
 }
}
'@
    }
    try { return (Test-AllowedCloudTag ([CopilotLauncher.ReparseMetadata]::ReadTag($Entry.FullName))) } catch { return $false }
}

function Read-PythonMethod {
    Write-Host 'Python setup: 1. Detect automatically  2. Paste an installation folder or python.exe path'
    for ($attempt = 0; $attempt -lt 5; $attempt++) {
        $answer = (Read-Host 'Choose 1 or 2').Trim()
        if ($answer -in @('1','2')) { return $answer }
        Write-Host 'Enter 1 for automatic detection or 2 to paste a path.'
    }
    throw 'Python setup selection stopped after five attempts.'
}

function Read-PythonPath {
    Write-Host 'Paste the full path to python.exe or its installation folder. Surrounding quotes are allowed.'
    if ($productionShare) { Write-Host 'The complete Python installation must be on S:.' }
    for ($attempt = 0; $attempt -lt 5; $attempt++) {
        Add-PythonCandidate (Read-Host 'Python path')
        if ($candidates.Count -gt 0) { return }
        Write-Host 'No usable python.exe was found at that absolute path. Check the folder and access permissions.'
    }
    throw 'Python path entry stopped after five attempts.'
}

function Invoke-SetupPython([string]$Executable, [string[]]$Arguments) {
    # Windows PowerShell 5 turns native stderr into a terminating error when
    # ErrorActionPreference is Stop. Let Python print its complete diagnostic.
    $ErrorActionPreference = 'Continue'
    & $Executable @Arguments | Out-Host
    $commandExitCode = $LASTEXITCODE
    if ($commandExitCode -ne 0) { throw ('Python setup command failed with exit code ' + $commandExitCode + '. See the complete Python error above. Existing files were retained.') }
}

function Get-PipConfiguration([string]$Executable, [string[]]$PythonFlags) {
    $ErrorActionPreference = 'Continue'
    $configuration = @(& $Executable @PythonFlags -m pip config list)
    if ($LASTEXITCODE -ne 0) { throw 'Unable to verify pip installation settings. Existing files were retained.' }
    return ($configuration -join "`n")
}

function Get-WorkingPip([string]$Executable, [string[]]$PythonFlags) {
    $ErrorActionPreference = 'Continue'
    # A damaged virtualenv seed can import pip but lack its distribution metadata.
    $pipProbe = @'
import pip
from importlib.metadata import distribution
package = distribution(pip.__name__)
assert package.version == pip.__version__
print('pip ' + package.version + ' from ' + str(package.locate_file('')))
'@
    $description = @(& $Executable @PythonFlags -c $pipProbe 2>$null)
    if ($LASTEXITCODE -ne 0 -or $description.Count -eq 0) { return $null }
    return ($description -join ' ').Trim()
}

function Get-RecoveryBasePython([string]$SelectedPython, [string[]]$PythonFlags, [string]$EnvironmentPython) {
    if ([System.IO.Path]::GetFullPath($SelectedPython) -ine [System.IO.Path]::GetFullPath($EnvironmentPython)) { return $SelectedPython }
    $ErrorActionPreference = 'Continue'
    $locator = @'
import sys
print(getattr(sys, '_base_executable', ''))
print(sys.base_prefix)
'@
    $reported = @(& $SelectedPython @PythonFlags -c $locator 2>$null)
    if ($LASTEXITCODE -ne 0 -or $reported.Count -lt 2) { throw 'The selected project environment cannot report its base Python installation. Existing files were retained.' }
    $possible = @([string]$reported[0], (Join-Path ([string]$reported[1]) 'python.exe'))
    foreach ($candidate in $possible) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            Write-Host ('Using the project environment''s reported base Python: ' + $candidate)
            return $candidate
        }
    }
    throw 'The selected project environment has no accessible base Python executable. Existing files were retained.'
}

function Preserve-ProjectEnvironment([string]$ProjectRoot, [string]$EnvironmentPath) {
    $entry = Get-Item -LiteralPath $EnvironmentPath -Force
    if (-not (Test-SafePythonEntry $entry)) { throw 'The project .venv must be a real directory, not a redirected path.' }
    $archivePath = Join-Path $ProjectRoot ('.venv-incomplete-' + [guid]::NewGuid().ToString('N'))
    $projectFull = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') + '\'
    if (-not ([System.IO.Path]::GetFullPath($EnvironmentPath).StartsWith($projectFull, [System.StringComparison]::OrdinalIgnoreCase) -and [System.IO.Path]::GetFullPath($archivePath).StartsWith($projectFull, [System.StringComparison]::OrdinalIgnoreCase))) { throw 'Environment recovery paths are outside the project.' }
    Move-Item -LiteralPath $EnvironmentPath -Destination $archivePath -ErrorAction Stop
    Write-Host ('Preserved the previous environment at ' + $archivePath)
}

function Initialize-AgentEnvironment([string]$BasePython, [string[]]$PythonFlags, [string]$Probe, [string]$RuntimeMode, [string]$ProjectRoot) {
    $environmentPath = Join-Path $ProjectRoot '.venv'
    $environmentPython = Join-Path $environmentPath 'Scripts\python.exe'
    $requirements = Join-Path $ProjectRoot 'requirements.lock.txt'
    $bootstrap = Join-Path $ProjectRoot 'bootstrap\virtualenv.pyz'
    $bootstrapSha256 = '9096EFA6E3A8457CC3EC56E749A2D1E17505B756EE3CB2B7E889526367EFC187'
    $setupLock = $null
    try {
        $lockPath = Join-Path $ProjectRoot '.venv-setup.lock'
        if (Test-Path -LiteralPath $lockPath) {
            if (-not (Test-SafePythonEntry (Get-Item -LiteralPath $lockPath -Force))) { throw 'Setup lock must not be a redirected path.' }
        }
        try {
            $setupLock = [System.IO.File]::Open((Join-Path $ProjectRoot '.venv-setup.lock'), [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        } catch { throw 'Another setup is running, or this project is not writable. Retry after setup completes.' }
        $BasePython = Get-RecoveryBasePython $BasePython $PythonFlags $environmentPython
        Invoke-SetupPython $BasePython ($PythonFlags + @('-c',$Probe,($RuntimeMode + '-bootstrap'),$requirements))
        if (Test-Path -LiteralPath $environmentPath) {
            $environmentEntry = Get-Item -LiteralPath $environmentPath -Force
            if (-not (Test-SafePythonEntry $environmentEntry)) { throw 'The project .venv must be a real directory, not a redirected path.' }
            $recoveryReason = $null
            if (-not (Test-Path -LiteralPath (Join-Path $environmentPath 'pyvenv.cfg') -PathType Leaf) -or -not (Test-Path -LiteralPath $environmentPython -PathType Leaf)) {
                $recoveryReason = 'The existing project Python environment is incomplete.'
            } elseif (-not (Get-WorkingPip $environmentPython $PythonFlags)) {
                $recoveryReason = 'The existing project Python environment has no working pip.'
            }
            if ($recoveryReason) {
                Write-Host $recoveryReason
                $basePip = Get-WorkingPip $BasePython $PythonFlags
                if ($basePip) { Write-Host ('Located pip in the selected Python installation: ' + $basePip) }
                else { Write-Host 'The selected Python has no working pip; the bundled bootstrap will seed it in the project environment.' }
                Preserve-ProjectEnvironment $ProjectRoot $environmentPath
            } else {
                Write-Host 'Reusing the existing project Python environment.'
            }
        }
        if (-not (Test-Path -LiteralPath $environmentPath)) {
            Write-Host 'Creating the project Python environment.'
            if (-not (Test-Path -LiteralPath $bootstrap -PathType Leaf) -or -not (Test-SafePythonEntry (Get-Item -LiteralPath $bootstrap -Force))) { throw 'Bundled virtualenv bootstrap is missing or redirected. Restore the official repository files and retry Setup.' }
            if ((Get-FileHash -LiteralPath $bootstrap -Algorithm SHA256).Hash -ne $bootstrapSha256) { throw 'Bundled virtualenv bootstrap failed its SHA-256 check. Restore the official repository files and retry Setup.' }
            try {
                Invoke-SetupPython $BasePython ($PythonFlags + @($bootstrap,'--no-download','--no-periodic-update',$environmentPath))
                if (-not (Get-WorkingPip $environmentPython $PythonFlags)) { throw 'Default virtualenv seeder did not create a working pip installation.' }
            } catch {
                Write-Host 'Default virtualenv seeder failed. Retrying with the direct pip seeder.'
                if (Test-Path -LiteralPath $environmentPath) { Preserve-ProjectEnvironment $ProjectRoot $environmentPath }
                Invoke-SetupPython $BasePython ($PythonFlags + @($bootstrap,'--no-download','--no-periodic-update','--seeder','pip',$environmentPath))
            }
        }
        if (-not (Test-Path -LiteralPath (Join-Path $environmentPath 'pyvenv.cfg') -PathType Leaf) -or -not (Test-Path -LiteralPath $environmentPython -PathType Leaf)) { throw 'Virtual environment creation was incomplete. Files were retained.' }
        $priorCandidates = $candidates
        $priorSeen = $seen
        try {
            $candidates = [System.Collections.Generic.List[string]]::new()
            $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
            Add-PythonCandidate $environmentPython
            if ($candidates.Count -ne 1) { throw 'Project environment Python is redirected or unavailable.' }
        } finally { $candidates = $priorCandidates; $seen = $priorSeen }
        Invoke-SetupPython $environmentPython ($PythonFlags + @('-c',$Probe,($RuntimeMode + '-bootstrap'),$requirements,$environmentPath))
        if (-not (Get-WorkingPip $environmentPython $PythonFlags)) { throw 'Project environment pip is unavailable after creation or reuse. Packages were not installed; existing files were retained.' }
        Write-Host 'Project environment pip verified.'
        if ($env:PIP_TARGET) { throw 'PIP_TARGET redirects package installation. Clear that override before running Setup; no settings were changed.' }
        $pipConfiguration = Get-PipConfiguration $environmentPython $PythonFlags
        if ($pipConfiguration -match '(?im)^\s*[^=]*\.target\s*=') { throw 'Pip configuration redirects installation with target. Remove that override before Setup; no settings were changed.' }
        $dependencySetup = Join-Path $ProjectRoot 'bootstrap\setup_dependencies.py'
        if (-not (Test-Path -LiteralPath $dependencySetup -PathType Leaf) -or -not (Test-SafePythonEntry (Get-Item -LiteralPath $dependencySetup -Force))) { throw 'The package setup helper is missing or redirected. Pull the complete repository and retry Setup.' }
        Write-Host 'Checking existing packages first. Downloads use your configured package source and tested unpacking folders.'
        Invoke-SetupPython $environmentPython ($PythonFlags + @($dependencySetup,'install',$requirements,$environmentPath))
        return $environmentPython
    } finally { if ($setupLock) { $setupLock.Dispose() } }
}

try {
    $projectVersion = $null
    if ($Mode -in @('Start','UI')) {
        Write-Host 'Which version do you want to run? 1. Live repository  2. Copilot testing environment'
        $projectVersion = (Read-Host 'Choose 1 or 2').Trim()
        if ($projectVersion -notin @('1','2')) { throw 'Enter 1 or 2; no version was started.' }
    }
    $savedInterpreters = [System.Collections.Generic.List[string]]::new()
    $localSettings = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CopilotLocalAgent\settings.json'
    if ((Test-Path -LiteralPath $localSettings -PathType Leaf) -and (Get-Item -LiteralPath $localSettings).Length -le 65536) {
        try {
            $settings = Get-Content -LiteralPath $localSettings -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($settings.python_executable) { $savedInterpreters.Add([string]$settings.python_executable) }
        } catch { Write-Host 'Local app settings could not be read; choose a Python path if the project environment is unavailable.' }
    }
    if ($Mode -eq 'Tests') {
        $env:COPILOT_TEST_ROOT = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CopilotLocalAgent\runtime\test-runs'
        New-Item -ItemType Directory -Path $env:COPILOT_TEST_ROOT -Force | Out-Null
        $env:TEMP = $env:COPILOT_TEST_ROOT
        $env:TMP = $env:COPILOT_TEST_ROOT
    }
    if ($env:COPILOT_PYTHON) {
        Add-PythonCandidate $env:COPILOT_PYTHON
        if ($candidates.Count -ne 1) { throw 'COPILOT_PYTHON must identify an existing Python executable on S: for a shared-drive deployment.' }
    } else {
        if ($Mode -ne 'Setup') {
            Add-PythonCandidate (Join-Path $repoRoot '.venv\Scripts\python.exe')
            if ($candidates.Count -eq 0) { foreach ($value in $savedInterpreters) { Add-PythonCandidate $value } }
            if ($candidates.Count -eq 0) {
                $operatorConfig = Join-Path $repoRoot 'python-launcher.txt'
                if (Test-Path -LiteralPath $operatorConfig -PathType Leaf) {
                    Add-PythonCandidate ([string](Get-Content -LiteralPath $operatorConfig -Encoding UTF8 -TotalCount 1))
                }
            }
        }
        $method = if ($candidates.Count -eq 0) { Read-PythonMethod } else { 'saved' }
        if ($method -eq '2') { Read-PythonPath }
        if ($method -eq '1') {
            foreach ($value in $savedInterpreters) { Add-PythonCandidate $value }
            if ($candidates.Count -eq 0) {
                $operatorConfig = Join-Path $repoRoot 'python-launcher.txt'
                if (Test-Path -LiteralPath $operatorConfig -PathType Leaf) {
                    Add-PythonCandidate ([string](Get-Content -LiteralPath $operatorConfig -Encoding UTF8 -TotalCount 1))
                }
            }
            if ($candidates.Count -eq 0 -and -not $productionShare) {
                Add-PythonCandidate (Join-Path $repoRoot '.venv\Scripts\python.exe')
            }
            if ($candidates.Count -eq 0) {
                foreach ($command in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) { Add-PythonCandidate $command.Source }
                $pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
                if ($pythonLauncher) {
                    foreach ($line in @(& $pythonLauncher.Source -0p 2>$null)) {
                        if ($line -match '([A-Za-z]:\\.+?python\.exe)\s*$') { Add-PythonCandidate $Matches[1] }
                    }
                }
                $nearby = [System.Collections.Generic.List[string]]::new()
                $cursor = [System.IO.DirectoryInfo]::new($repoRoot)
                for ($depth = 0; $depth -lt 4 -and $cursor; $depth++) {
                    if (-not $productionShare -or $cursor.Root.FullName -ieq 'S:\') {
                        $nearby.Add($cursor.FullName)
                        foreach ($folder in @('Python','python','Shared Python','.venv')) {
                            $nearby.Add((Join-Path $cursor.FullName $folder))
                        }
                    }
                    $cursor = $cursor.Parent
                }
                foreach ($directory in $nearby) {
                    Add-PythonCandidate (Join-Path $directory 'python.exe')
                    Add-PythonCandidate (Join-Path $directory 'Scripts\python.exe')
                }
            }
            if ($candidates.Count -eq 0 -and (Test-Path -LiteralPath 'S:\' -PathType Container)) {
                Write-Host 'Finding shared Python on S: (bounded directory search, no account or document scanning).'
                $queue = [System.Collections.Generic.Queue[object]]::new()
                $queue.Enqueue(@{ Path='S:\'; Depth=0 })
                $visited = 0
                while ($queue.Count -gt 0 -and $visited -lt 20000) {
                    $item = $queue.Dequeue()
                    $visited++
                    Add-PythonCandidate (Join-Path $item.Path 'python.exe')
                    if ($item.Depth -ge 8) { continue }
                    foreach ($child in @(Get-ChildItem -LiteralPath $item.Path -Directory -Force -ErrorAction SilentlyContinue)) {
                        if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
                        if ($child.Name -in @('.git','node_modules','runtime','workspace','deliveries')) { continue }
                        if ($queue.Count -lt 20000) { $queue.Enqueue(@{ Path=$child.FullName; Depth=$item.Depth+1 }) }
                    }
                }
            }
            if ($candidates.Count -eq 0) {
                Write-Host 'Automatic detection found no usable Python. Paste its path to continue.'
                Read-PythonPath
            }
        }
    }
    if ($candidates.Count -eq 0) { throw 'No usable Python interpreter was selected.' }
    if ($candidates.Count -eq 1) {
        $python = $candidates[0]
    } else {
        Write-Host 'Available shared Python interpreters:'
        for ($index = 0; $index -lt $candidates.Count; $index++) { Write-Host (('{0}. {1}' -f ($index+1), $candidates[$index])) }
        $selected = 0
        for ($attempt = 0; $attempt -lt 5; $attempt++) {
            $answer = Read-Host 'Choose an interpreter number'
            if ([int]::TryParse($answer, [ref]$selected) -and $selected -ge 1 -and $selected -le $candidates.Count) { break }
            $selected = 0
        }
        if ($selected -eq 0) { throw 'Interpreter selection stopped after five attempts.' }
        $python = $candidates[$selected-1]
    }
    Write-Host ('Using Python: ' + $python)
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $pythonProbe = @'
import ntpath
import os
import sys
import sysconfig
from functools import lru_cache
from importlib.metadata import distribution

WINDOWS_SLASH = chr(92)

def normalized_final_path(value):
    result = os.path.realpath(value, strict=True)
    extended = WINDOWS_SLASH * 2 + '?' + WINDOWS_SLASH
    unc_prefix = extended + 'UNC' + WINDOWS_SLASH
    if result[:len(unc_prefix)].casefold() == unc_prefix.casefold():
        result = WINDOWS_SLASH * 2 + result[len(unc_prefix):]
    elif result.startswith(extended):
        result = result[len(extended):]
    return ntpath.normcase(ntpath.normpath(result)).rstrip(WINDOWS_SLASH)

@lru_cache(maxsize=1)
def mapped_shared_root():
    try:
        result = normalized_final_path('S:' + WINDOWS_SLASH)
    except (OSError, ValueError):
        return None
    return result if result.startswith(WINDOWS_SLASH * 2) else None

def is_shared_path(value):
    if not isinstance(value, str) or not ntpath.isabs(value):
        return False
    if ntpath.splitdrive(ntpath.normpath(value))[0].casefold() == 's:':
        return True
    if not value.startswith(WINDOWS_SLASH * 2):
        return False
    root = mapped_shared_root()
    if root is None:
        return False
    try:
        resolved = normalized_final_path(value)
    except (OSError, ValueError):
        return False
    return resolved == root or resolved.startswith(root + WINDOWS_SLASH)

def same_directory(left, right):
    identity_match = None
    try:
        identity_match = os.path.samefile(left, right)
    except (OSError, ValueError):
        pass
    if identity_match:
        return True
    try:
        return normalized_final_path(left) == normalized_final_path(right)
    except (OSError, ValueError):
        return identity_match

def valid_environment_prefix(actual, base, expected):
    return same_directory(actual, expected) is True and same_directory(actual, base) is False

def assert_shared_runtime(executable, base_prefix, base_executable, stdlib):
    paths = {'running executable': executable, 'base Python prefix': base_prefix,
             'base executable': base_executable or executable, 'standard library': stdlib}
    for label, value in paths.items():
        if not is_shared_path(value):
            raise RuntimeError('Shared deployment requires the '+label+' on S: or its mapped UNC share. Reported runtime paths: '+repr(paths)+'. This interpreter depends on a local or unmapped Python runtime; the operator must provide a complete shared installation.')

def locked_versions(text):
    if len(text) > 65536:
        raise RuntimeError('Shared dependency lock exceeds its size limit.')
    result = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        name, separator, pinned = line.partition('==')
        name = name.lower().replace('-', '_').replace('.', '_')
        if (not separator or not name or not pinned or name in result
                or not all(char.isalnum() or char in '._-' for char in name)
                or not all(char.isalnum() or char in '._+-!' for char in pinned)):
            raise RuntimeError('Shared dependency lock must contain unique exact package versions.')
        result[name] = pinned
    if not {'playwright', 'greenlet', 'pyee', 'typing_extensions'}.issubset(result):
        raise RuntimeError('Shared dependency lock must include Playwright and its required dependencies.')
    return result

def assert_dependencies(installed, expected, require_shared):
    for name, pinned in expected.items():
        record = installed.get(name, {})
        if record.get('version') != pinned:
            raise RuntimeError('Required dependency '+name+'=='+pinned+' is unavailable. The operator must install requirements.lock.txt for this shared interpreter.')
        location = record.get('location')
        if require_shared and not is_shared_path(location):
            raise RuntimeError('Shared dependency '+name+' must be installed on S: or its mapped UNC share, not in a local or per-user package directory. Reported location: '+repr(location))

assert sys.version_info >= (3, 10), 'Python 3.10+ is required'
if len(sys.argv) > 3:
    if not valid_environment_prefix(sys.prefix, sys.base_prefix, sys.argv[3]):
        raise RuntimeError('Existing project environment is not a valid virtual environment at the expected path. Files were retained.')
bootstrap = sys.argv[1].endswith('-bootstrap')
shared = sys.argv[1].startswith('shared')
if shared:
    assert_shared_runtime(sys.executable, sys.base_prefix,
                          getattr(sys, '_base_executable', None), sysconfig.get_path('stdlib'))
if bootstrap:
    print('Base Python runtime verified.')
    sys.exit(0)
if shared:
    with open(sys.argv[2], encoding='utf-8-sig') as stream:
        expected = locked_versions(stream.read(65537))
else:
    expected = {'playwright':'1.55.0'}
installed = {}
for name in expected:
    package = distribution(name)
    installed[name] = {'version':package.version, 'location':str(package.locate_file(''))}
assert_dependencies(installed, expected, shared)
print('Python runtime and Playwright verified.')
'@
    $runtimeMode = if ($productionShare) { 'shared' } else { 'development' }
    [string[]]$pythonArgs = if ($productionShare) { @('-B','-E','-s') } else { @('-B') }
    if ($Mode -eq 'Setup') { $python = Initialize-AgentEnvironment $python $pythonArgs $pythonProbe $runtimeMode $repoRoot }
    & $python @pythonArgs -c $pythonProbe $runtimeMode (Join-Path $repoRoot 'requirements.lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Python or pinned dependencies are unavailable. Run Setup.cmd to create or repair the project environment; existing files are retained.' }
    Push-Location -LiteralPath $repoRoot
    try {
        if ($Mode -eq 'Setup') {
            & $python @pythonArgs (Join-Path $repoRoot 'app.py') --setup-only
        } elseif ($Mode -in @('Start','UI')) {
            if ($Mode -eq 'UI') {
                & $python @pythonArgs (Join-Path $repoRoot 'version_launcher.py') $projectVersion --ui
            } else {
                & $python @pythonArgs (Join-Path $repoRoot 'version_launcher.py') $projectVersion
            }
        } else {
            & $python @pythonArgs (Join-Path $repoRoot 'app.py') --setup-only
            if ($LASTEXITCODE -ne 0) { throw 'Per-user storage setup must complete before running tests.' }
            & $python @pythonArgs -m unittest discover -s tests -v
            if ($LASTEXITCODE -ne 0) { throw 'Core agent tests failed.' }
            & $python @pythonArgs -m unittest discover -s agent_ui/tests -v
        }
        $result = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    exit $result
} catch {
    Write-Host ('Setup/run stopped: ' + $_.Exception.Message)
    exit 1
}
<!-- END SOURCE: Launcher.ps1 -->



---

<!-- BEGIN VERBATIM SOURCE: requirements.lock.txt -->
## Source: `requirements.lock.txt` (verbatim text; line endings normalized to LF)

# Windows Python 3.14.2; Crawl4AI offline extraction, no extra browser setup.
aiofiles==25.1.0
aiohappyeyeballs==2.7.1
aiohttp==3.14.5
aiosignal==1.4.0
aiosqlite==0.22.1
alphashape==1.3.1
annotated-types==0.8.0
anyio==4.15.1
attrs==26.1.0
beautifulsoup4==4.15.0
brotli==1.2.0
certifi==2026.7.22
cffi==2.1.1
chardet==7.6.0
charset-normalizer==3.5.2
click==8.5.0
click-log==0.4.0
cloudpickle==3.1.2
colorama==0.4.6
crawl4ai==0.9.5
cryptography==50.0.2
cssselect==1.6.0
defusedxml==0.7.1
fake-useragent==2.2.0
fastuuid==0.14.0
filelock==4.1.2
frozenlist==1.8.0
fsspec==2026.9.0
greenlet==3.5.6
h11==0.16.0
h2==4.4.1
hf-xet==1.7.0
hpack==4.2.0
httpcore==1.0.9
httpcore2==2.13.1
httpx==0.28.1
httpx2==2.13.1
huggingface-hub==2.2.0
humanize==4.16.0
hyperframe==6.1.0
idna==3.20
importlib-metadata==9.0.1
jinja2==3.1.6
jiter==0.17.0
joblib==1.6.0
jsonschema==4.26.0
jsonschema-specifications==2025.9.1
lark==1.3.1
lxml==6.1.3
markdown-it-py==4.2.0
markupsafe==3.0.4
mdurl==0.1.2
multidict==7.1.0
networkx==3.7
nltk==3.10.3
numpy==2.5.4
openai==3.31.0
packaging==26.3
patchright==1.63.0
pillow==12.3.0
playwright==1.55.0
playwright-stealth==2.0.3
propcache==0.5.4
psutil==7.2.2
pycparser==3.11
pydantic==2.14.1
pydantic-core==2.50.1
pyee==13.0.1
pygments==2.21.0
pyopenssl==26.4.0
python-dotenv==1.2.4
pyyaml==6.0.3
rank-bm25==0.2.2
referencing==0.37.0
regex==2026.9.29
requests==2.34.2
rich==15.0.0
rpds-py==2026.9.1
rtree==1.4.1
scipy==1.18.1
shapely==2.2.0
sniffio==1.3.1
snowballstemmer==2.2.0
soupsieve==3.0.3
tiktoken==0.14.0
tokenizers==0.23.3
tqdm==4.70.1
trimesh==5.1.1
truststore==0.10.5
typing-extensions==4.16.0
typing-inspection==0.4.4
unclecode-litellm==1.81.13
urllib3==2.8.0
xxhash==3.8.1
yarl==1.25.1
zipp==4.1.1
<!-- END SOURCE: requirements.lock.txt -->



---

<!-- BEGIN VERBATIM SOURCE: requirements.txt -->
## Source: `requirements.txt` (verbatim text; line endings normalized to LF)

playwright==1.55.0
crawl4ai==0.9.5
<!-- END SOURCE: requirements.txt -->



---

<!-- BEGIN VERBATIM SOURCE: Run Tests.cmd -->
## Source: `Run Tests.cmd` (verbatim text; line endings normalized to LF)

@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launcher.ps1" -Mode Tests
set "agent_result=%errorlevel%"
pause
exit /b %agent_result%
<!-- END SOURCE: Run Tests.cmd -->



---

<!-- BEGIN VERBATIM SOURCE: schemas/response-v1.schema.json -->
## Source: `schemas/response-v1.schema.json` (verbatim text; line endings normalized to LF)

{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:copilot-local-agent:response:1.0",
  "title": "Copilot Local Agent response 1.0",
  "type": "object",
  "additionalProperties": false,
  "required": ["protocol_version", "session_id", "request_id", "response_id", "response_type", "user_response", "task_interpretation", "decision_summary", "assumptions", "action_plan", "tools_required", "tool_requests", "approval_required", "code_runner_proposal", "risk_summary", "continuation_state", "clarification", "useful_findings", "completion_status", "recoverable_errors"],
  "properties": {
    "protocol_version": {"const": "1.0"},
    "session_id": {"type": "string", "minLength": 1, "maxLength": 100},
    "request_id": {"type": "string", "minLength": 1, "maxLength": 100},
    "response_id": {"type": "string", "minLength": 1, "maxLength": 100},
    "response_type": {"enum": ["final", "tool_request", "clarification", "error"]},
    "user_response": {"type": "string", "maxLength": 30000},
    "task_interpretation": {"type": "string", "minLength": 1, "maxLength": 4000},
    "decision_summary": {"type": "string", "minLength": 1, "maxLength": 4000},
    "assumptions": {"type": "array", "maxItems": 30, "items": {"type": "string", "maxLength": 2000}},
    "action_plan": {"type": "array", "minItems": 1, "maxItems": 30, "items": {"$ref": "#/$defs/step"}},
    "tools_required": {"type": "boolean"},
    "tool_requests": {"type": "array", "maxItems": 20, "items": {"$ref": "#/$defs/tool"}},
    "approval_required": {"type": "boolean"},
    "code_runner_proposal": {"type": ["object", "null"]},
    "risk_summary": {"type": "string", "maxLength": 4000},
    "continuation_state": {"enum": ["continue", "await_user", "complete", "blocked"]},
    "clarification": {"type": ["string", "null"], "maxLength": 4000},
    "useful_findings": {"type": "array", "maxItems": 30, "items": {"$ref": "#/$defs/finding"}},
    "completion_status": {"enum": ["in_progress", "complete", "blocked"]},
    "recoverable_errors": {"type": "array", "maxItems": 20, "items": {"$ref": "#/$defs/error"}}
  },
  "$defs": {
    "step": {"type": "object", "additionalProperties": false, "required": ["step", "action", "verification"], "properties": {"step": {"type": "integer", "minimum": 1}, "action": {"type": "string", "minLength": 1, "maxLength": 4000}, "verification": {"type": "string", "minLength": 1, "maxLength": 2000}}},
    "tool": {"type": "object", "additionalProperties": false, "required": ["call_id", "name", "version", "arguments", "expected_result"], "properties": {"call_id": {"type": "string", "minLength": 1, "maxLength": 100}, "name": {"type": "string", "minLength": 1, "maxLength": 100}, "version": {"const": "1.0"}, "arguments": {"type": "object"}, "expected_result": {"type": "string", "minLength": 1, "maxLength": 2000}}},
    "finding": {"type": "object", "additionalProperties": false, "required": ["key", "content", "provenance"], "properties": {"key": {"type": "string", "minLength": 1, "maxLength": 200}, "content": {"type": "string", "minLength": 1, "maxLength": 2000}, "provenance": {"type": "string", "minLength": 1, "maxLength": 2000}}},
    "error": {"type": "object", "additionalProperties": false, "required": ["code", "message"], "properties": {"code": {"type": "string", "minLength": 1, "maxLength": 100}, "message": {"type": "string", "minLength": 1, "maxLength": 2000}}}
  }
}
<!-- END SOURCE: schemas/response-v1.schema.json -->



---

<!-- BEGIN VERBATIM SOURCE: Setup.cmd -->
## Source: `Setup.cmd` (verbatim text; line endings normalized to LF)

@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launcher.ps1" -Mode Setup
set "agent_result=%errorlevel%"
pause
exit /b %agent_result%
<!-- END SOURCE: Setup.cmd -->



---

<!-- BEGIN VERBATIM SOURCE: Start Agent UI.cmd -->
## Source: `Start Agent UI.cmd` (verbatim text; line endings normalized to LF)

@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launcher.ps1" -Mode UI
set "agent_result=%errorlevel%"
pause
exit /b %agent_result%
<!-- END SOURCE: Start Agent UI.cmd -->



---

<!-- BEGIN VERBATIM SOURCE: Start Agent.cmd -->
## Source: `Start Agent.cmd` (verbatim text; line endings normalized to LF)

@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launcher.ps1" -Mode Start
set "agent_result=%errorlevel%"
pause
exit /b %agent_result%
<!-- END SOURCE: Start Agent.cmd -->
