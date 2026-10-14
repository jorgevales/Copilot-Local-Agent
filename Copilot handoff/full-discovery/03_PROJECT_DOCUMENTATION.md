# Project documentation source package

The following documentation is included verbatim as readable UTF-8 text. Each boundary names the exact source path.


---

<!-- BEGIN VERBATIM SOURCE: agent_ui/README.md -->
## Source: `agent_ui/README.md` (verbatim text; line endings normalized to LF)

# Copilot Agent Workspace

## Status
This is the optional graphical interface to the existing Copilot Local Agent. **Start Agent UI.cmd** asks whether to run the live repository or the Copilot testing environment, then launches that exact source copy. **Start Agent.cmd** remains the terminal fallback. Both use the same policy-controlled orchestrator, session evidence, isolated browser, approvals and diagnostic handling; the UI does not create a second agent or bypass approval.

## Install
The separate launcher requires normal project setup. The UI server uses Python standard-library modules; no Node installation, package download, administrator rights, model API key or external font/CDN is required.

Double-click **Start Agent UI.cmd**.

The launcher asks which project version to run, then starts an authenticated local server on loopback and opens the workspace in your default browser. This UI port is separate from Edge debugging; it never takes over the Copilot browser. The launch token stays in page memory and is removed from the address bar. Keep the launcher window open. Closing it denies pending approvals and ends the agent session; it cannot roll back an action already submitted.

## Implemented
- A compact Start agent card appears at the single local-navigation and knowledge-saving confirmation prompt. Start and Cancel submit the same `y` and `n` replies through `/api/submit`, the prompt broker and `app.run`; no terminal command or launch configuration is rebuilt. The card waits for backend feedback, prevents duplicate confirmation, preserves the first-request draft and reports local submission errors inline.
- During regular startup, verified existing Edge sessions are offered through the normal backend prompt. Choose a listed port, start a new isolated Edge session, or cancel startup; if no verified session exists, a new one starts directly.
- A cohesive light workspace palette and compact display mode.
- Collapsible navigation and context panels; responsive layout.
- Safe Markdown subset, code copy, basic tables and lists; raw HTML is inert.
- Structured message, tool, plan, error, warning, artifact and status cards.
- Backend event inspector, reported timings, model verification indicator.
- Explicit immutable approval review, with exact backend plan/call hash checks.
- Multiline draft composer, templates, search, in-memory bookmarks, command palette.
- The composer stays active during an agent run. Messages enter a FIFO outbox, keep stable message IDs across retries, and show waiting, upload, received, incorporated or failed/retry states. A message sent during execution steers the existing run.
- Browser-local file attachments work on the initial request, later messages and steering. The picker accepts multiple files; drag-and-drop and paste are supported. File name/type/size and per-file removal are shown before send. A whole-message precheck blocks more than 20 files before any upload; the backend independently enforces the limit.
- Selected file bytes are read through the browser File API and uploaded to the authenticated loopback workspace. The browser does not expose or send local source paths. Uploads are tied to stable message IDs for safe retry; attachment content remains untrusted review material and is never run by the UI.
- Export review for visible UI transcript; clear-view does not clear backend context.
- Keyboard focus, reduced-motion and high-contrast support.
- Local bearer authentication, Host/Origin checks, no external assets or telemetry.
- New-session uses the existing agent command. Stop requests the backend's supported cancellation; model switching and resume remain unavailable. Voice is unavailable.

## Limitations
- Backend conversation history, pinned sessions, durable bookmarks or saved workflows.
- Model switching and resume are unsupported. Cancellation cannot roll back submitted effects; uncertain actions still require reconciliation.
- Full CommonMark, syntax highlighting, resizable panel splitters, large-session virtualisation.
- Production accessibility/security audit and live Windows/VDI acceptance. Automated tests are synthetic, not target-VDI acceptance.

## Runtime integration

`agent_ui.runtime` adapts the existing application prompt loop, orchestrator events and exact approval callback. Its actions enqueue existing `:new` and `:attach` commands; it does not create another event loop or execute tools itself. The server runs on loopback with a per-launch bearer token, strict Host/Origin checks, a restrictive content security policy and no external assets or telemetry. Raw reasoning is not emitted to the UI.

Backend policy, exact approval hashes, uncertainty and persistence remain authoritative. UI decisions are user input only. The workspace does not send model requests without the connected runtime.

## Event payloads
All events use `emit(kind, payload)`; payloads must be JSON objects.
- `copilot` / `user`: `text`
- `system` / `error` / `warning`: `summary`, optional `details`
- `status`: `state`, `summary`
- `tool`: `name`, `status`, optional measured `duration_ms`, `summary`, `result`
- `plan`: `title`, `steps` with `step`, `action`, `verification`, `status`
- `context`: redacted authoritative requirements/constraints/findings
- `model`: `name`, `verified` (true only after backend verification)
- `session`: `title`, redacted session metadata
- `artifact`: actual backend evidence; UI does not manufacture download links

Do not emit a success until backend evidence supports it. `uncertain` is not `failed` or `complete`.

## Validation
From the project root:

```powershell
python -B -m unittest discover -s agent_ui\tests -v
```

Tests use synthetic inputs and a local fake runtime only. They do not establish target-VDI acceptance or production accessibility. The UI keeps up to 5,000 events in memory; authoritative long-term history remains the backend's responsibility.

The launch presentation tests use the existing Playwright dependency and installed Microsoft Edge in headless mode. They check exact confirmation payloads, keyboard activation, retained drafts, steering availability during a run, file batches up to 20, rejection of 21 files, message/attachment payloads, error/cancel/disconnection states, reduced motion, and layouts down to 320 pixels. Review screenshots remain under ignored `runtime/ui-design/`. The reference ZIP is ignored and is never a build input.
<!-- END SOURCE: agent_ui/README.md -->


---

<!-- BEGIN VERBATIM SOURCE: bootstrap/README.md -->
## Source: `bootstrap/README.md` (verbatim text; line endings normalized to LF)

# Portable Python environment bootstrap

`virtualenv.pyz` is the official self-contained virtualenv zipapp downloaded from
`https://bootstrap.pypa.io/virtualenv.pyz` on 6 October 2026. It reports
virtualenv 21.14.5 and supports Python 3.9 and later. Its SHA-256 is
`9096efa6e3a8457cc3ec56e749a2d1e17505b756ee3cb2b7e889526367efc187`.
`Launcher.ps1` verifies that hash before executing it. The archive contains
virtualenv's license and third-party notices in its `.dist-info/licenses` folder.

Setup runs this archive with the selected Python using `--no-download` and
`--no-periodic-update`. This creates `.venv` and seeds its pip without modifying
the base Python installation or requiring administrator rights. Project packages
are subsequently installed into `.venv` from the configured package index.
<!-- END SOURCE: bootstrap/README.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/API_ANYTHING_INTEGRATION.md -->
## Source: `docs/API_ANYTHING_INTEGRATION.md` (verbatim text; line endings normalized to LF)

# API Anything evaluation and operation-reuse integration

Date: 2026-10-11
Branch: `integration/api-anything`
External source: `goodnight000/api-anything` at `fe5cca70fe145634e49a1c9ba1f3e8250b291bea`
Licence: MIT; no external source was copied into the product.

## Executive summary

The local agent already has the stronger authority boundary: one orchestrator, explicit approvals, a versioned discovery ledger, exact-origin public HTTPS transport, browser ownership, graph-backed site knowledge and fail-closed response validation. API Anything has the stronger reusable-operation lifecycle: learn a request from observations, infer variable slots, validate with a changed input, run it directly, classify failures and preserve versions.

The selected integration is a small local adapter, not a dependency or second orchestrator. Three new tools learn, list and call public read-only JSON GET operations. Learning requires separate approval, two distinct observed URLs and a third unseen validation input. Calling uses the existing SSRF-resistant pinned transport, batches up to eight calls, deduplicates identical work, caches successful results for 60 seconds and records outcomes in the existing discovery SQLite ledger. The feature defaults off.

## Existing architecture

The verified execution path is:

`Launcher.ps1 -> app.py -> copilot_agent.app -> Orchestrator -> ToolRegistry -> BrowserAdapter or deterministic local tool`

- Copilot Chat UI performs reasoning and emits the existing response-v1 envelope. It is not a policy authority.
- `Orchestrator` validates correlation, tool requests, approval state and lifecycle transitions.
- `ToolRegistry` is the single local tool surface and generates the runtime catalogue supplied to Copilot.
- Browser work stays in owned tabs in a verified Edge profile. Public discovery uses a separate exact-origin, DNS/peer-pinned GET/HEAD transport.
- `discovery_*` modules compile bounded manifests, enforce scope and budgets, retain evidence, and persist versioned knowledge.
- `site_knowledge` retains approved browser navigation knowledge. Existing graph/knowledge remains the primary model.
- Session state, diagnostic events, approvals and immutable evidence are retained under configured per-user storage.

The material gap was between discovery and reuse. Existing discovery could collect public evidence and existing browser knowledge could retain routes, but `api_patterns` were deliberately rejected by the current knowledge semantics. A later task therefore had no narrowly governed direct-HTTP operation to reuse.

## API Anything findings

API Anything implements a capture -> match -> learn lifecycle. It stores verbatim request observations plus decoded slots, compares multiple executions to distinguish constants from parameters/nonces, emits an operation specification, and executes through three tiers: direct HTTP, browser-context fetch, then browser-triggered capture. Results are classified as success, drift, authentication, rate limiting, blocking, input or general error. Its healing flow is reactive and promotes a repaired version only after validation. Credentials are represented by references rather than embedded values, and write operations require exact allow-listing.

Its design is site-neutral and its TypeScript interfaces, MCP server and CLI are cohesive. The most valuable patterns here are multi-observation parameter inference, unseen-input validation, tier-aware direct execution, response classification, compact structured results and versioned promotion. Importing its runtime would duplicate orchestration, storage, HTTP policy, browser authority and tool exposure, so the package itself was not integrated.

External validation at the pinned commit:

- `npm ci --no-audit --no-fund`: passed; 117 packages installed in the isolated research checkout.
- `npm run check`: passed.
- Default parallel `npm test`: could not establish a semantic result because all 29 workers hit Windows `uv_os_get_passwd` / `ENOMEM` process pressure.
- `npm run lint`: failed on checkout-wide CRLF formatting, not a TypeScript semantic error.

The isolated checkout is ignored by Git and is not part of the product or deliverable.

## Comparison decisions

Migration cost is relative (`L`, `M`, `H`). “Required test” identifies the minimum gate for the decision.

| Capability | Existing / external evidence | Decision | Benefit, risk, compatibility | Cost / required test |
|---|---|---|---|---|
| 1. Website scouting | Bounded manifest and browser recon / capture-oriented exploration | KEEP_EXISTING | Existing scope and approval model is stronger; no compatibility change | L / discovery regressions |
| 2. Request capture | No passive network capture / browser network capture | REIMPLEMENT_MINIMALLY | Future browser evidence adapter could reduce manual URLs; credential exposure risk | H / redaction and owned-tab tests |
| 3. DOM and structured extraction | Mature browser structure/read / response extraction | HYBRIDISE | Keep DOM tools; add deterministic JSON paths only | L / extraction drift |
| 4. Endpoint inference | No reusable endpoint schema / learned request templates | REIMPLEMENT_MINIMALLY | Whole-segment and query-value inference; intentionally conservative | M / ambiguous-slot tests |
| 5. Parameter learning | None for operations / multi-run slot inference | ADOPT_EXTERNAL | Two examples plus unseen input reduces false promotion | M / unseen validation |
| 6. Operation schema | Catalogue plus unused `api_patterns` field / versioned specs | REIMPLEMENT_MINIMALLY | Local v1 payload fits existing ledger; no second schema authority | M / schema validation |
| 7. Graph representation | Existing versioned discovery graph / separate store | KEEP_EXISTING | Avoid competing sources of truth | L / graph-link test |
| 8. Navigation retention | Approved `site_knowledge` / operation store | KEEP_EXISTING | Browser routes remain authoritative and unchanged | L / existing knowledge tests |
| 9. Direct HTTP execution | Pinned public transport, no retained operation / tier-one replay | ADOPT_EXTERNAL | Reuse known public calls without browser/UI | M / transport and shape tests |
| 10. Browser fallback | Explicit owned-tab tools / automatic tiers | KEEP_EXISTING | Targeted new request only; prevents silent authority escalation | L / degraded-op test |
| 11. Authentication/session | Same-profile browser only / secret references and browser fetch | KEEP_EXISTING | Public adapter rejects authentication entirely | L / auth rejection |
| 12. Credential safety | Strong local policy/redaction / reference-based secrets | HYBRIDISE | Reject credential names and high-entropy values; never persist headers | M / leakage scan |
| 13. Drift detection | Evidence freshness / response and extraction classification | HYBRIDISE | Compare promoted response shape and mark current revision degraded | M / changed-shape test |
| 14. Self-healing | Targeted repair disabled / reactive heal and validate | REJECT | Automatic repair is premature; approved versioned relearn is safer | H / future adversarial suite |
| 15. Retry logic | Bounded public-read presets / classified tier retries | KEEP_EXISTING | Operation path performs no blind retry | L / retry-count assertion |
| 16. Error classification | Discovery codes / operation classes | ADOPT_EXTERNAL | Actionable `drift/auth/rate/blocked/input/error` classes | L / class mapping tests |
| 17. Caching | Persistent evidence, no response cache / reusable execution cache | HYBRIDISE | 60-second in-memory success cache; no stale persistent payloads | L / expiry and cache-hit tests |
| 18. Deduplication | Manifest task identities / call coalescing | ADOPT_EXTERNAL | Identical batch calls issue one HTTP request | L / duplicate batch test |
| 19. Parallelism and batching | Bounded discovery workers / batched execution | HYBRIDISE | Up to eight calls, concurrency four, shared exact origin | M / concurrency budget test |
| 20. LLM/UI minimisation | Compact state but repeated task reasoning / direct operation reuse | ADOPT_EXTERNAL | Learned calls report zero browser and Copilot UI round trips | L / metrics assertion |
| 21. Context compression | Output truncation / compact structured results | ADOPT_EXTERNAL | Homogeneous rows become columns plus row arrays | L / output-bound test |
| 22. MCP/tool exposure | Single catalogue and response envelope / MCP and CLI | REIMPLEMENT_MINIMALLY | Register in current catalogue; do not install another MCP server | L / catalogue validation |
| 23. Observability | Session/discovery ledgers / execution records | HYBRIDISE | Revision, outcome, failure class and call metrics in current ledger | M / restart audit test |
| 24. Testing | Broad unittest suite / fixture-heavy Node tests | HYBRIDISE | Add isolated Python lifecycle tests and retain existing suites | M / focused plus full suite |
| 25. Extensibility | Adapter-oriented tools / site-neutral operations | HYBRIDISE | Small module and ledger extension leave room for later capture | M / no site-specific code scan |
| 26. Read/write safety | Exact approvals and uncertain-effect ledger / `allowWrites` | KEEP_EXISTING | GET-only public preview; writes and non-idempotent replay absent | L / method and schema tests |

## Target architecture

### Discovery plane

Search bound site knowledge and retained operations first. For an unknown task, use the existing browser/public discovery tools to gather the smallest useful evidence set. Operation learning currently accepts two already-observed, sanitized public URLs; passive browser network capture is deliberately not part of this slice. A third unseen input is executed locally before promotion.

### Execution plane

`operation.list` reads the exact-origin partition. `operation.call` resolves the latest active revision, materializes only whole path-segment or query-value parameters, executes through `PublicReader`, validates the stored response shape, compacts the result and records success. Independent unique calls run with bounded concurrency; duplicates and short-lived repeats avoid traffic.

### Recovery plane

Failures are classified. Shape/route drift degrades the current head and directs a new browser-evidence/relearn request. Authentication, blocking and rate limiting stop. There is no automatic browser fallback, retry, write, repair or promotion. A new version uses compare-and-swap and keeps every previous version and event.

### Knowledge plane

The existing discovery SQLite ledger now contains `operations`, `operation_heads` and `operation_events`. An operation stores exact public origin, intent, method, sanitized request template, parameter names, extraction rule, validated output shape, provenance, safety claims, revision and an optional link to the existing graph partition/revision. It does not store variable example inputs, response bodies, cookies, headers or secrets.

## Implemented changes

- `copilot_agent/web_operations.py`: opt-in learn/list/call adapter, inference, validation, direct execution, batching, deduplication, compact output, failure classification and metrics.
- `copilot_agent/discovery_store.py`: additive versioned operation heads, records and audit events with compare-and-swap promotion.
- `copilot_agent/discovery_http.py`: configurable accepted media types while preserving the existing HTML/text default; JSON operations use the same pinned transport.
- `copilot_agent/tools.py`: registered the three tools in the existing validation, approval and execution path.
- `copilot_agent/prompts.py`: marks operation tools unavailable in the runtime catalogue unless the opt-in flag is enabled.
- `copilot_agent/config.py` and `config.example.json`: added `operation_reuse`, default `false`, requiring persistent graph storage.
- `tests/test_web_operations.py`: lifecycle, restart, unseen input, cache, dedupe, drift, credential rejection and stale-revision coverage.
- `guidance/03-tools-and-selection.md`, `guidance/07-errors-recovery-retries.md` and `README.md`: selection, safety, recovery and operator guidance.
- `.gitignore`: keeps the pinned research clone outside product changes.
- `schemas/tool-catalogue-v1.json`: extended with the three definitions generated by the authoritative runtime registry; unrelated pre-existing catalogue drift is left out of this review.

## Validation results

### Baseline

Before source edits, `.venv\\Scripts\\python.exe -m unittest discover -s tests -v` ran 530 tests in 464.937 seconds: 9 failures, 9 errors and 1 skip. The failures pre-existed this integration and cluster in browser-plan catalogue examples, web-document tests and website-integration setup (`_configure_tool_context()` missing `page`). This is not a clean full-suite baseline, so the integration is judged by focused regressions plus transparent full-suite comparison rather than a claimed green build.

### Added and focused checks

- Seven operation tests pass, including lifecycle/restart persistence, stale compare-and-swap preservation, strict JSON/shape rejection and recovery-class boundaries.
- Existing discovery transport and discovery-knowledge tests remain the compatibility gate for the reused ledger and transport.
- Each new catalogue example validates independently.
- Python compilation covers every changed Python module.

The post-change full discovery run completed with all seven new operation tests passing and reproduced the same legacy failure groups (browser-plan approval text, an older catalogue example, web-document cases and website-integration setup). Its final numeric footer was displaced from captured output by Windows Playwright subprocess-cleanup warnings, so no unsupported exact post-change count is claimed. A requested quiet recount could not start because Windows then rejected new processes with `CreateProcessWithLogonW` error 1909. No real website, authenticated session, Copilot UI or VDI was contacted during this validation.

## Performance impact

Synthetic deterministic evidence shows the work removed from the expensive path:

- Learn: three unique public HTTP validations, zero browser launches and zero Copilot UI round trips.
- Two identical calls in one batch: one HTTP request instead of two (50% avoided).
- Immediate repeat of that batch: zero additional HTTP requests (100% cache hit for the unique call).
- Retained direct call: zero browser launches and zero Copilot UI round trips by construction and test assertion.

These are call-count measurements with mocked public responses, not wall-clock or live-site performance claims. The current instrumentation does not isolate Copilot UI wait duration or token usage, and no valid before/after live latency benchmark was available.

## Security and privacy findings

- Exact HTTPS origin, public DNS and connected-peer checks remain enforced by the existing transport.
- Only GET and strict UTF-8 JSON are accepted; compressed bodies, private destinations, cross-origin redirects and changed query-key shapes fail closed.
- No browser profile, cookies, headers, tokens, credential references or response bodies enter the operation ledger.
- Credential-like parameter names/values and high-entropy public inputs are rejected. Operators must still provide sanitized, non-customer observed URLs because fixed public route/query literals are necessarily part of a reusable request template.
- Learning is separately approved and performs exactly three GETs. Listing/calling cannot write to a website.
- Results are bounded and compacted; successful response cache entries are memory-only and expire after 60 seconds.
- The feature is disabled by default and does not alter existing browser/discovery behavior.

