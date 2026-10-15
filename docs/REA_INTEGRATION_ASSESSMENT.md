# REA integration assessment

Assessment baseline: `3a22557`; inspected before implementation on 2026-10-15.
The implementation follows the supplied REA brief with the subsequent interview
agreement taking precedence where the two differ.

## Existing architecture and research inventory

The Python application uses visible Copilot Chat for reasoning. `Orchestrator`
in `copilot_agent/orchestrator.py` validates the response envelope and tool
arguments, prepares exact effects, obtains local approval where needed, invokes
`ToolRegistry.execute`, records results and uncertainty, and returns evidence to
Copilot. `copilot_agent/tools.py` owns registered schemas and dispatch.
`approvals.py`, `policy.py`, `state.py`, `reconciliation.py`, and the managed
process registry remain the execution and recovery boundaries.

The actual API integration is the **API Anything-inspired public operation
adapter**, implemented in `web_operations.py`: `operation.learn`,
`operation.list`, and `operation.call`. It uses the existing pinned public HTTPS
transport, retains verified GET specifications, and never exports browser
credentials. The external API Anything project is not itself an unrestricted
registered runner. Crawl4AI is implemented by `local_crawler.py` through
`crawl4ai.crawl` and `crawl4ai.read`; discovery manifests also use its extractor.

The existing catalogue supplies browser navigation, owned tabs, DOM/structure,
JavaScript, screenshots/PDF, network observations, discovery campaigns, document
inspection, file reads/hashes, knowledge, and recovery tools. The generated
`RESEARCH_TOOL_INVENTORY.json` records their exact schemas, approval classes,
implementation families, output contracts, limits, and complementary roles.
Specialized API calls, structured crawling, retained fresh knowledge, exact
screenshots, and narrow file observations remain preferred for their specific
operations. Existing bounded parallel reads and package browser waves are reused.

## Inspected REA source and selected interface

REA was obtained as a separate sibling research checkout from
`https://github.com/morluto/rea.git`, revision
`d7651b6` (package version 6.5.0). Its MIT license permits this separate adapter;
redistributed upstream code must retain its copyright and permission notice.
No REA source is vendored. Node versions supported by its package include
22.19+, 24.11+, and 26+ (within the upstream declared ranges). Optional native
analysis providers have their own runtime/platform requirements.

Select the one-shot CLI, using fixed argument arrays and deterministic JSON.
Its passive owned-page inspection, offline HAR/SAZ inspection, and static
managed/Go/Rust/JavaScript inspection provide a small useful boundary without
starting REA's agent or raw MCP server. Page inspection uses the existing owned
browser target and orchestrator-managed loopback CDP endpoint. Captures are
analyzed offline; analysis targets are never executed. Deep native provider
support is not claimed by this adapter.

## Planned implementation boundary

- `rea.py`: three typed tools, trusted dependency configuration, validation,
  managed CLI lifecycle, bounded output, redaction, normalized session evidence,
  and explicit partial/failed/timeout/cancelled/uncertain outcomes.
- `research_routing.py`, `tools.py`, `config.py`, `prompts.py`, and
  `orchestrator.py`: catalogue and deterministic REA-first research planning,
  complementary API/Crawl4AI/specialized tools, failure recommendations, retained
  evidence reuse, and independent bounded work.
- Session authorization remains ephemeral. Read-only discovery on approved
  targets and sanitized knowledge saves run immediately. Target mutations,
  ordinary file writes, new unrelated origins, and private/local scope expansion
  retain concise approval. One already-filled login-button click is permitted;
  denial or MFA requires the user. Secrets are never extracted or saved.
- The existing S:-backed ledger remains authoritative. Knowledge tools produce
  compact per-site readable views, preserve verified previous navigation methods,
  deduplicate updates, and instruct Copilot with actual resolved S:/UNC paths.
- Setup retains existing seeders, cache reuse, and temporary candidates, expands
  proven S:/UNC and writable scratch fallbacks, and reports exhausted candidates
  without a manual unpack-folder question.

## Risks, compatibility, and validation

REA output and page/capture content are untrusted and may contain secrets.
Redaction precedes persistence and model exposure; raw cookies/tokens are not
exported. Tool arguments cannot select commands, runtimes, environment variables,
or raw MCP options. Files remain under approved path policy, browser pages remain
owned, origin scope is checked, and time/output/concurrency limits remain active.
Uncertain termination is not successful completion. Missing/disabled optional
REA leaves the rest of the research stack available.

The previous fast mode authorized arbitrary edits and cross-site access; the
interview explicitly narrows this to scoped read-only access, automatic safe
knowledge, and a single prefilled login click. Prompt, runtime, and approval
language must agree. Preserve persisted configuration compatibility and existing
knowledge/evidence revisions. Derived per-site files cannot become an independent
authority or duplicate evidence store.

Validation will use focused offline adapter, routing, session, knowledge, setup,
and browser tests first, then relevant existing unittest suites and UI unit
tests. Include real local REA CLI smoke tests on synthetic offline artifacts and
an owned synthetic browser page where feasible. Syntax and diff checks,
schema/catalogue checks, redaction/injection/timeout/cancellation tests, final
tree review, and handoff refresh precede publication. Live VDI/S: installation
cannot be proved here and will be reported explicitly, as agreed.
