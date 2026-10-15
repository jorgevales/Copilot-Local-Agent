# Project briefing

## Purpose and operating boundary

Copilot Local Agent is a Windows/VDI application that uses visible Microsoft Edge automation to interact with Microsoft 365 Copilot. It validates structured Copilot responses and mediates local tools, file access, code execution, downloads, persistence, and delivery through explicit policy and approval controls. It does not call a reasoning-model API. The visible browser and approved local execution environment are part of the runtime contract.

Sources: `README.md`; `copilot_agent/app.py`; `copilot_agent/orchestrator.py`; `copilot_agent/browser.py`; `copilot_agent/protocol.py`; `copilot_agent/tools.py`.

## Entry points and main execution path

- Setup: `Setup.cmd` -> `Launcher.ps1` launcher configuration (`Launcher.ps1 -Mode Setup`).
- Terminal runtime: `Start Agent.cmd` -> `Launcher.ps1 -Mode Start` -> `Launcher.ps1 -> app.py -> copilot_agent.app -> Orchestrator -> BrowserAdapter -> visible Edge/Copilot UI`.
- Graphical runtime: `Start Agent UI.cmd -> Launcher.ps1 -Mode UI -> agent_ui.runtime -> existing Orchestrator`.
- Tests: `Run Tests.cmd` -> `Launcher.ps1 -Mode Tests`; the repository test suite uses `unittest`.
- The launcher owns environment/resource validation. The orchestrator owns request state, policy dispatch, approval, retries, recovery, and completion. The browser adapter owns the visible Copilot exchange.

## Core turn and trust flow

`user request -> prompt/context assembly -> reviewed attachments -> visible Copilot send -> correlated response capture -> strict protocol/schema validation -> policy and approval -> bounded tool execution -> persisted evidence -> next Copilot turn or final response`.

Copilot text, files, pages, OCR and tool results are untrusted inputs. Graph edges marked inferred are navigation hypotheses. A successful launch, offline test or zero exit code does not establish live VDI, Copilot, shared-drive or production success.

Sources: `copilot_agent/orchestrator.py`, `copilot_agent/browser.py`, `copilot_agent/protocol.py`, `copilot_agent/policy.py`, `copilot_agent/tools.py`, `guidance/`, `docs/THREAT_MODEL.md`, `docs/KNOWN_LIMITATIONS.md`.

## Major component boundaries

| Boundary | Responsibility | Source locations |
|---|---|---|
| Launch and configuration | Setup/start/test modes, Python/Edge discovery, config validation and storage roots. | `Launcher.ps1`; `copilot_agent/app.py`; `copilot_agent/config.py`; `copilot_agent/storage.py` |
| Conversation control | Structured turn state, dispatch, approval, retries, uncertainty and findings. | `copilot_agent/orchestrator.py`; `copilot_agent/state.py`; `copilot_agent/approvals.py` |
| Copilot transport | Visible Edge/CDP lifecycle, attachment upload, send and correlated response capture. | `copilot_agent/browser.py`; `copilot_agent/reused_browser.py`; `copilot_agent/attachments.py` |
| Protocol and policy | JSON envelope validation, tool schemas, path/domain scope and side-effect decisions. | `copilot_agent/protocol.py`; `schemas/`; `copilot_agent/policy.py`; `copilot_agent/tools.py` |
| Execution and delivery | Restricted/approved code, downloads, archives, delivery checks and display actions. | `copilot_agent/code_runner.py`; `copilot_agent/local_python_*`; `copilot_agent/downloads.py`; `copilot_agent/archives.py`; `copilot_agent/delivery.py`; `copilot_agent/desktop.py` |
| Graphical front end | Local authenticated UI that submits to the same runtime and approval path. | `agent_ui/runtime.py`; `agent_ui/workspace.py`; `agent_ui/web/` |

## Runtime assumptions and limits

- Visible Edge/Copilot operation and manual completion of interactive sign-in are required; headless operation is not established.
- Shared S: workflows require the checkout to resolve to the expected UNC share; the application fails closed when that identity is unavailable.
- `local_python` is approved host execution with defense in depth, not an operating-system sandbox.
- Production, VDI, current Copilot UI, downloads, physical displays and mapped-drive behavior require fresh target-environment evidence.
- Repository history and configuration vary over time. This package analyzes source revision `af0afd151bde4cd635e94d046adc706aaaae7165`.

## Source understanding and packaging decision

The source scan found 277 eligible text files. Project docs and guidance are included verbatim, along with compact launchers, the safe example config, and the response schema. Python modules are represented by their paths, AST-derived imports and symbols, and Graphify relationships; implementation bodies are summarized rather than copied. The repository contains multiple megabytes of source, so a verbatim code mirror would consume the model context without improving the initial architectural map. Exact source remains identifiable by stable repository-relative path and hash in the manifest.

No additional project files are needed to understand the package's essential architecture, workflows, security boundaries, configuration, operations or known limits. This statement does not claim the handoff contains full source code.
