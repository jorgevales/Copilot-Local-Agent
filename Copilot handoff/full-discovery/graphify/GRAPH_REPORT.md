# Graph Report - copilot-local-agent-20261012-230703  (2026-10-12)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 2504 nodes · 7652 edges · 107 communities (63 shown, 44 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 501 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a42e4e14`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41
- Community 42
- Community 43
- Community 44
- Community 45
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- Community 53
- Community 54
- Community 55
- Community 56
- Community 57
- Community 58
- Community 59
- Community 60
- Community 61
- Community 62
- Community 63
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70
- Community 71
- Community 72
- Community 73
- Community 74
- Community 75
- Community 76
- Community 78
- Community 79
- Community 80
- Community 81
- Community 82
- Community 83
- Community 84
- Community 85
- Community 86
- Community 87
- Community 89
- Community 90
- Community 91
- Community 92
- Community 93
- Community 94
- Community 95
- Community 96
- Community 97
- Community 98
- Community 99
- Community 100
- Community 102
- Community 103
- Community 104

## God Nodes (most connected - your core abstractions)
1. `PolicyError` - 167 edges
2. `DiscoveryError` - 109 edges
3. `Orchestrator` - 107 edges
4. `BrowserAdapter` - 82 edges
5. `ToolRegistry` - 82 edges
6. `Store` - 81 edges
7. `SessionState` - 75 edges
8. `PathPolicy` - 72 edges
9. `final_response()` - 60 edges
10. `Config` - 54 edges

## Surprising Connections (you probably didn't know these)
- `SiteKnowledgeTests` --uses--> `PolicyError`  [INFERRED]
  tests/test_site_knowledge.py → copilot_agent/policy.py
- `SiteKnowledgeTests` --uses--> `SessionState`  [INFERRED]
  tests/test_site_knowledge.py → copilot_agent/state.py
- `CodeRunnerTests` --uses--> `PathPolicy`  [INFERRED]
  tests/test_code_runner.py → copilot_agent/policy.py
- `LocalPythonRunnerTests` --uses--> `PathPolicy`  [INFERRED]
  tests/test_code_runner.py → copilot_agent/policy.py
- `CatalogueTests` --uses--> `PathPolicy`  [INFERRED]
  tests/test_document_catalogue.py → copilot_agent/policy.py

## Import Cycles
- None detected.

## Communities (107 total, 44 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (37): validate_schema(), _approval(), _canonical(), _digest(), execute_knowledge(), _fingerprint(), _hash(), _json_pairs() (+29 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (27): ArchiveError, ArchiveService, _digest(), _entries(), extract_zip(), directory(), inspect_zip(), _limits() (+19 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (6): copied_code_response(), model_access_exhausted(), main(), CorrelationTests, RecoveryOrchestrationTests, Response

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (9): main(), LaunchUITests, submit_route(), Handler, main(), _public_file_metadata(), Workspace, run() (+1 more)

### Community 4 - "Community 4"
Cohesion: 0.10
Nodes (13): ApprovalManager, format_valid(), call_summary(), exchange_summary(), readable(), correction_message(), _object_pairs(), parse_response() (+5 more)

### Community 5 - "Community 5"
Cohesion: 0.10
Nodes (25): start_new_session(), model_rank(), Config, documents_directory(), write_json(), ToolRegistry, run(), require() (+17 more)

### Community 6 - "Community 6"
Cohesion: 0.09
Nodes (9): final_response(), OrchestratorTests, interrupted(), request_both(), two_calls(), malformed(), diagnostics(), partial_failure() (+1 more)

### Community 7 - "Community 7"
Cohesion: 0.08
Nodes (14): choice(), choose_edge(), pasted_path(), default_local_storage(), discoveries_storage(), discoveries_storage_paths(), machine_key(), profile_directory() (+6 more)

### Community 8 - "Community 8"
Cohesion: 0.10
Nodes (5): canonical(), DiscoveryError, verify_page(), digest(), Store

### Community 9 - "Community 9"
Cohesion: 0.12
Nodes (47): action(), addFiles(), api(), approvalReview(), attachmentContainer, backendPrompt(), bookmarkIds, button() (+39 more)

