# Graph Report - copilot-local-agent-20261007-183507  (2026-10-07)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1688 nodes · 4916 edges · 65 communities (40 shown, 25 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 344 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c42e673f`
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
- Community 56
- Community 57
- Community 58
- Community 59
- Community 61
- Community 62
- Community 63

## God Nodes (most connected - your core abstractions)
1. `PolicyError` - 124 edges
2. `Orchestrator` - 78 edges
3. `BrowserAdapter` - 64 edges
4. `ToolRegistry` - 63 edges
5. `PathPolicy` - 60 edges
6. `SessionState` - 53 edges
7. `final_response()` - 50 edges
8. `Config` - 46 edges
9. `redact()` - 41 edges
10. `OrchestratorTests` - 40 edges

## Surprising Connections (you probably didn't know these)
- `SiteKnowledgeTests` --uses--> `PolicyError`  [INFERRED]
  tests/test_site_knowledge.py → copilot_agent/policy.py
- `ToolTests` --uses--> `PathPolicy`  [INFERRED]
  tests/test_tools.py → copilot_agent/policy.py
- `ToolTests` --uses--> `PolicyError`  [INFERRED]
  tests/test_tools.py → copilot_agent/policy.py
- `ToolTests` --uses--> `ToolRegistry`  [INFERRED]
  tests/test_tools.py → copilot_agent/tools.py
- `CodeRunnerTests` --uses--> `CodeRunner`  [INFERRED]
  tests/test_code_runner.py → copilot_agent/code_runner.py

## Import Cycles
- None detected.

## Communities (65 total, 25 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (30): URLPolicy, validate_schema(), _approval(), _canonical(), _current_origin(), _digest(), execute_knowledge(), _fingerprint() (+22 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (39): CodeRunner, bounded_hash(), build_catalogue(), _catalogue(), _compact(), current_scope(), execute_catalogue(), export_catalogue() (+31 more)

