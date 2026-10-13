# Graph Report - copilot-local-agent-20261013-151728  (2026-10-13)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 2763 nodes · 8400 edges · 115 communities (69 shown, 46 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 569 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `62c6fb33`
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
- Community 77
- Community 78
- Community 79
- Community 80
- Community 81
- Community 83
- Community 84
- Community 85
- Community 86
- Community 87
- Community 88
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
- Community 101
- Community 102
- Community 103
- Community 106
- Community 107
- Community 108
- Community 111
- Community 112

## God Nodes (most connected - your core abstractions)
1. `PolicyError` - 177 edges
2. `Orchestrator` - 129 edges
3. `DiscoveryError` - 109 edges
4. `ToolRegistry` - 92 edges
5. `BrowserAdapter` - 91 edges
6. `SessionState` - 86 edges
7. `Store` - 84 edges
8. `PathPolicy` - 82 edges
9. `final_response()` - 75 edges
10. `OrchestratorTests` - 66 edges

## Surprising Connections (you probably didn't know these)
- `execute()` --indirect_call--> `active()`  [INFERRED]
  tests/test_orchestrator.py → copilot_agent/research_permissions.py
- `SiteKnowledgeTests` --uses--> `PolicyError`  [INFERRED]
  tests/test_site_knowledge.py → copilot_agent/policy.py
- `SiteKnowledgeTests` --uses--> `SessionState`  [INFERRED]
  tests/test_site_knowledge.py → copilot_agent/state.py
- `run()` --uses--> `Config`  [INFERRED]
  tests/inspect_download_settings.py → copilot_agent/config.py
- `run()` --uses--> `Config`  [INFERRED]
  tests/live_acceptance.py → copilot_agent/config.py

## Import Cycles
- None detected.

## Communities (115 total, 46 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (38): validate_schema(), _approval(), _canonical(), _digest(), execute_knowledge(), _fingerprint(), _hash(), _json_pairs() (+30 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (32): _actionable(), ask(), error(), main(), persist_runtime_settings(), read_runtime_settings(), _recent_events(), _record_bug_fix() (+24 more)

