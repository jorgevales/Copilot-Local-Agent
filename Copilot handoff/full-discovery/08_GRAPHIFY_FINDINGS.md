# Graph Report - copilot-local-agent  (2026-10-07)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1249 nodes · 3529 edges · 47 communities (32 shown, 15 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 264 edges (avg confidence: 0.89)
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
- Community 40
- Community 41
- Community 42
- Community 43
- Community 45
- Community 46

## God Nodes (most connected - your core abstractions)
1. `PolicyError` - 69 edges
2. `Orchestrator` - 68 edges
3. `BrowserAdapter` - 61 edges
4. `ToolRegistry` - 53 edges
5. `PathPolicy` - 47 edges
6. `SessionState` - 46 edges
7. `final_response()` - 43 edges
8. `Config` - 41 edges
9. `OrchestratorTests` - 40 edges
10. `redact()` - 40 edges

## Surprising Connections (you probably didn't know these)
- `OrchestratorTests` --uses--> `Orchestrator`  [INFERRED]
  tests/test_orchestrator.py → copilot_agent/orchestrator.py
- `OrchestratorTests` --uses--> `ProtocolError`  [INFERRED]
  tests/test_orchestrator.py → copilot_agent/protocol.py
- `AssembledCapacityTests` --uses--> `PolicyError`  [INFERRED]
  tests/test_attachment_capacity.py → copilot_agent/policy.py
- `DeliveryIntegrationTests` --uses--> `ApprovalManager`  [INFERRED]
  tests/test_delivery_integration.py → copilot_agent/approvals.py
- `DeliveryIntegrationTests` --uses--> `PolicyError`  [INFERRED]
  tests/test_delivery_integration.py → copilot_agent/policy.py

## Import Cycles
- None detected.

## Communities (47 total, 15 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (16): start_new_session(), Orchestrator, correction_message(), _object_pairs(), parse_response(), ProtocolError, NewSessionTests, SessionBrowser (+8 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (31): _actionable(), ask(), choose_browser_endpoint(), error(), main(), _recent_events(), _record_bug_fix(), _record_turn_error() (+23 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (14): ApprovalManager, Findings, EventLog, now(), PromptBuilder, SessionState, retained_root(), StateAndPromptTests (+6 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (8): CodeRunner, config_value(), PolicyError, validate_schema(), configured_path_policy(), scrub_urls(), validate(), ToolTests

### Community 4 - "Community 4"
Cohesion: 0.10
Nodes (17): ArchiveError, ArchiveService, _digest(), _entries(), extract_zip(), inspect_zip(), _limits(), _office() (+9 more)

### Community 5 - "Community 5"
Cohesion: 0.06
Nodes (5): directory(), EdgeLaunchTests, PythonSetupChoiceTests, SharedRuntimeProbeTests, resolve()

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (10): final_response(), OrchestratorTests, request_both(), two_calls(), diagnostics(), malformed(), finished(), planned() (+2 more)

### Community 7 - "Community 7"
Cohesion: 0.07
Nodes (6): AttachmentError, AttachmentQueue, upload_name(), select_files(), AttachmentTests, FilePickerTests

### Community 8 - "Community 8"
Cohesion: 0.08
Nodes (22): capture_display(), enumerate_displays(), collect(), inspect_windows(), snapshot(), launch_viewers(), _MonitorInfo, _png_chunk() (+14 more)

### Community 9 - "Community 9"
Cohesion: 0.08
Nodes (17): _category(), _caught_frame(), DiagnosticReports, _exception_chain(), _frames(), _ownership(), _recommend(), _safe_text() (+9 more)

### Community 10 - "Community 10"
Cohesion: 0.08
Nodes (10): delivery_instruction(), delivery_requirements(), DeliveryRequirements, detect_requirements(), _expected_names(), retry_message(), _without_negated_clauses(), DeliveryRequirementTests (+2 more)

### Community 12 - "Community 12"
Cohesion: 0.10
Nodes (4): response_envelope_closed(), ExchangeTests, OfflineAdapter, ToolContextTests

### Community 13 - "Community 13"
Cohesion: 0.12
Nodes (8): build_bundle(), _build_reference(), build_startup_attachments(), _hash(), _read_bounded(), read_bundle_components(), _write_verified_reference(), BundleTests

### Community 14 - "Community 14"
Cohesion: 0.16
Nodes (6): Config, run(), run(), run(), main(), run()

### Community 15 - "Community 15"
Cohesion: 0.18
Nodes (7): copied_code_response(), _check_component_names(), _check_reference_names(), _manifest_prefix(), _canonical(), _terminal_text(), canonical_hash()