## Known limitations

- Request/network capture is not automated; safe observed URLs must be supplied to the approved learning call.
- Only unauthenticated, exact-origin JSON GETs are supported. Browser-context fetch, forms, GraphQL bodies, pagination and writes are excluded.
- Output extraction uses a deterministic JSON path and optional field projection, not a general transformation language.
- Drift recovery is a guided new learning request, not autonomous healing.
- Response-cache expiry is lazy and process-local; it is not a durable freshness policy.
- The optional graph link records the current knowledge partition/revision but does not add new graph node or edge types.
- Live latency, Copilot wait time, tokens, real cache hit rate, discovery success and repair success remain unmeasured.
- The repository's unrelated baseline failures prevent a clean all-tests-passing claim.

## Rollback procedure

1. Leave `operation_reuse` absent or set it to `false`; this immediately removes all three tools from executable use while preserving existing behavior.
2. Revert the integration commits (do not reset the worktree or touch unrelated generated files).
3. The three additive SQLite tables may remain safely unused. If policy requires removal, copy the runtime database first and perform a separately reviewed migration; do not delete the database.
4. Regenerate `schemas/tool-catalogue-v1.json` from the reverted `ToolRegistry`.
5. Re-run the focused discovery tests and compare with the documented baseline.

## Prioritised next actions

1. High: repair the existing full-suite baseline so future integrations have a trustworthy regression signal.
2. High: add a redacted owned-tab network-observation adapter that emits candidate URLs without cookies/headers and requires review before learning.
3. High: run a local controlled HTTPS fixture through the real pinned transport, including redirects, rate limiting, authentication responses and size limits.
4. Medium: add operation freshness/expiry policy and cache-expiry/concurrency stress tests.
5. Medium: expose Copilot UI wait duration and compact-context byte counts in existing observability, then benchmark a repeated task end to end.
6. Medium: add explicit browser-required operation metadata while keeping fallback as a new approved request.
7. Low: consider richer JSON extraction only after adversarial resource-limit and privacy tests.
<!-- END SOURCE: docs/API_ANYTHING_INTEGRATION.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/ARCHITECTURE.md -->
## Source: `docs/ARCHITECTURE.md` (verbatim text; line endings normalized to LF)

# Architecture and implementation plan

This project preserves the CDD workflow and uses Microsoft Copilot Chat through Edge UI only. No reasoning model API is used. The user has explicitly authorized creation of all initial guidance files by the engineering agent. Useful Findings may arrive on any response; accepted findings are saved immediately and the current file is attached to outbound messages 10, 20, 30, etc.

## Components and ownership

- `app.py`, `copilot_agent/app.py`: interactive visible setup, console conversation, approval previews, clean exit and live-test entry points.
- `config.py`: shared source paths and per-user local app-data runtime paths, explicit operator storage paths, allowed roots/domains, browser settings and limits. Defaults restrict file tools to configured roots and disable Created monitoring until the user supplies its exact path.
- `browser.py`, `reused_browser.py`: dedicated Edge lifecycle, bounded CDP attachment, owned chat and guarded website tabs in the same verified profile, discovered model names/modes and checked selection, exact file upload, correlated plain-text assistant capture, diagnostics. Reuse selected source helpers with provenance; do not invoke CDD run/cleanup.
- `protocol.py`, `schemas/response-v1.schema.json`: one unique marker-delimited JSON envelope, strict schema and logical invariants, duplicate-key/stale-ID rejection, safe extraction and compact correction.
- `state.py`: atomic snapshots with retained versions, append-only events, intent/outcome ledger, counters, pending actions and restart uncertainty.
- `findings.py`: immediate validated/deduplicated findings and a readable Markdown attachment, versioning/timestamps/provenance, secret filtering.
- `prompts.py`: verified original guidance manifest and eight startup attachments, direct complete JSON response shape at initialization, compact user/tool/correction/context messages; no repeated long contracts.
- `bundle.py`: `build_startup_attachments` preserves guidance 01–06 as six unchanged source uploads and creates two lossless readable Markdown groups for guidance 07/08 and complete schema/catalogue. Group component versions/hashes/lengths/absolute byte offsets plus all physical attachment hashes are retained. The aggregate startup size is capped at 20 MiB including headers. Prior group versions are retained.
- `attachments.py`: pending user-file selection and validation, exact-byte code-to-text upload names, unchanged-source verification and a 20-file per-message queue cap. The final assembled Copilot message is checked again against its 20-file ceiling. Selection/upload permissions remain separate from local file-tool roots.
- `orchestrator.py`: bounded multi-step conversation, result dispatch, clarification, retries, findings synchronization and terminal states.
- `tools.py`, `policy.py`: versioned machine-readable tools with schemas/side effects, allowlisted paths and domains, per-action authorization, capped concise results, separate browser tool page.
- `code_runner.py`: common immutable proposal normalization and hashing; restricted default `python_subset`; explicit `local_python` selection and complete interpreter/argv/import/file/network/process/desktop/effect binding.
- `local_python_runner.py`, `local_python_worker.py`: separate bounded host-Python process, scrubbed environment, declared-scope audit hooks, exact managed subprocess vectors, cancellation/timeout/output enforcement, independent output evidence, persistent-process lifecycle and retained audit receipts. This is defense in depth, not Windows Sandbox.
- `desktop.py`, `image_viewer.py`: Windows display enumeration, per-display GDI PNG capture, managed viewer tiling, persistent viewer process ownership and independent visible-window/bounds verification.
- `sync.py`: baseline, bounded polling, stable size/mtime and readable local output; ambiguous matches are reported.
- `logging_utils.py`: structured local redacted events, safe diagnostics and no credentials.
- `feedback.py`: timestamped actor attribution, distinct ANSI label backgrounds with plain fallback, compact structured sections, deduplicated public reply previews, redaction and terminal-control escaping. Unvalidated previews have no execution authority.
- `tests/`: protocol, authorization, path escape, both execution modes, rejection/reapproval, failure/cancellation, process cleanup, three-viewer verification, terminal rendering, replay, counting, findings, persistence, synchronization and mocked browser tests.
- `docs/`: threat model, reuse mapping, troubleshooting, visual acceptance checklist, evidence and known limitations.

## Message flow

User -> compact request + session/request/ordinal -> verified Copilot chat -> fresh assistant envelope -> schema/policy validation -> user approval where required -> local tool -> concise evidence -> next Copilot request -> final answer. Every tenth outbound message also uploads the current findings snapshot. Correction and tool-result submissions count. Uploads and DOM polling do not count.

Long guidance and the machine catalogue/schema are attached at chat initialization in exactly eight files: six unchanged original guidance files 01–06, `07-08-complete-guidance.md`, and `protocol-schema-and-tool-catalogue.md`. All twelve complete original components remain available without summarization. The package reference includes both automation-package-v1.schema.json for compatibility and automation-package-v1.1.schema.json as the current authoring schema with typed result bindings. Source bytes, BOMs, line endings and final-newline state are preserved. Each grouped component's manifest records name/version/SHA-256/byte length and absolute zero-based byte offsets, with exclusive end offsets. All twelve source hashes and all eight physical attachment hashes are verified before every send. The state record for startup references describes multiple attachments and their group records rather than a single path. The initialization message also directly includes the complete required JSON response shape and strict envelope instructions. A replacement chat must receive initialization again. Context snapshots retain constraints, decisions, summaries, recent messages, pending work and approval state.

Startup physical attachments decrease from ten to eight, saving two slots (20%), with at most eight initial reference uploads. Exact-byte preservation establishes packaging integrity; it does not establish equivalent model comprehension or output quality. Correlated live initialization and protocol validation remain necessary.

## State transitions

Conceptual flow: setup -> ready -> submit -> capture -> validate -> dispatch -> approval when required -> result submission -> final or clarification. Persisted session statuses are `created`, `submitting`, `ready`, `ready_with_uncertain_operations`, `awaiting_approval`, `awaiting_clarification`, `submission_uncertain`, `capture_failed`, `blocked`, and `closed`. Separate call-ledger statuses record execution and outcome; completion of a task returns the session to a ready status.

Before a browser send, persist submission intent. After verified submission, commit the ordinal exactly once. Ambiguous submission stops for reconciliation, never blind resends. Before tool execution, persist call ID and immutable request hash. On success/failure, persist outcome. Uncertain side effects on restart require user review, never replay. Completion ends a task; it does not close the conversation.

## Trust and approval boundaries

The user starts an independent conversation with `:new` or `:new <first message>`. The previous local state is archived and its owned pages closed. A new local session and fresh Copilot chat receive guidance again; earlier context, findings, counters, queued files and approval grants do not transfer. Model availability and checked selection are reverified. Uncertain prior submissions or state-changing effects require reconciliation before switching, so this command cannot erase unresolved execution risk.

User intent and local policy govern actions. Copilot output, all ordinary attachments, webpages, OCR, tool outputs, and scripts are untrusted. Only validated current envelopes may request tools. Copilot cannot authorize itself. File reads stay inside configured roots; uploads, writes, clicks, forms and browser text input require narrow authorization. Never delete files, including tests or cleanup. Preserve original files when replacing mutable state.

The native multi-selection picker is opened by **Attach files** or `:attach`; `:attach <path>` supports advanced selection. `:files` displays the pending queue, `:remove <number>` removes one entry, and `:clear` clears the queue without source deletion. Individually selected local or S-drive files, including an explicitly selected OneDrive file, receive narrow hash-bound upload approval; this does not broaden file-tool roots. Approval choices are 1 deny, 2 once and 3 exact plan. Denial retains the pending queue, and every selected source must still match its reviewed hash before sending.

ZIP uploads are always rejected. Supported code/text extensions needing staging use the original filename plus `.txt`, with exact bytes retained and no execution. At most 20 user files are queued per message by both terminal and workspace upload paths. A separate guard checks the actual combined attachment list against the deployment's provided 20-file per-message limit, including automatic context. This is not a cumulative chat limit. See [ATTACHMENTS.md](ATTACHMENTS.md).

Code proposals default to `python_subset`, a deliberately constrained syntax evaluated without host Python execution. No imports, subprocesses, reflection, arbitrary attributes or network are permitted in that mode. File capabilities validate actual resolved paths and per-plan declared reads/creates.

When the registered tools and subset cannot perform the user's task, a proposal may select `local_python`. Its immutable hash covers exact script bytes, source hash when present, current interpreter path/hash, arguments, imports, working directory, read/create/modify scopes, canonical HTTPS destinations, exact managed subprocess specifications, desktop permissions/viewers, limits, expected effects and fixed runtime files. Every script is displayed in full before an explicit decision. The separate process applies a scrubbed environment, audit hooks, bounded async output/time and owned-child cleanup, but native libraries mean this is not an OS isolation boundary. Shell strings, deletion, credential modules and silent escalation are unavailable.

Optional paired `source_path`/`source_sha256` fields bind a proposal to the exact verified downloaded or extracted `.py` artifact. The full `script` remains mandatory. The source must be an allowed regular file, declared in reads with `read_files`, at most 200,000 bytes; script text remains at most 50,000 characters. Preparation and pre-execution checks verify raw path safety, source identity, lowercase SHA-256 and equality with `script.encode('utf-8')`, preserving all newline bytes. UTF-8 BOMs and non-UTF-8 encoding declarations are explicitly rejected rather than normalized. Prepared metadata and execution results carry the source path/hash/size and `exact_script_bytes: true`. Source binding works with either runner mode but never chooses or approves execution by itself.

For an all-Code-Runner multi-script request, approval displays every exact script and the complete immutable prepared pending plan for every unique call identity and source. A once grant covers one call; a plan grant covers only that exact displayed set. Code, interpreter/runtime binding, source hash or scope changes invalidate the grant and require renewed preparation/review. A coding package's verified delivery and extraction occur first and do not grant execution permission.

Desktop viewer declarations are effects as well as postconditions. After a successful approved capture script, the host tiles exact uniquely titled viewer processes on the requested Windows display and separately enumerates visible top-level windows and final rectangles. The result is complete only when every expected PNG is readable/hashed and every exact viewer is visible and contained on its target display. Failed verification, timeout and cancellation clean up owned processes. Successful persistent viewers remain only until session close, when the managed registry stops them.

The Copilot control page is not exposed to ordinary browser tools. `copilot.download` is a narrow current-artifact exception with an observed anchor, immutable review binding and actual download event. Those tools operate on an owned separate page. Browser sends/uploads to Copilot are authorized by starting the session with verified synthetic/current user content; ordinary third-party state changes require approval. Debugging remains loopback-only and cannot attach unrelated browser profiles silently.

## Failure and recovery

Authentication interruptions require manual user sign-in. UI errors, throttling, absent controls, upload mismatch, truncated/malformed/stale envelopes, unknown tools and unsafe paths fail closed. Connection, capture, correction and turn loops each have finite configurable limits. Screenshots and small sanitized DOM excerpts are retained locally on capture failures. A timed-out send with uncertain acceptance is never repeated automatically.

Created monitoring is disabled unless the user explicitly configures a path and sets `created_sync_enabled: true`. The application does not discover OneDrive roots or Created folders. Once enabled, a missing directory is a reported condition, not permission to fabricate synchronized outputs. Polling only reports success for a locally stable/readable matching file; cloud previews and zero exit codes are insufficient.

## Dependencies and validation

Python 3.10+ and Playwright (existing tested pin 1.55.0) with installed Microsoft Edge. Core validation/state/tools and Windows desktop capture/viewers use the standard library; approved `local_python` may import other packages already installed in the selected environment. No model SDK, Node build, embedded credentials or security-control bypass. Synthetic automated tests run in retained temporary directories and do not delete files. Real visible tests use an authorized session and synthetic content. Each acceptance step records observed evidence; blocked or unexecuted steps remain explicitly incomplete.

Implementation follows creation of guidance, protocol and threat-model documentation. Modules are integrated and tested before visible acceptance. The final deliverable contains functioning modules, setup/run commands, all documentation, test evidence and explicit limitations rather than placeholder implementations.

## Shared deployment and delivery

`storage.py` resolves the project's parent-level `Discoveries knowledge` folder through the live S: mapping and records both the S: alias and final UNC path. Runtime sessions, settings, downloads, temporary files and persistent knowledge all stay under this S: folder; configured C: or OneDrive storage is redirected there. Temporary storage retries use separate locations within the S: tree. File mutation tools are S:-only. Profiles/remembered debugging ports are scoped by VDI machine; reused Edge endpoints require verified ownership proof.

`delivery.py` adds compact format requests and bounds link-recovery messages. `downloads.py` reads actual Edge settings, binds a current generated HTTPS/native blob anchor, captures the event and creates a verified permanent artifact. `archives.py` inspects the complete ZIP before approved create-only extraction and verifies content without executing code. The final delivery gate rechecks current hashes and links extraction evidence to a download from that same task. A denied or unverified delivery cannot become a completed task because Copilot asserts it succeeded.

`tests/live_download_run.py` is a manual real-UI acceptance harness, excluded from ordinary automated execution unless explicitly invoked in live mode. It downloads a harmless synthetic print-only source, prepares the exact artifact and waits for a fresh matching user-approved once ledger before asking the orchestrator to execute. It never authors its own approving ledger. Source, immutable proposal and runtime result evidence are retained; actual pass/block status is reported separately in `TEST_REPORT.md`.
<!-- END SOURCE: docs/ARCHITECTURE.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/ATTACHMENTS.md -->
## Source: `docs/ATTACHMENTS.md` (verbatim text; line endings normalized to LF)

# Attach files to a request

Choose **Attach files** or enter `:attach` in the visible conversation console. The native Windows file picker supports selecting several files at once. Review the pending queue, then write the message that should use those files. Selecting a file queues it; the next request requires approval of the actual upload.

| Command | Effect |
| --- | --- |
| `:attach` | Open the native multi-selection file picker. |
| `:attach <path>` | Queue one explicitly named file; useful for advanced users. |
| `:files` | List pending entries with their numbers and recorded file details. |
| `:remove <number>` | Remove that entry from the pending queue only. |
| `:clear` | Clear pending entries only. |
| `:new` or `:new <first message>` | Start an independent session with an empty attachment queue. |

Removing or clearing entries never deletes or changes source files. Starting a new session preserves the previous session's records and files. Earlier attachments and approval grants do not transfer to the new conversation.

## Sources, review and approval

Select supported regular files from the configured local roots or S:, including a OneDrive path when you explicitly select or name it. The app validates the selected source and records its name, size and SHA-256. Runtime files, browser profiles, redirected paths and unsupported files are excluded. Selection does not grant directory-wide access or expand configured local file-tool roots.

The upload review binds the actual selected files and hashes. Approval choices are **1: deny, 2: once, 3: plan** for the exact displayed scope; there is no permanent approve-all. Denial retains the pending queue so you can inspect it, remove entries or try a revised request. Before sending, the app checks that each file still matches the reviewed bytes. If a source changed, remove it and select it again for a new review rather than sending it under the old approval.

## Formats and exact content

Supported native uploads include text/Markdown, JSON/CSV, PDF, DOCX/XLSX/PPTX and common images. Other supported text and code types must be readable UTF-8. When a code extension needs text staging, the app adds `.txt` to the original filename: `report.py` becomes `report.py.txt`. It preserves the complete original bytes, including line endings and any UTF-8 BOM. This provides source content for Copilot to inspect; it does not run the file.

ZIP archives are forbidden as uploads, including archives renamed to another extension. Select their extracted supported files instead. Native DOCX/XLSX/PPTX documents are accepted as Office documents after their package structure is checked. The separate generated-file delivery workflow may download and inspect ZIPs locally; that does not permit uploading ZIPs. See [FILE_DELIVERY.md](FILE_DELIVERY.md).

Files with the same basename from different folders remain attachable. The approval preview keeps each original name and assigns a distinct upload name (for example, `report.py.txt` and `report (2).py.txt`) so neither file overwrites or hides the other.

## Per-request limits

At most **20 user files** can be queued for one message by both the terminal and workspace upload service. Before every actual message, the app checks the final combined attachment list against the **20-file per-message limit provided for this deployment**. Startup references are uploaded at initialization; findings and context are attached only when due or needed, so the final check may leave fewer than 20 slots for user files. The cap applies per message, not cumulatively across the chat.

These are per-request and per-message limits. They do not establish a cumulative limit for the entire chat. Actual Copilot availability and organizational controls can still reject an upload. A picker selection or a local staged file alone is not proof that Copilot received it; the browser must confirm the intended uploads before submission.

## Large document collections

The orchestrator can retain up to 1000 authorised references in a document catalogue while selecting only the available document slots for a message. Website downloads remain bounded to 30 documents per batch. `files.transfer_to_copilot` ranks requested files, active workflow evidence and task-query matches, omits exact SHA duplicates and confirmed prior uploads, and reports why files were deferred. Different files with similar names remain available and only produce review warnings.

When files defer, a JSON index uses one of the available slots; existing queued files and images reduce the allowance. The final message still includes startup guidance, findings and context within the hard 20-file limit. An index is a metadata bundle with references to preserved originals; it does not replace their contents or permit ZIP upload. Use `documents.find` to locate evidence and `documents.retrieve` to reverify selected paths/hashes before approved transfer. No manual splitting of a 21-, 50- or 100-file collection is required.

Catalogues stay within the current task/customer/tenant/site namespace. A later task explicitly imports the retained index with its reviewed SHA-256 and matching customer/tenant/user/environment scope. Imported references are revalidated. Same-session download resumption additionally requires the original verified download manifest and its hash. Queued and retrieved files are not proof of Copilot receipt; successful attachment UI and submission checks remain required.

## Startup references

