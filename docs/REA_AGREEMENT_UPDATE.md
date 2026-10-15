# Agreed REA follow-up

This agreement supersedes conflicting privacy, timing and partial-result wording
in the copied Copilot implementation brief and earlier implementation reports.
The existing implementation is the baseline; changes address verified gaps.

## Node gets 180 seconds

Setup and readiness use separate shared budgets of 180 seconds by default. Each
phase and retry consumes the remaining budget rather than restarting it. Setup
excludes time spent waiting for the operator to paste a path. Portable Node
executable/folder/ZIP paths on the S Drive and actual UNC aliases remain supported.
Ordinary startup performs no installation. Node readiness is cached by source and
runtime identity; a changed runtime invalidates the result. Python remains the
fallback when Node cannot be verified. Unconfirmed cleanup stops execution.

`rea_node_readiness_timeout_seconds` defaults to 180(range 1..180). The analysis
budget remains `rea_timeout_seconds` (default 45). Registry deadlines explicitly
include readiness, analysis and cleanup; readiness does not consume the analysis
budget. Python-only mode never probes or installs Node/npm.

## Partial observations are useful success

A successfully collected, verified observation may have incomplete coverage.
It returns `ok:true`, `status:partial`, `observation_verified:true` and
`coverage_complete:false`. Findings, unknowns and limitations remain visible.
Copilot is told to use that evidence and collect only material missing evidence,
rather than repeatedly treating the same useful partial analysis as a failure.
Fresh verified partial evidence can be reused with its gaps intact.

A changed source/page, failed verification, missing findings, an actual error,
cancellation, timeout, output limit or uncertain cleanup does not become a
successful observation. Complete output-size limits apply after original path
restoration as well as to worker transport. Existing authority remains local.

## Complete authorized knowledge and paths

The earlier company-path masking rule applied to the previous instruction author.
It does not restrict the local Copilot agent. Authorized reports, knowledge,
input provenance, JavaScript source inventory/source maps, diagnostic commands,
evidence references and retained scratch locations may contain complete exact
paths and internal navigation instructions. No blanket company-root replacement
is applied. Public tool schemas remain compatible.

Previously agreed credential, sign-in, target/path approval and uncertainty rules
continue. Automatic reusable notes still exclude credentials and identifiable
personal/customer records; requested business artifacts keep their task scope.
Source maps are metadata only: external sources are not followed, and embedded
source contents are not automatically emitted.

## Meaningful readiness

Python readiness runs tiny real HAR/SAZ, JavaScript, managed, Go and Rust parser
fixtures and exercises the passive collector against a synthetic owned-page
adapter. It does not create a browser, navigate a website, run an artifact,
or install anything. Actual owned-browser validation still happens on invocation.
Source identity controls reuse of functional readiness. Node checks load the
real fixed CLI and verify the supported commands within the shared budget.
Scratch candidates retain fallback support for full/unavailable temporary drives.

## Validation references

Focused regressions cover budgets, caching/source changes, functional checks,
full paths with credential exclusion, successful partial observations, changed
input rejection, retained hashes, output bounds, reuse with gaps, and existing
session/registry/routing behavior. Real local browser and CLI fixtures provide
additional proof. Full VDI, live S:/UNC capacity and production authenticated
Copilot behavior still require target-environment verification.


## Validation results for this update

- 103 setup, portable path, source-map, parser, Python registry, real-browser and routing tests: passed.
- 72 session lifecycle, compact startup, protocol, partial-observation, real-browser and path/routing tests: passed using an explicit unavailable-S fixture for storage lookups.
- 78 readiness/backend/registry/availability tests ran with actual Node/Edge integrations enabled:76 passed initially. Two old mock seams were updated for the bounded native probe; all13 session/alias/partial follow-up tests passed.
- 41 setup tests and51/55 readiness checks also passed during implementation (counts overlap).
- The final output guard preserves output_limit and never turns excess evidence into successful partial coverage.
- Live VDI, actual S:/UNC installation capacity and production authenticated Copilot remain unverified.
