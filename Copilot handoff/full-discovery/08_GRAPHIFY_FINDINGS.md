# Graph Report - copilot-local-agent  (2026-10-07)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1376 nodes · 3756 edges · 60 communities (33 shown, 27 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 252 edges (avg confidence: 0.89)
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

## God Nodes (most connected - your core abstractions)
1. `PolicyError` - 66 edges
2. `BrowserAdapter` - 59 edges
3. `Orchestrator` - 54 edges
4. `ToolRegistry` - 50 edges
5. `SessionState` - 46 edges
6. `PathPolicy` - 46 edges
7. `final_response()` - 43 edges
8. `Config` - 41 edges
9. `redact()` - 41 edges
10. `OrchestratorTests` - 40 edges

## Surprising Connections (you probably didn't know these)
- `run()` --uses--> `Config`  [INFERRED]
  tests/live_verify_completed_run.py → copilot_agent/config.py
- `FeedbackIntegrationTests` --uses--> `Config`  [INFERRED]
  tests/test_feedback.py → copilot_agent/config.py
- `StateAndPromptTests` --uses--> `Config`  [INFERRED]
  tests/test_protocol_state.py → copilot_agent/config.py
- `ResourceSetupTests` --uses--> `Config`  [INFERRED]
  tests/test_setup_resources.py → copilot_agent/config.py
- `StorageTests` --uses--> `Config`  [INFERRED]
  tests/test_storage.py → copilot_agent/config.py

## Import Cycles
- None detected.

## Communities (60 total, 27 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (43): model_rank(), Config, main(), main(), approved_popen(), audit(), _normalized_executable(), _within() (+35 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (31): _actionable(), ask(), choose_browser_endpoint(), error(), main(), _recent_events(), _record_bug_fix(), _record_turn_error() (+23 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (29): capture_display(), enumerate_displays(), collect(), inspect_windows(), snapshot(), launch_viewers(), _MonitorInfo, _png_chunk() (+21 more)

### Community 3 - "Community 3"
Cohesion: 0.07
Nodes (13): Findings, EventLog, now(), PromptBuilder, SessionState, retained_root(), StateAndPromptTests, exercise() (+5 more)

### Community 4 - "Community 4"
Cohesion: 0.06
Nodes (5): directory(), EdgeLaunchTests, PythonSetupChoiceTests, SharedRuntimeProbeTests, resolve()