Initialization uploads **eight reference files** containing all twelve original components:

- Guidance 01–06 remain six separate original files, unchanged byte-for-byte.
- `07-08-complete-guidance.md` contains the complete original guidance 07 and 08 in separate labelled sections.
- `protocol-schema-and-tool-catalogue.md` contains the complete response schema, runtime tool catalogue, automation package schema 1.0 compatibility version, and current automation package schema 1.1 with typed result bindings, each in its own JSON fence.

Nothing is summarized. Each grouped component's manifest records its name, version, SHA-256, original byte length and absolute start/end byte offsets; end offsets are exclusive. Original source bytes, including BOMs, line endings and final-newline state, are preserved. All eight physical files also have locally recorded SHA-256 hashes. The aggregate startup reference size, including generated group headers and manifests, is capped at 20 MiB. The initialization message directly includes the complete required JSON response shape and envelope instructions so the requested format is explicit alongside the full schema.

The orchestrator rechecks all twelve source component hashes and all eight physical attachment hashes before every send. Previous generated group versions are retained when replaced; original guidance remains unchanged. A fresh or replacement chat receives initialization again. Ten physical uploads become eight, reducing startup attachment slots by 20% while preserving exact source bytes. This does not prove that a model will use the material identically; the visible initialization response and protocol checks remain acceptance evidence.
<!-- END SOURCE: docs/ATTACHMENTS.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/AUTOMATION_PACKAGE_ARCHITECTURE.md -->
## Source: `docs/AUTOMATION_PACKAGE_ARCHITECTURE.md` (verbatim text; line endings normalized to LF)

# Automation package architecture

This document describes the current package runtime and its approval boundaries.

## Runtime flow

```text
Copilot Chat creates ZIP
  -> copilot.download verifies the delivered artifact
  -> automation.inspect validates the exact ZIP and registered tool versions
  -> automation.run repeats inspection and binds approval to hashes and scope
  -> bounded stage scheduler executes Python and registered-tool stages
  -> outputs, hashes, validation and checkpoints are retained in the package workspace
```

`ToolRegistry` and the fixed local Python worker remain the only execution entry points. ZIP extraction is hash-checked and never executes code by itself. Every run is freshly inspected, even after a session package grant. The run approval display contains the ZIP and manifest hashes, stages and tool arguments, declared paths, outputs and resource ceilings.

## Package contracts

- Schema 1.0 remains supported for existing packages.
- Schema 1.1 adds typed `result_bindings` on tool stages. Downstream tool arguments can use only exact `{ "$binding": "stage.name" }` nodes. The source must be an earlier declared dependency, and the runtime validates the fully resolved arguments against the registered tool schema.
- Tool results remain in memory for one package execution. Durable stage checkpoints keep result hashes and byte counts rather than raw website content. A resumed run cannot reuse private result values from an earlier session.
- Stages may call registered `read_only` and ordinary `user_approval` tools under exact package approval. A session grant covers registered tool stages in freshly inspected packages, including bounded file edits inside already allowed roots or session-approved path extensions. Package Python source receives complete source-and-hash review and fresh one-run approval; a session or plan grant cannot authorize executable package code. Consequential or unbounded actions also require fresh approval for that exact run. Package stages cannot call `files.grant_path`; requested new locations still require their separate exact path approval. Recursive automation, immutable-plan code execution, customer authorization, external delivery, archive extraction and uncertain-operation recovery stay on their separate review paths.
- Independent `browser.recon` and `browser.route` stages may run concurrently only when each resolves to a distinct owned tab ID on the same origin. Same-tab calls serialize. The scheduler honors the package and configured concurrency ceilings. Effectful and otherwise ineligible tool stages do not run concurrently.
- Browser tabs are owned by the current Edge session, same-origin, task-bound and capped at six. They are not restored as authority after restart.
- Python stages receive declared inputs and exact final outputs beneath the per-run output root. Their final argument remains the exact output root. The fixed worker also provides `COPILOT_PACKAGE_STAGE_SCRATCH`, a fresh per-attempt directory beneath that run's outputs for intermediate files; only that stage may read or write its scratch tree. Scratch is bounded to 100 files and 50 MiB, verified and removed after each attempt. Native file stores and raw file APIs that bypass the worker's path and quota checks are disabled for package stages.
- Independent Python stages may overlap only when they have no network permission or destinations, have disjoint exact outputs, and use separate scratch directories. Python stages with network destinations, effectful tool stages, and mixed waves remain serialized; dependency constraints gate which stages are ready. On failure or cancellation, only declared output files that were absent before launch and remain regular single-link files are removed; no unverified partial output is recorded as completed.

## Approval and file access

One in-memory grant on `ApprovalManager` can cover registered tool stages in later freshly inspected package runs, including bounded file edits inside already allowed roots or session-approved path extensions. It also covers public HTTPS hosts statically declared by package `browser.open` and `browser.tabs.open` stages after each ZIP passes fresh hash-bound inspection; direct browser tools retain their approved-navigation host scope. Result-bound destinations require fresh one-run approval and must resolve within inspected public package hosts. Private, reserved, and ambiguous numeric result-bound hosts are rejected. Every package Python stage shows its full source and SHA-256 and requires fresh one-run approval; session or reusable plan grants cannot authorize that code. Packages with consequential or unbounded stages also require fresh one-run approval and cannot use a session or reusable plan grant. Package stages cannot call `files.grant_path`; requested new locations need its separate exact approval. Grants do not skip automatic inspection, path checks, tool preflight or platform-required handoffs. The session grant is cleared on close, a new agent session, or process restart; it is not written to `SessionState`.

Normal durable agent-owned storage stays anchored to mapped S: in VDI. A local live proof may use only the explicitly selected C: test store. A standalone `files.replace` call requires separate normal tool approval and an expected SHA-256. A package may call it only when declared in the freshly inspected ZIP and covered by that exact package's individual or session-scoped approval; the expected hash and path checks still apply. Replacement stages a same-directory temporary file, rechecks target identity and content, atomically replaces, and reads back the approved content. `files.grant_path` separately adds one reachable existing file or directory for the current session after user approval. A file grant is exact-file only; a directory grant covers that directory and descendants. Protected profile, credential, device and redirected paths remain denied.

## Validation status

Offline tests cover package inspection, hash-bound execution, result binding, private checkpoint projection, distinct-tab scheduling, session-grant lifetime, atomic file replacement and path-extension containment. The final local GOV.UK proof passed on exact Edge port 63741: a fresh 14-stage ZIP opened five tabs, ran reconnaissance with four overlapping stages, and saved then read back five navigation routes in the explicit C: test store. Stage checkpoints retain start/end timestamps for direct timing verification. See [the dated acceptance report](LIVE_GOVUK_PACKAGE_ACCEPTANCE_20261013.md) for hashes, measurements, test results and scope.
<!-- END SOURCE: docs/AUTOMATION_PACKAGE_ARCHITECTURE.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/BROWSER_RECOVERY.md -->
## Source: `docs/BROWSER_RECOVERY.md` (verbatim text; line endings normalized to LF)

# Browser recovery, navigation approval and visible exchanges

The authoritative ledger is `SessionState.data['calls']`, persisted through
`SessionState.save`. Compact model context is a summary, never execution authority.

## Architecture and root cause

`BrowserAdapter.start` verifies the Edge profile/CDP endpoint and registers the
shared signed-in context. `_configure_tool_context` registers owned website tabs;
`new_tool_page` creates guarded replacement tabs. An attached Edge context has no
agent-launched PID; that alone does not mean the browser is missing.

`Orchestrator.turn` records a pre-action fingerprint, calls `begin_call`, executes
the registered tool, and records `finish_call`. Failed effects become uncertain
unless the tool establishes certainty. `_preflight` and `begin_call` enforce the
ledger's block on further state changes.

The deadlock had two sources: `capture_baseline` called `_owned_page` before
`browser.open` could create a replacement tab, even when there was no pending
operation; and reconciliation required an unavailable original tab forever.
Fresh approved opens now establish a replacement owned tab before fingerprinting.
`recover_missing_navigation` closes only the blocking requirement for lost
navigation-only records, preserving their unverified outcome.

## Recovery matrix

| Situation | Ledger outcome | Next action |
| --- | --- | --- |
| Original navigation tab available, matching fresh evidence | Reconciled completed/not executed | New approved action or approved session navigation |
| Original navigation tab unavailable or connection lost | `unverifiable_original_tab_missing`, completion not credited | Fresh approved open, then live observation |
| Fresh tab has the same URL as the missing original | Original remains uncredited | Never use replacement state as proof of the old operation |
| Form, search, write, download or consequential uncertainty | Uncertain and blocking | Independent evidence/review; never replay automatically |
| Profile, CDP or context binding changed | Reconciliation rejected | Diagnose the binding; never substitute another browser |
| Evidence conflicts with a proposed outcome | Uncertain and blocking | Inspect the actual original tab before correcting the request |

Quarantine preserves the original request/result hashes and adds its reason and
timestamp atomically. Repeated recovery is idempotent. Live pre-action
classification excludes forms, searches, customer-bound plans, and consequential
grants. A multi-transition navigation plan can be quarantined when its tab is lost;
a final URL alone cannot credit every step as completed.

## Navigation freedom after approval

Every locally reviewed browser approval displays a continued-navigation scope.
It grants the current agent session navigation within approved HTTPS websites and
their subdomains: opens, history navigation, navigation-only plans, inspection,
and bounded same-origin new tabs. The orchestrator supplies the actual scope to
Copilot on subsequent messages. Runtime origin, tab ownership and consequential
control checks continue to apply. Navigation still enters the effect ledger even
when no additional approval prompt is needed.

Forms, searches, customer-bound actions, writes, downloads and scripts retain
their normal exact approval. New websites and dependency hosts need approval.
Closing/resetting tabs retains approval. Scope expires with the orchestrator
session and is never restored silently from disk.

## Diagnostics and compatibility

Copilot may request the read-only `browser.diagnostics` tool for registration
type, connection state, owned-tab count, binding hashes and authoritative uncertain
or quarantined ledger states. It returns no URLs, titles, cookies or page content.
Its hashed operation IDs can be supplied directly to `browser.reconcile`.
Query-free URLs returned by ordinary inspection can be matched against the
original tab's fresh URL locally; private query values remain hashes in the audit.

Existing ledgers with a retained navigation-only baseline support recovery after
restart: unavailable live tokens are quarantined, never credited. Legacy uncertain
entries without a trusted baseline remain blocked because their effect class
cannot safely be reconstructed from redacted arguments. Browser context identity
and profile/CDP fingerprints prevent changed bindings from reconciling live calls.

## Visible interaction and knowledge

The terminal and graphical workspace display every validated Copilot response as
**Copilot process summary (delivered)**, including its understanding, decision,
assumptions, action plan, risk and user message. Each outgoing task, tool-result
message and correction is labelled **Orchestrator → Copilot**. The graphical
transcript includes expandable delivered-envelope details. These are delivered
public summaries; hidden private model reasoning is not requested or displayed.
Malformed responses execute nothing and are corrected through the visible flow.

Website transcript content is live local session content; persistent audit logs
retain hashes. Existing `site_knowledge.bind/retrieve/save` provide scoped,
expiring, revisioned and sanitized knowledge. Use fresh retrieved routes for a
narrow live check; stale or contradicted knowledge requires fresh reconnaissance.
Lost-tab facts must be re-observed and must never be promoted to verified knowledge.
<!-- END SOURCE: docs/BROWSER_RECOVERY.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/COPILOT_TESTING.md -->
## Source: `docs/COPILOT_TESTING.md` (verbatim text; line endings normalized to LF)

# Testing Copilot replacement files

Double-click **Start Agent.cmd** and choose **1: Live repository** or **2: Copilot testing environment**. Setup remains the usual prerequisite. No Git installation or GitHub access is required for this workflow.

