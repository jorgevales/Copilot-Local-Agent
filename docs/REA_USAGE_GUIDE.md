# REA usage before constructing a request

This guide follows the inspected **rea-agents 6.5.0** documentation and source
(revision `d7651b6a0dde6cfe658144cc52794ae6aaf23306`) plus this project's stricter
ToolRegistry schemas. `copilot_agent.rea_guidance.rea_usage_guidance(config)`
supplies the same rules and current limits to Copilot before tool selection.
The current catalogue schema is authoritative when constructing arguments.

## Three exposed methods

| Local method | Purpose and supported input | Exact arguments |
| --- | --- | --- |
| `rea.inspect_page` | Passive inspection of an already owned, approved HTTP(S) browser tab: structure, accessibility and observed network metadata. No navigation, login or explicit target requests. | Optional `tab_id`: existing owned ID, string length 1–100. Optional `observation_ms`: integer **0–3000**, default **500**. No other fields. |
| `rea.analyze_capture` | Offline inspection of an existing approved **HAR 1.2** or **Fiddler Everywhere SAZ** file. Recorded requests are never replayed. | Required `path`: string length 1–4096. Required `format`: exactly `har` or `saz`. No other fields. |
| `rea.analyze_artifact` | Static inspection of an existing approved artifact; target code is never executed. | Required `path`: string length 1–4096. Required `kind`: exactly `managed`, `go`, `rust` or `javascript`. No other fields. |

Artifact kinds mean:

- `managed`: PE/CLI .NET assembly identity/deployment metadata. This is not a
  native decompiler, IL2CPP decoder, NativeAOT analyzer or arbitrary single-file
  host unpacker.
- `go`: supported executable/library with embedded Go build metadata. Upstream
  supports ELF, PE and thin Mach-O. Missing metadata proves no absence of dependencies.
- `rust`: supported executable/library with cargo-auditable dependency metadata.
  Missing `.dep-v0` is reported, not interpreted as no dependencies.
- `javascript`: for upstream Node, use an extracted JavaScript/Electron
  application **directory or ASAR**. A standalone `.js` file is not the upstream
  application workflow described here. The wrapper admits at most 2,000 directory
  entries and the configured aggregate input bytes.

Upstream REA has many additional commands, MCP parameters and content-selection
flags. They are not exposed by these three local methods. In particular,
`max_nodes`, `cdp_endpoint`, `target_id`, `record_ordinals`, `detail`, `provider`
and CLI flags are not valid local arguments.

## Construct requests from existing evidence

A valid argument example for an already approved default owned tab is:

```json
{"observation_ms": 0}
```

The live-agent diagnostic also successfully used `3000`. `5000` is invalid.
For another tab add its actual `tab_id` from current browser evidence. The
orchestrator binds the matching CDP target and exact origin; Copilot does not
supply an endpoint, URL or fabricated target ID.

For capture/artifact calls first obtain an **existing approved path** from a
capture result or file listing. These are substitution templates, not paths to
submit literally:

```json
{"path": "<EXISTING_APPROVED_CAPTURE_PATH>", "format": "har"}
{"path": "<EXISTING_APPROVED_APPLICATION_DIRECTORY>", "kind": "javascript"}
```

A nonexistent path is a preflight failure, not a REA defect. The orchestrator
verifies artifact identity, creates a suitable immutable scratch snapshot and
checks that the original did not change. Credentials, cookies, payloads and
other excluded carriers remain excluded from returned evidence.

## Backend selection and deadlines

- `rea_backend=auto` prefers validated upstream `node_cli`. `python_native` can
  supply useful evidence after a safe upstream failure or unavailability.
- `rea_backend=node_cli` requires upstream Node REA; Python cannot substitute.
- `rea_backend=python_native` explicitly selects the bundled fallback.
- A fallback is **degraded**, even if its observation is verified. Report
  `backend`, `degraded`, `fallback_used`, `intended_backend`,
  `intended_backend_succeeded` and `prior_backend_attempt`. A user asking for
  upstream REA success has not received it when `backend=python_native`.
- Uncertain cleanup blocks automatic fallback/retry.

Current defaults: readiness **180 seconds** shared across readiness phases,
Node analysis **600 seconds** (10 minutes), optional fallback **15 seconds** separately.
Set `rea_timeout_seconds` between 1 and 1800 seconds for complex investigations.
The previous shipped value of 45 seconds is upgraded to 600 when configuration is validated.
Node receives a 1024 MiB old-space heap ceiling for large page observations.
These are maximum allowances: successful calls return immediately, and cancellation remains available.
Readiness is cached by runtime identity. The `observation_ms` window is only
one part of analysis, not its total process deadline. Catalogue limits reflect
configuration: input **20 MiB**, concurrency **3**, model-facing output **1 MiB**,
complete Node transport **32 MiB**. Configuration ranges are readiness/analysis/
fallback **1–180 seconds**, input **1 KiB–100 MiB**, concurrency **1–8**, output
**16 KiB–8 MiB**, transport **16 KiB–64 MiB**.

