# Project overview

## Verified purpose

`Copilot Local Agent` is a Windows/VDI application that drives Microsoft 365 Copilot through a visible Edge browser UI. It maintains continuous conversation state, sends structured requests, validates Copilot responses, exposes controlled local tools, requires explicit approval for code/state-changing actions, persists session evidence, and maintains Useful Findings. It deliberately does not use a reasoning-model API.

The original CDD workflow is preserved as a separate project and is not part of this sample scope.

## Main capabilities

- Visible Copilot Chat through Playwright/CDP and a dedicated Edge profile.
- New sessions, resume handling, request/response correlation, bounded capture, and recovery.
- Marker-delimited JSON response protocol validated against `schemas/response-v1.schema.json`.
- Machine-readable tool catalogue in `schemas/tool-catalogue-v1.json`.
- Allowlisted file, browser, download, archive, synchronization, desktop, and inspection tools.
- `python_subset` Code Runner plus explicitly approved, exact-plan `local_python` execution.
- Exact-byte attachments, eight startup reference attachments, ten-file user queue, findings cadence, and source hashing.
- Event-backed download verification, ZIP inspection, create-only extraction, and delivery evidence.
- Windows display capture and independently verified managed viewers.
- Redacted event logs, retained state versions, approval ledgers, diagnostics, and audit receipts.

## Top-level structure

| Path | Responsibility |
|---|---|
| `app.py` | Thin command-line entry point importing `copilot_agent.app.main`. |
| `copilot_agent/` | Runtime implementation. |
| `tests/` | Offline unit/integration tests and explicitly named live acceptance harnesses. |
| `guidance/` | Copilot/orchestrator behavioral contracts and security rules. |
| `schemas/` | Response and tool JSON contracts. |
| `docs/` | Architecture, threat model, operations, evidence, delivery, and limitations. |
| `bootstrap/virtualenv.pyz` | Bundled environment bootstrap artifact used by the launcher. |
| `Launcher.ps1` | Setup/start/test orchestration and shared-runtime validation. |
| `Setup.cmd`, `Start Agent.cmd`, `Run Tests.cmd` | User-facing PowerShell launchers. |
| `config.example.json` | Safe configuration template with no secret values. |
| `requirements.lock.txt` | Exact runtime package pins. |

## Entry points and normal paths

1. `Setup.cmd` invokes `Launcher.ps1 -Mode Setup`.
2. `Start Agent.cmd` invokes `Launcher.ps1 -Mode Start`.
3. The launcher starts `app.py` with the selected shared Python and isolation flags.
4. `copilot_agent.app.main()` parses command-line arguments and calls `run()`.
5. `run()` selects storage/browser resources, creates or resumes a session, and starts `Orchestrator.run()`.
6. The orchestrator exchanges structured messages through `BrowserAdapter`, validates them, executes approved tools, and remains available for the next turn.

