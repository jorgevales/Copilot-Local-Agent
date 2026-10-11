# Graph Report - copilot-local-agent-20261011-102323  (2026-10-11)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 2164 nodes · 6719 edges · 93 communities (55 shown, 38 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 433 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

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
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70
- Community 71
- Community 72
- Community 74
- Community 75
- Community 76
- Community 77
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
- Community 88
- Community 89
- Community 91
- Community 92

## God Nodes (most connected - your core abstractions)
1. `PolicyError` - 145 edges
2. `DiscoveryError` - 104 edges
3. `Orchestrator` - 90 edges
4. `BrowserAdapter` - 77 edges
5. `ToolRegistry` - 76 edges
6. `PathPolicy` - 67 edges
7. `SessionState` - 63 edges
8. `Store` - 63 edges
9. `final_response()` - 54 edges
10. `Config` - 49 edges

## Surprising Connections (you probably didn't know these)
- `NavigationBrowserTests` --uses--> `PolicyError`  [INFERRED]
  tests/test_web_navigation.py → copilot_agent/policy.py
- `NavigationBrowserTests` --uses--> `SessionState`  [INFERRED]
  tests/test_web_navigation.py → copilot_agent/state.py
- `NavigationBrowserTests` --uses--> `ToolRegistry`  [INFERRED]
  tests/test_web_navigation.py → copilot_agent/tools.py
- `run()` --uses--> `Config`  [INFERRED]
  tests/live_attachments.py → copilot_agent/config.py
- `run()` --uses--> `Config`  [INFERRED]
  tests/live_download_run.py → copilot_agent/config.py

## Import Cycles
- None detected.

## Communities (93 total, 38 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (40): _assertion(), _boundary(), _candidates(), _check_cancelled(), _close_tab(), _compact_recon(), _consequential_control(), execute_navigation() (+32 more)

### Community 1 - "Community 1"
Cohesion: 0.11
Nodes (15): Config, documents_directory(), write_json(), write_preserving(), run(), require(), run(), decide() (+7 more)

### Community 2 - "Community 2"
Cohesion: 0.10
Nodes (16): ArchiveError, ArchiveService, _digest(), _entries(), extract_zip(), directory(), inspect_zip(), _limits() (+8 more)

### Community 3 - "Community 3"
Cohesion: 0.07
Nodes (6): AttachmentError, AttachmentQueue, upload_name(), select_files(), AttachmentTests, FilePickerTests

### Community 4 - "Community 4"
Cohesion: 0.09
Nodes (8): final_response(), OrchestratorTests, request_both(), two_calls(), malformed(), diagnostics(), partial_failure(), tool_response()

### Community 5 - "Community 5"
Cohesion: 0.07
Nodes (13): bounded_shape(), compile_manifest(), CompiledGraph, _pairs(), parse_contract(), _schema(), retry_after(), matches() (+5 more)

### Community 6 - "Community 6"
Cohesion: 0.11
Nodes (7): canonical(), DiscoveryError, verify_page(), alias(), digest(), Store, slot()

### Community 7 - "Community 7"
Cohesion: 0.11
Nodes (28): origin(), _call(), run(), _compact(), _decode(), _enabled(), _entropy(), execute_operation() (+20 more)

### Community 8 - "Community 8"
Cohesion: 0.08
Nodes (10): delivery_instruction(), delivery_requirements(), DeliveryRequirements, detect_requirements(), _expected_names(), retry_message(), _without_negated_clauses(), DeliveryRequirementTests (+2 more)

### Community 9 - "Community 9"
Cohesion: 0.15
Nodes (15): execute_discovery(), prepare_discovery(), Response, budgets(), intent(), manifest(), task(), workspace() (+7 more)

### Community 10 - "Community 10"
Cohesion: 0.10
Nodes (9): ApprovalManager, Orchestrator, AssembledCapacityTests, DeliveryIntegrationTests, MockBrowser, PreloadingBrowser, make_fixture(), RecoveryOrchestrationTests (+1 more)

### Community 11 - "Community 11"
Cohesion: 0.07
Nodes (14): config_value(), URLPolicy, validate_schema(), configured_path_policy(), definitions(), execute(), obj(), schema_example() (+6 more)

### Community 12 - "Community 12"
Cohesion: 0.12
Nodes (25): _approval(), _canonical(), _digest(), execute_knowledge(), _fingerprint(), _hash(), _json_pairs(), knowledge_directory() (+17 more)

### Community 13 - "Community 13"
Cohesion: 0.15
Nodes (10): format_valid(), call_summary(), exchange_summary(), readable(), correction_message(), canonical_hash(), audit_evidence(), private_id() (+2 more)

### Community 14 - "Community 14"
Cohesion: 0.15
Nodes (38): action(), api(), approvalReview(), attachmentContainer, backendPrompt(), bookmarkIds, button(), details() (+30 more)

