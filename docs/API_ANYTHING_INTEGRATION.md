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
- Session state, diagnostic events, approvals and immutable evidence are retained under configured OneDrive storage.

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
