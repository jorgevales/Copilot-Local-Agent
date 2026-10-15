# REA research and fast scoped discovery

Copilot Chat plans; the existing local orchestrator validates and authorizes
ToolRegistry calls. REA is a one-shot CLI adapter, never another reasoning agent,
raw MCP catalogue, or execution authority. No model API is introduced.

## Install the inspected runtime

The adapter was inspected against `morluto/rea` revision
`d7651b6a0dde6cfe658144cc52794ae6aaf23306`, package `rea-agents` 6.5.0.
REA uses the MIT license. This integration does not vendor its source or binary;
retain the upstream copyright/permission notice when redistributing REA.

Install Node in one of REA's declared ranges: `^22.19.0`, `^24.11.0`, or `>=26`.
From the project's parent directory:

```powershell
git clone https://github.com/morluto/rea.git "Copilot Local Agent Research/rea"
git -C "Copilot Local Agent Research/rea" checkout d7651b6a0dde6cfe658144cc52794ae6aaf23306
Push-Location "Copilot Local Agent Research/rea"
npm ci
npm run build:cached
```

Windows source checkouts omit the native controls from Git. Follow the inspected
upstream `native/windows/README.md` matching-version recovery:

```powershell
npm pack rea-agents@6.5.0 --ignore-scripts
New-Item -ItemType Directory -Force .setup-cache/rea-native | Out-Null
tar -xzf rea-agents-6.5.0.tgz -C .setup-cache/rea-native package/native/windows/build/manifest.json package/native/windows/build/rea-windows-x64.node
New-Item -ItemType Directory -Force native/windows/build | Out-Null
Copy-Item .setup-cache/rea-native/package/native/windows/build/manifest.json native/windows/build/
Copy-Item .setup-cache/rea-native/package/native/windows/build/rea-windows-x64.node native/windows/build/
npm run verify:windows-native:artifact
Pop-Location
```

The compatible sibling checkout is discovered by project-relative convention.
Alternatively set an absolute trusted `rea_repository` and native Node executable
in administrator configuration. Copilot cannot choose these paths or command
arguments. Optional missing/disabled dependencies produce an unavailable tool
and leave the rest of the stack working; startup never installs REA implicitly.

## Typed capabilities and limits

| Tool | Input | Behavior |
| --- | --- | --- |
| `rea.inspect_page` | optional `tab_id`, `observation_ms` 0–3000 | Passive inspection of an already owned, approved browser page. The adapter obtains the target ID and loopback CDP endpoint. No navigation, login, page text, storage values or script bodies. |
| `rea.analyze_capture` | approved `path`, `format`: `har` or `saz` | Offline capture metadata/source analysis. Never replays requests; removes headers, payload values and query parameters. |
| `rea.analyze_artifact` | approved `path`, `kind`: `managed`, `go`, `rust`, `javascript` | Static assembly/binary/JavaScript application analysis. Never executes the target. JavaScript may use a directory/ASAR; admitted directories have a 2,000-entry and total-byte bound. |
| `research.route` | approved `target`, `target_type`, `objective`, optional `prior_call_id` and `refresh` | Deterministic local selection and evidence/fallback advice; performs no investigation or authorization itself. |

The three REA tools are read-only with respect to the target and require existing
target/path authority. Default execution is 45 seconds, 1 MiB output, 20 MiB input,
and three concurrent REA processes. JavaScript helper limits include 256 MiB heap
and 10,000 semantic nodes; the parent heap is 384 MiB. Time/output limits and
Stop terminate owned work; uncertain termination/cleanup blocks subsequent
execution. Results distinguish completed, partial, failed, unavailable, timeout,
cancelled, output-limit and uncertain outcomes. Unsupported native-provider
decompilation is not exposed.

Windows native workflows require fixed local NTFS. The adapter snapshots approved
inputs from S:/UNC into verified LocalAppData or temporary scratch, enforces
member paths/size/hash identity, and removes only its owned scratch after confirmed
termination. Original paths/hashes remain provenance; durable evidence stays in
the existing session store. If local scratch is unavailable, report the limitation
and use a relevant existing tool. Uncertain cleanup retains the exact scratch
location for diagnosis and never reports success.

