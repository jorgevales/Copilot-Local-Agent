# REA implementation report

Update: the later [availability deployment repair](REA_AVAILABILITY_RECOVERY.md) supersedes this report's original manual-only dependency setup and startup availability behavior.

Implementation baseline: `3a22557`. The interview agreement overrides conflicting requirements in the original implementation brief. No project files were removed. External REA dependencies remain in a separate research checkout.

## Architecture implemented

Copilot Chat plans structured calls; the existing orchestrator validates schemas, target/path authority and approvals, dispatches ToolRegistry, retains evidence/uncertainty and returns results. The orchestrator is the sole execution authority. Three passive/static REA CLI tools run fixed argument arrays with bounded managed lifecycle; no model API, raw MCP or second agent authority is exposed. Independent bounded reads run concurrently. Per-session scoped read-only discovery and sanitized knowledge writes are immediate; other effects keep approval. A single prefilled login click is permitted; denial/MFA pauses for the user.

## Integration assessment

See [the pre-change assessment](REA_INTEGRATION_ASSESSMENT.md). Actual REA source revision `d7651b6a0dde6cfe658144cc52794ae6aaf23306`, version6.5.0, MIT was inspected and built. The fixed one-shot CLI supplies passive owned-page inspection, offline HAR/SAZ analysis and static managed/Go/Rust/JavaScript analysis. The existing API integration is the API Anything-inspired public operation adapter (`operation.learn/list/call`), with Crawl4AI and specialized tools preserved. See the exact91-tool [inventory](RESEARCH_TOOL_INVENTORY.json).

## Files changed

