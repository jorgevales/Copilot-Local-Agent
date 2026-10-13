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

Normal durable storage prefers the live mapped S: share and otherwise uses the current canonical UNC or local-app-data store. Explicit isolated local proof stores remain supported. ZIP authoring uses runtime-provided paths rather than paths copied from another host. A standalone `files.replace` call requires separate normal tool approval and an expected SHA-256. A package may call it only when declared in the freshly inspected ZIP and covered by that exact package's individual or session-scoped approval; the expected hash and path checks still apply. Replacement stages a same-directory temporary file, rechecks target identity and content, atomically replaces, and reads back the approved content. `files.grant_path` separately adds one reachable existing file or directory for the current session after user approval. A file grant is exact-file only; a directory grant covers that directory and descendants. Protected profile, credential, device and redirected paths remain denied.

## Validation status

Offline tests cover package inspection, hash-bound execution, result binding, private checkpoint projection, distinct-tab scheduling, session-grant lifetime, atomic file replacement and path-extension containment. The final local GOV.UK proof passed on exact Edge port 63741: a fresh 14-stage ZIP opened five tabs, ran reconnaissance with four overlapping stages, and saved then read back five navigation routes in the explicit C: test store. Stage checkpoints retain start/end timestamps for direct timing verification. See [the dated acceptance report](LIVE_GOVUK_PACKAGE_ACCEPTANCE_20261013.md) for hashes, measurements, test results and scope.