### Community 5 - "Community 5"
Cohesion: 0.08
Nodes (10): final_response(), OrchestratorTests, request_both(), two_calls(), diagnostics(), malformed(), finished(), planned() (+2 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (18): _category(), _caught_frame(), DiagnosticReports, _exception_chain(), _frames(), _ownership(), _recommend(), _safe_text() (+10 more)

### Community 7 - "Community 7"
Cohesion: 0.08
Nodes (19): key(), cdp_endpoint(), connect_bounded(), EndpointError, find_edge_executable(), get_cdp_version(), _hidden_command(), launch_edge() (+11 more)

### Community 8 - "Community 8"
Cohesion: 0.08
Nodes (10): delivery_instruction(), delivery_requirements(), DeliveryRequirements, detect_requirements(), _expected_names(), retry_message(), _without_negated_clauses(), DeliveryRequirementTests (+2 more)

### Community 9 - "Community 9"
Cohesion: 0.07
Nodes (4): response_envelope_closed(), ExchangeTests, OfflineAdapter, ToolContextTests

### Community 10 - "Community 10"
Cohesion: 0.13
Nodes (4): BrowserAdapter, BrowserUIError, ModelAccessError, SubmissionAmbiguousError

### Community 11 - "Community 11"
Cohesion: 0.11
Nodes (11): build_bundle(), _build_reference(), build_startup_attachments(), _check_component_names(), _check_reference_names(), _hash(), _manifest_prefix(), _read_bounded() (+3 more)

### Community 12 - "Community 12"
Cohesion: 0.17
Nodes (30): action(), api(), approvalReview(), attachmentContainer, bookmarkIds, button(), details(), events (+22 more)

### Community 13 - "Community 13"
Cohesion: 0.13
Nodes (3): correction_message(), _object_pairs(), ProtocolError

### Community 14 - "Community 14"
Cohesion: 0.19
Nodes (3): extract_zip(), inspect_zip(), ArchiveTests

### Community 15 - "Community 15"
Cohesion: 0.17
Nodes (12): ArchiveError, ArchiveService, _digest(), _entries(), _limits(), _office(), _reject_links(), _relative() (+4 more)

### Community 17 - "Community 17"
Cohesion: 0.12
Nodes (4): composer_comparison(), fresh_assistant(), upload_alert_is_error(), RemainingCorrelationTests

### Community 19 - "Community 19"
Cohesion: 0.19
Nodes (5): Orchestrator, AssembledCapacityTests, DeliveryIntegrationTests, MockBrowser, make_fixture()

### Community 24 - "Community 24"
Cohesion: 0.25
Nodes (3): CodeRunner, PolicyError, NoExecutionRegistry

### Community 25 - "Community 25"
Cohesion: 0.24
Nodes (5): _canonical(), DownloadError, DownloadService, _Ticket, validate_download_args()

### Community 26 - "Community 26"
Cohesion: 0.14
Nodes (3): ApprovalManager, BrowserPlanExtensionTests, QuietFeedback

### Community 27 - "Community 27"
Cohesion: 0.23
Nodes (6): error(), config_value(), configured_path_policy(), ToolRegistry, scrub_urls(), ExtractionLocationTests

### Community 28 - "Community 28"
Cohesion: 0.13
Nodes (4): ArgumentsTests, FakeAnchor, FakeLocator, FakePage

### Community 29 - "Community 29"
Cohesion: 0.14
Nodes (7): CaptureTimeoutError, copied_code_response(), model_access_exhausted(), SubmissionNotSentError, uploads_verified(), CorrelationTests, interrupted()

### Community 31 - "Community 31"
Cohesion: 0.18
Nodes (4): create_runtime(), main(), PromptBroker, PromptBrokerTests

### Community 32 - "Community 32"
Cohesion: 0.25
Nodes (3): start_new_session(), NewSessionTests, SessionBrowser

### Community 33 - "Community 33"
Cohesion: 0.21
Nodes (3): CreatedSync, snapshot(), SyncTests

### Community 36 - "Community 36"
Cohesion: 0.23
Nodes (7): guard(), register(), check_navigation(), download(), failed(), websocket_guard(), URLPolicy

### Community 37 - "Community 37"
Cohesion: 0.29
Nodes (10): Add-PythonCandidate(), Get-PipConfiguration(), Get-RecoveryBasePython(), Get-WorkingPip(), Initialize-AgentEnvironment(), Invoke-SetupPython(), Preserve-ProjectEnvironment(), Read-PythonPath() (+2 more)

### Community 38 - "Community 38"
Cohesion: 0.15
Nodes (3): FakeContext, FakeDownload, FakeSettingsPage

### Community 39 - "Community 39"
Cohesion: 0.42
Nodes (4): parse_response(), encoded(), envelope(), ProtocolTests

### Community 42 - "Community 42"
Cohesion: 0.27
Nodes (7): PathPolicy, bounded_bytes(), load_json(), unique(), require(), run(), verify_completed_report()

### Community 45 - "Community 45"
Cohesion: 0.22
Nodes (4): definitions(), execute(), obj(), validate()

## Knowledge Gaps
- **5 isolated node(s):** `attachmentContainer`, `bookmarkIds`, `events`, `focusedComposer`, `labels`
  These have ≤1 connection - possible missing edges. (Counts symbols only; 377 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **27 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `BrowserAdapter` connect `Community 10` to `Community 32`, `Community 1`, `Community 0`, `Community 36`, `Community 9`, `Community 42`, `Community 13`, `Community 51`, `Community 21`, `Community 23`, `Community 29`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `PolicyError` (e.g. with `ArchiveService` and `_reject_links()`) actually correct?**
  _`PolicyError` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `attachmentContainer`, `bookmarkIds`, `events` to the rest of the system?**
  _5 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.0599728168535508 - nodes in this community are weakly interconnected._
- **Why does `PolicyError` connect `Community 24` to `Community 0`, `Community 1`, `Community 2`, `Community 5`, `Community 13`, `Community 14`, `Community 15`, `Community 19`, `Community 20`, `Community 22`, `Community 23`, `Community 27`, `Community 30`, `Community 34`, `Community 36`, `Community 42`, `Community 44`, `Community 45`, `Community 46`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `BrowserAdapter` (e.g. with `CodeExpansionTests` and `ExchangeTests`) actually correct?**
  _`BrowserAdapter` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.05642080517190714 - nodes in this community are weakly interconnected._