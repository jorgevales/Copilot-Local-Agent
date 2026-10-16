# NNCY known-task repeat — 16 October 2026

## Verified result

The actual local orchestrator and Microsoft 365 Copilot Chat created a second,
distinct synthetic patient and opened its new consultation at the initial
**Ficha de identificación** page. The repeat used the earlier learned route and
locators, with fresh synthetic inputs. No broad discovery, schema correction,
consultation completion, later clinical fields, agreement or signature ran in
this repeat. The earlier patient was not edited.

The verified seven-step browser plan ended with `side_effects_uncertain=false`,
zero locator retries and exact heading plus displayed-patient assertions.

| Stage | Observed UTC time | Duration |
|---|---|---|
| Retained-session startup to ready | 14:13:11–14:13:21 | about 10 seconds |
| New task submitted to verified website goal | 14:13:21–14:14:16 | about 55 seconds |
| Bounded form plan | 14:14:02–14:14:16 | about 14 seconds |
| Entire task, including knowledge save, explicit readback and final answer | 14:13:21–14:16:44 | about 203 seconds |

The website goal needed two decision requests: `browser.open`, then one
`browser.plan` containing checks, four fills, a consequential create/start click
and a non-editable heading capture. Knowledge maintenance and its confirmation
added reasoning exchanges; 55 seconds is not the full learning-cycle duration.
The earlier debugging run is not a controlled successful timing baseline.
One successful repeat does not establish repeatability or production reliability.

## Durable procedure

The agent saved and successfully read back immutable note
`640e3b5bb15cba21d68c7d96be722f8e5188e2bd2eb6fe52a030b4af7f525484`.
Independent local checking confirmed its filename matches the SHA-256 of its
bytes. Spanish labels are intact. It contains input slots, generic routes,
control labels, exact outcome assertions, stop point and observed timing;
it excludes the actual synthetic patient values and concrete record identifiers.

The reusable entry is `/pacientes/nuevo`; the stop route is
`/consultas/{consultation_id}/ficha`. The create/start control is
`Registrar e iniciar consulta ahora`. Success requires both
`Ficha de identificación` and `Paciente: {input_name}`; the bare patient name
alone is not the exact displayed paragraph.

At the user's request, every completed known task is now instructed to compare
full-task duration, decision rounds and reliability, retain earlier verified
procedures, and save a generic improved procedure. Partial or failed runs must
remain diagnostics. Saved knowledge remains evidence and requires a fresh live
entry check before reuse.

Small `knowledge.note` results now return the exact locally verified note body
as `verified_knowledge` with `readback_complete=true`, avoiding a redundant
model/lookup exchange. Larger notes retain the explicit readback tool. This
last optimization is covered offline; it was added after the live repeat.

## Fixes made during diagnosis

- Startup Y permits broader task-label changes and necessary intermediate
  actions, while exact prepared plan validation and record/origin checks remain.
- Browser-plan failures before actual dispatch return `not_started` and
  `side_effects_uncertain=false`; dispatched failures retain uncertainty.
- Semantic plan/target validation runs before dispatch and identifies the faulty
  step or assertion. Compact browser and knowledge construction references
  reduce repeated catalogue searches.
- Text postconditions read ordinary input values correctly. Startup Y also
  permits capturing authorized business inputs; credentials remain excluded.
- Reconnaissance prioritizes relevant form controls over repeated sidebar links.
- Transient server-error pages receive bounded passive recovery time, without
  another click or reload.
- Private prompt packing compacts repeated advice and losslessly encodes opaque
  attachment-audit rows; it preserves current data, scope and pending operations.
- Explicit local test mode skips the optional S: mapping probe. Storage-path
  descriptions resolve a mapping once per call, with no stale global cache.
- Numeric startup phases and current-turn elapsed/decision measurements expose
  time spent in setup and complete execution rather than early partial output.
- Recovered runs activate terminal steering. A new instruction supersedes an
  unexecuted captured proposal before its tools dispatch. `--resume-instruction`
  can supply that new goal during startup.

## Evidence and reproduction

The retained local test store is under
`%LOCALAPPDATA%/CopilotLocalAgent/live-navigation-tests/nncy-live-20261016-132322`.
Normal production S:/UNC storage was not changed. The agent exited cleanly;
the retained Edge profile and initial consultation page remain available.

Within session `8127d797a6b44438ad7e55d89964d40d`:

- `screenshots/89319d2e7ea54550a18d1a06ed4ab0cb-automatic.pdf`: live repeat BEFORE/AFTER evidence.
- `tool-results/tool-results-c198b94358d1452fba0e00467a0552f2-01.json`: verified plan and final route.
- `performance.jsonl`: numeric phases with hashed correlation identifiers.
- The note is in the exact site's scoped `notes` folder beneath `Discoveries knowledge`.

Focused tests and synthetic benchmark commands:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_y_browser_workflow tests.test_outbound_results tests.test_storage tests.test_app_startup_flow tests.test_terminal_input tests.test_centralized_knowledge tests.test_knowledge_repair -q
.\.venv\Scripts\python.exe -B tools\benchmark_goal_navigation.py --output runtime\benchmark-y-repeat --runs 2 --scenario known_segments
```

Final retained checks: 58 focused tests passed in 185.231 seconds
(`runtime/y-final-acceptance-tests.log`), and 17 learning/recovery checks passed
in 88.063 seconds (`runtime/y-learning-tests.log`). The two sets overlap;
these are separate successful invocations, not 75 distinct tests. An earlier
62-test browser/regression invocation also passed before the final learning
and startup changes. `git diff --check` passed.

The retained offline benchmark `runtime/benchmark-y-20261016/report.json` passed
four of four synthetic runs: median local times were 3818 ms for individual
actions and 3438 ms for goal continuations, with six versus three scripted
decisions. These are synthetic measurements with no live model wait or VDI.

## Subsequent runs and push checkpoint

A fresh independent chat retrieved the saved procedure automatically. Its resumed
run completed in 207.533 seconds after a final assertion required read-only
verification; this was not a speed improvement.

A separate GPT-5.6 Sol Quick response run verified all 11 plan steps with zero
retries and stopped at the initial consultation identification page. The complete
cycle took 125.325 seconds including knowledge saving, readback and final response,
versus about 203 seconds previously. Request-to-website completion was about
60 seconds, versus the earlier 55 seconds. Model and workflow changes are combined,
so the complete-cycle improvement cannot be attributed to the model alone. The
saved note's 40.829-second action-only comparison needs correction before reuse
as comparative timing evidence.

A 56-test procedure/browser regression invocation passed before the latest
automatic template persistence changes. Those latest changes and their template
metadata deduplication are not yet fully tested. This checkpoint is pushed at the
user's explicit request before all tests finish. The generated full-discovery
snapshot predates the latest procedure-memory additions; its refresh is pending.