### Community 10 - "Community 10"
Cohesion: 0.07
Nodes (17): _actionable(), ask(), choose_browser_endpoint(), error(), main(), persist_runtime_settings(), read_runtime_settings(), _recent_events() (+9 more)

### Community 11 - "Community 11"
Cohesion: 0.11
Nodes (29): origin(), _call(), run(), _compact(), _decode(), _enabled(), _entropy(), execute_operation() (+21 more)

### Community 12 - "Community 12"
Cohesion: 0.08
Nodes (4): upload_name(), Orchestrator, consequential(), operation_domains()

### Community 13 - "Community 13"
Cohesion: 0.09
Nodes (7): PublicReader, ReadFailure, retry_after(), TLSStream, FakeTLS, FakeTLSContext, TransportTests

### Community 14 - "Community 14"
Cohesion: 0.14
Nodes (33): _assertion(), _boundary(), _candidates(), _check_cancelled(), clear_navigation_state(), _close_tab(), _compact_recon(), execute_navigation() (+25 more)

### Community 15 - "Community 15"
Cohesion: 0.09
Nodes (14): abandon_uncertain_browser_call(), _binding(), browser_diagnostics(), capture_baseline(), _hash(), _navigation_only(), navigation_scope_allows(), _origin() (+6 more)

### Community 16 - "Community 16"
Cohesion: 0.08
Nodes (10): delivery_instruction(), delivery_requirements(), DeliveryRequirements, detect_requirements(), _expected_names(), retry_message(), _without_negated_clauses(), DeliveryRequirementTests (+2 more)

### Community 18 - "Community 18"
Cohesion: 0.11
Nodes (30): bounded_hash(), build_catalogue(), _catalogue(), _compact(), current_scope(), execute_catalogue(), export_catalogue(), rank_records() (+22 more)

### Community 19 - "Community 19"
Cohesion: 0.16
Nodes (16): execute_discovery(), prepare_discovery(), Response, execute_knowledge_tool(), prepare_knowledge_tool(), budgets(), intent(), task() (+8 more)

### Community 20 - "Community 20"
Cohesion: 0.09
Nodes (23): error(), redact(), run_one(), canonical_hash(), InjectedCaptureBrowser, file_record(), RecordedBrowser, committed() (+15 more)

### Community 21 - "Community 21"
Cohesion: 0.11
Nodes (10): bounded_shape(), compile_manifest(), CompiledGraph, _pairs(), parse_contract(), _schema(), extract(), Scope (+2 more)

### Community 22 - "Community 22"
Cohesion: 0.08
Nodes (5): response_envelope_closed(), ExchangeTests, OfflineAdapter, PreloadedOfflineAdapter, ToolContextTests

### Community 23 - "Community 23"
Cohesion: 0.11
Nodes (12): build_bundle(), _build_reference(), build_startup_attachments(), _check_component_names(), _check_reference_names(), _hash(), _manifest_prefix(), _read_bounded() (+4 more)

### Community 24 - "Community 24"
Cohesion: 0.10
Nodes (8): AssembledCapacityTests, DeliveryIntegrationTests, MockBrowser, execute(), unavailable(), PreloadingBrowser, make_fixture(), cancel_after_response()

### Community 25 - "Community 25"
Cohesion: 0.14
Nodes (9): _canonical(), _download_path_identity(), DownloadError, DownloadService, _Ticket, validate_download_args(), _wait_for_completed_file(), ArgumentsTests (+1 more)

### Community 26 - "Community 26"
Cohesion: 0.17
Nodes (22): validate_budgets(), validate_contract(), correlation(), enabled(), input_object(), testing_gate(), validate_discovery(), candidate() (+14 more)

### Community 27 - "Community 27"
Cohesion: 0.11
Nodes (7): _actor_style(), _enable_colour(), Feedback, public_preview(), _terminal_text(), FeedbackIntegrationTests, PreviewTests

### Community 28 - "Community 28"
Cohesion: 0.19
Nodes (19): reject_path_redirection(), active(), audit(), bind_namespace(), collection(), directory(), execute_permissions(), guard_customer_read() (+11 more)

