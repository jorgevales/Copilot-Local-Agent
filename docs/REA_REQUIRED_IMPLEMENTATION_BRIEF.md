# Codex Brief: REA Is Mandatory, Implement a Reliable Non-Node Backend

## Non-negotiable outcome

REA capability must remain available. Node failure must not disable REA.

Implement two interchangeable execution backends behind the existing three REA ToolRegistry contracts:

```text
1. node_cli: existing rea-agents 6.5.0 adapter
2. python_native: local Python implementation requiring no Node/npm
```

Backend selection:

```text
Use a verified Node backend when healthy.
Otherwise use the verified Python backend automatically.
Report REA unavailable only if both backends fail validation.
```

Do not weaken existing path, target, browser ownership, approval, redaction, timeout, evidence, uncertainty, or no-deletion controls.

## Live failure evidence

- Windows corporate VDI without administrator rights.
- Project and portable Node are on the S Drive.
- Node `v24.22.0` and npm `11.19.1` execute successfully.
- npm registry connectivity works.
- The original C: npm cache failed with `ENOSPC`.
- Cache, temp, Local AppData, AppData, and npm prefix were redirected to writable S Drive folders.
- REA provisioning still timed out across project and redirected runtime candidates with 90-second and 180-second limits.
- `bootstrap/setup_rea.py` reports only generic `write, download or execution failure`, hiding the actual failing stage.

Do not expose company paths. Use only `S Drive`, `<project-root>`, `<setup-temp>`, and similar labels.

## Required architecture

Keep these public tools and schemas stable:

```text
rea.inspect_page
rea.analyze_capture
rea.analyze_artifact
```

Add a backend interface, for example:

```python
class REABackend:
    def health(self) -> dict: ...
    async def inspect_page(self, prepared, context) -> dict: ...
    async def analyze_capture(self, prepared, context) -> dict: ...
    async def analyze_artifact(self, prepared, context) -> dict: ...
```

Implement:

```text
NodeCliREABackend
PythonNativeREABackend
```

`copilot_agent/rea.py` must continue to own validation, staging, bounds, redaction, evidence persistence, normalization, cancellation, and uncertainty. Backends perform analysis only.

## Python backend scope

Implement equivalent supported outputs, not a generic placeholder.

### `rea.inspect_page`

Use the existing owned Playwright/CDP page supplied by the orchestrator. Collect bounded passive evidence already available through the project:

```text
URL/origin classification without sensitive query values
frame and document structure
DOM and accessibility controls
scripts and resource metadata
request method/status/resource-type metadata
application/framework indicators
forms and navigation surfaces
explicit gaps and limits
```

Do not extract cookies, browser storage, credentials, password values, request payloads, or authentication headers. Do not navigate or mutate the page.

Reuse existing browser inspection and discovery collectors where possible. Do not create a second browser authority.

### `rea.analyze_capture`

Implement offline HAR analysis in Python using standard JSON parsing and the current bounded file policy.

Required evidence:

```text
entry/request counts
hosts and route templates
methods and status classes
redirect chains
content-type and timing summaries
API candidates
repeated request shapes
security/redaction findings
source locations
unknowns and truncation
```

Remove query values, headers, cookies, payload values, tokens, and customer identifiers before persistence or return.

For SAZ, parse only through a reviewed bounded archive reader. Reject encrypted, unsafe, malformed, oversized, or ambiguous archives. Never replay traffic.

### `rea.analyze_artifact`

Implement Python-native static analysis for the currently declared kinds:

```text
javascript
managed
go
rust
```

Minimum reliable implementation:

```text
JavaScript:
  bounded source-tree/file inventory
  imports/exports
  routes/endpoints with values sanitized
  framework/build indicators
  source maps when present and safe
  AST analysis using an already approved Python parser if available, otherwise a conservative tokenizer

Managed:
  PE/CLI metadata, assembly references, namespaces/types/method metadata when readable

Go:
  executable/file metadata, build information, module/package/string evidence when safely readable

Rust:
  executable/file metadata, crate/panic/path/string evidence when safely readable
```

Never execute the target. Provider-dependent deep decompilation may remain explicitly partial, but the tool must return useful structured evidence with confidence, unknowns, and limitations.

Prefer Python standard library and already pinned project dependencies. Do not add another model API, cloud service, autonomous agent, shell execution, or unreviewed binary dependency.

## Output compatibility

Both backends must normalize into the existing REA result contract:

```text
backend
execution_id
status
started_at / finished_at
input identity and hashes
source locations
findings
confidence
unknowns
limitations
artifact references
retained evidence hash
```

Statuses must remain distinct:

```text
completed
partial
failed
unavailable
cancelled
timeout
output_limit
uncertain
```

A Python result must not claim evidence it did not collect. Backend provenance must always be visible.

## Health and selection

Health must test both backends independently.

Selection rule:

```python
if node_backend.complete_and_verified:
    selected = node_backend
elif python_backend.complete_and_verified:
    selected = python_backend
else:
    unavailable_with_both_diagnostics()
```

Configuration:

```json
{
  "rea_backend": "auto"
}
```

Allowed values:

```text
auto
node_cli
python_native
```

`auto` must guarantee automatic Python fallback when Node provisioning or verification fails. `python_native` must perform no Node/npm discovery or installation.

Ordinary startup must never install software. `Setup.cmd` may repair the Node backend, but the Python backend must be ready from the project environment.

## Fix Node diagnostics too

Add exact stages to `bootstrap/setup_rea.py`:

```text
node_probe
npm_probe
archive_acquire
archive_verify
archive_extract
dependency_install
native_verify
cli_smoke
publish
```

Retain sanitized stage, safe command identity, duration, timeout, return code, bounded stdout/stderr, termination status, and filesystem error codes. Never collapse all failures into one generic message.

## Tests

Add tests proving:

- `python_native` performs no Node/npm calls.
- All three REA tools execute through `python_native` with synthetic inputs.
- `auto` selects Python when Node setup, native validation, or CLI smoke testing fails.
- Node and Python outputs satisfy the same public schema.
- HAR/SAZ secrets and payload values never appear in results or retained evidence.
- Artifact analysis never executes the target.
- Page inspection uses only the owned approved page and performs no mutation.
- Time, input, output, entry, and concurrency limits are enforced.
- Cancellation and uncertain cleanup remain distinct.
- No company paths appear in public diagnostics or fixtures.
- Existing REA registry, routing, availability-session, and research-routing tests pass with both backends.

## Files to inspect first

```text
bootstrap/setup_rea.py
copilot_agent/rea.py
copilot_agent/browser_inspection.py
copilot_agent/discovery_contracts.py
copilot_agent/policy.py
copilot_agent/tools.py
copilot_agent/research_routing.py
copilot_agent/config.py
tests/test_rea.py
tests/test_rea_registry.py
tests/test_rea_availability.py
tests/test_rea_availability_session.py
tests/test_setup_rea.py
```

## Acceptance criteria

1. REA remains available when Node is missing or unusable.
2. The Python backend implements all three existing REA tool contracts.
3. `rea_backend=python_native` never invokes Node/npm.
4. `rea_backend=auto` falls back automatically and records backend provenance.
5. Existing controls and schemas remain enforced.
6. Node setup failures identify the exact stage.
7. No company paths are exposed.
8. Ordinary startup performs no installation.
9. Synthetic end-to-end tests prove useful outputs for page, HAR/SAZ, and artifact analysis.
10. Unsupported deep analysis is reported as partial, never fabricated or silently treated as complete.
