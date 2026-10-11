# Graph Report - copilot-local-agent-20261011-203756  (2026-10-11)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 2176 nodes · 6766 edges · 93 communities (51 shown, 42 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 438 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b57d8b29`
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
- Community 82
- Community 83
- Community 85
- Community 86
- Community 88
- Community 89
- Community 90
- Community 91
- Community 92

## God Nodes (most connected - your core abstractions)
1. `PolicyError` - 146 edges
2. `DiscoveryError` - 104 edges
3. `Orchestrator` - 92 edges
4. `ToolRegistry` - 77 edges
5. `BrowserAdapter` - 77 edges
6. `PathPolicy` - 67 edges
7. `SessionState` - 64 edges
8. `Store` - 63 edges
9. `final_response()` - 56 edges
10. `Config` - 49 edges

## Surprising Connections (you probably didn't know these)
- `CodeRunnerTests` --uses--> `PathPolicy`  [INFERRED]
  tests/test_code_runner.py → copilot_agent/policy.py
- `LocalPythonRunnerTests` --uses--> `PathPolicy`  [INFERRED]
  tests/test_code_runner.py → copilot_agent/policy.py
- `CatalogueTests` --uses--> `PathPolicy`  [INFERRED]
  tests/test_document_catalogue.py → copilot_agent/policy.py
- `DownloadTests` --uses--> `PathPolicy`  [INFERRED]
  tests/test_downloads.py → copilot_agent/policy.py
- `StateAndPromptTests` --uses--> `PathPolicy`  [INFERRED]
  tests/test_protocol_state.py → copilot_agent/policy.py

## Import Cycles
- None detected.

## Communities (93 total, 42 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (19): ArchiveError, ArchiveService, _digest(), _entries(), extract_zip(), directory(), inspect_zip(), _limits() (+11 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (30): _actionable(), ask(), error(), main(), persist_runtime_settings(), read_runtime_settings(), _recent_events(), _record_bug_fix() (+22 more)

### Community 2 - "Community 2"
Cohesion: 0.05
Nodes (18): consequential(), abandon_uncertain_browser_call(), _binding(), browser_diagnostics(), capture_baseline(), _hash(), _navigation_only(), navigation_scope_allows() (+10 more)

### Community 3 - "Community 3"
Cohesion: 0.09
Nodes (29): validate_schema(), bind_namespace(), _approval(), _canonical(), _digest(), execute_knowledge(), _fingerprint(), _hash() (+21 more)