### Community 18 - "Community 18"
Cohesion: 0.16
Nodes (10): find_edge_executable(), _hidden_command(), launch_edge(), loopback_listener_pid(), port_listening(), _profile_argument(), profile_in_use(), stop_launched_edge() (+2 more)

### Community 22 - "Community 22"
Cohesion: 0.14
Nodes (5): fresh_assistant(), model_rank(), upload_alert_is_error(), uploads_verified(), RemainingCorrelationTests

### Community 23 - "Community 23"
Cohesion: 0.11
Nodes (5): CaptureTimeoutError, ModelAccessError, SubmissionAmbiguousError, SubmissionNotSentError, interrupted()

### Community 24 - "Community 24"
Cohesion: 0.16
Nodes (7): URLPolicy, definitions(), execute(), obj(), ToolRegistry, ExtractionLocationTests, FeedbackIntegrationTests

### Community 25 - "Community 25"
Cohesion: 0.16
Nodes (7): write_json(), write_preserving(), InjectedCaptureBrowser, require(), run(), decide(), record()

### Community 26 - "Community 26"
Cohesion: 0.17
Nodes (7): model_access_exhausted(), cdp_endpoint(), connect_bounded(), EndpointError, get_cdp_version(), validate_endpoint(), CorrelationTests

### Community 27 - "Community 27"
Cohesion: 0.14
Nodes (5): validate_download_args(), ArgumentsTests, FakeAnchor, FakeLocator, FakePage

### Community 28 - "Community 28"
Cohesion: 0.20
Nodes (9): error(), file_record(), RecordedBrowser, committed(), require(), run(), decide(), display() (+1 more)

### Community 29 - "Community 29"
Cohesion: 0.33
Nodes (3): DownloadError, DownloadService, _Ticket

### Community 30 - "Community 30"
Cohesion: 0.29
Nodes (11): redact(), read_approval(), unique_pairs(), require(), run(), decide(), display(), save() (+3 more)

### Community 31 - "Community 31"
Cohesion: 0.29
Nodes (10): Add-PythonCandidate(), Get-PipConfiguration(), Get-RecoveryBasePython(), Get-WorkingPip(), Initialize-AgentEnvironment(), Invoke-SetupPython(), Preserve-ProjectEnvironment(), Read-PythonPath() (+2 more)

### Community 33 - "Community 33"
Cohesion: 0.15
Nodes (3): FakeContext, FakeDownload, FakeSettingsPage

### Community 34 - "Community 34"
Cohesion: 0.27
Nodes (3): CreatedSync, snapshot(), SyncTests

### Community 35 - "Community 35"
Cohesion: 0.40
Nodes (7): choose_source(), create_version(), digest(), main(), prepare_drop_folder(), replacement_map(), source_files()

### Community 36 - "Community 36"
Cohesion: 0.36
Nodes (9): bounded_bytes(), load_json(), unique(), NoExecutionRegistry, require(), run(), decide(), save() (+1 more)

### Community 41 - "Community 41"
Cohesion: 0.39
Nodes (6): guard(), register(), check_navigation(), download(), failed(), websocket_guard()

### Community 42 - "Community 42"
Cohesion: 0.29
Nodes (6): main(), approved_popen(), audit(), _normalized_executable(), _within(), _write_event()

## Knowledge Gaps
- **15 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `BrowserAdapter` connect `Community 17` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 36`, `Community 39`, `Community 41`, `Community 11`, `Community 12`, `Community 43`, `Community 14`, `Community 20`, `Community 23`, `Community 24`, `Community 25`, `Community 26`, `Community 28`, `Community 30`?**
  _High betweenness centrality (0.146) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `PolicyError` (e.g. with `ArchiveService` and `_reject_links()`) actually correct?**
  _`PolicyError` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.05434173669467787 - nodes in this community are weakly interconnected._
- **Why does `PolicyError` connect `Community 3` to `Community 0`, `Community 1`, `Community 4`, `Community 36`, `Community 6`, `Community 7`, `Community 8`, `Community 11`, `Community 14`, `Community 15`, `Community 17`, `Community 19`, `Community 21`, `Community 24`?**
  _High betweenness centrality (0.106) - this node is a cross-community bridge._
- **Are the 22 inferred relationships involving `Orchestrator` (e.g. with `ApprovalManager` and `ArchiveService`) actually correct?**
  _`Orchestrator` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.058333333333333334 - nodes in this community are weakly interconnected._
- **Why does `Orchestrator` connect `Community 0` to `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 34`, `Community 36`, `Community 7`, `Community 8`, `Community 9`, `Community 6`, `Community 14`, `Community 15`, `Community 23`, `Community 24`, `Community 25`, `Community 28`, `Community 29`, `Community 30`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._