### Community 15 - "Community 15"
Cohesion: 0.09
Nodes (29): error(), redact(), InjectedCaptureBrowser, file_record(), RecordedBrowser, committed(), require(), run() (+21 more)

### Community 16 - "Community 16"
Cohesion: 0.08
Nodes (5): response_envelope_closed(), ExchangeTests, OfflineAdapter, PreloadedOfflineAdapter, ToolContextTests

### Community 17 - "Community 17"
Cohesion: 0.09
Nodes (10): Findings, PromptBuilder, retained_root(), StateAndPromptTests, exercise(), exercise(), exercise(), exercise() (+2 more)

### Community 18 - "Community 18"
Cohesion: 0.08
Nodes (9): composer_comparison(), copied_code_response(), fresh_assistant(), model_access_exhausted(), model_rank(), upload_alert_is_error(), value(), CorrelationTests (+1 more)

### Community 19 - "Community 19"
Cohesion: 0.11
Nodes (11): default_storage(), discover_onedrive_accounts(), OneDriveAccount, profile_directory(), read_user_settings(), _registry_paths(), save_user_settings(), saved_storage_choice() (+3 more)

### Community 20 - "Community 20"
Cohesion: 0.12
Nodes (11): build_bundle(), _build_reference(), build_startup_attachments(), _check_component_names(), _check_reference_names(), _hash(), _manifest_prefix(), _read_bounded() (+3 more)

### Community 21 - "Community 21"
Cohesion: 0.12
Nodes (25): bounded_hash(), build_catalogue(), _catalogue(), _compact(), current_scope(), execute_catalogue(), export_catalogue(), rank_records() (+17 more)

### Community 22 - "Community 22"
Cohesion: 0.14
Nodes (5): PublicReader, ReadFailure, TLSStream, FakeTLSContext, TransportTests

### Community 23 - "Community 23"
Cohesion: 0.12
Nodes (10): cancelled(), enabled(), Engine, extract(), input_object(), project_result(), StructureParser, testing_gate() (+2 more)

### Community 24 - "Community 24"
Cohesion: 0.10
Nodes (7): _actor_style(), _enable_colour(), Feedback, public_preview(), _terminal_text(), FeedbackIntegrationTests, PreviewTests

### Community 25 - "Community 25"
Cohesion: 0.20
Nodes (21): reject_path_redirection(), active(), audit(), bind_namespace(), collection(), directory(), execute_permissions(), guard_customer_read() (+13 more)

### Community 26 - "Community 26"
Cohesion: 0.13
Nodes (14): key(), connect_bounded(), find_edge_executable(), get_cdp_version(), _hidden_command(), launch_edge(), loopback_listener_pid(), port_listening() (+6 more)

### Community 27 - "Community 27"
Cohesion: 0.16
Nodes (3): EventLog, now(), SessionState

### Community 28 - "Community 28"
Cohesion: 0.17
Nodes (12): _category(), _caught_frame(), DiagnosticReports, _exception_chain(), _frames(), _ownership(), _recommend(), _safe_text() (+4 more)

### Community 31 - "Community 31"
Cohesion: 0.16
Nodes (11): _children(), execute_local_python(), _hash_file(), _ledger_records(), _pid_running(), _preflight_imports(), _read_bounded(), runtime_binding() (+3 more)

### Community 34 - "Community 34"
Cohesion: 0.12
Nodes (4): create_runtime(), main(), RuntimeCancellationTests, main()

### Community 35 - "Community 35"
Cohesion: 0.19
Nodes (6): choose_browser_endpoint(), cdp_endpoint(), EndpointError, validate_endpoint(), BrowserEndpointTests, FakeSockets

### Community 36 - "Community 36"
Cohesion: 0.19
Nodes (3): CodeRunner, PolicyError, NoExecutionRegistry

### Community 37 - "Community 37"
Cohesion: 0.25
Nodes (19): validate_budgets(), validate_contract(), correlation(), candidate(), check_plan(), compile_intent(), execute_intent(), execute_knowledge_tool() (+11 more)

### Community 40 - "Community 40"
Cohesion: 0.12
Nodes (5): _query_free(), reconcile_browser_call(), ReconciliationRequired, recover_missing_navigation(), ReconciliationTests

### Community 42 - "Community 42"
Cohesion: 0.18
Nodes (10): capture_display(), enumerate_displays(), collect(), inspect_windows(), snapshot(), launch_viewers(), _MonitorInfo, _png_chunk() (+2 more)

### Community 43 - "Community 43"
Cohesion: 0.19
Nodes (6): choice(), choose_account(), choose_edge(), pasted_path(), machine_key(), ResourceSetupTests