### Community 5 - "Community 5"
Cohesion: 0.07
Nodes (20): choose_browser_endpoint(), key(), cdp_endpoint(), connect_bounded(), EndpointError, find_edge_executable(), get_cdp_version(), _hidden_command() (+12 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (15): ApprovalManager, _actor_style(), _enable_colour(), Feedback, public_preview(), _terminal_text(), call_summary(), exchange_summary() (+7 more)

### Community 7 - "Community 7"
Cohesion: 0.09
Nodes (9): final_response(), OrchestratorTests, interrupted(), request_both(), two_calls(), malformed(), diagnostics(), partial_failure() (+1 more)

### Community 8 - "Community 8"
Cohesion: 0.09
Nodes (6): execute_documents(), DocumentTests, FakeContext, FakeDownload, FakePage, Pending

### Community 9 - "Community 9"
Cohesion: 0.14
Nodes (13): Config, _write_private(), write_json(), write_preserving(), run(), require(), run(), decide() (+5 more)

### Community 10 - "Community 10"
Cohesion: 0.09
Nodes (13): execute_discovery(), extract(), Response, budgets(), manifest(), task(), ContractTests, EngineTests (+5 more)

### Community 11 - "Community 11"
Cohesion: 0.12
Nodes (30): DiscoveryError, origin(), path(), directory(), _call(), run(), _compact(), _decode() (+22 more)

### Community 12 - "Community 12"
Cohesion: 0.14
Nodes (26): correlation(), enabled(), input_object(), prepare_discovery(), testing_gate(), validate_discovery(), candidate(), check_plan() (+18 more)

### Community 13 - "Community 13"
Cohesion: 0.11
Nodes (4): canonical(), alias(), digest(), Store

### Community 14 - "Community 14"
Cohesion: 0.10
Nodes (9): delivery_instruction(), delivery_requirements(), DeliveryRequirements, detect_requirements(), _expected_names(), retry_message(), _without_negated_clauses(), DeliveryRequirementTests (+1 more)

### Community 15 - "Community 15"
Cohesion: 0.15
Nodes (38): action(), api(), approvalReview(), attachmentContainer, backendPrompt(), bookmarkIds, button(), details() (+30 more)

### Community 16 - "Community 16"
Cohesion: 0.11
Nodes (13): bounded_shape(), compile_manifest(), CompiledGraph, _pairs(), parse_contract(), _schema(), validate_budgets(), validate_contract() (+5 more)

### Community 17 - "Community 17"
Cohesion: 0.10
Nodes (4): AttachmentError, AttachmentQueue, upload_name(), AttachmentTests

### Community 18 - "Community 18"
Cohesion: 0.17
Nodes (31): _assertion(), _boundary(), _candidates(), _check_cancelled(), _close_tab(), _consequential_control(), execute_navigation(), _execute_plan() (+23 more)

### Community 19 - "Community 19"
Cohesion: 0.15
Nodes (20): PolicyError, URLPolicy, active(), audit(), collection(), directory(), execute_permissions(), guard_customer_read() (+12 more)

### Community 20 - "Community 20"
Cohesion: 0.11
Nodes (11): build_bundle(), _build_reference(), build_startup_attachments(), _check_component_names(), _check_reference_names(), _hash(), _manifest_prefix(), _read_bounded() (+3 more)

### Community 21 - "Community 21"
Cohesion: 0.12
Nodes (25): bounded_hash(), build_catalogue(), _catalogue(), _compact(), current_scope(), execute_catalogue(), export_catalogue(), rank_records() (+17 more)

### Community 22 - "Community 22"
Cohesion: 0.09
Nodes (17): _category(), _caught_frame(), DiagnosticReports, _exception_chain(), _frames(), _ownership(), _recommend(), _safe_text() (+9 more)

### Community 23 - "Community 23"
Cohesion: 0.10
Nodes (11): error(), select_files(), file_record(), RecordedBrowser, committed(), require(), run(), decide() (+3 more)

### Community 24 - "Community 24"
Cohesion: 0.12
Nodes (9): DeliveryIntegrationTests, MockBrowser, PreloadingBrowser, make_fixture(), RecoveryOrchestrationTests, approve(), new_page(), new_page() (+1 more)

### Community 26 - "Community 26"
Cohesion: 0.09
Nodes (5): AgentRuntime, create_runtime(), PromptBroker, PromptBrokerTests, RuntimeCancellationTests

### Community 27 - "Community 27"
Cohesion: 0.10
Nodes (15): redact(), obj(), InjectedCaptureBrowser, record(), read_approval(), unique_pairs(), require(), run() (+7 more)

### Community 30 - "Community 30"
Cohesion: 0.12
Nodes (8): retained_root(), StateAndPromptTests, exercise(), exercise(), exercise(), exercise(), exercise(), exercise()

### Community 31 - "Community 31"
Cohesion: 0.20
Nodes (3): PublicReader, ReadFailure, TLSStream

### Community 32 - "Community 32"
Cohesion: 0.11
Nodes (5): composer_comparison(), fresh_assistant(), upload_alert_is_error(), value(), RemainingCorrelationTests

### Community 35 - "Community 35"
Cohesion: 0.18
Nodes (4): FakeTLSContext, TransportTests, OperationTests, counted()

### Community 36 - "Community 36"
Cohesion: 0.15
Nodes (7): _record_turn_error(), CaptureTimeoutError, copied_code_response(), model_access_exhausted(), model_rank(), SubmissionNotSentError, CorrelationTests

### Community 38 - "Community 38"
Cohesion: 0.18
Nodes (10): capture_display(), enumerate_displays(), collect(), inspect_windows(), snapshot(), launch_viewers(), _MonitorInfo, _png_chunk() (+2 more)

### Community 39 - "Community 39"
Cohesion: 0.13
Nodes (7): definitions(), execute(), ToolRegistry, validate(), BrowserPlanExtensionTests, QuietFeedback, ExtractionLocationTests

### Community 42 - "Community 42"
Cohesion: 0.18
Nodes (6): format_valid(), Orchestrator, correction_message(), _object_pairs(), parse_response(), ProtocolError

### Community 43 - "Community 43"
Cohesion: 0.21
Nodes (11): _children(), execute_local_python(), _hash_file(), _ledger_records(), _pid_running(), _preflight_imports(), _read_bounded(), runtime_binding() (+3 more)

### Community 44 - "Community 44"
Cohesion: 0.24
Nodes (5): _canonical(), DownloadError, DownloadService, _Ticket, validate_download_args()

### Community 45 - "Community 45"
Cohesion: 0.15
Nodes (8): config_value(), configured_path_policy(), schema_example(), scrub_urls(), validate_documents(), _validate_shape(), _compact_recon(), ShapeTests

### Community 47 - "Community 47"
Cohesion: 0.19
Nodes (3): start_new_session(), NewSessionTests, SessionBrowser

### Community 50 - "Community 50"
Cohesion: 0.13
Nodes (4): ArgumentsTests, FakeAnchor, FakeLocator, FakePage

### Community 54 - "Community 54"
Cohesion: 0.16
Nodes (3): response_envelope_closed(), ExchangeTests, PreloadedOfflineAdapter

### Community 55 - "Community 55"
Cohesion: 0.29
Nodes (3): cancelled(), Engine, project_result()

### Community 56 - "Community 56"
Cohesion: 0.21
Nodes (3): CreatedSync, snapshot(), SyncTests

### Community 57 - "Community 57"
Cohesion: 0.19
Nodes (8): clear_navigation_state(), plan_hash(), _validate_assertion(), _validate_locator(), validate_navigation(), steps(), _validate_schema(), NavigationSchemaTests

### Community 60 - "Community 60"
Cohesion: 0.14
Nodes (3): FakeContext, FakeDownload, FakeSettingsPage

### Community 61 - "Community 61"
Cohesion: 0.29
Nodes (10): Add-PythonCandidate(), Get-PipConfiguration(), Get-RecoveryBasePython(), Get-WorkingPip(), Initialize-AgentEnvironment(), Invoke-SetupPython(), Preserve-ProjectEnvironment(), Read-PythonPath() (+2 more)

### Community 63 - "Community 63"
Cohesion: 0.26
Nodes (3): WebsiteIntegrationTests, baseline(), approve()

### Community 64 - "Community 64"
Cohesion: 0.35
Nodes (10): canonical_hash(), bounded_bytes(), load_json(), unique(), NoExecutionRegistry, require(), run(), decide() (+2 more)

### Community 66 - "Community 66"
Cohesion: 0.35
Nodes (3): encoded(), envelope(), ProtocolTests

### Community 69 - "Community 69"
Cohesion: 0.40
Nodes (7): choose_source(), create_version(), digest(), main(), prepare_drop_folder(), replacement_map(), source_files()

### Community 74 - "Community 74"
Cohesion: 0.42
Nodes (3): WebTransportTests, exchange(), exchange()

### Community 77 - "Community 77"
Cohesion: 0.33
Nodes (6): guard(), register(), check_navigation(), download(), failed(), websocket_guard()

## Knowledge Gaps
- **6 isolated node(s):** `attachmentContainer`, `bookmarkIds`, `events`, `focusedComposer`, `labels` (+1 more)
  These have ≤1 connection - possible missing edges. (Counts symbols only; 552 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **42 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PolicyError` connect `Community 19` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 6`, `Community 7`, `Community 8`, `Community 17`, `Community 18`, `Community 21`, `Community 24`, `Community 25`, `Community 27`, `Community 34`, `Community 36`, `Community 39`, `Community 41`, `Community 42`, `Community 43`, `Community 45`, `Community 51`, `Community 52`, `Community 57`, `Community 58`, `Community 64`, `Community 74`, `Community 90`?**
  _High betweenness centrality (0.116) - this node is a cross-community bridge._
- **Are the 26 inferred relationships involving `PolicyError` (e.g. with `_actionable()` and `ArchiveService`) actually correct?**
  _`PolicyError` has 26 INFERRED edges - model-reasoned connections that need verification._
- **What connects `attachmentContainer`, `bookmarkIds`, `events` to the rest of the system?**
  _6 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.06388888888888888 - nodes in this community are weakly interconnected._
- **Why does `PathPolicy` connect `Community 0` to `Community 2`, `Community 3`, `Community 4`, `Community 6`, `Community 8`, `Community 9`, `Community 11`, `Community 13`, `Community 17`, `Community 19`, `Community 23`, `Community 27`, `Community 29`, `Community 30`, `Community 34`, `Community 37`, `Community 39`, `Community 41`, `Community 42`, `Community 45`, `Community 50`, `Community 52`, `Community 58`, `Community 60`, `Community 63`, `Community 64`, `Community 80`?**
  _High betweenness centrality (0.070) - this node is a cross-community bridge._
- **Are the 15 inferred relationships involving `DiscoveryError` (e.g. with `Engine` and `StructureParser`) actually correct?**
  _`DiscoveryError` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.05322947095098994 - nodes in this community are weakly interconnected._