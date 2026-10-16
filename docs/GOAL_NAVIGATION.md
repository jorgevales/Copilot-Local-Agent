# Goal-directed visual navigation baseline

Later live discovery findings and the unresolved paused-test blocker are recorded
in [NNCY_LIVE_TEST_PAUSED_20261016.md](NNCY_LIVE_TEST_PAUSED_20261016.md).

Implemented on 16 October 2026. This baseline adds an additive registered tool,
compact navigation decision evidence, concise protocol-preserving guidance,
content-free timings and reproducible offline benchmarks. It uses the existing
orchestrator/Copilot UI exchange and approval path. No additional model, parallel
worker, laptop/VDI channel or automated authentication was added.

Raw private conversation stays inline: repeated strategy prose is reduced when
needed, and an oversized live conversation stops before disk spill or truncation.
The existing explicit transport for complete current tool-result artifacts is
preserved. A registry without REA tools no longer probes or advertises host REA.
Registered REA tools retain one authoritative availability snapshot per session.

## Operation

For an approved owned website tab, request `browser.navigate_goal@1.0` with
`task_id`, `goal` and nonempty `success` assertions. A known target uses an exact
same-origin URL plus a visible landmark. If its route is unknown, exact rendered
target text under the bound origin permits discovery without guessing a URL.
Text target assertions also require that the matched element is visible and
unique. Customer-bound work carries the existing `customer_key`/`identity` checks.
Snapshots and freshness checks include at most four immediate visible same-origin
frames with observed frame selectors. Deeper or inaccessible frames need focused
inspection through the existing browser tools; they are not claimed as covered.

The first call omits `steps`. It returns `needs_visual_decision`, a one-use
`observation_id`, a current screenshot and up to eight goal-ranked observed
controls/routes. Copilot reads that view, then requests another call with the
same goal/target and token plus at most three predictable navigation-only steps.
Use the returned locator objects exactly. Every step has explicit postconditions.
No fills, searches, submissions, new tabs, arbitrary JavaScript, branches or
consequential effects are accepted by this tool. Existing broader tools retain
their separate contracts.

The tool runs one local slice and returns to the existing orchestrator turn loop;
it never starts a nested Copilot exchange. A local URL/visible target check runs
before movement and after every completed step, stopping a segment as soon as the
target is reached. `target_verified` still requires current visual review before
the final answer. The orchestrator rejects premature complete answers after a
goal call and allows at most two corrective continuation requests.

Discovery and navigation proceed together: inspect enough of the current page
to choose the next move; do not finish a website crawl before approaching the
target. Existing comprehensive discovery remains available when requested.

```json
{
  "task_id": "find-reports",
  "goal": "Reach the quarterly reports page",
  "success": [
    {"kind": "text", "locator": {"role": "heading", "name": "Quarterly reports"}, "value": "Quarterly reports"}
  ]
}
```

Use the existing complete response-v1 envelope around tool requests. This example
is only tool arguments; it does not authorize a site or invent a locator.

## Scope, interruptions and recovery

Each slice binds the live owned page, task, goal, target, customer/tenant namespace
and observation fingerprint. Stale tokens or changed page content cause a fresh
observation request with no stale action. The first transition must use an
observed control/route. The exact approved short plan supplies later predictable
steps; their postconditions and browser ownership/origin guards still apply.

The tool stays on its original origin even in legacy permissive embedded modes.
The existing navigation grant can cover valid navigation-only continuations;
otherwise ordinary exact local approval applies. It is excluded from automation
package stages because a package cannot own the interactive goal continuation.

Unexpected dialogs, authentication/MFA, ambiguous target matches, missing or
unstable mandatory imagery, cancellation and uncertain effects stop mutation.
Budgets default to 30 local steps and 600 seconds across continuations; they cannot
be expanded after the goal begins. A burst defaults to 15 seconds, with a schema
ceiling of 30 seconds. Repeated unchanged observations trigger a no-progress stop.
Goal state is ephemeral; restart needs fresh observation and existing ledger
reconciliation. No process-restart resumption claim is made.

