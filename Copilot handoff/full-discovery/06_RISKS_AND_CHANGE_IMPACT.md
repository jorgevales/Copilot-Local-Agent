# Risks and change impact

## Verified limitations

- Visible authenticated Edge is the supported Copilot mode; headless operation is not established.
- Copilot may return malformed or misleading content; local validation and human approval remain authoritative.
- Model availability, labels, quotas, tenant behavior, and UI selectors can change.
- `local_python` is not Windows Sandbox or a full OS security boundary; native extensions and a trusted local machine remain residual risks.
- Physical display capture/viewer placement requires an unlocked Windows desktop, available displays, GDI/Tk access, and organizational permission.
- Created-folder monitoring is disabled until the user explicitly configures an approved OneDrive directory; local paths do not prove cloud synchronization.
- Browser and download behavior is environment-specific. Offline mocks do not prove production UI, VDI, or delivery behavior.
- Internal bug reports include filtered error context and source-relative frames; send them only to authorized Copilot. Sanitized reports use an allowlist and require manual review before external sharing.

## High-impact change areas

1. `copilot_agent/orchestrator.py` — changing dispatch, retry, approval, counting, or uncertainty can affect every capability.
2. `copilot_agent/browser.py` and `reused_browser.py` — selector, correlation, endpoint, profile, or ownership changes affect all Copilot interaction.
3. `protocol.py` and both JSON schemas — contract changes can make every response invalid or authorize the wrong structure.
4. `tools.py`, `policy.py`, `code_runner.py`, and `local_python_*` — security boundary and approval scope.
5. `state.py`, `persistence.py`, `logging_utils.py` — replay, atomicity, retention, redaction, and recovery behavior.
6. `bundle.py`, `prompts.py`, and guidance files — startup context completeness, exact-byte integrity, attachment capacity, and model behavior.
7. `downloads.py`, `archives.py`, `delivery.py`, `sync.py` — artifact identity, extraction, and completion claims.
8. `Launcher.ps1`, `storage.py`, `config.py`, and requirements lock — shared-drive deployment and per-user runtime assumptions.

## Technical debt / review points

- The application has many cross-cutting policy/state/browser responsibilities, reflected by Graphify hubs and low-cohesion communities. Refactors need focused regression tests.
- Graphify reported 264 inferred edges and 19 thin communities omitted from the report. Treat these as navigation leads, not facts.
- Live acceptance evidence is retained in runtime storage outside source and must be refreshed for target VDI, physical display, delivery, synchronization, and current Copilot UI behavior.
- The project intentionally retains logs, history, diagnostics, and test artifacts; storage retention is an operational responsibility.

## Security review checklist for proposals

Preserve exact source/plan hashes, approval binding, path/domain allowlists, loopback/profile ownership, no-deletion rules, fail-closed behavior, uncertainty handling, redaction, current-artifact download binding, create-only extraction, and independent postcondition verification. Never claim a live or remote result from a local test.