## Routing and combined research

User requests with explicit URLs receive deterministic routing hints. Copilot can
request `research.route` for an exact target/objective and receives the preferred
capability, prerequisites, complementary tools, alternatives and reasons.

- General supported investigation prefers healthy REA.
- Known API questions prefer the **API Anything-inspired public operation
  adapter**, `operation.list`/`operation.call` in `web_operations.py`. This opt-in
  adapter uses retained verified public GET operations; enable `operation_reuse`
  with `persistent_graph` to use it. `operation.learn` retains its exact approval.
- Structured extraction/crawling prefers `crawl4ai.crawl`; `crawl4ai.read`
  retrieves saved task evidence.
- Navigation, screenshots, focused DOM/script queries and file metadata use
  their specialized registered tools. Discovery manifests remain public-static
  evidence collection; browser campaigns remain separately approved navigation.
- Combine REA, API observations, crawling and browser artifacts only when each
  contributes distinct evidence. Independent bounded reads run concurrently;
  same-tab dependent work and target mutations remain ordered.
- An actual prior failed/partial call can select an existing alternative while
  preserving the original attempt. Denial and uncertain effects block fallback.
  Hash-verified recent evidence can be reused; local input identity is rechecked.
  Refresh and later browser effects prevent inappropriate snapshot reuse.

No route invokes every tool or silently turns a failed inspection into success.
Each contributing result keeps its own provenance. See
`RESEARCH_TOOL_INVENTORY.json` for exact current registered schemas and families.

## Session, evidence and knowledge

The initial session confirmation enables scoped read-only discovery and automatic
useful sanitized knowledge saves. Other file writes, transactions, code and new
unrelated/private/local target scopes retain concise approval. Grants expire on
close/restart/resume and can be revoked. `browser.login_once` permits one visible
prefilled login-button click per approved origin; it never reads/types/exports
credentials and stops for denial, failed verification or MFA.

REA uses fixed argument vectors, no shell/raw MCP forwarding, a restricted child
environment and bounded output. Redaction occurs before persistence and Copilot
exposure. Its session JSON is a redacted projection of upstream Evidence, with
execution ID, original input identity, timestamps, status, confidence/unknowns,
source locations, artifact references and retained evidence hash. It is not a raw
re-importable REA bundle. Absence of evidence remains distinct from evidence of
absence; partial JavaScript recovery remains partial.

The authoritative S:-backed ledger holds evidence/revisions. Canonical site
folders and namespace files provide concise readable knowledge. Explicit
app/tenant/environment binds override defaults. Save new verified workflows,
precise sanitized URLs/paths and successful examples; skip empty/noisy/duplicate
notes, label prior methods, and prefer a faster method only with local proof.
Credentials/tokens/cookies and identifiable records never belong in automatic
knowledge. Raw Crawl4AI/browser captures are separately approved task evidence.
Copilot receives the actual resolved S: and UNC knowledge root paths.

## Configuration and troubleshooting

`config.example.json` documents `rea_enabled` (true), `rea_repository` and
`rea_node_executable` (empty means discovered), `rea_timeout_seconds` (45, 1–180),
`rea_max_output_bytes` (1 MiB, 16 KiB–8 MiB), `rea_max_input_bytes` (20 MiB,
1 KiB–100 MiB), and `rea_max_parallel` (3, 1–8). Invalid settings are rejected.
Disabling REA marks its catalogue entries unavailable without changing other
tool registration. Health verifies the package/build/Node path and matching
Windows addon version/hash; the upstream runtime validates Node compatibility.

For missing runtime, follow the installation above. For scope denial, obtain the
target/path grant instead of changing tool or forwarding raw arguments. For
partial evidence, inspect limitations and combine a relevant tool. For uncertain
process state, verify owned-process termination/cleanup before continuing. For
knowledge errors, inspect S:/UNC identity/write/readback diagnostics; no C: fallback
is invented. Setup scratch fallbacks are separate and preserve existing installs.

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