- `Copilot handoff/full-discovery/01_PROJECT_BRIEFING.md`: Refreshed source/documentation/interface handoff and hashes.
- `Copilot handoff/full-discovery/02_CODE_AND_GRAPH_INDEX.md`: Refreshed source/documentation/interface handoff and hashes.
- `Copilot handoff/full-discovery/03_PROJECT_DOCUMENTATION.md`: Refreshed source/documentation/interface handoff and hashes.
- `Copilot handoff/full-discovery/04_GUIDANCE_AND_CONFIGURATION.md`: Refreshed source/documentation/interface handoff and hashes.
- `Copilot handoff/full-discovery/05_HANDOFF_MANIFEST.json`: Refreshed source/documentation/interface handoff and hashes.
- `Copilot handoff/full-discovery/README.md`: Refreshed source/documentation/interface handoff and hashes.
- `README.md`: Describe REA, current session policy, knowledge and setup recovery.
- `agent_ui/tests/test_launch_ui.py`: Regression coverage for the changed behavior.
- `agent_ui/web/app.js`: Display and recognize the current scoped startup/approval grant.
- `agent_ui/web/index.html`: Display and recognize the current scoped startup/approval grant.
- `bootstrap/README.md`: Document installer candidates, mapping recovery and diagnostics.
- `bootstrap/setup_dependencies.py`: Preserve/expand verified installation scratch and S/UNC fallbacks.
- `config.example.json`: Document optional bounded REA configuration.
- `copilot_agent/app.py`: Start/renew scoped sessions and avoid the default pre-discovery question.
- `copilot_agent/approvals.py`: Keep effects exact-approved and change option4 to scoped discovery.
- `copilot_agent/browser_auth.py`: One prefilled login-button click with owned target and no secret extraction.
- `copilot_agent/config.py`: Validate REA dependency/resource configuration.
- `copilot_agent/discovery_knowledge.py`: Session saves, semantic no-op and readable public-map views.
- `copilot_agent/discovery_store.py`: Retain authoritative site knowledge revisions.
- `copilot_agent/knowledge_notes.py`: Sanitize/deduplicate canonical site notes.
- `copilot_agent/knowledge_views.py`: Canonical site/namespace folders and derived concise method views.
- `copilot_agent/local_crawler.py`: Centralize per-site raw task evidence while retaining legacy reads.
- `copilot_agent/orchestrator.py`: Scoped target/session authority, knowledge/login grants, parallel reads and recovery.
- `copilot_agent/prompts.py`: Precise current routing, knowledge paths, auth rules and compact initialization.
- `copilot_agent/rea.py`: Bounded actual CLI adapter, immutable local staging and redacted evidence.
- `copilot_agent/reconciliation.py`: Use the same approved-origin policy during navigation recovery.
- `copilot_agent/research_routing.py`: Deterministic selection, complementary/fallback recommendations and evidence reuse.
- `copilot_agent/session_mode.py`: Ephemeral scoped grant and exact separately approved origins.
- `copilot_agent/site_discovery.py`: Reuse canonical browser campaign evidence folders.
- `copilot_agent/site_knowledge.py`: Session grants, verified navigation methods, history and concise retrieval.
- `copilot_agent/state.py`: Retain/gate uncertain REA process or cleanup state.
- `copilot_agent/tools.py`: Register and dispatch typed REA/routing/login capabilities and normalize failures.
- `docs/BUSINESS_DATA_WORK.md`: Architecture, operation, exact tool contracts, validation or acceptance documentation.
- `docs/DISCOVERY_NAVIGATION.md`: Architecture, operation, exact tool contracts, validation or acceptance documentation.
- `docs/DOM_AND_VISUAL_NAVIGATION.md`: Architecture, operation, exact tool contracts, validation or acceptance documentation.
- `docs/KNOWLEDGE_PERSISTENCE.md`: Architecture, operation, exact tool contracts, validation or acceptance documentation.
- `docs/LOCAL_WEBSITE_DISCOVERY.md`: Architecture, operation, exact tool contracts, validation or acceptance documentation.
- `docs/REA_IMPLEMENTATION_REPORT.md`: Architecture, operation, exact tool contracts, validation or acceptance documentation.
- `docs/REA_INTEGRATION.md`: Architecture, operation, exact tool contracts, validation or acceptance documentation.
- `docs/REA_INTEGRATION_ASSESSMENT.md`: Architecture, operation, exact tool contracts, validation or acceptance documentation.
- `docs/RESEARCH_TOOL_INVENTORY.json`: Architecture, operation, exact tool contracts, validation or acceptance documentation.
- `docs/SUPERVISED_SESSIONS.md`: Architecture, operation, exact tool contracts, validation or acceptance documentation.
- `guidance/01-copilot-orchestrator-contract.md`: Align trusted runtime guidance with scoped sessions and centralized knowledge.
- `guidance/03-tools-and-selection.md`: Align trusted runtime guidance with scoped sessions and centralized knowledge.
- `guidance/06-session-memory-context.md`: Align trusted runtime guidance with scoped sessions and centralized knowledge.
- `guidance/07-errors-recovery-retries.md`: Align trusted runtime guidance with scoped sessions and centralized knowledge.
- `guidance/website/customers.md`: Align trusted runtime guidance with scoped sessions and centralized knowledge.
- `guidance/website/memory.md`: Align trusted runtime guidance with scoped sessions and centralized knowledge.
- `guidance/website/privacy.md`: Align trusted runtime guidance with scoped sessions and centralized knowledge.
- `tests/test_app_sessions.py`: Regression coverage for the changed behavior.
- `tests/test_browser_auth.py`: Regression coverage for the changed behavior.
- `tests/test_centralized_knowledge.py`: Regression coverage for the changed behavior.
- `tests/test_local_crawler.py`: Regression coverage for the changed behavior.
- `tests/test_orchestrator.py`: Verify compact initialization preserves the exact eight preloaded contract attachments.
- `tests/test_permissive_mode.py`: Regression coverage for the changed behavior.
- `tests/test_protocol_state.py`: Verify compact startup and full first-task automation guidance separately.
- `tests/test_rea.py`: Regression coverage for the changed behavior.
- `tests/test_rea_registry.py`: Regression coverage for the changed behavior.
- `tests/test_research_routing.py`: Regression coverage for the changed behavior.
- `tests/test_scoped_research_session.py`: Regression coverage for the changed behavior.
- `tests/test_setup_dependencies.py`: Regression coverage for the changed behavior.
- `tests/test_site_discovery.py`: Regression coverage for the changed behavior.
- `tests/test_supervised_session.py`: Regression coverage for the changed behavior.
- `tools/refresh_research_inventory.py`: Regenerate the exact catalogue without machine state.

## REA operations exposed

| Registered name | Input/targets | Approval | Bounds/results |
| --- | --- | --- | --- |
| `rea.inspect_page` | optional owned `tab_id`, `observation_ms`0..3000 | read-only within existing target grant |45s default,1MiB output; redacted structural/network Evidence projection |
| `rea.analyze_capture` | approved `path`, `format`har/saz | read-only within approved roots/exact file grant |20MiB input,45s,1MiB output; offline metadata/source findings, no replay |
| `rea.analyze_artifact` | approved `path`, `kind`managed/go/rust/javascript | read-only within approved roots/exact file grant |20MiB total input,2,000 directory entries,45s,1MiB output; static findings/locations/unknowns |

