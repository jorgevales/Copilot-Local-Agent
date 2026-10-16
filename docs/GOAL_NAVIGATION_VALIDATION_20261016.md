# Goal navigation validation — 16 October 2026

Implementation and reproduction commands: [GOAL_NAVIGATION.md](GOAL_NAVIGATION.md).
All results below are local/offline. No authenticated Copilot, production website,
live shared-drive persistence, laptop/VDI interaction or cloud model was exercised.

## Final checks

| Check | Result | Retained log under `runtime/` |
|---|---|---|
| Browser goal schema, freshness, targets, early stop, frames, dialogs and uncertainty | 16 passed, 74.260s | `goal-browser-final.log` |
| Goal orchestration, performance, privacy, result transport, REA session consistency and initialization preload | 36 passed, 150.346s | `goal-final-validation.log` |
| Existing session plan approval controls | 6 passed, 5.954s | `goal-session-approval-verified.log` |
| Additional compact transport assertion preserving current data and policy | 1 passed, 11.640s; overlaps the combined run | `goal-compact-transport-verified.log` |

The first three rows contain 58 distinct checks, including 28 new tests. Python
AST parsing passed for 87 implementation, tool and focused test files. `git diff
--check` passed. Existing line-ending conversion warnings are informational.

An earlier broader run passed 282 of 284 checks. Its two failures concerned
initialization overflow and persistence of a raw private user request; both are
included and passing in the final combined run. Follow-up checks also caught and
fixed redundant REA probing and oversized steering packets. The entire broader
suite was not repeated after those transport changes; this is a focused final
validation, not a claim that every repository test passed on the final tree.

Raw private conversation cannot become an overflow attachment. Repeated strategy
and routing prose, duplicate storage paths and older messages can be omitted to
fit transport, while current content, requirements, constraints, approvals and
unresolved operations remain intact. Oversized remaining conversation fails
before persistence or sending. Existing complete current tool-result attachment
transport remains supported and is covered by its regression tests.

## Reproducible benchmark evidence

Real headless browser, synthetic intercepted routes, alternating AB/BA order,
three runs per variant and scenario, no simulated decision delay:

| Scenario | Baseline median | Goal median | Scripted decision requests | Independent target checks |
|---|---:|---:|---:|---|
| Known predictable segments | 3925.896ms | 3357.371ms | 6 → 3 | 3/3 per variant |
| Branching discovery with only the next route exposed | 5288.696ms | 5322.113ms | 12 → 7 | 3/3 per variant |

Reports, images and numeric traces remain in
`runtime/navigation-known-verified-20261016/` and
`runtime/navigation-branching-verified-20261016/`. Each report records the executed
source hashes and Python, Playwright and browser versions. The known-route trace
was also processed successfully by `tools/report_navigation_performance.py`.

Fewer scripted exchanges are demonstrated. Branching discovery was slightly
slower locally; a live end-to-end improvement and unchanged production reliability
are unproven. No reasoning tokens, provider cost, GPU use or inaccessible resource
measurements are inferred. Missing measurements remain null. UI response spans
include service, network and frontend effects; they do not isolate model thinking.

## Handoff and next evidence

The deterministic six-file `Copilot handoff/full-discovery` package is refreshed
from the local Graphify extraction and current source inventory. It describes
architecture and does not prove live behavior. Changes remain local and require
a fresh agent process to load.

The next acceptance exercise is an authorized real complex website task with an
explicit target, repeated baseline/candidate runs, independently verified arrival,
full completion time and failure rate. Additional models, parallel workers and
laptop/VDI integration remain deferred until that evidence supports them.