The JavaScript lane additionally bounds semantic work to 10,000 nodes total,
3,000 per file and a 256 MiB analysis heap. These are adapter-owned flags, not
request parameters. A complete large Node observation can be retained in a
bounded sanitized artifact while Copilot receives a compact projection and
artifact reference. A projection limit does not establish backend failure.

## Status and coverage

| Status/condition | Meaning and action |
| --- | --- |
| `completed` | Verified observation completed; still read limitations and unknowns. |
| `partial` | Coverage gaps exist. Useful only when `observation_verified=true`, findings exist, and no error/uncertainty invalidates them. `coverage_complete=false`. |
| `not_started` | ToolRegistry preflight prevented execution. Correct parameters, scope, ownership or input first. Some backend replies use `unavailable`/`failed` with `execution_started=false`; inspect both fields. |
| `unavailable` | Backend/runtime capability did not pass readiness; inspect its specific diagnostics. |
| `timeout` | A deadline expired. Diagnostics distinguish readiness/startup from analysis. |
| `output_limit` | A byte/resource output bound was exceeded; this is not a timeout. Deliberately truncated JSON is never a complete observation. |
| `failed` | Invocation, process or output processing failed; inspect stage, error code, exit code and bounded stream diagnostics. |
| `cancelled` | Operation cancelled; confirm cleanup before retrying. |
| `uncertain` | Effects or cleanup cannot be verified; reconcile before retry/fallback. |
| `degraded=true` / `fallback_used=true` | Conditions alongside status, not replacement status enums. Successful fallback does not prove upstream Node success. Preserve the failed Node attempt. |

Upstream exit code `0` means an operation completed, which can still contain
partial evidence or warnings. Nonzero exit and structured error carry separate
signals. Do not turn every nonzero exit or malformed output into `timeout`.

## Python page ceiling

The bundled passive fallback intentionally has a **fixed 2,000-element DOM
ceiling**, plus 1,000 resources, 500 response events, 100 frames, 200 navigation
routes, 200 scripts and 100 forms. It is currently **not configurable**.
`max_nodes` is not accepted. A hit records `truncated=true`, partial findings
and incomplete coverage. This bound is not an upstream Node REA DOM limit:
the user-reported live Node inspection observed 9,980 DOM nodes and 5,825
accessibility nodes.

## Upstream output and manual comparison

The user-reported live Node 24.22.0 / REA 6.5.0 command returned valid Evidence,
exit `0`, **4,008,122 stdout bytes** and empty stderr with observation `0`.
This is supplied live-agent evidence, not a claim of a fresh local VDI test.
Use this operator-only invocation pattern to compare the adapter's sanitized
argument array (substitute actual already verified values):

```text
"<NODE_ROOT>\node.exe" "<REA_RUNTIME_ROOT>\scripts\rea.mjs"
  inspect-web-page <LOOPBACK_CDP_ENDPOINT> <VERIFIED_TARGET_ID>
  --allowed-origins <APPROVED_EXACT_ORIGIN> --observation-ms 0
  --json --full-output
```

`<PROJECTS_ROOT>\REA` is the source repository. `<REA_RUNTIME_ROOT>` is the
working installed runtime (for example the `rea-agents` package below the npm
global modules directory); do not assume they are interchangeable.

Upstream `src/cliOutput.ts` supports `--filter-output` with comma-delimited
property paths/slices and `--full-output`. `docs/cli.md` states piped `--json`
is compact already. **Do not invent `--fields`, `--compact` or `--out`.**
Structured JSON combined with `--token-limit`/`--token-offset` is rejected.
Filtering must preserve required Evidence identity/status/coverage fields.
The adapter retains complete bounded output rather than guessing a projection
that drops those fields. Upstream guidance for very large application/capture
results is complete JSON retention followed by `inspect-analysis-view`
summary/pages; that command is not a fourth exposed local method.

Source references in the installed repository/distribution:
`docs/browser-observation.md`, `docs/web-network-captures.md`,
`docs/managed-code-analysis.md`, `docs/go-binaries.md`, `docs/rust-binaries.md`,
`docs/javascript-artifact-reconstruction.md`, `docs/cli.md`, `src/cliOutput.ts`.
The local binding is `copilot_agent/rea.py:REA_SPECS`; Python ceiling and
collection details are in `copilot_agent/rea_python_page.py:SNAPSHOT`.
