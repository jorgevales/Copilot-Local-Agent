# Graph Report - copilot-local-agent-20261011-113706  (2026-10-11)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 2175 nodes · 6759 edges · 86 communities (51 shown, 35 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 436 edges (avg confidence: 0.9)
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
- Community 73
- Community 74
- Community 75
- Community 76
- Community 77
- Community 78
- Community 79
- Community 80
- Community 81
- Community 84
- Community 85

## God Nodes (most connected - your core abstractions)
1. `PolicyError` - 146 edges
2. `DiscoveryError` - 104 edges
3. `Orchestrator` - 91 edges
4. `ToolRegistry` - 77 edges
5. `BrowserAdapter` - 77 edges
6. `PathPolicy` - 67 edges
7. `SessionState` - 64 edges
8. `Store` - 63 edges
9. `final_response()` - 55 edges
10. `Config` - 49 edges

## Surprising Connections (you probably didn't know these)
- `NewSessionTests` --uses--> `Orchestrator`  [INFERRED]
  tests/test_app_sessions.py → copilot_agent/orchestrator.py
- `OrchestratorTests` --uses--> `AttachmentQueue`  [INFERRED]
  tests/test_orchestrator.py → copilot_agent/attachments.py
- `OrchestratorTests` --uses--> `CaptureTimeoutError`  [INFERRED]
  tests/test_orchestrator.py → copilot_agent/browser.py
- `OrchestratorTests` --uses--> `SubmissionAmbiguousError`  [INFERRED]
  tests/test_orchestrator.py → copilot_agent/browser.py
- `OrchestratorTests` --uses--> `Orchestrator`  [INFERRED]
  tests/test_orchestrator.py → copilot_agent/orchestrator.py

## Import Cycles
- None detected.

## Communities (86 total, 35 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (15): start_new_session(), NewSessionTests, SessionBrowser, final_response(), OrchestratorTests, interrupted(), request_both(), two_calls() (+7 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (13): EventLog, now(), SessionState, FixtureRegistry, retained_root(), StateAndPromptTests, exercise(), exercise() (+5 more)