### Community 2 - "Community 2"
Cohesion: 0.07
Nodes (16): ApprovalManager, format_valid(), _terminal_text(), _bytes(), execute_note(), call_summary(), exchange_summary(), readable() (+8 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (37): model_rank(), _write_private(), main(), own_edge(), redact(), write_json(), write_preserving(), obj() (+29 more)

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (13): final_response(), OrchestratorTests, interrupted(), request_both(), two_calls(), inspect_request(), execute(), malformed() (+5 more)

### Community 5 - "Community 5"
Cohesion: 0.06
Nodes (5): error(), Orchestrator, storage_attempt_notice(), run_one(), consequential()

### Community 6 - "Community 6"
Cohesion: 0.10
Nodes (4): BrowserAdapter, BrowserUIError, ModelAccessError, SubmissionAmbiguousError

### Community 7 - "Community 7"
Cohesion: 0.10
Nodes (34): DiscoveryError, candidate(), _proofs(), _run(), origin(), path(), _call(), run() (+26 more)

### Community 8 - "Community 8"
Cohesion: 0.07
Nodes (13): AttachmentError, AttachmentQueue, select_files(), file_record(), RecordedBrowser, committed(), require(), run() (+5 more)

### Community 9 - "Community 9"
Cohesion: 0.06
Nodes (6): AgentRuntime, create_runtime(), PromptBroker, PromptBrokerTests, PromptBrokerTests, SteeringQueueTests

### Community 10 - "Community 10"
Cohesion: 0.08
Nodes (6): DocumentTests, FakeBrowser, FakeContext, FakeDownload, FakePage, Pending

### Community 11 - "Community 11"
Cohesion: 0.09
Nodes (5): canonical(), alias(), digest(), directory(), Store

### Community 12 - "Community 12"
Cohesion: 0.12
Nodes (47): action(), addFiles(), api(), approvalReview(), attachmentContainer, backendPrompt(), bookmarkIds, button() (+39 more)

### Community 13 - "Community 13"
Cohesion: 0.07
Nodes (16): _category(), _caught_frame(), DiagnosticReports, _exception_chain(), _frames(), _ownership(), _recommend(), _safe_text() (+8 more)

### Community 14 - "Community 14"
Cohesion: 0.14
Nodes (18): execute_discovery(), prepare_discovery(), Response, check_plan(), compile_intent(), execute_knowledge_tool(), prepare_knowledge_tool(), budgets() (+10 more)

### Community 15 - "Community 15"
Cohesion: 0.07
Nodes (5): response_envelope_closed(), ExchangeTests, OfflineAdapter, PreloadedOfflineAdapter, ToolContextTests

### Community 16 - "Community 16"
Cohesion: 0.09
Nodes (12): _children(), execute_local_python(), _hash_file(), _ledger_records(), _pid_running(), _preflight_imports(), _read_bounded(), runtime_binding() (+4 more)

### Community 17 - "Community 17"
Cohesion: 0.08
Nodes (20): configure_isolated_test_workspace(), CaptureTimeoutError, latest_committed_request_id(), extract_call(), free_loopback_port(), latest_failed_proof_run_state(), latest_package_run_was_denied(), load_proof_config() (+12 more)

### Community 18 - "Community 18"
Cohesion: 0.08
Nodes (10): delivery_instruction(), delivery_requirements(), DeliveryRequirements, detect_requirements(), _expected_names(), retry_message(), _without_negated_clauses(), DeliveryRequirementTests (+2 more)

### Community 19 - "Community 19"
Cohesion: 0.09
Nodes (10): clear_navigation_state(), plan_hash(), _validate_assertion(), _validate_locator(), validate_navigation(), steps(), _validate_schema(), NavigationBrowserTests (+2 more)

### Community 20 - "Community 20"
Cohesion: 0.15
Nodes (32): _assertion(), _boundary(), _candidates(), _check_cancelled(), _close_tab(), _compact_recon(), _consequential_control(), execute_navigation() (+24 more)

### Community 21 - "Community 21"
Cohesion: 0.07
Nodes (11): composer_comparison(), copied_code_response(), fresh_assistant(), model_access_exhausted(), public_progress(), SubmissionNotSentError, upload_alert_is_error(), uploads_verified() (+3 more)

### Community 22 - "Community 22"
Cohesion: 0.08
Nodes (12): bounded_shape(), CompiledGraph, _pairs(), parse_contract(), _schema(), validate_contract(), retry_after(), matches() (+4 more)

### Community 23 - "Community 23"
Cohesion: 0.11
Nodes (27): bounded_hash(), build_catalogue(), _catalogue(), _compact(), current_scope(), execute_catalogue(), export_catalogue(), rank_records() (+19 more)

### Community 24 - "Community 24"
Cohesion: 0.09
Nodes (9): AssembledCapacityTests, DeliveryIntegrationTests, MockBrowser, execute(), finished(), planned(), unavailable(), PreloadingBrowser (+1 more)

### Community 25 - "Community 25"
Cohesion: 0.11
Nodes (11): build_bundle(), _build_reference(), build_startup_attachments(), _check_component_names(), _check_reference_names(), _hash(), _manifest_prefix(), _read_bounded() (+3 more)

### Community 27 - "Community 27"
Cohesion: 0.12
Nodes (9): SessionState, retained_root(), StateAndPromptTests, exercise(), exercise(), exercise(), exercise(), exercise() (+1 more)

### Community 28 - "Community 28"
Cohesion: 0.13
Nodes (21): _assert_workspace(), _bounded_int(), _check_object(), execute_package(), _await_stage(), run_stage(), _file_hash(), _load_state() (+13 more)

### Community 29 - "Community 29"
Cohesion: 0.16
Nodes (20): URLPolicy, active(), audit(), bind_namespace(), collection(), directory(), execute_permissions(), guard_customer_read() (+12 more)

### Community 30 - "Community 30"
Cohesion: 0.15
Nodes (4): PublicReader, ReadFailure, TLSStream, TransportTests

### Community 31 - "Community 31"
Cohesion: 0.11
Nodes (3): ManagedProcessRegistry, LocalPythonRunnerTests, exercise()

### Community 32 - "Community 32"
Cohesion: 0.19
Nodes (3): extract_zip(), inspect_zip(), ArchiveTests

### Community 33 - "Community 33"
Cohesion: 0.16
Nodes (13): ArchiveError, ArchiveService, _digest(), _entries(), directory(), _limits(), _office(), _reject_links() (+5 more)

### Community 34 - "Community 34"
Cohesion: 0.14
Nodes (5): extract(), StructureParser, Scope, manifest(), ContractTests

### Community 37 - "Community 37"
Cohesion: 0.12
Nodes (4): _safe_name(), UploadError, UploadStore, _validate_content()

### Community 38 - "Community 38"
Cohesion: 0.11
Nodes (11): definitions(), execute(), ToolRegistry, BrowserPlanExtensionTests, ExtractionLocationTests, download_request(), finish_after_second_review(), repair_after_first_review() (+3 more)

### Community 39 - "Community 39"
Cohesion: 0.16
Nodes (9): estimate_task(), inspect_package(), PackageReviewError, prepare_package_run(), recover_denied_run_plan(), AutomationPackageTests, run(), run() (+1 more)

### Community 40 - "Community 40"
Cohesion: 0.17
Nodes (17): compile_manifest(), validate_budgets(), correlation(), enabled(), input_object(), testing_gate(), validate_discovery(), execute_intent() (+9 more)

### Community 42 - "Community 42"
Cohesion: 0.09
Nodes (5): FakeButton, FakeEditor, InteractionReadinessTests, ReadinessAdapter, ReadinessControl

### Community 43 - "Community 43"
Cohesion: 0.20
Nodes (3): CodeRunner, PolicyError, NoExecutionRegistry

### Community 44 - "Community 44"
Cohesion: 0.12
Nodes (5): filesystem_diagnostic(), SessionNavigationGrant, SessionPathPolicy, PathPolicy, LocalNavigationTests

### Community 45 - "Community 45"
Cohesion: 0.16
Nodes (4): _public_file_metadata(), Workspace, run(), WorkspaceSteeringTests

### Community 46 - "Community 46"
Cohesion: 0.22
Nodes (3): choose_browser_endpoint(), BrowserEndpointTests, FakeSockets

### Community 47 - "Community 47"
Cohesion: 0.15
Nodes (11): key(), cdp_endpoint(), connect_bounded(), EndpointError, find_edge_executable(), get_cdp_version(), launch_edge(), port_listening() (+3 more)

### Community 48 - "Community 48"
Cohesion: 0.17
Nodes (10): capture_display(), enumerate_displays(), collect(), inspect_windows(), snapshot(), launch_viewers(), _MonitorInfo, _png_chunk() (+2 more)

### Community 49 - "Community 49"
Cohesion: 0.16
Nodes (10): config_value(), _approved_write_target(), configured_path_policy(), schema_example(), tool_path_policy(), scrub_urls(), _write_target(), validate_documents() (+2 more)

### Community 50 - "Community 50"
Cohesion: 0.13
Nodes (10): discover_edge_debugging_endpoints(), _edge_listener_process(), _hidden_command(), loopback_listener_pid(), _profile_argument(), profile_in_use(), validate_edge_listener(), validate_launched_endpoint() (+2 more)

### Community 53 - "Community 53"
Cohesion: 0.19
Nodes (5): _candidate_directories(), configure_temp_directory(), _probe_directory(), select_temp_directory(), TempStorageTests

### Community 54 - "Community 54"
Cohesion: 0.13
Nodes (7): __init__(), new_page(), __init__(), new_page(), Browser, Page, new_page()

### Community 57 - "Community 57"
Cohesion: 0.20
Nodes (3): start_new_session(), NewSessionTests, SessionBrowser

### Community 58 - "Community 58"
Cohesion: 0.16
Nodes (9): abandon_uncertain_browser_call(), _binding(), browser_diagnostics(), capture_baseline(), _hash(), _navigation_only(), navigation_scope_allows(), _origin() (+1 more)

### Community 59 - "Community 59"
Cohesion: 0.15
Nodes (7): _canonical(), _download_path_identity(), _Ticket, validate_download_args(), _wait_for_completed_file(), ArgumentsTests, DownloadCompletionTests

### Community 61 - "Community 61"
Cohesion: 0.22
Nodes (4): FilesystemAccessError, _final_s_path(), is_s_drive_path(), resolve_s_drive_output()

### Community 63 - "Community 63"
Cohesion: 0.30
Nodes (3): cancelled(), Engine, project_result()

### Community 65 - "Community 65"
Cohesion: 0.20
Nodes (3): Findings, EventLog, now()

### Community 67 - "Community 67"
Cohesion: 0.13
Nodes (4): delayed_link(), FakeAnchor, FakeLocator, FakePage

### Community 69 - "Community 69"
Cohesion: 0.22
Nodes (3): RuntimeCancellationTests, payload(), UploadStoreTests

### Community 71 - "Community 71"
Cohesion: 0.22
Nodes (3): _query_free(), reconcile_browser_call(), ReconciliationTests

### Community 72 - "Community 72"
Cohesion: 0.14
Nodes (3): FakeContext, FakeDownload, FakeSettingsPage

### Community 73 - "Community 73"
Cohesion: 0.24
Nodes (5): WebsiteIntegrationTests, fixture_page(), serve(), baseline(), approve()

### Community 75 - "Community 75"
Cohesion: 0.37
Nodes (4): parse_response(), encoded(), envelope(), ProtocolTests

### Community 80 - "Community 80"
Cohesion: 0.33
Nodes (10): Add-PythonCandidate(), Get-PipConfiguration(), Get-RecoveryBasePython(), Get-WorkingPip(), Initialize-AgentEnvironment(), Invoke-SetupPython(), Preserve-ProjectEnvironment(), Read-PythonPath() (+2 more)

### Community 81 - "Community 81"
Cohesion: 0.27
Nodes (3): CreatedSync, snapshot(), SyncTests

### Community 87 - "Community 87"
Cohesion: 0.42
Nodes (3): WebTransportTests, exchange(), exchange()

### Community 88 - "Community 88"
Cohesion: 0.44
Nodes (7): choose_source(), create_version(), digest(), main(), prepare_drop_folder(), replacement_map(), source_files()

### Community 90 - "Community 90"
Cohesion: 0.33
Nodes (6): guard(), register(), check_navigation(), download(), failed(), websocket_guard()

### Community 94 - "Community 94"
Cohesion: 0.29
Nodes (6): main(), approved_popen(), audit(), _normalized_executable(), _within(), _write_event()

### Community 97 - "Community 97"
Cohesion: 0.38
Nodes (3): correction_message(), _object_pairs(), ProtocolError

### Community 103 - "Community 103"
Cohesion: 0.47
Nodes (3): Add-IssueComment(), Invoke-GitHubRequest(), Set-IssueProcessed()

## Knowledge Gaps
- **8 isolated node(s):** `attachmentContainer`, `bookmarkIds`, `events`, `focusedComposer`, `labels` (+3 more)
  These have ≤1 connection - possible missing edges. (Counts symbols only; 751 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **46 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PolicyError` connect `Community 43` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 8`, `Community 10`, `Community 16`, `Community 19`, `Community 20`, `Community 23`, `Community 24`, `Community 26`, `Community 28`, `Community 29`, `Community 31`, `Community 32`, `Community 33`, `Community 38`, `Community 39`, `Community 44`, `Community 49`, `Community 51`, `Community 58`, `Community 61`, `Community 62`, `Community 66`, `Community 87`, `Community 98`?**
  _High betweenness centrality (0.178) - this node is a cross-community bridge._
- **Are the 32 inferred relationships involving `PolicyError` (e.g. with `_actionable()` and `ArchiveService`) actually correct?**
  _`PolicyError` has 32 INFERRED edges - model-reasoned connections that need verification._
- **What connects `attachmentContainer`, `bookmarkIds`, `events` to the rest of the system?**
  _8 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.056043956043956046 - nodes in this community are weakly interconnected._
- **Why does `BrowserAdapter` connect `Community 6` to `Community 1`, `Community 2`, `Community 3`, `Community 5`, `Community 8`, `Community 15`, `Community 17`, `Community 21`, `Community 29`, `Community 42`, `Community 43`, `Community 57`, `Community 58`, `Community 70`, `Community 73`, `Community 78`, `Community 83`, `Community 85`, `Community 90`, `Community 92`, `Community 110`, `Community 113`, `Community 114`?**
  _High betweenness centrality (0.081) - this node is a cross-community bridge._
- **Are the 30 inferred relationships involving `Orchestrator` (e.g. with `ApprovalManager` and `ArchiveService`) actually correct?**
  _`Orchestrator` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.04994400895856663 - nodes in this community are weakly interconnected._