Three REA calls may run concurrently by default. Each result carries execution/target identity, timestamps, status, provenance, input hashes, limitations/uncertainty and retained sanitized evidence references. Completed is distinct from partial, failed, unavailable, cancelled, timeout, output-limit and uncertain. Preflight rejections contain a typed not-started result. General native decompilation providers are not exposed. JavaScript semantic recovery can remain partial. Exact schemas are in the inventory. `research.route` performs local selection without executing a target; `browser.login_once` enforces the agreed single prefilled click.

## Research routing rules

Healthy REA is preferred for supported broad investigation. Known public APIs use the API Anything-inspired `operation.list/call` adapter when enabled. Structured extraction uses Crawl4AI. Navigation, screenshots, focused DOM/script and file observations retain specialized tools. Fresh hash-verified evidence can be reused; local input identity is rechecked and later browser effects invalidate snapshots. Actual failed/partial results produce alternative recommendations with their original attempt reference. Denial and uncertainty block fallback. Complementary evidence keeps separate provenance; execution stops when the objective is satisfied.

## Security controls

All execution uses existing target/path/owned-tab policies and strict tool schemas. Copilot cannot supply executables, shell commands, environments or raw REA/MCP arguments. The adapter derives its loopback CDP endpoint and target locally, never exports credentials/cookies, redacts payload values before saving or returning findings, and checks source identity. Windows requires fixed local NTFS; verified temporary snapshots allow S/UNC inputs while original coordinates remain provenance and durable evidence stays in the existing store. Only owned scratch is cleaned after confirmed termination; uncertainty blocks replay and other operations. Shared concurrency, Stop, deadline, output and input limits are enforced. The S-backed ledger remains authoritative; readable per-site files and prior labeled methods are derived views. Sanitized knowledge excludes secrets/identifiable records and skips noise/duplicates. Raw crawler/browser capture is separately approved task evidence.

## Configuration added

`rea_enabled=true`; `rea_repository=''` and `rea_node_executable=''` select trusted discovery; `rea_timeout_seconds=45`(1..180); `rea_max_output_bytes=1048576`(16KiB..8MiB); `rea_max_input_bytes=20971520`(1KiB..100MiB); `rea_max_parallel=3`(1..8). Health verifies the package/build/runtime path and matching Windows native addon identity. Missing/disabled REA remains explicitly unavailable and does not crash startup or disable other tools. Grants are ephemeral and are renewed for new sessions. Actual S/UNC knowledge paths are sent in the runtime instructions.

## Validation performed

- Project Python `-m compileall -q copilot_agent bootstrap agent_ui tests tools`: passed.
- `git diff --check`: passed after trimming two documentation EOF blank lines.
- All91 registered input/output JSON schemas checked with Draft202012Validator: passed.
- Example configuration validated with an explicit offline mapping fixture: passed. Default Config.load could not establish S here; this is an expected environment limitation, not live installation proof.
- Changed-file machine-path/unfinished-code scan: no findings.
- REA sibling source: `npm ci`, `npm run build:cached`, matching-version native restoration and `npm run verify:windows-native:artifact`: passed. No external runtime/binaries are vendored.
- `tools/refresh_research_inventory.py`: generated91 exact tool contracts without machine state.

## Test results

Commands use `.venv/Scripts/python.exe` unless specified. Counts overlap; they are not summed as unique tests.

| Command/suite | Outcome |
| --- | --- |
| `-B -m unittest tests.test_setup_dependencies tests.test_launcher tests.test_setup_resources` |60passed; initial global Python attempt failed on missing Pillow, corrected by using project environment |
| `-m unittest tests.test_centralized_knowledge tests.test_site_knowledge tests.test_discovery_knowledge tests.test_crawl4ai_discovery -q` |55passed; additional earlier knowledge/repair regressions passed |
| `-B -m unittest tests.test_centralized_knowledge tests.test_local_crawler tests.test_site_discovery tests.test_rea_registry tests.test_research_routing tests.test_scoped_research_session tests.test_permissive_mode tests.test_supervised_session -q` |83run, no failures, one explicitly gated actual REA test skipped in this invocation |
| `COPILOT_REA_INTEGRATION=1; -B -m unittest tests.test_rea tests.test_rea_registry tests.test_browser_auth tests.test_research_routing -q` |68passed, no skips; actual synthetic HAR/JS/owned Edge and registry dispatch included |
| `-B -m unittest agent_ui.tests.test_launch_ui agent_ui.tests.test_runtime agent_ui.tests.test_workspace tests.test_web_operations tests.test_web_navigation tests.test_browser_inspection tests.test_crawl4ai_discovery -q` |77passed, including actual offline browser/UI fixtures |
| `-B -m unittest tests.test_scoped_research_session tests.test_permissive_mode tests.test_supervised_session` |27passed including revocation/file-write/auth dispatch |
| `-B -m unittest tests.test_orchestrator tests.test_protocol_state tests.test_tools tests.test_app_startup_flow tests.test_reconciliation -q` |Initial165run: one recovery failure, two platform/environment skips. Fresh explicit recovery target authority was fixed and the failed test rerun passed |
| `-B -m unittest tests.test_reconciliation.RecoveryOrchestrationTests.test_approved_recovery_continues_to_sanitized_site_knowledge_save -q` |1passed after repair |
| `-B -m unittest tests.test_app_sessions -q` |Initially exposed ninth overflow attachment; compact initialization repaired it. All6passed with unavailable S mapping represented by an offline fixture |
| Two focused Orchestrator independent-read/effectful-order tests |2passed |
| Final per-module orchestrator/protocol/tools/startup/reconciliation/session runs |171 tests across final module results:169 passed,2 existing environment skips. Protocol36 rerun passed after checking task guidance in the first task instead of compact initialization. S-mapping absence was an explicit offline fixture except in the tools mapping-contract suite |