### Community 2 - "Community 2"
Cohesion: 0.09
Nodes (20): compile_manifest(), execute_discovery(), extract(), prepare_discovery(), Response, Scope, budgets(), intent() (+12 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (24): _category(), _caught_frame(), DiagnosticReports, _exception_chain(), _frames(), _ownership(), _recommend(), _safe_text() (+16 more)

### Community 4 - "Community 4"
Cohesion: 0.11
Nodes (15): CaptureTimeoutError, SubmissionNotSentError, Config, write_json(), write_preserving(), audit_evidence(), private_id(), private_session_snapshot() (+7 more)

### Community 5 - "Community 5"
Cohesion: 0.10
Nodes (16): ArchiveError, ArchiveService, _digest(), _entries(), extract_zip(), directory(), inspect_zip(), _limits() (+8 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (8): DocumentTests, FakeContext, FakeDownload, FakePage, Pending, WebTransportTests, exchange(), exchange()

### Community 7 - "Community 7"
Cohesion: 0.10
Nodes (8): main(), PathPolicy, definitions(), execute(), ToolRegistry, main(), BrowserPlanExtensionTests, ExtractionLocationTests

### Community 8 - "Community 8"
Cohesion: 0.11
Nodes (4): BrowserAdapter, BrowserUIError, ModelAccessError, SubmissionAmbiguousError

### Community 9 - "Community 9"
Cohesion: 0.09
Nodes (16): consequential(), URLPolicy, abandon_uncertain_browser_call(), _binding(), browser_diagnostics(), capture_baseline(), _hash(), _navigation_only() (+8 more)

### Community 10 - "Community 10"
Cohesion: 0.07
Nodes (33): error(), redact(), canonical_hash(), obj(), InjectedCaptureBrowser, record(), file_record(), RecordedBrowser (+25 more)

### Community 11 - "Community 11"
Cohesion: 0.11
Nodes (29): origin(), _call(), run(), _compact(), _decode(), _enabled(), _entropy(), execute_operation() (+21 more)

### Community 12 - "Community 12"
Cohesion: 0.10
Nodes (6): canonical(), alias(), digest(), directory(), Store, reject_path_redirection()

### Community 13 - "Community 13"
Cohesion: 0.14
Nodes (33): _assertion(), _boundary(), _candidates(), _check_cancelled(), clear_navigation_state(), _close_tab(), _compact_recon(), execute_navigation() (+25 more)

### Community 14 - "Community 14"
Cohesion: 0.09
Nodes (4): AttachmentError, AttachmentQueue, upload_name(), AttachmentTests

### Community 15 - "Community 15"
Cohesion: 0.08
Nodes (10): delivery_instruction(), delivery_requirements(), DeliveryRequirements, detect_requirements(), _expected_names(), retry_message(), _without_negated_clauses(), DeliveryRequirementTests (+2 more)

### Community 16 - "Community 16"
Cohesion: 0.07
Nodes (14): bounded_shape(), CompiledGraph, format_valid(), _pairs(), parse_contract(), _schema(), retry_after(), matches() (+6 more)

### Community 17 - "Community 17"
Cohesion: 0.10
Nodes (29): bounded_hash(), build_catalogue(), _catalogue(), _compact(), current_scope(), execute_catalogue(), export_catalogue(), rank_records() (+21 more)

### Community 18 - "Community 18"
Cohesion: 0.09
Nodes (10): Orchestrator, correction_message(), _object_pairs(), ProtocolError, AssembledCapacityTests, DeliveryIntegrationTests, MockBrowser, make_fixture() (+2 more)

### Community 19 - "Community 19"
Cohesion: 0.16
Nodes (26): DiscoveryError, validate_budgets(), validate_contract(), correlation(), enabled(), input_object(), project_result(), testing_gate() (+18 more)

### Community 20 - "Community 20"
Cohesion: 0.15
Nodes (38): action(), api(), approvalReview(), attachmentContainer, backendPrompt(), bookmarkIds, button(), details() (+30 more)

### Community 21 - "Community 21"
Cohesion: 0.09
Nodes (19): copied_code_response(), model_access_exhausted(), cdp_endpoint(), connect_bounded(), EndpointError, find_edge_executable(), get_cdp_version(), _hidden_command() (+11 more)

### Community 22 - "Community 22"
Cohesion: 0.08
Nodes (5): response_envelope_closed(), ExchangeTests, OfflineAdapter, PreloadedOfflineAdapter, ToolContextTests

### Community 23 - "Community 23"
Cohesion: 0.12
Nodes (11): default_storage(), discover_onedrive_accounts(), OneDriveAccount, profile_directory(), read_user_settings(), _registry_paths(), save_user_settings(), saved_storage_choice() (+3 more)

### Community 24 - "Community 24"
Cohesion: 0.12
Nodes (23): _approval(), _canonical(), _digest(), _fingerprint(), _json_pairs(), knowledge_directory(), KnowledgeValidationError, _now() (+15 more)

### Community 25 - "Community 25"
Cohesion: 0.12
Nodes (11): build_bundle(), _build_reference(), build_startup_attachments(), _check_component_names(), _check_reference_names(), _hash(), _manifest_prefix(), _read_bounded() (+3 more)

### Community 26 - "Community 26"
Cohesion: 0.12
Nodes (3): NavigationBrowserTests, NavigationSchemaTests, search_plan()

### Community 27 - "Community 27"
Cohesion: 0.09
Nodes (5): AgentRuntime, create_runtime(), PromptBroker, PromptBrokerTests, RuntimeCancellationTests

### Community 28 - "Community 28"
Cohesion: 0.21
Nodes (3): execute_knowledge(), _timestamp(), SiteKnowledgeTests

### Community 29 - "Community 29"
Cohesion: 0.09
Nodes (8): composer_comparison(), fresh_assistant(), model_rank(), key(), upload_alert_is_error(), uploads_verified(), value(), RemainingCorrelationTests

### Community 30 - "Community 30"
Cohesion: 0.20
Nodes (21): active(), audit(), bind_namespace(), collection(), directory(), execute_permissions(), guard_customer_read(), list_grants() (+13 more)

### Community 33 - "Community 33"
Cohesion: 0.16
Nodes (15): _actionable(), ask(), choose_browser_endpoint(), error(), main(), persist_runtime_settings(), read_runtime_settings(), _recent_events() (+7 more)

### Community 34 - "Community 34"
Cohesion: 0.20
Nodes (3): PublicReader, ReadFailure, TLSStream

### Community 35 - "Community 35"
Cohesion: 0.13
Nodes (4): Findings, PromptBuilder, main(), run()

### Community 39 - "Community 39"
Cohesion: 0.18
Nodes (10): capture_display(), enumerate_displays(), collect(), inspect_windows(), snapshot(), launch_viewers(), _MonitorInfo, _png_chunk() (+2 more)

### Community 40 - "Community 40"
Cohesion: 0.19
Nodes (6): choice(), choose_account(), choose_edge(), pasted_path(), machine_key(), ResourceSetupTests

### Community 42 - "Community 42"
Cohesion: 0.18
Nodes (3): cancelled(), Engine, StructureParser

### Community 43 - "Community 43"
Cohesion: 0.21
Nodes (11): _children(), execute_local_python(), _hash_file(), _ledger_records(), _pid_running(), _preflight_imports(), _read_bounded(), runtime_binding() (+3 more)

### Community 46 - "Community 46"
Cohesion: 0.24
Nodes (5): _canonical(), DownloadError, DownloadService, _Ticket, validate_download_args()

### Community 48 - "Community 48"
Cohesion: 0.13
Nodes (4): ArgumentsTests, FakeAnchor, FakeLocator, FakePage

### Community 49 - "Community 49"
Cohesion: 0.17
Nodes (5): Browser, Page, approve(), new_page(), new_page()

### Community 50 - "Community 50"
Cohesion: 0.18
Nodes (5): ApprovalManager, call_summary(), exchange_summary(), readable(), QuietFeedback

### Community 52 - "Community 52"
Cohesion: 0.19
Nodes (4): config_value(), configured_path_policy(), schema_example(), scrub_urls()

### Community 53 - "Community 53"
Cohesion: 0.21
Nodes (3): CreatedSync, snapshot(), SyncTests

### Community 55 - "Community 55"
Cohesion: 0.14
Nodes (3): FakeContext, FakeDownload, FakeSettingsPage

### Community 56 - "Community 56"
Cohesion: 0.37
Nodes (4): parse_response(), encoded(), envelope(), ProtocolTests

### Community 57 - "Community 57"
Cohesion: 0.29
Nodes (10): Add-PythonCandidate(), Get-PipConfiguration(), Get-RecoveryBasePython(), Get-WorkingPip(), Initialize-AgentEnvironment(), Invoke-SetupPython(), Preserve-ProjectEnvironment(), Read-PythonPath() (+2 more)

### Community 62 - "Community 62"
Cohesion: 0.40
Nodes (7): choose_source(), create_version(), digest(), main(), prepare_drop_folder(), replacement_map(), source_files()

### Community 64 - "Community 64"
Cohesion: 0.33
Nodes (3): WebsiteIntegrationTests, baseline(), approve()

### Community 72 - "Community 72"
Cohesion: 0.33
Nodes (6): guard(), register(), check_navigation(), download(), failed(), websocket_guard()

### Community 76 - "Community 76"
Cohesion: 0.53
Nodes (5): _validate_assertion(), _validate_locator(), validate_navigation(), steps(), _validate_schema()

## Knowledge Gaps
- **6 isolated node(s):** `attachmentContainer`, `bookmarkIds`, `events`, `focusedComposer`, `labels` (+1 more)
  These have ≤1 connection - possible missing edges. (Counts symbols only; 552 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **35 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PolicyError` connect `Community 36` to `Community 0`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 10`, `Community 12`, `Community 13`, `Community 14`, `Community 17`, `Community 18`, `Community 24`, `Community 26`, `Community 28`, `Community 30`, `Community 33`, `Community 38`, `Community 41`, `Community 43`, `Community 45`, `Community 52`, `Community 54`?**
  _High betweenness centrality (0.134) - this node is a cross-community bridge._
- **Are the 26 inferred relationships involving `PolicyError` (e.g. with `_actionable()` and `ArchiveService`) actually correct?**
  _`PolicyError` has 26 INFERRED edges - model-reasoned connections that need verification._
- **What connects `attachmentContainer`, `bookmarkIds`, `events` to the rest of the system?**
  _6 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.051189400782896716 - nodes in this community are weakly interconnected._
- **Why does `BrowserAdapter` connect `Community 8` to `Community 0`, `Community 33`, `Community 64`, `Community 35`, `Community 4`, `Community 36`, `Community 67`, `Community 7`, `Community 72`, `Community 9`, `Community 10`, `Community 73`, `Community 74`, `Community 78`, `Community 83`, `Community 51`, `Community 21`, `Community 22`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._
- **Are the 15 inferred relationships involving `DiscoveryError` (e.g. with `Engine` and `StructureParser`) actually correct?**
  _`DiscoveryError` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.05714285714285714 - nodes in this community are weakly interconnected._