Drop replacements into the fixed **Copilot testing environment/Updated files/** folder. Mirrored directories are already present and are extended automatically at startup as the live project grows. Place root replacements directly in `Updated files`; put other files in their original relative directories. For example, these identically named files coexist safely:

```text
Copilot testing environment/
  Updated files/
    app.py
    copilot_agent/
      app.py
      browser.py
    tests/
      test_browser.py
    schemas/
      response-v1.schema.json
    guidance/
    docs/
    bootstrap/
  versions/                    retained complete runnable copies
```

Ask Copilot to label each delivered file with its project-relative path. Extract ZIP deliveries into `Updated files` preserving those paths. Create matching directories for new files. Flat files are accepted only when they identify a root file or one unique existing destination; ambiguous filenames stop with placement instructions.

The launcher creates a complete source copy under `Copilot testing environment/versions/<timestamp>/source`, applies all replacements, and runs that copy using the live project's configured Python environment. Imports resolve together inside the copy. Python syntax is checked before a version is created; this does not prove that the fix works. Copilot code is untrusted and executes with your normal user permissions.

The launcher applies `Updated files` automatically when testing is selected, without asking for a delivery path. Accept the latest testing version, choose an older version, or choose **L** to rebuild from live. Keep current replacements in the fixed folder and overwrite them with Copilot's next revisions. Changes accumulate on the selected version; unchanged replacements reuse that version. Removing a dropped file does not undo a previously applied change: choose **L** to rebuild using only the remaining replacements.

Graphify excludes the entire `Copilot testing environment` and `Copilot proposals` folders via `.graphifyignore`, including dropped files, copies and manifests. Only empty folder placeholders are committed; candidate files and retained versions remain ignored.

Each version retains `manifest.json` beside `source/`, including base source hashes and replacement hashes. Versions and proposals are excluded from Git. Existing versions and the live implementation are preserved. The dependency environment is shared: dependency changes require separate review/setup. Normal agent storage, allowed roots, sessions and approvals still apply, so a testing source copy does not isolate your personal files or external services. Ordinary application startup creates a fresh session.

To run a selected copy's automated tests, use the configured interpreter from a terminal with that copy as the current directory:

```powershell
& '<live-project>/.venv/Scripts/python.exe' -B -m unittest discover -s tests -v
```

After reproducing the original failure and verifying the fix in the real target environment, provide the successful version's `manifest.json`, changed files under `source/`, and reproduction/test evidence for review and incorporation. The launcher never promotes a testing version into live automatically. Further live edits do not silently alter existing testing versions; choose **L** when rebasing onto current live is required.
<!-- END SOURCE: docs/COPILOT_TESTING.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/CRAWL4AI_VALIDATION.md -->
## Source: `docs/CRAWL4AI_VALIDATION.md` (verbatim text; line endings normalized to LF)

# Crawl4AI integration validation — 14 October 2026

Windows Python 3.14.2; actual Crawl4AI 0.9.5 offline extraction, synthetic HTTPS
transport fixtures. This is not a live VDI, authenticated-site or S:/UNC proof.

- Core discovery/contracts/knowledge/transport/storage/persistence: 66 tests passed.
- Tools/site knowledge/repair/health/startup: 89 tests completed, 87 passed and two
  existing platform checks skipped.
- After adding explicit S: alias normalization, targeted mapping/tools/site
  checks completed: 70 tests, 68 passed and the same two checks skipped.
- A 126-page crawl used real Crawl4AI extraction, overlapped bounded page reads,
  saved all routes and read every route through pagination. An interrupted
  frontier was reused only from an approved bound map; cancellation stopped all
  child reads. Password pages, secret values and unapproved origins were excluded.
- Existing independent-run route trust and static navigation tests passed.
- Dependency installation and `pip check` passed; compilation and Git whitespace
  checks passed. The full repository suite was not run.

Run `Setup.cmd` in the target shared deployment before using the new extractor.
Verify a real approved discovery, cancellation, knowledge save/readback and a
long redirected UNC ledger read in that environment before claiming live success.
<!-- END SOURCE: docs/CRAWL4AI_VALIDATION.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/DIAGNOSTICS.md -->
## Source: `docs/DIAGNOSTICS.md` (verbatim text; line endings normalized to LF)

# Bug diagnostics and review

When the agent catches an actionable browser, protocol, operating-system, or application failure, it sets the session's `bug_fix` flag and writes two JSON reports under S: `Discoveries knowledge`. Reporting runs quietly so the user can continue the conversation and other work:

- `runtime/diagnostics/internal/` contains `internal_bug_report_<id>.json`. It includes the filtered exception message, project-relative stack locations, and a short evidence-based file recommendation. Send this report only to an authorized internal Copilot environment. Review each recommended source file before attaching it.
- `runtime/diagnostics/external_review/` contains `sanitized_bug_report_<id>.json`. It uses a fixed allowlist and file/function aliases. The raw error message, source paths, repository identity, and session identifier are omitted. The report is validated before it is written.

When the user ends the agent, the terminal gives a short handoff reminder. Send internal reports only to an authorized Copilot environment. Review the sanitized report manually before any external sharing. The agent never uploads or sends either report.

Reports are uniquely named and stored separately. The default retention period is 30 days; set `COPILOT_AGENT_DIAGNOSTIC_RETENTION_DAYS` to an integer from 1 to 3650 to change it. Expiration removes only matching generated bug-report JSON files from these two diagnostic folders. On non-Windows systems, report files are created with owner-only permissions. On Windows, they inherit the selected storage directory's access controls.

Diagnostics intentionally omit prompts, document contents, environment values, clipboard data, network traffic, and open-file inventories. Unknown values are left null where the report schema supports them.
<!-- END SOURCE: docs/DIAGNOSTICS.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/DISCOVERY_NAVIGATION.md -->
## Source: `docs/DISCOVERY_NAVIGATION.md` (verbatim text; line endings normalized to LF)

# Live discovery and navigation

Crawl4AI 0.9.5 ([upstream](https://github.com/unclecode/crawl4ai)) is the default
navigation extractor for `discovery.manifest`. Run `Setup.cmd` to install the
updated pinned dependencies. No extra crawler browser installation is needed.
The adapter uses Crawl4AI's LXML scraping tools on sanitized observed navigation
HTML; the existing public-IP-pinned HTTPS reader owns all network access. Page
text, values, scripts, media and credentials never enter the reusable map.
Evidence remains static; use approved visible Edge tools for JavaScript rendering
or manual sign-in.

For broad exploration, prefer one manifest with `expand_urls: true` over one
Copilot turn per page. The local loop investigates successive frontiers with
up to eight concurrent reads and four per origin. Suggested deep budgets are
1,000 pages, depth 10, 5,000 tasks/requests, 512 MiB, 1,800 run seconds, 1,500
task/branch seconds, 30-second reads, three attempts and two requests per second
per origin. See `docs/examples/deep-discovery.json`; replace the exact origin,
seeds and nested request ID. Each full manifest is reviewed locally. Queue
exhaustion, resource limits, cancellation and safety boundaries end the loop.

Bind the exact namespace and look up saved knowledge first. Expansion prioritizes
previously observed unexplored links from a separately consented map with matching
scope, intact evidence and unexpired provenance. Each reused candidate receives
a fresh approved GET. Another run needs its own approval and budgets. Save useful
runs with `discovery.knowledge_save`; maps are never silently promoted or saved.
`discovery.knowledge_lookup` accepts `offset` and `limit` (1–40), returns
`next_offset`, and retrieves all 1,000 saved routes without recrawling. Missing,
invalidated or stale maps require discovery; integrity failures stop reuse.

Deep runs retain full sanitized results up to 8 MiB while Copilot receives a
compact projection. The shared SQLite ledger is bounded at 256 MiB and individual
structural artifacts at 2 MiB. Oversized maps are explicitly partial. Operators
can select `discovery_extractor: "structure"` for the legacy parser; missing
Crawl4AI dependencies stop preparation without silently changing engines.

The bounded public-site discovery and static navigation tools are installed in the live agent. The supported flags (`manifest_path`, `persistent_graph`, `bounded_parallelism`, `local_recovery`, `knowledge_write`, `knowledge_reuse`) are enabled by default. `targeted_repair` stays unavailable because no safe browser repair adapter exists. An operator can set these booleans in an explicit configuration file or select a smaller set with `COPILOT_AGENT_DISCOVERY_FLAGS`. Flags expose tools; they never approve a request.

`discovery.shadow` compiles a manifest without network access. `discovery.manifest` runs one bounded, separately approved public HTTPS GET/HEAD manifest with local bootstrap, HTTP, structure, validation, and aggregation workers. It uses exact origins, public DNS and pinned peers, installed route patterns, task/request/byte/deadline limits, and an isolated local graph store. It does not use authenticated browser sessions, generated code, network observers, or autonomous browser actions. A failed or interrupted run retains only committed evidence and marks unfinished tasks terminal.

Knowledge writes require their own approval and revision check. `navigation.intent` compiles a read-only route from bound, trusted evidence and verifies fresh public fingerprints and links. Its result does not claim an interactive browser transition or authenticated access. Browser discovery and targeted repair remain unavailable.

Copilot replies use one marker pair with plain-text JSON between the markers. The local adapter captures the current assistant chat text after generation ends, validates the complete envelope, and sends a bounded correction request promptly when a finished reply is malformed. It never resends a submission whose delivery is uncertain.

The signed-in Copilot checks on 2026-10-08 confirmed a committed synthetic request, current-turn plain-text capture, rejection of a Copilot refusal, and a later valid marker-delimited JSON response. A fresh full-orchestrator run uploaded the eight startup references and validated initialization, but its first page request could not be proven submitted; the agent blocked without retry or tool execution. The page-understanding chat reported that Copilot could not access the supplied authenticated URL. Read-only inspection of the already open Edge page identified its major sections and navigation; a discovery shadow now accepts the generic `/inicio` route while still rejecting patient-ID routes. These observations do not establish a successful live browser tool cycle or authenticated discovery.
<!-- END SOURCE: docs/DISCOVERY_NAVIGATION.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/FEEDBACK.md -->
## Source: `docs/FEEDBACK.md` (verbatim text; line endings normalized to LF)

# Terminal feedback and participant roles

Feedback is enabled throughout the terminal conversation. Every emitted line has a UTC time and actor label. Interactive terminals receive distinct readable ANSI foreground/background colours; redirected output, unsupported terminals, `NO_COLOR`, and `TERM=dumb` receive the same labels in plain text. Terminal control characters in untrusted content are escaped, repeated blank lines are collapsed, and common Markdown chrome is removed from the normal view.

| Actor | Meaning |
|---|---|
| `User` | Human input and explicit choices, including model selection, approvals and session commands. |
| `Copilot` | Copilot's public reply, task interpretation, concise decision summary, assumptions, action plan and risk summary. Proposed actions are distinct from performed actions. |
| `Orchestrator` | Local coordination: submission ordinal, response validation, findings acceptance, dispatch, denial and stopping conditions. |
| `System` | Browser/startup status, visible generation status, upload metadata and ordinary infrastructure information. |
| `Approval` | Exact immutable approval scope and every full proposed script with SHA-256. |
| `Error` | Rejected protocol, stopped action or other failure needing attention. |
| `Tool/<name>` | Concise actual start, authorization basis, status, output paths, verification summary, error and audit reference. |

## Structured normal view

When a validated response parses reliably, the terminal renders short sections such as `PROPOSED ACTION`, `EXPLICIT APPROVAL REQUIRED`, `STARTING`, `RESULT`, and `FINAL RESULT`. Fields are limited to the task, action, purpose, authority, status, output paths, verification and errors. Long protocol arguments and complete results remain in the session state/events and immutable approval/audit files instead of flooding the normal view.

Code is the deliberate exception: the approval view prints every exact script in full between clear begin/end lines and shows its SHA-256. It also shows the interpreter, argv, permissions, file/network/process/desktop scope, expected effects, plan hash and retained full-preview path. Choosing a plan approves only the complete scripts already displayed.

## Live Copilot output

The browser reports changing request-correlated assistant text during capture. The orchestrator reads only completed top-level public JSON values after matching the current session and request identities. New values are visibly prefixed `UNVALIDATED PREVIEW`; incomplete strings remain buffered, malformed/incomplete envelopes execute nothing, and tool requests/scripts/hidden reasoning are never streamed as authority. Identical preview text is not printed again when the final envelope validates; the terminal says that the preview is validated.

Example plain-text output:

```text
[14:52:01] [Orchestrator] Sending message 3 (user_turn), with 0 attachment(s).
[14:52:02] [System] Copilot is generating a response.
[14:52:03] [Copilot] UNVALIDATED PREVIEW — Task
[14:52:03] [Copilot]   Capture three physical displays and keep three viewers on display 2.
[14:52:06] [Copilot] PROPOSED ACTION
[14:52:06] [Copilot]   Action: 1. Inspect versions | verify: use the actual result
[14:52:07] [Tool/system.versions] RESULT
[14:52:07] [Tool/system.versions]   Status: completed
```

## Authority and retention

A live preview is display data only. It cannot execute a tool, change the message counter, grant approval or replace authoritative state. Only one complete current validated envelope can dispatch actions. Malformed responses receive bounded correction and an `Error` entry.

The app shows public fields and generation status, not private chain-of-thought. UI buffering can delay fields. Feedback events are recorded in redacted `events.jsonl`; full authoritative tool results, approval JSON and local-Python audit receipts remain in session storage. Session changes and exit preserve records without deleting files.
<!-- END SOURCE: docs/FEEDBACK.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/FILE_DELIVERY.md -->
## Source: `docs/FILE_DELIVERY.md` (verbatim text; line endings normalized to LF)

# Generated-file delivery

This document defines the current delivery policy and the implemented integration of `copilot.download`, `archives.inspect` and `archives.extract`. Their exact versions, arguments, schemas, limits and availability come from the current generated machine catalogue. A documented flow is not proof that its live UI acceptance has passed; the evidence report must record observed outcomes separately.

## Website documents and bounded return to Copilot

Website document discovery/download is separate from generated Copilot artifact delivery. `browser.documents` returns temporary observed same-origin identities; `browser.download_batch` accepts at most 30 documents per batch, 1–3 concurrent owned tabs, and lowered per-file/aggregate limits within 20 MiB/100 MiB. Every file needs a completed browser event and verified retained bytes. Resume requires the returned manifest path and SHA-256, unchanged same-session provenance and reverified files. Different customer/task/tenant/site namespaces cannot share a batch. Retained-file quotas do not guarantee a cap on browser temporary network bytes.

Copilot accepts a hard **20 attachments in the complete outgoing message**. `files.transfer_to_copilot` can consider up to 1000 reviewed local references but queues at most 10 document slots, reduced by queued images and existing files. It ranks query matches and requested/active workflow paths, omits exact SHA duplicates and confirmed prior transfers, and retains deferred references. An index consumes one available slot when documents defer. Similar filenames with different contents are flagged for review, not discarded.

The retained JSON document index provides searchable metadata and exact original identities. Use `documents.find` and `documents.retrieve` for later evidence; retrieval rechecks authority and SHA-256 and still requires separate transfer approval. A later session explicitly imports the reviewed index with `documents.catalogue(manifest_path, manifest_sha256)` and matching customer/tenant/user/environment namespace. Private task indexes can include authorised file paths and names; reusable website knowledge and generic logs exclude customer evidence. A JSON index is the supported metadata bundle. Downloading or creating a ZIP never makes ZIP upload supported. Queued files become delivered only after attachment and submission verification.

## Format requested from Copilot

| Requested result | Required request and fallback |
|---|---|
| One or several Office files | Always ask for one downloadable ZIP containing the requested files. One file still requires a ZIP. |
| Complete coding project/package | Always ask for a downloadable ZIP preserving the required project structure. |
| One non-Office `.py`, `.md`, `.txt`, `.json`, `.csv` or similar file | Ask explicitly for an actual downloadable file in the Copilot UI. If the result is plaintext, a code block or only a sandbox reference, ask for a downloadable ZIP containing that single file. |

Office includes Word/Excel/PowerPoint documents, workbooks, presentations, related templates, macro-capable variants and legacy formats. Request the exact original output types inside the ZIP; do not replace an Excel workbook with CSV or a Word document with plain text without a new user decision. Never report a model-provided `sandbox:/...` path, suggested filename or rendered preview as a local file.

The default permanent delivery root is the per-user local app-data storage. The app does not discover or select OneDrive; an operator can explicitly provide an absolute `storage_dir` when they want delivery/runtime files stored elsewhere. ZIP extraction stays inside that configured storage. The S-drive source repo holds no per-user session state. No reasoning API, fabricated endpoint or bypass of organizational download controls is part of this flow.

## Clickable-link presentation

The strict response JSON remains in plain chat text between its marker lines. One useful actual Markdown artifact download link may follow the END marker outside the JSON object. This is the sole delivery exception to envelope-only presentation. A Markdown URL inside the JSON `user_response` is plain text rather than a clickable anchor. A link after the marker must represent the actual generated artifact, not a guessed URL, sandbox reference or second response envelope.

The browser binds a unique actual artifact anchor: allowlisted HTTPS or an observed native same-origin Microsoft 365 UUID blob with an exact `download` filename in the current correlated assistant container, checks configured download hosts and records a source-response hash and safe link identity for approval. The `copilot.download` request uses `expected_name` (plain basename), optional `link_text` and optional independently supported `expected_sha256`. It accepts no raw URL argument. Signed URLs remain transient browser data; their authentication-bearing query tokens must be excluded from logs, persisted response/context content and approval metadata.

## Message and artifact flow

1. Record the user's intended outputs, formats and names. Build a compact Copilot request using the required delivery format. Keep long delivery guidance in the attached contract file.
2. Capture and validate the assistant response. Distinguish an artifact claim from an actual observed generated-file control/link in that response's Copilot UI container.
3. Discover the actual current artifact controls with the browser adapter. Resolve ambiguity before interaction. Do not let Copilot invent an arbitrary external URL or substitute an unrelated earlier artifact.
4. Obtain narrow download authorization when required by local policy. Display artifact identity, safe observed link identity, source-response hash, browser download settings/destination, retained local target, anticipated file format and effects. An existing explicit task grant may apply only if it already covers those exact generated artifacts; it never becomes a permanent download grant.
5. Use `copilot.download` to activate the observed actual UI control and await a bounded Edge download event. Inspect relevant download event metadata and browser download location/settings when needed. Do not read cookies, credentials, profile contents or unrelated browser downloads.
6. Retain the downloaded artifact in a configured permitted delivery directory with a new name if a collision exists. Verify local existence, stable/readable content, size, SHA-256 and plausible format. A click, UI filename or zero-error message is insufficient.
7. For a ZIP, retain the original and use `archives.inspect` to obtain a bounded manifest and safety result. Match the proposed member set to the user's requested files/package.
8. Display an extraction proposal containing the inspected archive SHA-256, complete inspected manifest and required expected files, destination and expected output paths. Obtain extraction approval for that scope before calling `archives.extract`. Inspection alone grants no extraction permission.
9. Extract exclusively into a new scoped directory. Verify actual local outputs, their hashes, expected names and format/structure; return concise evidence to Copilot.
10. Give the user the retained ZIP path and verified extracted artifact paths. Report any unverified content quality or unavailable capability honestly. Do not execute a delivered project or launch Office automatically. A later execution request follows the separate source-bound approval flow below.

## Download boundary

The Copilot control page remains unavailable to ordinary browser tools. `copilot.download` is a specific mediated delivery capability, not arbitrary access to that page or all links. It acts only on a currently observed generated-artifact control under the user's authorized task. Its policy must cover the actual destination and retain the original artifact; redirects or organizational restrictions must not be circumvented.

Edge's observed download event and a verified local file supply evidence. If browser download settings select a different location, resolve the relevant actual event/location without guessing a OneDrive directory. Preserve a record of current session/request identity, artifact name, observed control, download result and retained target/hash. Do not collect authentication-bearing URLs or tokens in logs.

## Archive boundary

Inspection is read-only and bounded. Reject an unsafe/unsupported archive rather than partially extracting it. Check actual normalized Windows destinations, not only raw archive names. Required rejection categories include:

- `..` traversal; absolute, drive, UNC and alternate-data-stream paths; reserved device names and ambiguous trailing spaces/dots.
- Symlinks, special file entries, path escapes through existing links/reparse points, or extraction outside approved roots.
- Duplicate names, case-insensitive/normalization collisions, and file-versus-directory collisions.
- Unsupported encryption, corrupt ZIP structure, excessive members, excessive compressed/uncompressed size or expansion ratio.

Extraction approval binds the exact archive hash, complete inspected member set (all members are extracted; `expected_files` asserts required outputs) and destination. Recheck the archive before extraction. Use exclusive creation; existing targets fail without overwrite. Retain the original ZIP and any safely created partial artifacts if extraction fails. Never delete outputs as rollback, silently change approved member names, recursively unpack a nested archive or run an extracted script during extraction. An uncertain partial extraction requires inspection and user reconciliation before another state-changing attempt.

## Delivered-format verification

Record output names, sizes, readable access and SHA-256 hashes. Check expected text encoding or JSON structure where applicable without executing content. A coding package may be inspected for expected files and directory layout, but its code remains untrusted and any later execution requires a separate Code Runner proposal and authorization.

For OOXML `.docx`, `.xlsx` and `.pptx`, inspect their internal ZIP structure for `[Content_Types].xml`, `_rels/.rels` and the appropriate `word/document.xml`, `xl/workbook.xml` or `ppt/presentation.xml`. Related OOXML formats require their corresponding package structure. For legacy Office or other supported formats, validate applicable signatures and state when deeper structure validation is unavailable. File extension alone is insufficient. Structural plausibility is not proof of visual rendering, formulas, business correctness, macro safety or absence of malicious content. No application or macro is opened automatically.

## Approved execution of delivered Python source

Downloading or extracting a file does not authorize execution. After a separate user request to run it, a supported `.py` artifact can be bound to a Code Runner proposal. A package must first complete actual ZIP download, safe inspection, approved extraction and local artifact verification. Each script proposed for execution is then reviewed individually as part of the complete pending plan.

The normal complete Code Runner fields remain required, including the full `script` text. Use the restricted `python_subset` by default. Use `local_python` only through its separate complete interpreter/argv/import/file/network/process/desktop/effect declaration when the subset cannot perform the user's task. Optional `source_path` and `source_sha256` must be supplied together. `source_path` must resolve to an allowed regular `.py` file and be declared in `read_paths`, with `read_files` permission. The lowercase SHA-256 binds its raw downloaded/extracted bytes. `script.encode('utf-8')` must equal those bytes exactly, including CRLF/LF and final-newline state. No silent rewriting, newline normalization or source substitution is permitted.

Source files are capped at 200,000 bytes; script text remains capped at 50,000 characters. UTF-8 BOMs and non-UTF-8 Python encoding declarations are explicitly rejected. The implementation rechecks raw path safety, regular-file identity, size, hash and exact script-byte equality during preparation and again before execution. The prepared metadata and execution result include `source_verification` with `path`, `sha256`, `size` and `exact_script_bytes: true`, including runs that only print and create no outputs. A changed source or materially changed proposal cannot use the earlier approval.

For several supported scripts, the orchestrator prepares and displays the complete immutable all-Code-Runner plan: every call identity, complete script, source verification, declared reads/creates, permissions, expected outputs, risks and proposal hashes. Choose **1: deny**, **2: once** for one call, or **3: plan** for that exact displayed set. A plan grant binds all prepared calls, not an open-ended project directory or future generated scripts. Material code, source-hash or scope changes require renewed preparation and approval. Download and extraction approvals remain separate from execution approval.

Source binding does not select a mode or authorize execution. `python_subset` evaluates the constrained AST. A separately proposed and explicitly approved `local_python` plan may launch the exact source bytes through the bound current interpreter with declared installed imports and scope. Missing dependencies are not installed automatically. Shell strings, deletion, credentials, hidden persistence and undeclared access remain unavailable, and native libraries are not contained by an OS sandbox.

The manual `tests/live_download_run.py` harness exercises a real synthetic source download followed by exact-byte approval-bound execution. It requires explicit `--live`, prepares the downloaded print-only script, displays pending approval and waits within a bound for a fresh matching once ledger. The supervising operator must obtain explicit user approval of the displayed script and scope before creating that ledger; the harness never creates an approving decision itself. The ledger binds its nonce, source path/hash and immutable proposal. No live success is established by this document: consult `TEST_REPORT.md` for observed download, approval and execution evidence.

## Recovery and honest completion

Use finite generation, control-discovery, download and extraction retry budgets with recorded reasons. A missing actual link, download timeout, unsafe archive, missing expected member or format mismatch returns evidence to Copilot for a bounded correction of the same requested output. For a single non-Office plaintext/sandbox-only result, request ZIP fallback. For Office or complete projects, request the required ZIP again within the budget, or report that the capability is unavailable.

Do not repeat an action whose acceptance/effects are uncertain, expand the task to unrelated files, or claim delivery from a model assertion. Ambiguous matching artifacts/members require disambiguation. Final delivery evidence distinguishes each completed step from blocked/unexecuted steps, preserves the original ZIP and verifies the actual extracted files.

## Visible acceptance evidence required

Use harmless synthetic artifacts in the real authorized UI. Record an Office-in-ZIP request, actual UI download control and Edge event, retained ZIP/hash, safe archive inspection, explicit extraction approval and verified Office structure. Separately exercise a full coding-package ZIP and a single non-Office downloadable file or observed ZIP fallback. Verify denial performs no download/extraction, unsafe ZIPs fail closed, existing targets are preserved, and downloaded/extracted scripts never run automatically. Mock tests cannot establish real Copilot generation or download availability. No Created-folder access is needed for these tests.

Edge settings are read through its actual settings UI before link selection. The verified artifact is retained under the configured `deliveries` folder, even if the observed browser artifact is temporarily elsewhere. The report distinguishes the configured Edge Downloads directory from the actual event-backed artifact and permanent target; it does not claim a normal default-directory save unless proven. Native Save As prompts remain under the user's control within a bounded wait. Neither sandbox text nor a guessed URL is converted into a download.
<!-- END SOURCE: docs/FILE_DELIVERY.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/KNOWLEDGE_PERSISTENCE.md -->
## Source: `docs/KNOWLEDGE_PERSISTENCE.md` (verbatim text; line endings normalized to LF)

# Local navigation and Discoveries persistence

Runtime S: resolution preserves the direct path first, then tries live PowerShell
drive DisplayRoot, CIM ProviderName and SMB RemotePath providers when strict Python
resolution fails. Accessible destinations are validated as UNC directories.
Knowledge and SQLite use the same canonical store; extended UNC I/O spelling is
applied after logical path validation for long redirected paths. No provider
permits automatic local C: or OneDrive fallback. Provider lookup is a fixed,
hidden, read-only command with a ten-second timeout.

Read saved routes directly with `discovery.knowledge_lookup` and offset/limit
pagination. Reads validate the exact bound namespace, hashes, evidence and
freshness. Broad discovery can reuse its consented unexplored frontier.

Each visible run asks once for local filesystem navigation and verified knowledge
saving. This in-memory grant expires with the process; it does not authorize code
execution, authentication bypass, website transactions or arbitrary file changes.
File navigation probes the current local/mapped/network volume and reports sanitized
OS errors. Browser-profile access remains protected.

Knowledge uses `Discoveries knowledge` beside the project's parent on the live
S: share. It does not follow runtime, workspace, profile or OneDrive storage. On
a machine where the project is not on the mapped S: share, the agent stops before
writing rather than silently falling back. A configured `knowledge_directory`
must match this canonical folder. Startup creates a unique probe, flushes it,
checks its hash, removes it, and checks SQLite schema and integrity. The verified
S: path and resolved UNC filesystem path are included in the startup contract and
each agent save response.

For a local live navigation test only, `app.py --local-knowledge-test-directory`
can select an empty direct child of `%LOCALAPPDATA%\\CopilotLocalAgent\\live-navigation-tests`.
The test store is reported explicitly and scoped as the only agent write root for
that run. This opt-in does not change the normal S:-only production path or act as
an automatic fallback.

Website knowledge and discovery records share the SQLite ledger. Compatible JSON
records already under the selected S: Discoveries root are read through a
compatibility path and promoted on approved saves. The app no longer searches
legacy OneDrive or LocalAppData knowledge stores automatically.
Known columns in newer stores remain readable; incompatible writes return a
specific diagnostic. Executable website hints retain privacy and authentication
checks. Custom bounded JSON categories support ordinary knowledge.

`knowledge.note` saves ordinary findings in immutable files under Discoveries,
verifies the bytes, and attempts indexing in the shared ledger. A schema/index
failure does not invalidate an already verified note: the receipt reports both
statuses. `knowledge.lookup` lists note identifiers or reads verified content for
the reasoning agent. Notes are evidence, never execution authority.

Uncertain optional knowledge operations are inspected against retained hashes.
Proven outcomes become completed/not-executed; unknowable operations are quarantined
without success credit or replay. Damaged active rows are retained transactionally
before removal from the active namespace. Materially different safe knowledge
writes can then proceed. Recovery tools do not depend on operation-learning flags.

The local UI journals run events across launches, including failed, cancelled,
blocked and recovered runs. A visibility choice is no longer offered. Real VDI
drive mappings, permissions and authentication still require target-environment
confirmation; synthetic tests do not establish those conditions.
<!-- END SOURCE: docs/KNOWLEDGE_PERSISTENCE.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/KNOWN_LIMITATIONS.md -->
## Source: `docs/KNOWN_LIMITATIONS.md` (verbatim text; line endings normalized to LF)

# Known limitations

The real execution evidence and any acceptance blockers are recorded separately in `TEST_REPORT.md`; the presence of an implementation is not proof of real UI acceptance.

- Visible Windows Edge is the supported Copilot mode. Headless operation has not passed real authenticated acceptance and is unavailable.
- The response protocol depends on Copilot following uploaded guidance. Malformed decisions fail closed and receive bounded correction; exhausting recovery stops the affected task.
- Model labels and capabilities depend on the authenticated account and tenant. Newest GPT versions rank before modes; cross-provider quality is incomparable and the interactive user chooses among observed alternatives.
- Daily model allowances can expire after checked selection. The observed exhausted-access/Auto-fallback notice stops the task without format-correction retries or local execution; select an available model through fresh setup or wait for access to return.
- Code Runner keeps `python_subset` as the restricted default and now offers explicitly approved `local_python` for tasks the registered tools and subset cannot perform. `local_python` is ordinary host Python with defense-in-depth checks, not Windows Sandbox, low-integrity execution or a security boundary against a malicious approved native library. PowerShell/shell strings, deletion, credential access and silent privilege escalation remain unavailable.
- Source-bound execution verifies exact downloaded/extracted `.py` bytes in either mode. Paired `source_path`/`source_sha256` require a declared source read and `read_files`; the mandatory script must match raw UTF-8 bytes exactly. Sources are limited to 200,000 bytes and scripts to 50,000 characters. UTF-8 BOMs and non-UTF-8 encoding declarations are rejected, not silently repaired. Downloading a package does not approve execution or install missing dependencies.
- Local Python can import standard-library and already installed packages declared by the script. It does not install packages at runtime. Python audit hooks and static checks cannot fully mediate native extension code; exact preview, minimal permissions and trusted-source judgment remain essential.
- Physical-display capture and viewer verification require an unlocked visible Windows desktop, the requested displays, working GDI/Tk APIs and permission from organizational controls. Automated tests mock the three-window observation; no three-display live acceptance was performed in this development turn. A blocked capture/window API is reported rather than bypassed.
- Multiple supported scripts can receive one exact prepared-plan grant after all scripts, source hashes and scopes are displayed. A once grant covers one call. Changed code, source hashes or scope require renewed approval; there is no approval for arbitrary future files. Packages must first be actually downloaded, safely inspected, approved for extraction and verified. Neither delivery nor extraction automatically runs their code.
- Tool browsing uses guarded owned tabs in the same verified Edge profile as Copilot, so website sign-ins can be reused. The profile persists after agent exit. Owned-tab HTTP requests and WebSockets are filtered; service-worker traffic already active in the shared profile cannot be fully mediated by page routing, so the profile and approved sites remain trusted. Cross-domain resources outside the exact HTTPS allowlist can prevent some sites from functioning. General browsing downloads are detected/canceled. The separate `copilot.download` capability mediates only the current generated artifact and verifies its retained file under configured user storage.
- The read-only process tool reports only this agent process. It does not collect broad process command lines or arbitrary environment variables.
- OCR/image analysis uses approved Copilot attachments where the active UI supports them. No local OCR package is installed and successful attachment alone does not prove interpretation quality.
- Created-file monitoring cannot establish or repair OneDrive/Power Automate configuration. A missing folder, ambiguous output, unstable file or bounded timeout is reported, and organizational download/sync restrictions are respected.
- Created monitoring defaults to disabled. The user must configure the exact `created_dir` to enable it; OneDrive paths are not discovered or selected automatically.
- Public feedback streams completed response fields as the UI exposes them. UI buffering can delay content; generation/status feedback continues, without claiming token-by-token or private chain-of-thought access. ANSI colours depend on terminal support; redirected output uses plain labels.
- Application file tools do not delete files. Versioned state backups, diagnostics, session logs, test directories and browser profiles accumulate. Retention requires explicit user-managed housekeeping outside this application. Explicit Setup environment management preserves an incomplete `.venv` in a sibling `.venv-incomplete-*` directory before creating a replacement, and pip may replace packages within an otherwise usable environment.
- Diagnostics can contain synthetic or user-authorized content. Text logs are redacted; screenshots should be inspected locally before sharing because arbitrary visible personal data cannot be perfectly removed automatically.
- Approval binds scripts, interpreter/runtime identity, arguments, imports, declared execution scope and upload bytes. Path resolution rejects traversal/symlink escapes, but the local machine remains a trusted environment; native-code escape and privileged concurrent tampering are outside this application's enforcement boundary.
- The manual `tests/live_download_run.py` harness requires explicit live mode and a fresh matching user-approved once ledger. It never auto-approves its downloaded synthetic script. Its existence and automated source-binding tests do not prove real download/run success; current observed evidence belongs in `TEST_REPORT.md`.
- Long state is preserved locally and supplied through bounded recent context plus a reference attachment when needed. Uploaded references remain subject to Copilot attachment/context limits, with honest failure instead of invented history.

- Shared S-drive interpreter/repo discovery and per-user local storage are implemented and tested with fixtures. The private production VDI/S environment is unavailable here. Cloud synchronization to another device is never inferred from a local OneDrive path. Portable Python distributions without `venv` or `pip` are supported by the bundled virtualenv bootstrap; the configured package index must still provide the application's pinned dependencies.
- Native download prompts require the user to finish the browser's normal Save As UI; settings/security policies are never changed to suppress a prompt. Current accepted live downloads completed without such a prompt; its enabled behavior is covered with offline fixtures.
<!-- END SOURCE: docs/KNOWN_LIMITATIONS.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/LIVE_GOVUK_PACKAGE_ACCEPTANCE_20261013.md -->
## Source: `docs/LIVE_GOVUK_PACKAGE_ACCEPTANCE_20261013.md` (verbatim text; line endings normalized to LF)

# Live GOV.UK automation package acceptance — 2026-10-13

The final fresh local proof passed against the reviewed worktree on `main`. Microsoft 365 Copilot Chat generated and delivered a new schema 1.1 ZIP; the local agent verified its download, inspected it, executed it, and completed the final delivery gate. The agent then exited normally.

## Observed result

| Check | Evidence |
| --- | --- |
| Exact browser endpoint | Edge `155.0.4283.45`, loopback CDP port `63741`; dedicated profile ownership verified before the run |
| Package | `govuk-final-live-run18`, version `1.1.0`; only `manifest.json` and `README.md`, 14 registered-tool stages, no Python stages |
| Fresh execution | Run `1ecefe5bc41d419989a1ddf3f367d91e`; full rebuild, no prior run or reused stage |
| Stage completion | 14/14 completed, each on attempt 1; no failed, skipped or uncertain stages; validation passed both checks |
| Navigation | Five new owned same-origin GOV.UK tabs, independently distinguished from the 10 pre-existing public page targets |
| Parallel discovery | Five reconnaissance stages; recorded start/end intervals prove a maximum overlap of four |
| Persistence | Exactly five approved generic routes saved to the explicit local C: test store, then retrieved and queried |
| Final delivery | Verified retained ZIP credited by its exact local inspection receipt; final response completed without redelivery |

The visited and saved routes were `/browse/benefits`, `/browse/benefits/families`, `/child-benefit`, `/browse/benefits/disability`, and `/pip`. No forms were submitted or personal data collected.

## Measured execution time

Times are measured from retained stage timestamps, excluding Copilot generation and approval latency.

| Interval | Seconds |
| --- | ---: |
| Primary navigation start to fifth page open | 2.378231 |
| Primary navigation start to verified knowledge save | 3.334734 |
| Last reconnaissance finish to verified knowledge save | 0.064485 |

## Integrity and readback

An independent reviewer opened the ZIP and SQLite ledger read-only, verified the manifest and payload hashes, and reconstructed the actual save/retrieve/query result objects from the persisted record. Their canonical hashes and byte counts match the retained tool checkpoints. Both readbacks contain the five saved routes, with `age_seconds=0` consistent with their stage intervals.

| Artifact | SHA-256 |
| --- | --- |
| Delivered ZIP | `47e7c1cbef60cb9bc12fb99a80009c5ed55d0a6690e18e35c9665b3b9af2c30d` |
| Canonical manifest | `974b475ea0050b66f9628f91ba35184b99d4168d58d5dab4d33dfa6b2f1373a6` |
| README payload | `e50658af85fd2cb0ab0ec87909e18502c5299db64f709e88d29d30c14d17efc7` |
| Knowledge payload | `0520e955c9bc6fd20b0ae8dd9dd6cb14af14abcd0cbcc91cbbf29c0b47d1ac25` |
| Save result, 333 bytes | `c68ddaad8f47590f10b46b9a46667024b1479b47f3d927fab492776dc511b392` |
| Retrieve and query results, 1194 bytes each | `230d7f12d1d20502d5f47a5c82aed0159d2f78b47d01930e1e77ed561d9e5bd4` |

## Regression and review gates

The complete `unittest` suite passed: **758 tests in 234.475 seconds, two skipped**. Compilation and `git diff --check` passed. Independent review found no blocking findings.

The live work identified and fixed the missing primary `browser.open` tab ID, aligned package schemas with the runtime's major.minor Python version rule, and corrected delivery credit for an explicitly requested automation ZIP. Regression tests exercise the actual tool and orchestrator interfaces. Stage timestamps provide direct concurrency evidence. Office and named inner-file delivery retain their extraction verification requirements.

## Retained local evidence and scope

Evidence stays beneath `%LOCALAPPDATA%/CopilotLocalAgent/live-navigation-tests/final-20261013-run18`:

- `deliveries/86e7db8156074923b29e4c040ad4a1a9/govuk-final-live-run18-1.1.0.zip`
- `automation-runs/govuk-final-live-run18-new-1/runs/1ecefe5bc41d419989a1ddf3f367d91e/state.json`
- `Discoveries knowledge/discovery-v1/ledger.sqlite3`
- `validation/full-unittest.log`, `validation/edge-endpoint.json`, and `validation/before-govuk-targets.json`

Production storage remains S:-anchored in VDI. This proof used only the explicitly selected C: store; S:/VDI behavior was covered by design and offline tests, without a real VDI run. Public hostname policy checks do not resolve or pin DNS answers. Browser profiles, authentication data, runtime logs and raw website observations are excluded from publication.
<!-- END SOURCE: docs/LIVE_GOVUK_PACKAGE_ACCEPTANCE_20261013.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/REUSE_MAPPING.md -->
## Source: `docs/REUSE_MAPPING.md` (verbatim text; line endings normalized to LF)

# Browser reuse mapping

Source inspected: `../Scripts and projects/CDD Audit/Documents review workflow/Initial sanitized reference files/resources/implementation_sanitized.py`. The source and the existing workflow are preserved. This project never imports that engine at runtime.

| Existing source | New destination | Retained behavior and explicit changes |
| --- | --- | --- |
| `cdp_endpoint`, lines 1694-1695 | `reused_browser.cdp_endpoint` | Loopback-only endpoint, with added port range validation. |
| `get_cdp_version`, lines 1698-1717 | `reused_browser.get_cdp_version` | Bounded `/json/version` probe, capped response size and loopback validation. |
| `find_edge_executable`, lines 1720-1761 | `reused_browser.find_edge_executable` | Explicit executable validation and Windows install/PATH discovery; no installation or download. |
| `launch_edge`, lines 1764-1823 | `reused_browser.launch_edge` | Detached visible Edge with persistent dedicated profile. Removed background-throttling overrides and permissive remote-origins flag. Readiness belongs to bounded adapter startup. No process termination on failure. |
| `validate_dedicated_endpoint`, lines 939-961 | `reused_browser.validate_endpoint` | Exact local WebSocket port validation; additionally require Edge's version advertisement. |
| `validate_port_profile_ownership`, lines 696-720 | `reused_browser.validate_profile_ownership` | Listener/process/command-line profile association. Fail closed when ownership cannot be established; no original permissive hidden-metadata fallback. |
| `connect_existing_edge_with_retry`, lines 1957-2027 | `reused_browser.connect_bounded` | Sequential fresh WebSocket/HTTP route alternation. Replaced indefinite retry with one finite deadline. |
| Editor/model/send/attachment selectors, lines 2133-2172, 2988-2996, 3436-3458 | `reused_browser` selector constants and `BrowserAdapter` | Retain known UI selectors while isolating them from engine business logic. Send never targets Stop. |
| Attachment-name detection, lines 2998-3051 | `BrowserAdapter.attach_files` | Native bulk file selection, exact complete basename multiset verification, no upload error/progress, enabled Send, stable samples. Never accept a count alone; duplicate basenames fail closed. |
| Model checked-radio technique, lines 2688-2733 | `BrowserAdapter.discover_models/select_model` | Enumerate actual current radios/provider submenus; select exact discovered label and reopen to verify checked radio. No static six-model limit or fallback. |

New implementation: request-correlated user-turn proof and assistant capture, immutable baseline filtering, per-message submission callback, owned tool tab, bounded diagnostics, and Windows named controller mutex. The controller uses no lock file, so exit releases handles without deleting files. Browser close only closes the adapter's two owned pages and stops its Playwright transport; existing tabs, Edge process, profile and cookies remain.

The copied CDD cleanup and orchestration were deliberately excluded: `clean_user_temp_path`, `startup_edge_stability_cleanup`, `edge_resource_stability_monitor`, `run`, `_run_single_wave`, global result/queue bindings, attachment staging, and preloaded-chat reuse. The source's startup path permanently deletes user Temp contents and its reconnect loop is indefinite; neither behavior is appropriate for this standalone agent.

## Model ranking

`model_rank` is a documented preference heuristic: enabled options first, the newest enabled GPT version next, then reasoning/deeper modes within that same version. GPT 6 therefore precedes GPT 5.6 Think deeper. Enabled non-GPT options preserve discovery order and require explicit user choice if no GPT is available. GPT-first is an application preference, not a measured comparison of providers. Cross-provider model numbers and names are not comparable measures of capability. Setup shows the chosen exact label and permits an override. Availability and checked selection are observed; claims about answer quality are not inferred from names.

Website tools use guarded owned tabs in the same verified Edge context and CDP port as Copilot, sharing existing site cookies. Each owned page has an exact HTTPS host route and WebSocket guard; script popups are blocked. JavaScript stays enabled. Page routing cannot fully mediate existing service-worker traffic, so the signed-in profile and approved sites are trusted. Error/download events are recorded; unapproved downloads are canceled and reported as unsaved. Unowned tabs and the Copilot chat page receive no website guard. Agent exit disconnects Playwright and retains the Edge process and tabs for the next run.

## Submission and capture limits

Submission commits only after one newly observed user turn contains the current request ID and the composer clears. A failed/timed-out Send click is uncertain even if the underlying click might have fired. The adapter never resends it and blocks further sends until a user starts a reconciled session. The zero-argument `on_submitted` callback may be synchronous or asynchronous and fires once after delivery proof. A callback failure after proven delivery also requires reconciliation.

`SubmissionNotSentError` distinguishes preparation failures that occur before any Send attempt; its evidence records `send_attempted:false`. The orchestrator may cancel that persisted intent without incrementing the counter. Composer comparison permits only JSON formatting differences whose parsed values, types and literal strings remain identical; plain-text changes remain rejected. Live synthetic inspection showed the Lexical editor appends a structurally identified `span[aria-hidden="true"][data-lexical-text="true"]` containing exactly U+200B U+200C. The editor reader removes only that observed trailing caret span, preserving all payload characters. Hashes, lengths and a sanitized first-difference classification are retained on mismatch, not raw payload excerpts. The same reader verifies the composer cleared after submission.

Assistant capture inspects message-scoped nodes after the committed user turn, excludes unchanged baseline nodes and the composer, requires generation controls to disappear and text to remain stable, and enforces a character cap. Complete stable malformed text is returned for protocol correction, not misclassified as a capture failure. Correctness of JSON/request IDs/marker pairs remains the protocol validator's responsibility. DOM recycling/virtualization or tenant-specific selectors can cause a bounded fail-closed timeout; no global page-body fallback is used.

If Copilot replaces/collapses the committed user DOM node, capture rebinds only when exactly one current user-message node contains the request ID; ambiguous anchors and recycled keys belonging to other users remain rejected. Timeout metadata records node roles/keys/order/length and request-ID presence without exporting payloads. For fenced responses, the owned assistant subtree is cloned, `pre/code.textContent` is retained verbatim, and only surrounding known language/copy controls are excluded. Adjacent envelope markers remain. Paragraph rendering can consume JSON backslashes; older malformed displayed text is returned as invalid rather than repaired. The controlled owned local DOM test retained Windows path escapes and excluded code chrome with exact JSON value equality (`runtime/acceptance/picker-20261006T140614Z-67982a/evidence.json`). This test sent no Copilot messages.

Diagnostics are retained in `runtime/diagnostics`: a small UI metadata/alert JSON and an owned-page screenshot where available. Input/account/profile controls are masked; sign-in-provider pages are not screenshotted. Screenshots can contain conversation content and remain local. No cookies, browser profile contents, password fields, storage state, or full DOM are exported.

Actual M365 fenced output also uses a `Code Preview` group with a `Code editor` textbox rather than PRE tags. Capture reads that editor's literal rendered content, replaces only its surrounding UI group and waits for hydration. A request-scoped Show more lines control can expand the current response without touching another chat. Verbose callbacks publish public response-field previews and generation status; they confer no execution authority. The observed daily model-access exhaustion/Auto-fallback notice stops before correction or tools.

Offline tests exercise stale-response exclusion, correlation ordering, disabled model ranking, endpoint isolation, exactly-once submission callbacks, malformed-response return, capture timeout, and ambiguous delivery without replay. Real account/model/upload/rendering behavior requires separately recorded visible acceptance testing.

Current response transport (2026-10-08): Copilot is instructed to emit plain chat-text JSON between the marker lines. Current-turn DOM text is captured without Copy code; finished malformed text is passed to protocol correction after a few stable samples. Historical fenced-code observations above document earlier behavior only.
<!-- END SOURCE: docs/REUSE_MAPPING.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/SHARED_VDI.md -->
## Source: `docs/SHARED_VDI.md` (verbatim text; line endings normalized to LF)

# Shared S-drive VDI use

An existing project environment is reused only if its interpreter and pip both work. If pip is missing, Setup discovers pip in the selected base installation automatically and preserves the old environment before rebuilding it with the bundled bootstrap. If automatic selection picked the project environment itself, Setup obtains the base executable from the running Python before moving that environment. The replacement's pip is verified before package installation; pinned application packages remain in the project environment.

Windows may report a running environment's base executable, other runtime paths, or installed-package locations as UNC paths even when the installation was launched through S:. The launcher accepts a UNC path only after resolving it to the currently mapped S: share; unrelated UNC shares and local drives still fail validation. An existing environment's prefix is checked by directory identity, so S: and UNC spellings of the same environment can be reused. If a runtime path fails validation, the error includes the live Python-reported values; the environment configuration file alone does not establish what Python reported.

Keep one copy of the source repository on S: and use an organisation-managed Python 3.10+ installation on S:. Setup offers automatic detection or a pasted absolute Python executable/installation-folder path. Quoted File Explorer paths are accepted; the same S-drive and link checks apply to both choices. If detection fails, paste a path locally without sharing private paths in chat. Start and Tests reuse a valid saved environment.

Setup creates/reuses the repository's `.venv` and installs `requirements.lock.txt` directly into it. It uses the bundled `bootstrap/virtualenv.pyz` archive, verified against a pinned SHA-256 before execution, so the selected portable Python does not need `venv`, `ensurepip`, or base-installation `pip`. The archive seeds pip offline in `.venv`; pinned project packages still require the organization's package index. An incomplete `.venv` from an interrupted setup is moved to `.venv-incomplete-*` within the repository before a new environment is created. The selected base interpreter and shared virtual environment both stay on S:. Setup needs write permission there and access to the organization's package index. Environment installation is serialized; another concurrent setup fails clearly rather than racing shared package writes. Ordinary Start does not install packages. Every production Python entrypoint ignores `PYTHONPATH`/other Python environment overrides and per-user package directories using `-E -s`. Setup verifies the base interpreter, standard library and each pinned dependency distribution are on S:. Development launches retain their local interpreter behavior.

The app resolves `Discoveries knowledge` beside the project root's parent on S: and verifies the final UNC identity. Per-user settings, workspace, deliveries, temporary files, session records and persistent website/discovery knowledge stay under that S: folder. An older configured C: or OneDrive storage path is redirected to the canonical S: location. The project source remains separate from mutable state; Setup writes the shared environment and retained setup lock. User grants and chat state are not inherited by another user.

The checkout and Python paths may be entered as S: paths or their equivalent UNC paths on the currently mapped share. Startup retains its previously working drive-based selection; UNC Python aliases are accepted using the PowerShell drive mapping, with CIM and SMB mapping fallbacks when the first provider is unavailable. Runtime checks still verify shared paths before execution.

Downloads may first pass through Edge's configured Downloads location, including a redirected UNC directory. The orchestrator inspects that setting, captures the actual event and retains the approved artifact in S: Discoveries storage before claiming delivery. Download verification accepts both direct and redirected filesystem paths; S: and its live UNC alias identify the same directory. ZIP retention, inspection, extraction, package outputs and knowledge read/write use the resolved shared identity. ZIP extraction stays within that storage. This does not assume that any ordinary VDI local directory will survive logoff.

Edge profiles are per user and VDI machine. Sessions have independent UUID directories and new topics use independent Copilot UI chats. The authenticated user completes sign-in/MFA. Existing managed-browser settings are respected; the agent never changes download security or authentication controls to make a test pass.

The private S: drive and shared Python installation cannot be exercised on the current development machine. Automated checks use isolated temporary paths and validate that the default knowledge root follows the project under a simulated mapped S: share. Actual VDI mapping, write permission and deployment still require target-environment confirmation.

Atomic approval previews and other retained JSON records use extended Windows filesystem paths internally, including extended UNC spelling, so hashed filenames and temporary-write suffixes do not depend on the VDI enabling legacy long-path support. The operator-visible destination and S: storage boundary remain unchanged.
<!-- END SOURCE: docs/SHARED_VDI.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/TEST_REPORT.md -->
## Source: `docs/TEST_REPORT.md` (verbatim text; line endings normalized to LF)

# Test evidence — 6 October 2026

The setup update and original release evidence are recorded below. Earlier failed reports are preserved; they are never relabelled as passed. Evidence files stay in the operator's selected OneDrive and are excluded from the source release.

## Approved local Python and terminal update

The current complete automated suite ran **320 tests: 319 passed, one skipped, zero failures or errors**. New coverage executes the real bounded local-Python worker for declared imports/argv/scoped files, immutable runtime hashing, undeclared-access rejection, failure, timeout, asynchronous cancellation, retained audit receipts and owned-process termination. It also covers changed-plan hashes, managed persistent cleanup, coloured/plain terminal rendering, malformed/incomplete preview handling, and mocked independent verification of three visible viewer windows on display 2 with failure cleanup.

This is automated development evidence, not a live three-display result. No physical-display capture or real viewer placement was performed during this implementation turn. A target Windows workstation must still complete the steps in `VISUAL_ACCEPTANCE.md`; fewer than three displays, a locked/noninteractive desktop, missing Tk/GDI access or organizational policy must be reported as blocked rather than bypassed.

## Existing environment without pip

An isolated full Setup run started from a real Python environment created without pip while the selected base Python had working pip. Setup found the base pip, retained the original environment and its marker file, rebuilt the environment, verified pip, installed all four pinned packages, and completed OneDrive and Edge setup. A second full run selected the pip-less project environment itself; Setup resolved its reported base executable before moving it, then completed the same recovery. Both runs used a local wheelhouse and a development-drive fixture, not the private S-drive VDI. The original files and both recovered environments remain in the ignored pip-recovery fixture. The complete suite ran 287 tests: 286 passed and one skipped for unavailable Windows symlink privilege. Retained evidence: workspace/user-storage/workspace/pip-recovery-20261006/report.json.

## Mapped S-drive and UNC runtime aliases

The launcher now validates live running-executable, base-executable, base-prefix, standard-library and pinned-package paths against the current mapped S: share. Synthetic mapping tests accept matching UNC aliases, including extended UNC paths, and reject unrelated shares, share-name prefix collisions, unavailable mappings and paths that resolve outside the share. Existing environment prefix validation uses directory identity with canonical-path fallback. The complete suite ran 284 tests: 283 passed, one skipped for unavailable Windows symlink privilege. The private production S: mapping is unavailable on this development machine; these mapping cases were validated with controlled filesystem-resolution fixtures, not claimed as a live VDI result.

## Portable Python without venv or pip

The official Windows Python 3.14.2 embedded distribution was verified to lack both `venv` and `pip`. Using that unmodified interpreter, isolated Setup completed environment creation with the bundled virtualenv zipapp, offline pip seeding, installation of all four pinned packages, runtime verification, OneDrive/Edge resource selection, and saving the new environment interpreter. A second real Setup started with an incomplete `.venv`, preserved its original file in `.venv-incomplete-*`, then completed the same installation and application setup. No administrator installation was used. The four pinned versions and archived file were checked after setup. The complete automated suite ran **278 tests: 277 passed, one skipped**; the skip is unavailable Windows symlink privilege. PowerShell syntax and zipapp SHA-256 checks passed.

Retained evidence: `workspace/user-storage/workspace/portable-python-setup-20261006/report.json` and its isolated fixture. The package installation used a local wheelhouse obtained from the package index, so this proves setup behavior without base `venv`/`pip` and without live index access during setup. Private S-drive write permissions, organizational package-index access and production VDI Edge remain environment-specific.

## Setup update — automatic or pasted resources and dependency installation

The updated full suite ran **275 tests: 274 passed, one skipped, zero failures or errors**, in 38.186 seconds. The skip remains unavailable Windows symlink privilege. All 55 Python sources parsed; PowerShell syntax validation passed. Nineteen launcher checks include actual native PowerShell/Python invocation, automatic/manual path choices, environment creation/reuse, pip redirect rejection and failure propagation. Nine resource-selection checks cover registered OneDrive paths, Edge executable/folder choices, fallback, remembered per-machine settings and setup-only persistence without launching a browser.

Actual isolated setup acceptance passed all three cases: fresh `.venv` creation and installation of all four pinned packages; automatic reuse with saved settings; deliberately unavailable packages stopping setup before the application starts, with partial environment files retained. The first case used manually selected Python, OneDrive and Edge paths and verified that the saved interpreter is the newly created virtual environment. Versions verified: Playwright 1.55.0, greenlet 3.5.6, pyee 13.0.1 and typing_extensions 4.16.0.

Retained evidence: `workspace/user-storage/workspace/setup-acceptance-4990fc793064480cbb6003622bbc8009/report.json` and the case-specific stdout/stderr. This was real venv/pip/application setup in an isolated development fixture inside Valcer Strategies OneDrive. Only account-metadata discovery and scripted launcher input were injected in copied source to avoid organizational accounts and console input buffering. No browser was launched. This does not establish private S-drive/VDI deployment or its network/write permissions. Earlier attempts exposed and fixed OneDrive CLOUD metadata handling and PowerShell's scalar argument splatting; their failed reports remain retained.

## Original release environment and automated checks

Windows, Python 3.14.2, Edge 154.0.4258.53 and Playwright 1.55.0. The release suite ran **255 tests: 254 passed, 1 skipped, zero failures or errors**, in 23.682 seconds. The skip is unavailable Windows symlink creation privilege. All 53 Python source files parsed successfully. Dependency consistency, CLI help and PowerShell launcher syntax checks passed.

Retained evidence: `workspace/user-storage/runtime/automated-tests-release.json` and `.txt`. These are synthetic offline tests, not evidence of private VDI deployment. Coverage includes strict response validation, malformed-output rejection, replay and uncertain-send handling, immutable source/plan/upload approval, source hashing and byte identity, bounded resource use, path and credential protections, session isolation, findings counting, eight-file guidance integrity, attachment limits, download gates, create-only ZIP extraction, OneDrive storage and shared-runtime checks.

## Current visible acceptance

All live submissions used harmless synthetic content in the actual authenticated Microsoft 365 Copilot UI, through the authorized dedicated Edge profile. The model was the observed available **GPT-6 Sol**. No reasoning API, organizational Created-folder access or authentication bypass was used. The exhausted GPT-6.1 allowance and Auto fallback were detected in an earlier run rather than silently accepted.

| Retained report | Observed result |
|---|---|
| `workspace/user-storage/runtime/acceptance/new-session-20261006T160732Z-d69875/report.json` | Two different actual Copilot chats and local session IDs. Both initialized on the first response with eight attachments. Fresh context, findings, counter, grants and attachment queue; real no-tool answer and `system.versions`; clean owned-page exit. Twenty public reply/plan preview events, nineteen during generation, with attributed tool feedback. |
| `workspace/user-storage/runtime/acceptance/attachments-20261006T161019Z-5af311f9/report.json` | First-response eight-document initialization, followed by two actual approved user-file uploads. Copilot read file-only sentinels from text and staged code. Original and staged bytes matched; no tool execution. The native picker backend was injected for this test; an interactive Windows dialog was not exercised live. |
| `workspace/user-storage/runtime/acceptance/delivery-20261006T161212Z-f26c79/report.json` | All three delivery cases passed: a direct text download, a two-file coding ZIP, and an outer ZIP containing one Excel workbook. Actual browser download events, readable retained OneDrive files and hashes; approved create-only extraction inside OneDrive. Twelve confirmed submissions, including the findings upload at message 10. No delivered code was executed. |
| `workspace/user-storage/runtime/acceptance/download-run-20261006T162653Z-66b212b6/report.json` | Direct `.py` download and the explicitly approved exact local execution succeeded. The overall report remains **blocked** because a delivery-intent classification bug caused unnecessary retries after execution. Its original records remain unchanged. |
| `workspace/user-storage/runtime/acceptance/completed-run-recovery-20261006T164504Z-b4f546c0/report.json` | A fresh actual Copilot chat received a compact locally verified execution receipt and completed the factual stdout/exit/interpreter report. All tool execution was blocked. No second execution or grant reuse; original source and blocked-report hashes remained unchanged. |

The eight physical startup files preserve all ten original guidance/schema/catalogue components byte for byte. Six Markdown files remain separate; two pairs are grouped with full component hashes and offsets. Current initialization also includes the exact response shape. First-response startup succeeded in six fresh chats across these runs; this does not promise that every later response is valid.

The direct text case retained 14 UTF-8 bytes (`delivery-test` plus newline). The coding ZIP contained exactly `README.md` and `main.py`; contents were read and checked, with no execution. The workbook was structurally validated, hashed and independently inspected as ZIP/XML: worksheet A1 contains `delivery-test`. This is not Office rendering or complete semantic/macro validation.

Edge's actual Downloads setting was inspected before downloads. Completed browser artifacts were copied exclusively into the approved OneDrive delivery folder. The reports explicitly say that saving through the configured default Downloads directory was **not proven**, and the modern prompt-switch state was unknown. No Edge setting was changed. Save As interaction is covered with offline fixtures, not a live prompted download.

## Approved downloaded-script execution

The exact preserved download was 27 UTF-8 bytes:

```python
print('download-run-test')
```

SHA-256: `051193104ae2eb28123a6fc755653928f1b7340d862ce3388576b35f4bda95bd`. The user's actual **Approve this execution once** decision matched the immutable full proposal, source path/hash and nonce ledger. The raw source was checked before approval and immediately before execution. Observed stdout was `download-run-test\n`, stderr empty, exit 0; no created files, imports, subprocesses or network. The interpreter was the restricted `python_subset`, not host Python. The one-use grant was consumed, and recovery did not run the script again.

One malformed execution request required a real UI correction; no action was taken from invalid output. After the completed execution, the detector incorrectly treated `download` inside a filename as a new artifact request. A subsequent read-only recovery also exposed a negated request being misclassified. Both detector cases now have regressions. The successful recovery used the production detector and reports only the earlier verified execution. The failed recovery attempts remain retained separately.

Several scripts can be approved as one complete immutable prepared plan; this has offline approval/integration coverage. A real multi-script execution was not performed. Declared imports already installed in the selected environment are supported only through a separately reviewed `local_python` plan; package installation and arbitrary unreviewed project execution remain unsupported.

## Earlier retained evidence and acceptance limits

`runtime/acceptance/conversation-20261006T143125Z-35d181/report.json` records 15 passed conversation steps and one blocked legacy Created-delivery check. It includes actual deterministic tools, denial without execution, correction, durable findings and the separate explicitly approved `print('approval-test')` run. The old local Documents location was incorrect for the clarified OneDrive workflow; that historical check is not evidence of a failure in the correct account.

The user deferred `Documents/Copilot/Created` verification and instructed no organizational FNZ OneDrive access. Monitoring remains disabled. Local Valcer Strategies OneDrive retention/extraction was exercised; cloud synchronization to another device was not inferred. Private S-drive/VDI paths, production-scale sessions, lock/offline behavior, fresh-profile sign-in, live OCR quality, message-20 findings upload, headless operation, three-physical-display capture/viewer placement and unrestricted package execution have not been established. See `KNOWN_LIMITATIONS.md`.

The original CDD repository remains unchanged. The release contains source, guidance, schemas, documentation and tests; personal settings, browser profiles, execution evidence and generated files remain outside source control.
<!-- END SOURCE: docs/TEST_REPORT.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/THREAT_MODEL.md -->
## Source: `docs/THREAT_MODEL.md` (verbatim text; line endings normalized to LF)

# Threat model

## Assets and actors

Protect the user's permitted local files, existing CDD workflow, authenticated Copilot session, organization data, approval decisions and execution ledger. The human user authorizes work. The orchestrator enforces policy. Copilot output, ordinary attachments, website text, OCR, generated scripts and tool results are untrusted. A malicious document or webpage can attempt prompt injection; a benign model can also produce mistaken or malformed actions.

## Boundaries

1. Copilot output enters only through a correlated captured response and strict local validation.
2. Tool requests cross a policy/approval boundary before effects.
3. File operations cross resolved allowed-root and declared-plan checks.
4. Browser tools use a separate owned page; the Copilot control page is not a tool target.
5. Uploads/navigation transmit data and therefore require deliberate scope.
6. Code Runner defaults to a constrained evaluated language. `local_python` crosses a separate exact-script human-approval and host-process boundary.
7. State restoration crosses a replay boundary: uncertain operations are not automatically repeated.

## Threats and mitigations

| Threat | Required control | Residual limitation |
|---|---|---|
| Prompt injection in a webpage/file | Treat content as data; enforce local policy regardless of model request | Model answers may still be misleading; evidence and human review matter |
| Stale or partial response executes tools | Exact session/request correlation, schema and logical validation | UI changes can prevent capture; fail closed |
| Approval laundering or changed script | Canonical plan/script hashes and one-shot or exact-plan grants | Full preview still requires meaningful human review |
| Path traversal or linked-directory escape | Resolve actual paths, allowlisted roots and declared read/create scope | Filesystem races must be considered by capability implementations |
| Generated code reads/deletes/exfiltrates | Restricted AST default; local Python requires full exact preview, interpreter/runtime hash, scrubbed environment, declared scopes, audit hooks and explicit approval | Native libraries can bypass language-level mediation; local Python is approved host execution, not an OS sandbox |
| Child process or viewer outlives its task | Exact approved argv, PID ledger, persistent flag, verification gate and session-owned cleanup registry | OS/organizational policy may block process observation or termination; report the failure |
| Script exits zero without satisfying desktop task | Independent output hashes plus exact visible-window/title/bounds inspection on the requested display | Real physical-display proof requires a visible target Windows session, not mocks |
| Replayed side effect after crash/retry | Persist intent/outcome, immutable call hashes, reject uncertain replay | Manual reconciliation may be necessary |
| Browser action performs unexpected mutation | Separate tool tab, destination policy, classified actions and approval | Website behavior can change; clicks cannot be called inherently harmless |
| Debugging port exposes authenticated browser | Dedicated profile/session, loopback-only debugging, bounded connection | Other processes running as the same user remain outside this application's protection |
| Secrets leak through context/logs/screenshots | Minimize, redact, scope files, keep diagnostics local | Automated redaction is imperfect; do not use sensitive content for tests |
| Fake synchronized-file success | Baseline, bounded polling, stable/readable local content checks | OneDrive/organizational delivery may be unavailable |
| Resource exhaustion/endless conversation | Finite turn/retry/step/output/time limits | Legitimate large tasks may need a new reviewed scope |

## Code Runner security claims

Every approved execution must match exact reviewed bytes and its complete plan. In `python_subset`, supported expressions/statements and file capabilities are a whitelist; imports, reflection, subprocesses, arbitrary attributes, unmediated file access, network and deletion are unavailable.

`local_python` deliberately executes approved host Python when the subset cannot do the job. Its grant additionally binds interpreter identity/hash, fixed worker files, argv, direct imports, read/create/modify paths, canonical HTTPS hosts, exact subprocess vectors, desktop effects, limits and postconditions. Static checks reject dynamic code/import helpers, credential/registry modules and undeclared imports. The worker adds a scrubbed environment, Python audit hooks, exact `Popen` mediation, output/time bounds, cancellation and owned-process cleanup. These are defense-in-depth controls: native extension code and desktop APIs are not contained by a Python audit hook. Meaningful exact human review and least privilege remain mandatory. Never claim Windows Sandbox, low-integrity or privilege isolation.

A conversational statement such as “approve runs” is not authorization. Approval is obtained after the exact script and scope are displayed. A plan decision covers only the complete prepared scripts already displayed. Any material change produces a different immutable hash and requires a new decision.

## No-deletion and overwrite rules

Runtime tools, cleanup, tests and recovery must never delete files. Mutable state uses preserved versions and atomic replacement where appropriate. User file overwrite requires explicit scope and preserved originals. Retained artifacts consume space; report disk limits rather than silently removing files.

## Verification obligations

Exercise malformed/stale protocol rejection, unsafe paths, unsupported syntax, scope changes, hashes, denial, changed-script reapproval, local-Python failures/timeouts/cancellation, output limits, persistent-process cleanup, three-window display verification, replay uncertainty, retry limits, secrets filtering, findings persistence and synchronization. Record real desktop/UI evidence separately from mocks. Controls are claims to validate against implementation, not assertions that documentation alone proves safety.

## Scope limits

This application cannot protect against a compromised operating system or other processes operating with the user's privileges. It cannot ensure Copilot always honors guidance or that Microsoft/OneDrive provides a requested capability. Local policy must remain authoritative even when the model is wrong. No authentication bypass, endpoint weakening or security-policy modification is a recovery strategy.
<!-- END SOURCE: docs/THREAT_MODEL.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/TOOL_CATALOGUE.md -->
## Source: `docs/TOOL_CATALOGUE.md` (verbatim text; line endings normalized to LF)

# Tool catalogue

The complete versioned machine-readable definitions are in `schemas/tool-catalogue-v1.json`; runtime setup regenerates the current catalogue from `ToolRegistry` and verifies its attachment hash. Each definition includes intended use, input/output schemas, preconditions, side effects, risk, approval, timeout, output limits, errors and examples.

| Family | Capabilities | Authorization |
|---|---|---|
| Files | List, existence, bounded text read, metadata, SHA-256 | Read-only within configured resolved roots |
| Files | Create, append, copy, mkdir | Displayed per-execution or immutable plan approval; create/copy never overwrite |
| System | Exact current Python executable/version, OS/package/browser versions, allowed-path disk capacity, current agent process | Read-only; no unrelated environment variables or credentials |
| Browser | URL/title, visible text, structured controls, errors and observed downloads | Read-only on an owned guarded tab in the verified Edge profile |
| Browser | Open/back/forward, click, fill, scroll, screenshots | Explicit approval; exact HTTPS domain policy covers redirects, resources and popups |
| Copilot delivery | Actual current-response artifact download after inspecting Edge settings; permanent verified configured-storage target | Immutable observed-artifact approval; strict HTTPS/native-blob binding |
| Archives | ZIP manifest and hash inspection | Read-only within permitted roots |
| Archives | Complete-manifest extraction and static output verification | Reviewed hash/destination approval; create-only inside configured storage; no code execution |
| Images | Supported local image queued for verified Copilot attachment/analysis | Approval bound to exact file hash; does not claim local OCR or guaranteed integrated availability |
| Created files | Baseline snapshot and stable/readable matching-output polling | Disabled until an exact path is explicitly configured/enabled; no access while disabled and no cloud-delivery assumption |
| Code Runner | Restricted default `python_subset`; or explicit `local_python` with declared imports, installed libraries, scoped files/HTTPS/processes/desktop effects, bounded runtime and independent output/window verification | Full immutable generated proposal review; user denial/once/exact displayed plan; no standing approval |

Ordinary browser tools cannot control the Copilot chat tab. Website tabs share its verified Edge profile and existing site logins; focus returns to Copilot after tool execution. Owned-tab WebSockets are blocked, and HTTP requests are filtered by the exact approved host policy. Service-worker traffic in an existing shared profile is not fully intercepted by page routes. Downloads need exact observed-source grants; other download events are canceled. Oversized private observations stay ephemeral with scoped follow-up references. Policies and verification failures are returned honestly.

Website capabilities include `browser.recon`, `browser.route`, `browser.plan`, `browser.tabs`, `browser.customer_summary`, `browser.documents` and `browser.download_batch`. `documents.catalogue/find/retrieve` keep large collections accessible; `files.transfer_to_copilot` ranks and queues relevant hash-bound files within the 20-total-file transport cap. `site_knowledge.bind/retrieve/query/save/invalidate/export` isolate optional approved navigation memory. `guidance.load` routes to concise workflow instructions. See [upgrade evidence](WEBSITE_UPGRADE_REPORT.md).

`python_subset` supports advertised basic builtins and `read_file`/`write_file`. It excludes imports, functions/classes, arbitrary attributes, reflection, host execution, shell/subprocess/network activity and deletion.

`local_python` is the separately approved mode for tasks the registered tools and subset cannot perform. Its proposal binds the current interpreter, exact script/argv/imports, read/create/modify scope, canonical HTTPS destinations, exact child vectors, desktop permissions/viewers, limits and expected effects. The worker applies a scrubbed environment, Python audit hooks, bounded asynchronous output, timeout/cancellation cleanup and retained audit records. Native libraries mean this is not an OS sandbox. The Windows desktop helper can enumerate displays, create separate PNG captures, launch managed viewers and independently verify exact visible titles/bounds on a target display.
<!-- END SOURCE: docs/TOOL_CATALOGUE.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/TROUBLESHOOTING.md -->
## Source: `docs/TROUBLESHOOTING.md` (verbatim text; line endings normalized to LF)

# Troubleshooting

Start with the session's structured events and current status. Keep diagnostic data local and inspect only relevant permitted content. Never delete files as remediation or bypass organization/security controls. Retry budgets are finite; an uncertain send or side effect requires reconciliation before repetition.

| Symptom | Safe investigation and response |
|---|---|
| Existing project environment reports No module named pip during Setup | Update the checkout and rerun Setup. Setup now probes the existing environment's pip before reuse, locates the selected base Python and its pip automatically, archives the old environment, rebuilds an isolated one, and verifies its pip before installing dependencies. The old files remain under a unique recovery directory. |
| Shared deployment requires the base executable on S: while reusing the environment | Update the checkout and rerun Setup. The launcher now checks whether a Python-reported UNC path resolves beneath the mapped S: share and checks the existing environment by directory identity. If it still stops, inspect the reported live runtime paths in the error and the current S: mapping; a configuration-file path alone is insufficient. Existing environment files are retained. |
| Edge does not start or CDP connection fails | Confirm configured Edge executable, dedicated profile and loopback port. Check the recorded launch/connection error. Do not attach an unrelated personal browser silently. |
| `No module named venv` or `No module named pip` in portable Python | Rerun Setup with this version of the repository. The bundled, checksum-verified `virtualenv.pyz` creates the project environment and seeds pip without either base module. Setup preserves an incomplete old `.venv` before retrying. The configured package index is still required for pinned application packages. |
| Copilot asks for sign-in | Sign in manually in the visible window. Do not extract browser cookies, credentials or tokens. |
| Model cannot be discovered/selected | Capture displayed names and actual UI state. Check isolated adapter selectors and permissions. Do not assume an example model exists. |
| Copilot reports daily access exhausted and switches to Auto | The selected model is unavailable. The app stops rather than silently accepting another model or sending format corrections. Start fresh setup, select an actually available model, or wait for the account allowance to return. |
| Headless/non-visible mode fails | Use tested visible operation. Authentication, file picker or download limitations must be reported, not bypassed. |
| Guidance or other file upload fails | Verify exact path, existence, size/type and policy. Inspect UI upload confirmation/error. A local existing file is not proof of upload. |
| Generation times out | Inspect new assistant container, streaming/stop state, text stability and error banners. Retain sanitized evidence. Do not use a long fixed sleep as proof of completion. |
| Submission may have succeeded | Reconcile submitted user-message containers/request identity. Do not blindly send again or roll back the count. |
| Envelope/JSON/schema validation fails | Preserve raw response; inspect classified errors. Allow only meaning-preserving extraction of one complete envelope, then bounded correction. Execute nothing from invalid content. |
| Tool name/version/input rejected | Compare with the current machine catalogue and schema. Ask Copilot to correct the same decision without expanding scope. |
| File path denied | Verify configured allowed roots, resolved path and declared plan. Do not extend access merely to make a request pass. |
| Code Runner rejects ordinary Python | Confirm `language`. `python_subset` intentionally rejects imports and ordinary host features. Use `local_python` only through a fresh complete proposal containing the exact interpreter from `system.versions`, argv, imports, file/network/process/desktop scope, limits and effects. Shell strings, dynamic code, credentials and deletion remain unavailable. |
| Local Python plan is rejected before approval | Compare every field with the current catalogue. Create targets must be new with existing parents; read/modify targets must exist; direct imports must be declared; HTTPS hosts and managed child argv must be exact; requested capabilities need matching permissions. Do not broaden scope silently. |
| Local Python times out or is cancelled | Inspect the retained `audit_path`, stdout/stderr, cleanup records and any readable outputs. Owned nonpersistent children and failed viewers should be stopped. Do not replay a possibly state-changing script until its outcome is reconciled and a fresh plan is approved. |
| Three-display capture/viewers are incomplete | Check the returned physical display enumeration, per-PNG hashes, viewer process records and independent visible-window bounds. An unlocked visible Windows desktop with three displays and working GDI/Tk is required. Report organizational or desktop restrictions; do not bypass them or claim success from exit code alone. |
| Approval rejected or changed hash | Display a fresh complete immutable proposal and obtain new authorization when appropriate. Denial is final for that proposed execution; it is not an automatic retry failure. |
| Tool effect is uncertain after interruption | Inspect safe local evidence and intent/outcome records. Seek user review before repeating a write/click/script. |
| Findings seem absent | Check response validity, entry schema/provenance, privacy filtering and deduplication. Findings save immediately; their cumulative file is attached every tenth submitted message. |
| Counter differs from visible expectations | Count confirmed submitted user messages, including initialization/corrections/tool results. Do not count assistant responses, uploads, local approvals or polling. Inspect the persisted submission ledger. |
| Created monitoring says disabled | Configure an absolute `created_dir` path and enable `created_sync_enabled` explicitly. The application does not discover OneDrive folders. |
| Created file never appears locally after enabling | Check the explicitly configured path, actual available creation capability and organizational delivery status. A preview is insufficient; bounded timeout is reported honestly. |
| Live reply preview appears before validation | Expected: it is attributed to Copilot and marked unvalidated. Only a complete validated envelope can dispatch actions. |
| Public text arrives in groups | The Copilot UI may buffer code-editor rendering. Field previews emit when readable; visible generation/status feedback continues. No hidden reasoning is requested. |
| Several synchronized files match | Request explicit disambiguation. Do not select arbitrarily or generate another duplicate file. |
| Session restart has pending work | Restore authoritative state and inspect uncertain intents. Do not treat old approvals or responses as fresh authority. A new chat must receive guidance/schema/catalogue again. |
| Retained artifacts consume disk space | Report disk usage and applicable scope. This application has no automatic deletion cleanup. |

## Reporting an issue

Provide the affected step, expected and observed behavior, session/request/call IDs, classified error, relevant version/configuration, sanitized log excerpt and local evidence paths. Do not paste credentials, cookies, full unrelated documents or sensitive screenshots. State whether the operation definitely failed, succeeded, or remains uncertain.

## Evidence limitations

A mocked test proves only the simulated path. A process exit code proves neither file delivery nor UI acceptance. Local synchronization requires a stable/readable matching file; real browser acceptance requires observed authorized UI behavior. Keep blocked and unexecuted steps explicit in the evidence report.
<!-- END SOURCE: docs/TROUBLESHOOTING.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/VISUAL_ACCEPTANCE.md -->
## Source: `docs/VISUAL_ACCEPTANCE.md` (verbatim text; line endings normalized to LF)

# Visible end-to-end acceptance

Use a real authorized Copilot Chat session, a visible dedicated Edge window and synthetic content. Do not bypass authentication, upload restrictions or organizational controls. This checklist is not test evidence until completed with observed results. Retain all synthetic artifacts; do not delete them.

## Evidence record

For each step record UTC timestamp, submitted-message ordinal where applicable, expected result, observed result, artifact/screenshot/log path and status: passed, failed, blocked or not run. Redact unnecessary user/organization data. Keep screenshots and small diagnostic DOM excerpts local. Automated/mock results must be labeled separately.

## Setup and capture

- Start the application and observe a dedicated visible Edge debugging session with loopback-only connection.
- Verify Playwright connects and Copilot Chat opens. Perform manual sign-in if prompted.
- Discover model names exactly as displayed. Record ranking/default rationale and verify the selected model's actual UI state.
- Verify startup contains exactly eight reference files: guidance 01–06 as six unchanged originals, `07-08-complete-guidance.md`, and `protocol-schema-and-tool-catalogue.md`. Recover all six grouped components using their recorded offsets and verify all twelve originals' exact bytes, lengths and SHA-256, including both automation package schemas. Confirm BOM, line-ending and final-newline preservation with synthetic fixtures.
- Observe exactly eight initial reference uploads containing those complete components. Record upload confirmation rather than inferring it from local file existence. Record the ten-to-eight physical slot change (20%), now preserving twelve source components in eight files separately from model-quality claims.
- Inspect the initialization message for the direct complete required JSON response shape and strict envelope instructions alongside the full attached schema and catalogue.
- Observe insertion/submission of the initial compact message, generation start, completion signals and one newly correlated assistant envelope.
- Record parsed session/request identity and successful schema validation.
- Change an original reference component or either completed group in an isolated synthetic test and verify the next send is refused. Verify all eight physical attachment hashes are checked as well as the twelve original component hashes. Do not alter the real live session's approved references to perform this check.

## Conversation and tools

- Request a harmless no-tool answer; verify final response and nonempty action plan.
- Request permitted read-only inspection of a synthetic project file; observe a valid tool request, local evidence returned to Copilot and a final answer grounded in that result.
- Request a constrained Code Runner script producing a uniquely named synthetic output. Choose deny. Verify the script did not run and the expected output was not created.
- Make a new independently reviewed request. Inspect full script/plan, hashes and declared scope; approve this execution only. Verify the exact approved script executed and expected local content exists.
- Change the script or scope and verify the earlier grant cannot authorize the changed execution.
- Request a harmless `local_python` task that genuinely needs an import. Confirm the full exact script, current interpreter/hash, argv, imports, file scope, permissions, timeout/output limits and expected effects appear before approval. Deny it and verify no process/output; propose it again and approve only the exact execution. Change one byte or argument and verify a fresh decision is required.
- Exercise a failing local script, a timeout and interactive cancellation. Verify the result distinguishes failed/cancelled states, stdout/stderr are bounded, an audit receipt is retained, owned child processes are stopped and existing files are not deleted.
- Exercise a harmless managed persistent child, then close the session. Verify its PID is registered while approved and stopped during session cleanup. Do not use an unrelated process as the fixture.
- On a workstation with at least three attached active displays, ask Copilot to enumerate them, capture each physical display separately to three new approved PNGs and declare three uniquely titled persistent viewers on Windows display 2. Verify all PNG sizes/SHA-256 values, three managed viewer PIDs, and independent window evidence showing all three exact titles visible with final bounds contained on display 2. Record the display enumeration and retained audit path. If the desktop, third display, GDI, Tk or organization policy blocks the task, mark it blocked; a script exit is not a pass.
- Exit or start a new session after the display test and verify all managed viewer processes close. The PNGs and audit evidence remain retained.
- Exercise the explicit invalid-format/correction test mechanism. Preserve the invalid output, observe validation errors and a bounded correction, and verify no action executed from invalid content.
- Observe a second user turn after task completion; confirm the continuous loop remains available.
- Use `:new` to start an independent topic. Verify a different Copilot conversation URL and local session ID, repeated guidance initialization, fresh counter and exclusion of prior requirements, findings, queued attachments and approvals. Confirm the previous session files remain.

## Findings and counting

- Include an evidence-supported synthetic finding before the first tenth-message boundary. Verify immediate accepted storage and readable cumulative Markdown update.
- Repeat an unchanged finding and verify no duplicate accepted entry.
- Track confirmed submitted message ordinals; include initialization, tool results and corrections, excluding assistant responses, uploads and polling.
- At ordinals 10 and 20 observe upload of the current cumulative findings snapshot before submission. Verify ordinary non-boundary messages do not trigger that cadence upload.
- Verify findings produced in a boundary response save immediately and appear in the next applicable snapshot.

## User attachments

- Choose **Attach files** or enter `:attach`. Observe the native Windows picker and select harmless files from configured local roots, including S: or a OneDrive path only when explicitly selected. Verify `:files` lists exactly the intended pending entries.
- Test advanced `:attach <path>` with an explicitly selected synthetic S-drive file when that drive is available. Verify this does not expand local file-tool roots. If S: is unavailable, record this step as not run.
- Use `:remove <number>` and `:clear`. Verify only pending entries change and every source file remains intact.
- Submit a request with pending files. Inspect filenames, sizes and SHA-256 in the approval preview, choose **1: deny**, and verify no upload/send executes and the queue remains. Review again and choose **2: once**; exercise **3: plan** only for the exact displayed scope in a separate reviewed test.
- Verify a harmless `.py` source is uploaded as its original filename plus `.txt`. Compare the staged and original bytes and hashes, including synthetic BOM/CRLF/no-final-newline cases, and verify no code executed.
- Change a selected source after queuing in a retained synthetic fixture. Verify sending is refused until that entry is removed and selected again for review.
- Select a ZIP archive and a ZIP renamed to a supported non-Office extension. Verify both are denied without upload. Separately verify a structurally valid synthetic native Office document is treated as that document type.
- Queue 20 distinct supported synthetic user files; verify a 21st is refused by both terminal and workspace upload paths. The final send guard independently checks user files plus startup references and any due automatic context against the 20-file Copilot ceiling. Record any actual UI limit rejection separately. These tests concern per-message limits, not a cumulative chat limit.
- After an approved upload, verify the browser confirms the exact intended filenames before submission. A picker selection or staged file alone is insufficient evidence.
- Start `:new` and confirm an empty pending queue, new session identity and retained prior source/session files.

## Files and synchronization

- Complete the user-attachment checks above before relying on uploaded content.
- Inspect the actual Edge download settings without changing them. Request a single harmless non-Office file with an explicit downloadable link, then request a complete coding package and a single Office document as downloadable ZIPs. Plaintext and sandbox references require bounded conversational correction; ZIP is the single-file fallback.
- Observe the actual browser download event and approved permanent OneDrive copy. Record the suggested name, byte count, readability and hash. Distinguish this from proof of a default Downloads-directory save or a user-controlled Save As prompt.
- Inspect each ZIP before approving create-only extraction to a new directory inside configured user storage. Verify every expected file, content/structure and hash; retain the original archive. Download and extraction never authorize code execution.
- Separately request one source-bound downloaded `.py` execution that fits `python_subset`. Review the exact immutable bytes, source hash, read permissions and full scope; obtain explicit user approval. Verify stdout, stderr, exit code and expected outputs, and return the result through the real UI. In a distinct test, a downloaded script may use `local_python` only after a new exact host-execution proposal and approval; delivery/extraction never grants execution.
- Exercise read-only reporting of a completed execution without creating or downloading another artifact. Verify no execution is repeated and no delivery retry is triggered by filenames or negated requests.
- Created-folder monitoring is optional and deferred by the user. Leave it disabled during the current acceptance; do not access the organizational FNZ OneDrive. Only after explicit enablement in the intended deployment, request a synthetic Created output and observe bounded polling of the configured OneDrive `Documents\Copilot\Created` directory. Verify stable readable matching bytes before claiming synchronization success. A cloud preview does not establish that optional local synchronization.

## Exit and delivery

- Exit through the supported user command. Verify session state was preserved, pending uncertainty was recorded, all managed persistent processes/viewers were stopped, and the owned browser/session closed cleanly according to configured lifecycle.
- Review retained synthetic files, sanitized logs and screenshots. Verify no files were deleted and no existing CDD workflow files were modified.
- Report total passed/failed/blocked/not-run steps, automation results separately, limitations and any required follow-up. Full acceptance cannot be claimed while required visible steps remain unexecuted or blocked.

## Recorded GOV.UK package proof

The scoped final local GOV.UK package proof passed on 2026-10-13 using exact Edge port 63741 and the explicit C: test store. It verified five fresh owned tabs, overlapping reconnaissance, navigation knowledge save/readback, and final ZIP delivery. See [the acceptance report](LIVE_GOVUK_PACKAGE_ACCEPTANCE_20261013.md) for independent hash verification and measured timings. Real S:/VDI operation was outside this local proof's scope.
<!-- END SOURCE: docs/VISUAL_ACCEPTANCE.md -->


---

<!-- BEGIN VERBATIM SOURCE: docs/WEBSITE_UPGRADE_REPORT.md -->
## Source: `docs/WEBSITE_UPGRADE_REPORT.md` (verbatim text; line endings normalized to LF)

# Website capability upgrade evidence

Engineering report, 7 October 2026. Live production websites and Copilot delivery were not exercised by these synthetic tests.

1. **Repository understanding.** Refreshed the Graphify handoff before implementation. Entry points remain Launcher/app -> Orchestrator -> visible Copilot BrowserAdapter. Strict marker-delimited responses, immutable local approvals, isolated Playwright website context, attachment staging, delivery checks and no-delete policy remain the execution foundation.
2. **Architecture.** Added bounded semantic navigation, a document pipeline, session document catalogues, consent-controlled site knowledge and private audit helpers. Extended the existing registry/adapter instead of introducing another browser or reasoning service. No new dependency.
3. **Tools.** The runtime catalogue has 53 tools. New capabilities: browser.recon/route/plan/tabs/customer_summary/documents/download_batch; files.transfer_to_copilot; documents.catalogue/find/retrieve; site_knowledge.bind/retrieve/query/save/invalidate/export; guidance.load. Input schemas, examples, versions, approvals and timeouts are registered. Plan operations include conditional branches, bounded loops, semantic fallback, assertions, captures and controlled tabs.
4. **Guidance.** Ten routed guides in guidance/website cover reconnaissance, plans, customers, documents, tabs, memory, recovery, privacy and tests. Three core startup guides, attachment/delivery documentation and tool documentation describe the new contracts. guidance.load retrieves up to three topics; the original eight physical startup attachments remain intact.
5. **Local orchestration.** Shared tickets/catalogues/queues survive cloned call contexts. Exact file hashes are checked before transfer and again before staging. Queues drain only at observed submission commit, never merely on upload preparation. Completed-transfer hashes prevent redundant delivery. UI Stop reaches the shared cancellation event. Failed verification returns failure and preserves known partials.
6. **Website learning.** One snapshot captures bounded visible semantics, headings, navigation, forms, tables, document routes, frames, modals, open shadow roots and meaningful state. Task-ranked maps record sources, confidence and freshness. Query/hash changes invalidate route knowledge. Maps, plans and customer observations remain ephemeral; restart requires fresh observations and reconciliation.
7. **Privacy and consent.** Reusable knowledge is separately namespaced by exact origin, declared tenant/user/environment and schema version. Local approval binds categories, scope, sanitized payload hash, expiry and storage at %LOCALAPPDATA%/CopilotLocalAgent/site-knowledge. Decline performs no save and leaves current-task tools usable. Customer IDs/names/values/query strings/tokens are rejected. Private session/event/approval/response records contain operational hashes; private context overflow and diagnostics do not persist raw customer text or screenshots. Website task findings cannot bypass save consent. Historical records predating this mode are unchanged. Declared namespaces do not prove the site's authenticated identity.
8. **Recovery.** Semantic locators require unique matches. Identity is reverified across customer transitions; ambiguous results require a user choice. Auth expiry, denial, CAPTCHA, rate limits and server failures stop effects. Consequential controls have a distinct exact local confirmation boundary, including semantic detection of mislabeled controls. Uncertain effects cannot resume automatically. Safe approved resets clear prior customer/task state; approved new-site navigation clears old origin guards. Downloads preserve failed/partial artifacts and require matching source scope, manifest provenance and hashes for same-session resume.
9. **Tests.** Baseline: 354 tests, one existing skip, passed. An intermediate complete run of 441 tests exposed three existing assertions expecting raw diagnostic logs; those were updated to verify correlated private evidence. Final regression partition: 423 tests passed, one existing skip, 73.221 seconds. All 24 navigation/schema scenarios have passing evidence across the main and targeted real-browser runs. Six combined Edge fixture scenarios passed; the latest four critical integration scenarios passed in 54.920 seconds. All 17 agent_ui tests passed. Document/catalogue tests cover 21/50/100-file sets, mixed sizes, duplicates, metadata bundles, deferred retrieval, manifest import and later exact-reference retrieval. Compilation, all 53 catalogue definitions/examples, dependency consistency and diff checks passed. No lint/type-check configuration exists in this repository; Python compilation/schema validation are the configured checks.
10. **Baseline/final metrics.** On the same synthetic landing-to-previously-unknown-search route, existing tool sequence used 7 registered calls; reconnaissance plus a verified plan used 2: 71.43% fewer tool calls. Both reached the asserted destination. Latest measured durations: 2.3698 versus 2.3648 seconds; this single sample establishes no latency advantage. Browser version 154.0.4258.53. Local benchmark evidence is runtime/verification/unseen-site-benchmark.json. Live LLM message count, tokens and production throughput are unmeasured; prior tools already supported multi-call envelopes.
11. **Defects repaired.** Enum validation, hidden/textarea text leakage, stale query/hash maps, partial results falsely marked successful, uncertain-effect replay, cancelled checkpoint loss, old-origin route guards, unsafe raw approval/context/diagnostic persistence, cloned-context ticket loss, mixed customer/namespace batches, forged resume manifests and transfer-queue drain timing. Each repaired behavior has executable regression evidence.
12. **Limits.** Native browser temporary bytes can arrive before retained-byte quotas apply. Static signatures/checksums do not prove full rendering or malware safety. Closed shadow roots and unsupported document controls remain unavailable. Unusual navigation vocabulary may be rejected by conservative persistent-memory filters. External requests remain within approved hosts; there is no indiscriminate crawl or credential sharing. Cancellation stops future work/checkpoints and does not roll back already submitted effects.
13. **Repository completion.** Code, guidance, catalogue and refreshed graph artifacts are committed together. Runtime logs, synthetic downloaded artifacts and local memory stores are excluded. Exact commit/branch/push verification is supplied in the final user report.
14. **Exact rapid-learning evidence.** tests/test_web_navigation.py verifies one-snapshot semantic coverage and unseen static/SPA workflows, fallback, identity, interruption/resume and boundaries. tests/test_website_integration.py invokes the actual registered tools through real Edge on routed synthetic HTTPS fixtures, verifies native downloads and measures the 7-to-2 call reduction. tests/test_web_transport.py checks hash-bound orchestrator transfer with a controlled Copilot transport; it does not substitute for live UI acceptance.
15. **Outstanding acceptance.** Actual signed-in Copilot attachment/submission for the new document workflow and target-VDI website/authentication/performance acceptance remain unverified. Local download success and queued files are explicitly distinct from observed live Copilot delivery. No unfinished local implementation is represented as live acceptance.

The hard Copilot limit is **20 total files per message**. A document selection uses at most ten reserved slots, including an index when files are deferred. Collections up to 1,000 authorized local references stay searchable; download batches are bounded to thirty observed documents and concurrency of three. Exact duplicates are deduplicated; similar names only produce review warnings. ZIP upload remains unsupported; metadata indexes preserve individual paths/hashes and originals stay retrievable.

Browser downloads and semantic locator handling follow the existing pinned Playwright interfaces: [downloads](https://playwright.dev/python/docs/downloads), [locators](https://playwright.dev/python/docs/locators). These references inform implementation, not live deployment claims.
<!-- END SOURCE: docs/WEBSITE_UPGRADE_REPORT.md -->


---

<!-- BEGIN VERBATIM SOURCE: README.md -->
## Source: `README.md` (verbatim text; line endings normalized to LF)

# Copilot Local Agent

Public exploration now defaults to [Crawl4AI](https://github.com/unclecode/crawl4ai)
through `discovery.manifest`: continuous bounded parallel expansion, up to 1,000
pages, and reuse of saved unexplored routes. Update dependencies with `Setup.cmd`.
Read all saved routes through paginated `discovery.knowledge_lookup` in the shared
S:/UNC store. See [operation](docs/DISCOVERY_NAVIGATION.md) and the
[deep manifest example](docs/examples/deep-discovery.json). Existing approvals,
public-address checks and cancellation remain active.

A Windows/VDI repository with continuous conversation, Microsoft 365 Copilot web UI reasoning, strictly validated responses, controlled tools, explicit code approval, retained session state and Useful Findings. The original CDD workflow is preserved. No reasoning API is used.

Actionable failures create separate internal and sanitized reports with an explicit review step before external sharing. See [diagnostics and report handling](docs/DIAGNOSTICS.md).

The Copilot Chat project map and handoff files are kept in [Copilot handoff/full-discovery](Copilot%20handoff/full-discovery/README.md) and are included when this repository is pulled.

For the graphical workspace, run **Start Agent UI.cmd**; it asks whether to use the live repository or the Copilot testing environment. **Start Agent.cmd** remains the terminal fallback. The UI shares the same agent session and approval policies. See [the UI guide](agent_ui/README.md).

At normal agent startup, verified running Edge sessions are listed so you can reuse one or launch a new isolated Edge session. Reuse is the default when a verified session is available; if none is available, a new session starts without another prompt. The choice is requested on each startup; canceling stops startup, and a selected session that fails attachment verification falls back to a new isolated session. Explicit `--port` and `--attach-existing` options keep their direct targeting behavior, and `--resume` does not show the selector.

## Setup and run

**Start Agent.cmd** asks whether to run the live repository or a Copilot testing version. Drop replacements into **Copilot testing environment/Updated files/** using the original project-relative folders, then choose testing. Separate mirrored folders support identical filenames. Later deliveries accumulate in complete retained project copies. See [Copilot testing workflow](docs/COPILOT_TESTING.md). No Git or GitHub access is needed inside the VDI. Graphify excludes the testing environment.

Setup checks pip before reusing an existing project environment. If pip is missing or cannot start, it locates the selected installation's base Python and pip, preserves the old environment under a unique recovery name, recreates an isolated environment, and verifies its pip before installing project packages. This requires no manual pip path or separate repair command.

Put the repository on the shared **S:** drive alongside the organisation's Python installation. Double-click **Setup.cmd**, choose **1: Automatic detection** or **2: Paste a path**, and select Python. You may paste the quoted full `python.exe` path or its installation folder. Setup creates or reuses the project's `.venv` and installs the pinned packages from `requirements.lock.txt`; then use **Start Agent.cmd**. On S:, the base Python and virtual environment remain shared on S:. No browser download is needed. See [SHARED_VDI.md](docs/SHARED_VDI.md).

The app stores ordinary per-user runtime data under local app data and does not discover or select OneDrive automatically. Supply an absolute `storage_dir` in an explicit config when you want session/runtime files in another location, including OneDrive. Edge setup offers detection or a pasted `msedge.exe` path; the executable choice is remembered per machine in configured user storage. **Start Agent.cmd** reuses valid saved resources. Rerun **Setup.cmd** to review Python and Edge choices. Dependencies need network access to the organization's configured package index and permission to create/update the project environment; errors show the complete Python diagnostic. Setup uses the bundled, checksum-verified `virtualenv` archive to create `.venv`, including when the selected portable Python has neither `venv` nor `pip`. If an earlier setup left `.venv` incomplete, Setup preserves it under `.venv-incomplete-*` and creates a fresh environment.

The visible terminal shows setup, discovered exact model labels, short structured task/action/result/verification sections, full script approval previews and answers. System, Orchestrator, Copilot, User, Approval, Error and Tool labels use distinct coloured backgrounds when the terminal supports ANSI colour, with a clean plain-text fallback. Complete sign-in/MFA yourself in the dedicated Edge window. Select a displayed model or accept the documented suggested choice. Visible operation is the only accepted mode; headless Copilot operation is not established.

Use `:new` for a new topic in an independent session and fresh Copilot UI chat, or `:new <first message>` to start it immediately. Previous records are retained; user context, findings, counters, attachment queues and approvals start fresh. Ordinary application launches also create a new session unless `--resume` is explicit. Reconcile uncertain earlier submissions or state-changing calls before switching.

Use `:exit` to end the session and `:status` for counts and findings. Use **Attach files** or `:attach` to open the native Windows picker and select several files for your next message. Advanced users can enter `:attach <path>`. While a turn is running, type any message to steer that same goal; `/steer <text>` is also accepted. Use `/attach "C:\\path with spaces\\file.py"` (repeat quoted paths for multiple files) to add local files to the active run, or `/stop` to request cancellation. Terminal paths are still checked against the configured local roots and every upload remains subject to exact approval. Use `:files` to inspect the pending queue, `:remove <number>` to remove one pending entry, or `:clear` to clear it; these commands never delete source files. Up to **20 user files per message** can be queued, subject to Copilot's combined 20-file send ceiling. See [ATTACHMENTS.md](docs/ATTACHMENTS.md) for formats, approval and limits.

Tool/code approvals offer **1: deny, 2: once, 3: plan** for the exact displayed scope. Denying an upload leaves the pending queue available for review. `--yes-setup` and general willingness to approve do not grant execution permission. Code Runner keeps the restricted `python_subset` evaluator as its default. When registered tools and the subset cannot perform the requested task, Copilot may propose `local_python`; every exact script and complete execution scope is displayed and must receive an explicit decision before it runs.

## Configuration

Run the project from its S: checkout. Settings, sessions, profiles, downloads and knowledge use the `Discoveries knowledge` folder beside (one level above) the project root; S: is resolved to its live UNC filesystem identity before use. A configured C: or OneDrive `storage_dir` is redirected to that canonical S: location. File tools cannot write to C:; one run confirmation grants local reads and new-file/folder creation within Discoveries knowledge, while deletion or overwrite still requires separate confirmation. Copilot's own UI is controlled separately. Root expansion is a user configuration decision; Copilot cannot expand it.

Public operation reuse is an opt-in preview. Set `operation_reuse` to `true` only with `persistent_graph` enabled. An explicitly approved `operation.learn` call can derive one public JSON GET operation from two already-observed URLs and validate it with a third unseen input. Later `operation.call` requests use the existing pinned public-HTTPS transport without opening the browser or returning to Copilot UI. This path never accepts authentication material, cookies, headers, non-GET methods, private destinations or automatic writes. See [API Anything integration](docs/API_ANYTHING_INTEGRATION.md).

Generated files use actual Copilot download links: Office files and full coding packages are requested as ZIPs; single non-Office files use direct links with ZIP fallback. Edge download settings are inspected before delivery, and permanent artifacts plus ZIP extraction stay inside configured user storage (local app data by default). Original archives are retained, outputs are verified, and delivered code never runs automatically. See [FILE_DELIVERY.md](docs/FILE_DELIVERY.md).

You can separately request execution of a verified downloaded `.py` file through Code Runner. The proposal keeps `script` mandatory and binds paired `source_path`/`source_sha256` fields to that exact artifact; the source must also appear in declared reads with `read_files` permission. Raw UTF-8 bytes, including newline bytes, must match exactly and are checked before approval and execution. `local_python` additionally binds the current interpreter path/hash, argv, imports, read/create/modify paths, exact HTTPS destinations, exact managed child-process vectors, desktop permissions, persistent viewers, limits, expected effects and the fixed runner implementation. For several scripts, **3: plan** approves only the complete set already displayed; **2: once** approves one call. Any material change requires a fresh approval. Shell command strings, deletion, credential access, silent privilege escalation and hidden persistence remain unavailable. See [Code Runner security](guidance/04-code-runner-approval-security.md).

On a visible Windows desktop, an approved `local_python` script can use `copilot_agent.desktop` to enumerate physical displays and capture each one to a new PNG. Exact `viewer_windows` declarations launch managed persistent viewers, tile them on the approved display, and independently verify visible titles and final bounds. The run returns image size/hash evidence, window/display evidence and a retained audit receipt. Viewer processes are stopped on failed verification, cancellation or session close. A zero exit code alone never proves the desktop end condition.

Created-file synchronization stays disabled unless you explicitly configure `created_dir` and `created_sync_enabled`. A OneDrive path is inspected only when directly supplied in that configuration; the application does not discover OneDrive accounts or inspect Created folders automatically.

Advanced run: use the discovered shared Python executable with `-B app.py --config <settings-file>`. The source checkout remains separate from personal writable storage. Attach to a verified dedicated existing session using `--attach-existing --port <port> --profile <dedicated-profile-path>`. The port must belong to that exact Edge profile. Existing chats are not reused; the app owns a new chat tab and a separate tool tab. On exit those owned pages close and the existing browser/profile remain.

Resume: use that shared Python with `-B app.py --resume <your-local-runtime-session-path>`. A new chat receives the guidance again. Uncertain sends require explicit reconciliation, incomplete state-changing operations cannot silently replay, and execution grants are not inherited across restart.

## Guidance and memory

The terminal displays timestamped, attributed feedback throughout the run: `User`, `Copilot`, `Orchestrator`, `System`, `Approval`, `Error`, and `Tool/<name>`. Public reply fields are streamed as soon as the UI exposes complete values; live previews are visibly marked unvalidated and identical validated text is not printed twice. Reliable parsed responses appear as short task, action, result and verification sections. Long protocol fields and full results stay in retained logs; every proposed script still appears in full at approval. See [FEEDBACK.md](docs/FEEDBACK.md).

The eight behavioural Markdown files, response schema and current machine-readable tool catalogue are supplied once at initialization in **eight attachments**. Guidance 01–06 are uploaded unchanged as six separate files; `07-08-complete-guidance.md` contains the complete original guidance 07 and 08, and `protocol-schema-and-tool-catalogue.md` contains the full response schema and runtime catalogue. No guidance is summarized. All ten original components retain their exact bytes; grouped components have recorded names, versions, SHA-256 hashes, lengths and byte offsets. Every component hash and physical attachment hash is checked before every send. Initialization also directly supplies the complete required JSON response shape and envelope instructions. This reduces startup attachment slots from ten to eight (20%). Packaging integrity does not establish equivalent model quality; live protocol validation remains required. `guidance/09-testing-acceptance.md` governs local testing. Ordinary messages contain compact state and identifiers rather than repeated long contracts.

User uploads may come from individually selected files in configured local roots or on S:, after review of exact filenames and hashes. A OneDrive file can be attached when the user selects it or supplies its local path. This upload permission does not expand local file-tool roots. ZIP archives are never uploaded. Supported code files such as `script.py` are staged as `script.py.txt` with their exact original bytes; attachments do not execute code. Downloaded delivery ZIPs remain a separate local delivery workflow.

Validated Useful Findings may be saved on any response. The cumulative `useful-findings.md` file is attached at submitted message numbers 10, 20, 30, etc. Initialization, tool results and corrections count; uploads, local approval interactions, polling and assistant responses do not. Structured entries retain provenance, timestamps and deduplication hashes.

Session state, redacted events, response diagnostics, immutable script/approval previews and `local_python` audit receipts are retained under configured user storage at `runtime/sessions`. Replaced state versions are retained in `.history`; application file tools preserve files. Failed or cancelled code runs stop owned processes but retain output evidence rather than deleting it. Setup uses bundled virtualenv and pip package management. Retained storage grows and retention is a user responsibility. Runtime/session/profile/workspace files are excluded from source control.

## Verification and limitations

Run **Run Tests.cmd** for the automated suite. Tests retain their isolated directories rather than deleting files. Real visible acceptance is explicit: see [VISUAL_ACCEPTANCE.md](docs/VISUAL_ACCEPTANCE.md) and the execution evidence in [TEST_REPORT.md](docs/TEST_REPORT.md). Mocks and UI previews are never treated as proof of local delivery.

See [ARCHITECTURE.md](docs/ARCHITECTURE.md), [THREAT_MODEL.md](docs/THREAT_MODEL.md), [REUSE_MAPPING.md](docs/REUSE_MAPPING.md), [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md), and [KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md). `local_python` is explicit approved host execution with defense-in-depth mediation, not an OS sandbox; unavailable desktop capabilities and organizational restrictions are reported honestly.
<!-- END SOURCE: README.md -->