### Community 45 - "Community 45"
Cohesion: 0.24
Nodes (5): _canonical(), DownloadError, DownloadService, _Ticket, validate_download_args()

### Community 47 - "Community 47"
Cohesion: 0.14
Nodes (3): LaunchUITests, Workspace, run()

### Community 48 - "Community 48"
Cohesion: 0.21
Nodes (13): _actionable(), ask(), error(), main(), persist_runtime_settings(), read_runtime_settings(), _recent_events(), _record_bug_fix() (+5 more)

### Community 49 - "Community 49"
Cohesion: 0.20
Nodes (9): _binding(), browser_diagnostics(), capture_baseline(), _hash(), _navigation_only(), navigation_scope_allows(), _origin(), _owned_page() (+1 more)

### Community 50 - "Community 50"
Cohesion: 0.25
Nodes (6): _object_pairs(), parse_response(), ProtocolError, encoded(), envelope(), ProtocolTests

### Community 51 - "Community 51"
Cohesion: 0.14
Nodes (6): ToolRegistry, BrowserPlanExtensionTests, QuietFeedback, ExtractionLocationTests, finished(), planned()

### Community 52 - "Community 52"
Cohesion: 0.19
Nodes (3): start_new_session(), NewSessionTests, SessionBrowser

### Community 54 - "Community 54"
Cohesion: 0.22
Nodes (6): CaptureTimeoutError, SubmissionNotSentError, interrupted(), WebTransportTests, exchange(), exchange()

### Community 55 - "Community 55"
Cohesion: 0.13
Nodes (4): ArgumentsTests, FakeAnchor, FakeLocator, FakePage

### Community 57 - "Community 57"
Cohesion: 0.12
Nodes (3): FakeContext, FakeDownload, FakePage

### Community 61 - "Community 61"
Cohesion: 0.21
Nodes (3): CreatedSync, snapshot(), SyncTests

### Community 64 - "Community 64"
Cohesion: 0.14
Nodes (3): FakeContext, FakeDownload, FakeSettingsPage

### Community 66 - "Community 66"
Cohesion: 0.29
Nodes (10): Add-PythonCandidate(), Get-PipConfiguration(), Get-RecoveryBasePython(), Get-WorkingPip(), Initialize-AgentEnvironment(), Invoke-SetupPython(), Preserve-ProjectEnvironment(), Read-PythonPath() (+2 more)

### Community 68 - "Community 68"
Cohesion: 0.26
Nodes (3): WebsiteIntegrationTests, baseline(), approve()

### Community 69 - "Community 69"
Cohesion: 0.36
Nodes (7): choose_source(), create_version(), digest(), main(), prepare_drop_folder(), replacement_map(), source_files()

### Community 72 - "Community 72"
Cohesion: 0.25
Nodes (6): main(), approved_popen(), audit(), _normalized_executable(), _within(), _write_event()

### Community 80 - "Community 80"
Cohesion: 0.33
Nodes (6): guard(), register(), check_navigation(), download(), failed(), websocket_guard()

### Community 83 - "Community 83"
Cohesion: 0.28
Nodes (3): Browser, Page, new_page()

## Knowledge Gaps
- **6 isolated node(s):** `attachmentContainer`, `bookmarkIds`, `events`, `focusedComposer`, `labels` (+1 more)
  These have ≤1 connection - possible missing edges. (Counts symbols only; 548 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **38 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PolicyError` connect `Community 36` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 10`, `Community 11`, `Community 12`, `Community 13`, `Community 21`, `Community 25`, `Community 30`, `Community 31`, `Community 32`, `Community 38`, `Community 41`, `Community 44`, `Community 48`, `Community 49`, `Community 51`, `Community 53`, `Community 54`, `Community 56`, `Community 58`, `Community 62`, `Community 63`?**
  _High betweenness centrality (0.114) - this node is a cross-community bridge._
- **Are the 26 inferred relationships involving `PolicyError` (e.g. with `_actionable()` and `ArchiveService`) actually correct?**
  _`PolicyError` has 26 INFERRED edges - model-reasoned connections that need verification._
- **What connects `attachmentContainer`, `bookmarkIds`, `events` to the rest of the system?**
  _6 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.0675990675990676 - nodes in this community are weakly interconnected._
- **Why does `BrowserAdapter` connect `Community 58` to `Community 1`, `Community 11`, `Community 15`, `Community 16`, `Community 18`, `Community 32`, `Community 36`, `Community 39`, `Community 48`, `Community 49`, `Community 52`, `Community 53`, `Community 60`, `Community 68`, `Community 76`, `Community 80`, `Community 81`, `Community 82`, `Community 87`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Are the 15 inferred relationships involving `DiscoveryError` (e.g. with `Engine` and `StructureParser`) actually correct?**
  _`DiscoveryError` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.11103896103896103 - nodes in this community are weakly interconnected._