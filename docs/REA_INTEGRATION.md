# REA research and fast scoped discovery

Copilot Chat plans; the existing local orchestrator validates and authorizes
ToolRegistry calls. REA is a one-shot CLI adapter, never another reasoning agent,
raw MCP catalogue, or execution authority. No model API is introduced.

## Install and recover the runtime

The adapter targets `rea-agents` 6.5.0 (MIT), inspected source revision
`d7651b6a0dde6cfe658144cc52794ae6aaf23306`. Runtime binaries are installed,
not committed. Normal **Setup.cmd** and the selected live/testing version's
**Start Agent.cmd / Start Agent UI.cmd** now run the repair helper before the
session catalogue is built. An external developer checkout is not required.
Tool requests and availability checks never install software.

Node must support `^22.19.0`, `^24.11.0`, or `>=26`, with npm available for a new
installation. The helper obtains the exact published npm archive, verifies its
pinned SHA-512, safely extracts it, installs production dependencies with scripts
and optional dependencies disabled, checks the matching Windows native artifact,
and runs the actual CLI `--help`. Existing complete installations are reused.
The original upstream license is retained in the installed distribution.

### Recovery options

1. **Automatic repair / explicit retry**, from the project directory:

   ```powershell
   .venv\Scripts\python.exe bootstrap\setup_rea.py
   ```

   Installation tries project `.runtime/rea`, then
   `%LOCALAPPDATA%/Copilot Local Agent/runtimes/rea/6.5.0`, then the corresponding
   system temporary directory. A failed writable location advances to the next;
   previous partial REA installations are preserved. Dependency setup tries the
   existing npm cache before a bounded registry request. `--timeout-seconds 90`
   sets the provisioning budget; individual version/download/smoke probes also
   have fixed limits. No manual unpack-folder prompt is added. Discovery data
   remains in the existing S:/UNC store.

2. **Use an existing complete installation**: set absolute `rea_repository`
   and, when Node is not on PATH, `rea_node_executable` in `config.local.json`.
   PATH and standard Program Files / LocalAppData Node locations are checked.
   Explicit configuration is authoritative; an invalid override is diagnosed
   instead of silently replaced with a different installation.

3. **Disconnected repair**: transfer the unchanged `rea-agents-6.5.0.tgz`
   published archive and a populated npm cache from a successful installation.
   Set `COPILOT_REA_ARCHIVE` to that archive's absolute path, then run:

   ```powershell
   .venv\Scripts\python.exe bootstrap\setup_rea.py --offline
   ```

   The same pinned integrity check applies. An archive alone does not contain
   Node dependencies; an incomplete offline cache produces a clear failure.
   Alternatively select a complete offline installation using option 2.

4. **Trusted source checkout**: the prior sibling
   `Copilot Local Agent Research/rea` remains a supported discovery fallback.
   Build the pinned revision with `npm ci` and `npm run build:cached`; Windows
   requires the exact-version published native addon as documented upstream in
   `native/windows/README.md`. New installations should prefer the repair helper.

After repair, start a **new session**. It refreshes one authoritative availability
snapshot used by `research_routing.rea`, all three REA catalogue entries and
`research.route`. Actual execution checks the runtime again before launch.
Diagnostics identify `package.json`, every checked repository/manifest path,
missing/unreadable/invalid/incompatible files, CLI and dependency admission,
Node candidates and compatible versions, and native identity failures. Reported
capabilities describe the pinned adapter contract; the setup CLI smoke check
verifies actual loading. A missing dependency is never called healthy.

For a supported approved website investigation, `research.route` must return
`preferred: rea.inspect_page` when REA is available. Dependency failure remains
explicit and preserves browser/API/Crawl4AI alternatives and existing approvals.


### Paste a portable Node path and continue automatically

Run **Setup.cmd**. Its Node prompt accepts a pasted absolute path to `node.exe`,
the extracted portable Node folder, or the original Windows Node ZIP. File
Explorer quotes and spaces are accepted. Examples are `S:\Tools\node\node.exe`,
`S:\Tools\node-v24.13.0-win-x64`, or `\\server\share\Tools\node-v24.13.0-win-x64.zip`.
S: aliases are resolved through the current mapped share, with direct and UNC
fallbacks. No share is guessed. A ZIP is extracted automatically into a verified
writable managed cache; the original archive stays unchanged.

After validation, setup saves `rea_node_executable` in `config.local.json`,
retaining its other settings. Normal startup now loads that local configuration
automatically; an explicit `--config` still takes precedence. Setup uses the
portable distribution's own `node_modules/npm/bin/npm-cli.js`, then continues
REA dependencies and runtime checks. Setup automatically reuses/detects Edge;
only a genuinely missing resource needs another path. Invalid Node paths can be
corrected at the same prompt. Enter reuses detected Node, or stops Node setup
clearly if none was found. No installer or global PATH change is required.

For a direct command instead of the prompt:

```powershell
.venv\Scripts\python.exe bootstrap\setup_rea.py --node-path "S:\Tools\node-v24.13.0-win-x64.zip"
```

Use `--prompt-node-path` to explicitly choose a different Node location, or
`--non-interactive` for unattended runs that must fail clearly instead of waiting
for input. ZIP layout/size/path checks and native version validation run before
continuing. Supply a trusted Windows Node ZIP with Node and npm included.

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
