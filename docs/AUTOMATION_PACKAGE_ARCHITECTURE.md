# Automation package architecture map

Discovery completed before implementation. The map combines the checked-in
`Copilot handoff/full-discovery/` with source inspection at `c5cb076`; Graphify
is navigation evidence and was generated from `a42e4e1`, so source wins where
the checkout has moved on.

## Current system

```text
Launcher.ps1 -> app.py -> copilot_agent.app -> Orchestrator
  -> PromptBuilder / BrowserAdapter / response-v1 protocol
  -> ToolRegistry -> approvals, local tools, SessionState and EventLog
  -> BrowserAdapter -> visible authenticated Copilot Chat
```

- `copilot_agent/orchestrator.py` owns each request/response loop, protocol
  validation, tool dispatch, cancellation, retries and recovery.
- `copilot_agent/prompts.py`, `bundle.py`, `schemas/response-v1.schema.json`,
  and `schemas/tool-catalogue-v1.json` define the agent contract and the
  capabilities exposed to Copilot. `ToolRegistry` definitions are generated
  from `copilot_agent/tools.py`.
- `ApprovalManager` binds a decision to the immutable pending call or complete
  prepared plan. `SessionState` persists evidence, but clears approvals on
  resume. The terminal and `agent_ui` approval surfaces both return explicit
  decisions; the backend remains authoritative.
- `CodeRunner` validates the reviewed source and scope. `local_python_runner`
  starts its fixed worker with exact interpreter, source, permissions, process,
  path, timeout and output bindings. Its worker adds defense in depth; it is
  not an operating-system sandbox.
- `copilot.download` binds a real artifact link in the current Copilot response.
  `ArchiveService` validates ZIP paths, aliases, sizes and hashes, then extracts
  create-only into configured allowed roots. The current contract explicitly
  stops before executing delivered code.
- `discovery_engine.py` and `discovery_store.py` already provide a bounded,
  resumable dependency graph with concurrency, retries, checkpoints and
  persistent evidence for public-site discovery. This is a domain-specific
  workflow and does not accept arbitrary package stages.

## Proposed extension points

1. Add a measurable local task router and configurable thresholds. Record its
   factors, score and decision in the run event/state, and pass the decision to
   `PromptBuilder` so the model follows the same route.
2. Add a versioned automation-package contract and runtime beside the existing
   delivery/archive code. Reuse `ArchiveService`, `PathPolicy`, `ToolRegistry`,
   and the fixed local-Python worker; do not make raw ZIP extraction itself an
   execution permission.
3. Add a package-run tool. Preflight the complete manifest, payload hashes,
   tool references, dependency availability, stage DAG, declared capabilities,
   outputs and configured budgets before requesting approval.
4. Extend approvals with bounded, explicit package/task scopes tied to the
   reviewed package revision, tool and capability set, paths, network hosts,
   resource limits and expiry. A changed revision or enlarged scope requires a
   new decision. Preserve the existing once/plan choices for current tools.
5. Implement stage-level fingerprints, durable checkpoints, bounded retry and
   cancellation, dependency-aware invalidation, patch decisions and structured
   results within the package runtime. Keep package output and run evidence in
   the configured test workspace for the proof.
6. Update the Copilot instructions/catalogue and approval presentation without
   weakening response-schema validation, exact source hashes, effect checks,
   uncertainty quarantine, redaction or existing direct execution.

## Files to change after this map

- New: package schema and focused `copilot_agent` router/package runtime modules.
- Existing runtime: `copilot_agent/tools.py`, `orchestrator.py`, `prompts.py`,
  `approvals.py`, `state.py`, `code_runner.py` or its fixed worker as inspection
  indicates, and `config.py`/`config.example.json` for bounded thresholds.
- Agent contract: relevant `guidance/` files and generated machine tool
  catalogue through `ToolRegistry`.
- Approval UI, only as needed for the scoped grant: `agent_ui/workspace.py`,
  `agent_ui/runtime.py`, and `agent_ui/web/app.js`.
- Validation: focused deterministic `tests/test_*.py` modules and a dedicated
  C:-based integration workspace. Existing production session data and the S:
  drive are outside that proof workspace.

## Constraints found

- The worktree was clean on `main` at `c5cb076` during discovery.
- Python tests use `unittest`; the handoff's `133 passed, 1 skipped` is a prior
  local result, not a baseline run for this change.
- Normal app startup anchors persistent knowledge/runtime storage to the live
  S: mapping. A proof that must avoid S: needs an explicit isolated test-mode
  storage path; production storage behavior must remain unchanged.
- Copilot output and package contents are untrusted. Existing approval controls,
  create-only behavior, finite limits, manual authentication and truthful
  completion evidence remain required.
