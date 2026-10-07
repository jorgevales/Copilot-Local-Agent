# Architecture and components

## Component map

`Launcher.ps1` -> `app.py` -> `copilot_agent.app` -> `Orchestrator` -> `BrowserAdapter` -> visible Edge/Copilot UI

The orchestrator also coordinates `SessionState`, `PromptBuilder`, `ToolRegistry`, `Findings`, `AttachmentQueue`, approvals, persistence, synchronization, delivery, and diagnostics.

## Responsibilities

| Component | Verified responsibility | Key paths/symbols |
|---|---|---|
| Application shell | Interactive setup, session selection, console loop, clean exit, resume/new-session behavior. | `copilot_agent/app.py:run`, `start_new_session`, `main` |
| Orchestrator | Bounded conversation loop, response dispatch, corrections, approvals, retries, findings, terminal states. | `copilot_agent/orchestrator.py:Orchestrator` |
| Browser adapter | Dedicated/attached Edge lifecycle, CDP checks, model discovery/selection, upload, send, correlated capture, diagnostics. | `copilot_agent/browser.py:BrowserAdapter` |
| Reused browser startup | Edge discovery, loopback endpoint/profile ownership, bounded Playwright connection, owned-process cleanup. | `copilot_agent/reused_browser.py` |
| Protocol | Marker extraction, duplicate-key rejection, schema validation, identity checks, logical invariants, correction text. | `copilot_agent/protocol.py:parse_response` |
| State/persistence | Atomic JSON state, retained versions, event log, intent/outcome ledger, restart uncertainty. | `state.py:SessionState`, `persistence.py` |
| Policy/tools | Root/domain allowlists, schema validation, side-effect classification, tool execution and result caps. | `policy.py:PathPolicy`, `URLPolicy`; `tools.py:ToolRegistry` |
| Code execution | Restricted AST subset and exact approved local-Python plan binding. | `code_runner.py:CodeRunner`; `local_python_runner.py:execute_local_python` |
| Attachments/prompts | Exact source hashing, queue limits, startup guidance bundling, compact context. | `attachments.py:AttachmentQueue`; `bundle.py:build_startup_attachments`; `prompts.py:PromptBuilder` |
| Delivery | User-intent classification, actual link/download binding, ZIP validation, create-only extraction. | `delivery.py`; `downloads.py:DownloadService`; `archives.py:ArchiveService` |
| Desktop | GDI PNG capture, viewer launch/tiling, independent title/bounds verification. | `desktop.py:capture_display`, `inspect_windows` |
| Storage/sync | OneDrive account discovery, per-machine profile/settings paths, deferred Created synchronization. | `storage.py`; `sync.py:CreatedSync` |
| Feedback/findings/logging | Attributed terminal output, redaction, immediate finding storage/deduplication, audit events. | `feedback.py:Feedback`; `findings.py:Findings`; `logging_utils.py:EventLog` |
| Bug reports | Separate restricted and allowlisted sanitized reports, file-origin mapping, retention, and integrity validation. | `copilot_agent/diagnostics.py:DiagnosticReports` |

## Trust boundaries

Copilot output, uploaded files, webpage content, OCR, generated scripts, and tool results are untrusted. The local application validates identity, schema, policy, path/domain scope, exact hashes, approval scope, and postconditions before effects. The Copilot control page is kept separate from the browser tool page. Uncertain submissions and uncertain state-changing calls are persisted and are not replayed automatically.

## Coupling and bridges

The graph identifies `Orchestrator`, `PolicyError`, `BrowserAdapter`, `ToolRegistry`, `PathPolicy`, `SessionState`, `Config`, and `redact()` as high-connectivity hubs. This is useful navigation evidence, not proof that the design is wrong. `Orchestrator` and `BrowserAdapter` are the highest-impact change areas because they bridge protocol, state, browser, tools, attachments, and recovery.

