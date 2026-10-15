# Mandatory REA with two analysis backends

Current behavior follows the [confirmed interview agreement](REA_AGREEMENT_UPDATE.md).

`rea_backend` accepts `auto` (default), `node_cli`, or `python_native`.
Auto prefers the verified rea-agents CLI and selects the bundled Python backend
when Node, the package, native controls, dependencies or CLI smoke check fail.
Python-only selection performs no Node/npm discovery or installation. All three
public ToolRegistry schemas are unchanged. Backend provenance is explicit.

Ordinary live/testing startup never installs software. Pull the code and start
a new session using the existing project Python environment. REA remains usable
without running Node setup. Setup.cmd now requires upstream Node success in auto/node_cli mode;
**Setup REA.cmd** explicitly repairs Node without Edge setup. Python fallback
remains available during ordinary sessions, with `upstream_available:false`
when the actual upstream runtime is missing. Use
`"rea_backend": "python_native"` in local configuration to bypass Node entirely.

## Evidence supplied by Python

- Owned page: bounded DOM/control/frame/form/script/resource/framework metadata
  and passive response metadata. No navigation, DOM mutation, labels/page text,
  credentials, cookie/storage access, payloads or authentication headers.
- HAR/SAZ: request counts, methods/status classes, templated routes, redirect
  edges, MIME/timing summaries, API/request shapes, omissions and source indices.
  SAZ uses a bounded reviewed archive reader; ambiguous/unsafe input is rejected.
- JavaScript: bounded file inventory, conservative tokenization, imports/exports,
  sanitized route shapes, build/framework indicators and safe source-map summaries.
- Managed: PE/CLI and ECMA335 assembly/type/method/reference metadata when readable.
- Go/Rust: file/executable metadata, recognized build/compiler/package/crate/panic
  evidence. Unsupported deep recovery remains explicitly partial.

The Python analyzer is a bundled independent implementation of these contracts,
not a claim that upstream Node algorithms were run. Findings include confidence,
unknowns, limits and source locations. Malformed input never creates invented
semantic evidence. No artifact is executed.

## Authority, lifecycle and privacy

rea.py retains target/path/owned-browser admission, immutable snapshot hashing,
shared concurrency, deadlines, cancellation, bounded output, redaction and evidence
writes. Static Python analysis runs in a fixed owned Python worker; page inspection
uses the existing owned page. Python snapshots may use writable S:/UNC scratch;
they do not require Node's fixed-local-NTFS admission. Durable evidence retains
existing storage policy. Cleanup uncertainty blocks replay and fallback.

Known-clean Node analysis failures can fall back within the remaining overall
time budget; Node gets a reserved share in auto mode. Cancelled or uncertain work
is never silently retried. Authorized reports and diagnostics retain exact original paths and input hashes.
Evidence references and retained scratch locations are complete filesystem paths.
Existing credential exclusions continue.
One session snapshot supplies metadata, catalogue entries and routing; a new
session refreshes it. Actual execution revalidates the runtime.

## Node repair diagnostics

Setup records node_probe, npm_probe, archive_acquire, archive_verify,
archive_extract, dependency_install, native_verify, cli_smoke and publish stages.
Records retain safe command identity, duration, timeout, return code, bounded
sanitized stdout/stderr, termination state and filesystem error codes. A verified
writable scratch npm cache avoids default-cache ENOSPC; valid explicit caches are
preserved. Unknown cleanup stops retries and retains owned staging for inspection.
Diagnostics are retained in the ignored setup cache with complete useful paths
and credential filtering. Portable Node path/ZIP selection remains available during Setup.

## Validation and remaining live checks

58 focused backend, parser, real-browser, registry, routing and setup-diagnostic
tests passed. A separate40-test setup/interactive/startup group passed. Existing
38 Node/availability/session tests were covered successfully, including actual
Node HAR/JavaScript and owned Edge integrations; the disabled-result field
regression passed after its fix. Counts overlap. Python tests prove real HAR/SAZ
and all four static kinds, schema compatibility, redaction, retained evidence,
passive real-browser observation and distinct termination states. Additional
selection/concurrency/clean-timeout-fallback regressions accompany the change.

Live corporate VDI, redirected S Drive and production authenticated Copilot were
not exercised here. On the VDI, start a new session after pulling: availability
must select python_native whenever Node validation fails; a supported investigation
must route to rea.inspect_page and results must report their actual backend.
