# Copilot Agent Workspace

## Status
This is the optional graphical interface to the existing Copilot Local Agent. **Start Agent UI.cmd** asks whether to run the live repository or the Copilot testing environment, then launches that exact source copy. **Start Agent.cmd** remains the terminal fallback. Both use the same policy-controlled orchestrator, session evidence, isolated browser, approvals and diagnostic handling; the UI does not create a second agent or bypass approval.

## Install
The separate launcher requires normal project setup. The UI server uses Python standard-library modules; no Node installation, package download, administrator rights, model API key or external font/CDN is required.

Double-click **Start Agent UI.cmd**.

The launcher asks which project version to run, then starts an authenticated local server on loopback and opens the workspace in your default browser. This UI port is separate from Edge debugging; it never takes over the Copilot browser. The launch token stays in page memory and is removed from the address bar. Keep the launcher window open. Closing it denies pending approvals and ends the agent session; it cannot roll back an action already submitted.

## Implemented
- A cohesive light workspace palette and compact display mode.
- Collapsible navigation and context panels; responsive layout.
- Safe Markdown subset, code copy, basic tables and lists; raw HTML is inert.
- Structured message, tool, plan, error, warning, artifact and status cards.
- Backend event inspector, reported timings, model verification indicator.
- Explicit immutable approval review, with exact backend plan/call hash checks.
- Multiline draft composer, templates, search, in-memory bookmarks, command palette.
- Export review for visible UI transcript; clear-view does not clear backend context.
- Keyboard focus, reduced-motion and high-contrast support.
- Local bearer authentication, Host/Origin checks, no external assets or telemetry.
- New-session and native attachment-picker actions use the existing agent commands. Stop, model switching and resume are disabled because the backend does not expose safe operations for them. Voice is unavailable.

## Limitations
- Backend conversation history, pinned sessions, durable bookmarks or saved workflows.
- Model switching, resume and mid-action cancellation are unsupported. Use a new session or close the launcher; uncertain actions still require reconciliation.
- Full CommonMark, syntax highlighting, resizable panel splitters, large-session virtualisation.
- Production accessibility/security audit and live Windows/VDI acceptance. Automated tests are synthetic, not target-VDI acceptance.

## Runtime integration

`agent_ui.runtime` adapts the existing application prompt loop, orchestrator events and exact approval callback. Its actions enqueue existing `:new` and `:attach` commands; it does not create another event loop or execute tools itself. The server runs on loopback with a per-launch bearer token, strict Host/Origin checks, a restrictive content security policy and no external assets or telemetry. Raw reasoning is not emitted to the UI.

Backend policy, exact approval hashes, uncertainty and persistence remain authoritative. UI decisions are user input only. The workspace does not send model requests without the connected runtime.

## Event payloads
All events use `emit(kind, payload)`; payloads must be JSON objects.
- `copilot` / `user`: `text`
- `system` / `error` / `warning`: `summary`, optional `details`
- `status`: `state`, `summary`
- `tool`: `name`, `status`, optional measured `duration_ms`, `summary`, `result`
- `plan`: `title`, `steps` with `step`, `action`, `verification`, `status`
- `context`: redacted authoritative requirements/constraints/findings
- `model`: `name`, `verified` (true only after backend verification)
- `session`: `title`, redacted session metadata
- `artifact`: actual backend evidence; UI does not manufacture download links

Do not emit a success until backend evidence supports it. `uncertain` is not `failed` or `complete`.

## Validation
From the project root:

```powershell
python -B -m unittest discover -s agent_ui\tests -v
```

Tests use synthetic inputs and a local fake runtime only. They do not establish target-VDI acceptance or production accessibility. The UI keeps up to 5,000 events in memory; authoritative long-term history remains the backend's responsibility.