Observation/action transactions on the same page share a lock. Existing
independent reads on different tabs remain independent. Raw before/after PNGs are
retained. Compact mode transmits the latest coherent DECISION image for each goal
call in a labeled PDF; a JSON manifest preserves all image references and gaps.
Known micro-actions are grouped only when their intermediate states require no
new decision. New/ambiguous choices require a fresh screenshot and model decision.
Goal-only result packets omit repeated unrelated package/crawl strategy prose and
older chat messages while retaining exact requirements, constraints, pending
operations, approval metadata, current results and verified-guidance references.
`compact_navigation: false` restores full visual bundles and normal reply style.

## Latency evidence

`performance_enabled: true` (default) writes bounded, batched numeric events to
`performance.jsonl` beneath the existing session directory. Live runtime storage
therefore follows the existing S:/UNC resolver; no new local fallback is added.
Events contain monotonic offsets/durations, byte/image/action counts, random run
IDs and SHA-256 correlation IDs. Prompts, page text, URLs, target/record names,
model private reasoning and raw exceptions are not logged in this file. Ordinary
scoped visual artifacts retain their separate data-handling requirements.

Measured stages include prompt assembly, attachment preparation, actual upload
preparation, committed send, first complete public preview field, observed
generation end, stable capture, validation, tools, actions, screenshots, visual
packaging, target verification and full task time. These spans can overlap. UI
response time includes cloud/network/rendering; it is not isolated inference time.
Unavailable token/cost metrics are never fabricated. Optional telemetry write
failures do not authorize or replay actions; buffered events remain bounded and
drop/write-failure counters are available on the trace object.

Summarize an existing trace into a new output file:

```powershell
.\.venv\Scripts\python.exe -B tools\report_navigation_performance.py --input "<session>\performance.jsonl" --output "<new-output>.json"
```

`performance_enabled: false` disables this optional trace. Mandatory operation and
approval ledgers remain authoritative.

## Offline validation and benchmark

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_performance tests.test_goal_navigation tests.test_goal_orchestrator -v
.\.venv\Scripts\python.exe -B tools\benchmark_goal_navigation.py --output runtime\navigation-benchmark-new --runs 3
.\.venv\Scripts\python.exe -B tools\benchmark_goal_navigation.py --output runtime\navigation-branching-new --runs 3 --scenario branching_discovery
```

The harness uses real headless browser rendering with all traffic intercepted by
synthetic fixtures. It alternates baseline/candidate order, verifies the target
independently, retains images and traces, and compares individual actions with
short goal segments. Output directories are create-only. `--decision-delay-ms`
optionally adds an explicitly simulated wait. Scripted decision requests are not
real model calls. CPU covers the Python process; unavailable memory/GPU/network,
provider usage and live Copilot metrics are null.

The latest three-pair run (no simulated wait) completed 3/3 tasks per variant:
median local time 3926ms individual versus 3357ms goal segments, with six versus
three scripted decision requests. Raw screenshot counts were 24 versus 23;
compact packages reduced transferred evidence bytes in this fixture. This is a
small local synthetic result, not a live Copilot/VDI speedup or a production
reliability claim. See the retained `runtime/navigation-known-verified-20261016/report.json`,
which records source hashes, Python, Playwright and browser versions for that run.
The detailed proposal's live end-to-end acceptance gates remain unproven.

The branching-discovery scenario reveals only the next route and uses the same
scripted, observed-label choice in both variants. It also completed 3/3 per variant:
median local times were 5289ms baseline versus 5322ms goal continuations, with
12 versus seven scripted decision requests. Thus the extra observation checks
were slightly slower locally in this small run; fewer decision exchanges are a
mechanism to test against real Copilot wait time, not a demonstrated live gain.
Evidence is retained in `runtime/navigation-branching-verified-20261016/report.json`.

## Deferred work

Additional model routing, speculative workers, local perception models, deep
procedural memory changes, durable per-step restart recovery and laptop/VDI
cooperation remain separate experiments after this baseline supplies evidence.
