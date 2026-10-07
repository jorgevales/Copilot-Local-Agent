# Data and control flow

## Startup and initialization

1. The launcher validates the selected shared Python, project environment, lock file, PowerShell bootstrap, OneDrive account, and Edge path.
2. `copilot_agent.app.run()` loads `Config`, discovers or validates the selected storage, and chooses a free/remembered loopback port or an explicitly owned existing endpoint.
3. `start_new_session()` creates a fresh local session and owned chat/tool pages; resume restores state but preserves uncertainty and clears inherited approvals where required.
4. `PromptBuilder` verifies the ten complete guidance/schema/catalogue components and builds eight physical startup attachments: guidance 01-06 separately, then two lossless groups for 07-08 and schema/catalogue.
5. `BrowserAdapter.exchange()` sends the compact initialization/request and captures only a newly correlated assistant response.

## Normal turn

`user input -> PromptBuilder context -> BrowserAdapter upload/send -> correlated Copilot envelope -> protocol.parse_response -> Orchestrator dispatch`

For a no-tool response, the orchestrator validates the final result and returns the session to ready. For tool calls, it validates the catalogue/schema, checks path/domain and side-effect policy, obtains approval when required, executes through `ToolRegistry`, records evidence, and sends the bounded result back to Copilot for the next response.

## Response contract

The response must have one marker-delimited JSON envelope with matching session/request identity, a unique response ID, valid state/step structure, and permitted tool calls. `protocol.py` rejects duplicate keys, stale IDs, unknown values, non-finite values, truncation, inconsistent state, invalid booleans, and schema violations. Invalid or incomplete captures receive bounded correction; invalid content never authorizes a tool.

## State-changing actions

- Code execution requires a complete immutable proposal. The default `python_subset` is constrained; `local_python` additionally binds interpreter/hash, argv, imports, file scopes, network destinations, subprocess vectors, desktop effects, limits, expected effects, and worker files.
- Downloads bind an observed current link/anchor, exact name/hash expectations, actual browser download event, retained artifact, and delivery destination. Packages are inspected before create-only extraction; downloaded code is never auto-executed.
- Attachments are reviewed by exact path/size/hash and rechecked immediately before upload. ZIPs are not user uploads. Findings are saved immediately and the current snapshot is attached on the documented message cadence.
- Desktop capture is complete only when PNG evidence and independent visible-window title/bounds evidence both pass.

## Failure paths

Authentication, missing controls, model exhaustion, upload mismatch, malformed/stale envelopes, unsafe paths, unknown tools, failed postconditions, timeout, cancellation, and ambiguous effects fail closed. Bounded retry/correction budgets are recorded. A timeout after a possibly accepted send is `submission_uncertain`; the application does not resend blindly. Existing files are preserved and retained evidence is preferred to deletion.

Actionable exceptions set a `bug_fix` session flag and are recorded to separate internal and sanitized JSON reports without replacing the session's normal status. Reporting failures are contained. The interactive loop records unexpected per-turn errors and returns to the prompt; when the user exits, the terminal gives one short handoff reminder. Neither report is sent automatically. See `docs/DIAGNOSTICS.md` and `copilot_agent/diagnostics.py`.

## External interfaces

The project interfaces with Microsoft Copilot through visible Edge UI/CDP, Edge download events/settings, local OneDrive paths, Windows registry/process/network/display APIs, Playwright, and the configured package index during setup. It does not call a reasoning-model API.