### Community 29 - "Community 29"
Cohesion: 0.15
Nodes (11): _children(), execute_local_python(), _hash_file(), _ledger_records(), _pid_running(), _preflight_imports(), _read_bounded(), runtime_binding() (+3 more)

### Community 30 - "Community 30"
Cohesion: 0.11
Nodes (8): retained_root(), StateAndPromptTests, exercise(), exercise(), exercise(), exercise(), exercise(), exercise()

### Community 32 - "Community 32"
Cohesion: 0.13
Nodes (10): filesystem_diagnostic(), FilesystemAccessError, _final_s_path(), is_s_drive_path(), mapped_s_drive_root(), resolve_s_drive_output(), definitions(), execute() (+2 more)

### Community 33 - "Community 33"
Cohesion: 0.16
Nodes (12): _category(), _caught_frame(), DiagnosticReports, _exception_chain(), _frames(), _ownership(), _recommend(), _safe_text() (+4 more)

### Community 34 - "Community 34"
Cohesion: 0.10
Nodes (6): composer_comparison(), fresh_assistant(), upload_alert_is_error(), uploads_verified(), value(), RemainingCorrelationTests

### Community 38 - "Community 38"
Cohesion: 0.17
Nodes (3): AttachmentError, AttachmentQueue, AttachmentTests

### Community 41 - "Community 41"
Cohesion: 0.15
Nodes (6): SubmissionNotSentError, FakeContext, FakePage, WebTransportTests, exchange(), exchange()

### Community 44 - "Community 44"
Cohesion: 0.21
Nodes (3): BrowserUIError, ModelAccessError, SubmissionAmbiguousError

### Community 45 - "Community 45"
Cohesion: 0.24
Nodes (3): CodeRunner, PolicyError, _approved_write_target()

### Community 46 - "Community 46"
Cohesion: 0.18
Nodes (10): capture_display(), enumerate_displays(), collect(), inspect_windows(), snapshot(), launch_viewers(), _MonitorInfo, _png_chunk() (+2 more)

### Community 47 - "Community 47"
Cohesion: 0.16
Nodes (6): directory(), check_knowledge_health(), _bytes(), execute_note(), KnowledgeHealthTests, KnowledgeRepairTests

### Community 50 - "Community 50"
Cohesion: 0.19
Nodes (5): _candidate_directories(), configure_temp_directory(), _probe_directory(), select_temp_directory(), TempStorageTests

### Community 51 - "Community 51"
Cohesion: 0.11
Nodes (4): FakeAnchor, FakeLocator, FakePage, Pending

### Community 53 - "Community 53"
Cohesion: 0.18
Nodes (9): key(), cdp_endpoint(), connect_bounded(), EndpointError, find_edge_executable(), get_cdp_version(), port_listening(), remote_debugging_blocked() (+1 more)

### Community 54 - "Community 54"
Cohesion: 0.26
Nodes (4): cancelled(), Engine, project_result(), alias()

### Community 58 - "Community 58"
Cohesion: 0.19
Nodes (8): discover_edge_debugging_endpoints(), _edge_listener_process(), _hidden_command(), launch_edge(), _profile_argument(), profile_in_use(), validate_edge_listener(), validate_profile_ownership()

### Community 62 - "Community 62"
Cohesion: 0.21
Nodes (3): CreatedSync, snapshot(), SyncTests

### Community 63 - "Community 63"
Cohesion: 0.19
Nodes (4): __init__(), new_page(), Browser, Page

### Community 64 - "Community 64"
Cohesion: 0.14
Nodes (3): FakeContext, FakeDownload, FakeSettingsPage

### Community 65 - "Community 65"
Cohesion: 0.24
Nodes (3): RuntimeCancellationTests, payload(), UploadStoreTests

### Community 66 - "Community 66"
Cohesion: 0.24
Nodes (3): _safe_name(), UploadError, _validate_content()

### Community 70 - "Community 70"
Cohesion: 0.21
Nodes (3): PromptBroker, PromptBrokerTests, PromptBrokerTests