A new route-test fixture initially selected a nonexistent external path; corrected to an existing outside-root fixture and all14routing tests passed. A reused knowledge grant survived revocation in an early regression; callback cleanup was fixed and the27-test scoped suite passed. An initial size reduction still exceeded the legacy16000-character composer budget; initialization now sends the established eight contract attachments without an added overflow document. No failure was treated as passed.

## Unresolved limitations

- Live VDI, mapped S/UNC installation/writes and production authenticated Copilot/site behavior cannot be exercised here; this was explicitly accepted for S setup. Synthetic and local real CLI/browser proofs do not establish these outcomes.
- Matching REA/Node and Windows native controls must be installed on deployment machines as documented; the external runtime is not committed or silently fetched at startup.
- JavaScript reconstruction can retain real semantic unknowns and is reported partial. Native provider-dependent decompilation is outside this adapter.
- Secret/record checks supplement structured schemas and the sanitized-knowledge contract; they are not a complete classifier for arbitrary personal prose. Some fixture suites emitted SQLite ResourceWarning messages without test failure.
- The entire repository-wide unittest discovery and production manual acceptance matrix were not run. Relevant focused/existing suites and actual local synthetic integration were run as listed.

## Exact manual acceptance checks


Use synthetic targets and the project's `.venv` Python. These checks require an
actual agent session; offline tests do not prove production Copilot/VDI/S: state.

1. Build/install the matching REA runtime. Start the agent and inspect the three
   REA catalogue entries: availability must be true and their limits bounded.
2. Name an approved synthetic site and request `research.route` with website /
   investigate. Open its owned tab and run `rea.inspect_page`; confirm REA-first
   selection, completed source evidence and preserved browser ownership.
3. Enable `operation_reuse`, list a synthetic site's retained approved operations,
   and use `operation.call` to verify an endpoint found during REA inspection.
4. Request crawl objective and run approved `crawl4ai.crawl`; confirm structured
   coverage complements REA and saved evidence can be read with `crawl4ai.read`.
5. Request screenshot objective; confirm `browser.screenshot` remains preferred
   and returns its labeled PDF plus capture evidence.
6. Request an ordinary file write/target mutation, deny approval and confirm it
   does not execute. Confirm a useful sanitized knowledge save has no extra prompt.
7. Add command/env/endpoint/raw-argument fields to a REA request; confirm rejection
   before process launch. Check invalid enum/timeout/size values too.
8. Request a path outside configured/exact session roots or an unrelated origin;
   confirm scope rejection. Approve one exact `files.grant_path` and confirm only
   that location becomes readable by static analysis.
9. Temporarily configure a nonexistent REA repository; confirm unavailable
   diagnostics and continued browser/API/crawler operation, then restore it.
10. Run the timeout/cancel fixtures in `tests.test_rea`; verify confirmed cleanup
    gives timeout/cancelled and simulated termination failure gives uncertainty
    that blocks replay and fallback.
11. Analyze a synthetic HAR containing an authorization header, cookie, query
    token and payload identifier. Inspect both returned and retained evidence:
    credential and payload values must be absent.
12. Inspect retained REA evidence paths/hashes, the knowledge ledger revision,
    canonical site folder and resolved S:/UNC paths. Read back the saved knowledge.
13. Combine two distinct relevant evidence sources; confirm each provenance and
    gaps remain visible and no duplicate note/revision is created for no new fact.
14. Supply a failed REA call ID to `research.route`; confirm a safe alternative and
    original attempt reference. Repeat with denial/uncertainty and confirm blocked.
15. Set `rea_enabled=false`; restart and confirm unavailable REA entries alongside
    working API, Crawl4AI and specialized browser tools.