### Community 2 - "Community 2"
Cohesion: 0.07
Nodes (42): _assertion(), _boundary(), _candidates(), _check_cancelled(), clear_navigation_state(), _close_tab(), _compact_recon(), _consequential_control() (+34 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (30): _actionable(), ask(), error(), main(), _recent_events(), _record_bug_fix(), _record_turn_error(), run() (+22 more)

### Community 4 - "Community 4"
Cohesion: 0.08
Nodes (19): ArchiveError, ArchiveService, _digest(), _entries(), extract_zip(), inspect_zip(), _limits(), _office() (+11 more)

### Community 5 - "Community 5"
Cohesion: 0.07
Nodes (29): capture_display(), enumerate_displays(), collect(), inspect_windows(), snapshot(), launch_viewers(), _MonitorInfo, _png_chunk() (+21 more)

### Community 6 - "Community 6"
Cohesion: 0.06
Nodes (5): directory(), EdgeLaunchTests, PythonSetupChoiceTests, SharedRuntimeProbeTests, resolve()

### Community 7 - "Community 7"
Cohesion: 0.08
Nodes (10): final_response(), OrchestratorTests, request_both(), two_calls(), diagnostics(), malformed(), finished(), planned() (+2 more)

### Community 8 - "Community 8"
Cohesion: 0.07
Nodes (20): choose_browser_endpoint(), key(), cdp_endpoint(), connect_bounded(), EndpointError, find_edge_executable(), get_cdp_version(), _hidden_command() (+12 more)

### Community 10 - "Community 10"
Cohesion: 0.09
Nodes (5): DocumentTests, FakeContext, FakeDownload, FakePage, Pending

### Community 11 - "Community 11"
Cohesion: 0.13
Nodes (11): Config, write_json(), write_preserving(), run(), require(), run(), decide(), run() (+3 more)

### Community 12 - "Community 12"
Cohesion: 0.08
Nodes (10): delivery_instruction(), delivery_requirements(), DeliveryRequirements, detect_requirements(), _expected_names(), retry_message(), _without_negated_clauses(), DeliveryRequirementTests (+2 more)

### Community 13 - "Community 13"
Cohesion: 0.08
Nodes (3): CodeRunnerTests, LocalPythonRunnerTests, exercise()

### Community 14 - "Community 14"
Cohesion: 0.13
Nodes (4): BrowserAdapter, BrowserUIError, ModelAccessError, SubmissionAmbiguousError

### Community 15 - "Community 15"
Cohesion: 0.08
Nodes (9): composer_comparison(), copied_code_response(), fresh_assistant(), model_access_exhausted(), model_rank(), upload_alert_is_error(), uploads_verified(), CorrelationTests (+1 more)

### Community 16 - "Community 16"
Cohesion: 0.17
Nodes (30): action(), api(), approvalReview(), attachmentContainer, bookmarkIds, button(), details(), events (+22 more)

### Community 17 - "Community 17"
Cohesion: 0.10
Nodes (4): response_envelope_closed(), ExchangeTests, OfflineAdapter, ToolContextTests

### Community 18 - "Community 18"
Cohesion: 0.12
Nodes (9): ApprovalManager, retained_root(), StateAndPromptTests, exercise(), exercise(), exercise(), exercise(), exercise() (+1 more)

### Community 19 - "Community 19"
Cohesion: 0.10
Nodes (11): error(), select_files(), file_record(), RecordedBrowser, committed(), require(), run(), decide() (+3 more)

### Community 21 - "Community 21"
Cohesion: 0.16
Nodes (12): _category(), _caught_frame(), DiagnosticReports, _exception_chain(), _frames(), _ownership(), _recommend(), _safe_text() (+4 more)

### Community 22 - "Community 22"
Cohesion: 0.20
Nodes (7): _canonical(), correction_message(), canonical_hash(), audit_evidence(), private_id(), private_session_snapshot(), _snapshot_evidence()

### Community 24 - "Community 24"
Cohesion: 0.17
Nodes (19): redact(), read_approval(), unique_pairs(), require(), run(), decide(), display(), save() (+11 more)

### Community 25 - "Community 25"
Cohesion: 0.11
Nodes (4): definitions(), execute(), obj(), record()

### Community 26 - "Community 26"
Cohesion: 0.15
Nodes (3): build_bundle(), build_startup_attachments(), BundleTests

### Community 27 - "Community 27"
Cohesion: 0.14
Nodes (5): _actor_style(), _enable_colour(), Feedback, public_preview(), PreviewTests

### Community 28 - "Community 28"
Cohesion: 0.21
Nodes (3): EventLog, now(), SessionState

### Community 30 - "Community 30"
Cohesion: 0.20
Nodes (9): _build_reference(), _check_component_names(), _check_reference_names(), _hash(), _manifest_prefix(), _read_bounded(), read_bundle_components(), _write_verified_reference() (+1 more)

### Community 32 - "Community 32"
Cohesion: 0.15
Nodes (4): AgentRuntime, create_runtime(), main(), RuntimeCancellationTests

### Community 33 - "Community 33"
Cohesion: 0.24
Nodes (3): AttachmentError, AttachmentQueue, upload_name()

### Community 34 - "Community 34"
Cohesion: 0.26
Nodes (5): DownloadError, DownloadService, _Ticket, validate_download_args(), ArgumentsTests

### Community 35 - "Community 35"
Cohesion: 0.21
Nodes (5): AssembledCapacityTests, DeliveryIntegrationTests, MockBrowser, make_fixture(), cancel_after_response()

### Community 36 - "Community 36"
Cohesion: 0.28
Nodes (6): _object_pairs(), parse_response(), ProtocolError, encoded(), envelope(), ProtocolTests

### Community 38 - "Community 38"
Cohesion: 0.25
Nodes (6): CaptureTimeoutError, SubmissionNotSentError, interrupted(), WebTransportTests, exchange(), exchange()

### Community 40 - "Community 40"
Cohesion: 0.14
Nodes (3): FakeContext, FakeDownload, FakeSettingsPage

### Community 42 - "Community 42"
Cohesion: 0.28
Nodes (3): start_new_session(), NewSessionTests, SessionBrowser

### Community 43 - "Community 43"
Cohesion: 0.29
Nodes (10): Add-PythonCandidate(), Get-PipConfiguration(), Get-RecoveryBasePython(), Get-WorkingPip(), Initialize-AgentEnvironment(), Invoke-SetupPython(), Preserve-ProjectEnvironment(), Read-PythonPath() (+2 more)

### Community 44 - "Community 44"
Cohesion: 0.15
Nodes (3): FakeAnchor, FakeLocator, FakePage

### Community 48 - "Community 48"
Cohesion: 0.27
Nodes (3): CreatedSync, snapshot(), SyncTests

### Community 56 - "Community 56"
Cohesion: 0.39
Nodes (6): guard(), register(), check_navigation(), download(), failed(), websocket_guard()

### Community 57 - "Community 57"
Cohesion: 0.29
Nodes (6): main(), approved_popen(), audit(), _normalized_executable(), _within(), _write_event()

## Knowledge Gaps
- **5 isolated node(s):** `attachmentContainer`, `bookmarkIds`, `events`, `focusedComposer`, `labels`
  These have ≤1 connection - possible missing edges. (Counts symbols only; 433 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **25 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PolicyError` connect `Community 1` to `Community 0`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 7`, `Community 9`, `Community 10`, `Community 11`, `Community 13`, `Community 14`, `Community 20`, `Community 22`, `Community 24`, `Community 25`, `Community 33`, `Community 35`, `Community 38`, `Community 39`, `Community 53`?**
  _High betweenness centrality (0.216) - this node is a cross-community bridge._
- **Are the 23 inferred relationships involving `PolicyError` (e.g. with `_actionable()` and `ArchiveService`) actually correct?**
  _`PolicyError` has 23 INFERRED edges - model-reasoned connections that need verification._
- **What connects `attachmentContainer`, `bookmarkIds`, `events` to the rest of the system?**
  _5 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.05787545787545788 - nodes in this community are weakly interconnected._
- **Why does `BrowserAdapter` connect `Community 14` to `Community 0`, `Community 1`, `Community 3`, `Community 4`, `Community 9`, `Community 42`, `Community 11`, `Community 15`, `Community 17`, `Community 19`, `Community 20`, `Community 55`, `Community 56`, `Community 24`, `Community 58`, `Community 29`?**
  _High betweenness centrality (0.090) - this node is a cross-community bridge._
- **Are the 25 inferred relationships involving `Orchestrator` (e.g. with `ApprovalManager` and `ArchiveService`) actually correct?**
  _`Orchestrator` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.05826330532212885 - nodes in this community are weakly interconnected._