### Community 72 - "Community 72"
Cohesion: 0.33
Nodes (10): Add-PythonCandidate(), Get-PipConfiguration(), Get-RecoveryBasePython(), Get-WorkingPip(), Initialize-AgentEnvironment(), Invoke-SetupPython(), Preserve-ProjectEnvironment(), Read-PythonPath() (+2 more)

### Community 73 - "Community 73"
Cohesion: 0.35
Nodes (3): encoded(), envelope(), ProtocolTests

### Community 74 - "Community 74"
Cohesion: 0.25
Nodes (6): main(), approved_popen(), audit(), _normalized_executable(), _within(), _write_event()

### Community 75 - "Community 75"
Cohesion: 0.25
Nodes (5): matches(), path(), public_address(), ScopedURL, _safe_route()

### Community 76 - "Community 76"
Cohesion: 0.40
Nodes (7): choose_source(), create_version(), digest(), main(), prepare_drop_folder(), replacement_map(), source_files()

### Community 81 - "Community 81"
Cohesion: 0.24
Nodes (4): configured_path_policy(), schema_example(), tool_path_policy(), scrub_urls()

### Community 82 - "Community 82"
Cohesion: 0.29
Nodes (6): _validate_assertion(), _validate_locator(), validate_navigation(), steps(), _validate_schema(), NavigationSchemaTests

### Community 85 - "Community 85"
Cohesion: 0.20
Nodes (3): StartupRecoveryTests, __init__(), new_page()

### Community 89 - "Community 89"
Cohesion: 0.33
Nodes (6): guard(), register(), check_navigation(), download(), failed(), websocket_guard()

### Community 92 - "Community 92"
Cohesion: 0.39
Nodes (3): URLPolicy, _current_origin(), _origin()

### Community 94 - "Community 94"
Cohesion: 0.29
Nodes (3): loopback_listener_pid(), stop_launched_edge(), validate_launched_endpoint()

### Community 95 - "Community 95"
Cohesion: 0.33
Nodes (3): approve(), new_page(), new_page()

### Community 99 - "Community 99"
Cohesion: 0.47
Nodes (3): Add-IssueComment(), Invoke-GitHubRequest(), Set-IssueProcessed()

## Knowledge Gaps
- **8 isolated node(s):** `attachmentContainer`, `bookmarkIds`, `events`, `focusedComposer`, `labels` (+3 more)
  These have ≤1 connection - possible missing edges. (Counts symbols only; 668 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **44 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PolicyError` connect `Community 45` to `Community 0`, `Community 1`, `Community 2`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 10`, `Community 12`, `Community 14`, `Community 15`, `Community 17`, `Community 18`, `Community 20`, `Community 24`, `Community 28`, `Community 29`, `Community 31`, `Community 32`, `Community 37`, `Community 38`, `Community 41`, `Community 42`, `Community 43`, `Community 47`, `Community 48`, `Community 60`, `Community 81`, `Community 92`?**
  _High betweenness centrality (0.122) - this node is a cross-community bridge._
- **Are the 29 inferred relationships involving `PolicyError` (e.g. with `_actionable()` and `ArchiveService`) actually correct?**
  _`PolicyError` has 29 INFERRED edges - model-reasoned connections that need verification._
- **What connects `attachmentContainer`, `bookmarkIds`, `events` to the rest of the system?**
  _8 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.05567765567765568 - nodes in this community are weakly interconnected._
- **Why does `PathPolicy` connect `Community 1` to `Community 0`, `Community 2`, `Community 4`, `Community 5`, `Community 8`, `Community 12`, `Community 20`, `Community 25`, `Community 26`, `Community 28`, `Community 29`, `Community 30`, `Community 32`, `Community 36`, `Community 37`, `Community 38`, `Community 41`, `Community 42`, `Community 43`, `Community 45`, `Community 48`, `Community 60`, `Community 64`, `Community 81`, `Community 91`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `DiscoveryError` (e.g. with `Engine` and `StructureParser`) actually correct?**
  _`DiscoveryError` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.05372405372405373 - nodes in this community are weakly interconnected._