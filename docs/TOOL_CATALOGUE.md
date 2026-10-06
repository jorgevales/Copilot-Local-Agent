# Tool catalogue

The complete versioned machine-readable definitions are in `schemas/tool-catalogue-v1.json`; runtime setup regenerates the current catalogue from `ToolRegistry` and verifies its attachment hash. Each definition includes intended use, input/output schemas, preconditions, side effects, risk, approval, timeout, output limits, errors and examples.

| Family | Capabilities | Authorization |
|---|---|---|
| Files | List, existence, bounded text read, metadata, SHA-256 | Read-only within configured resolved roots |
| Files | Create, append, copy, mkdir | Displayed per-execution or immutable plan approval; create/copy never overwrite |
| System | Python/OS/package/browser versions, allowed-path disk capacity, current agent process | Read-only; no unrelated environment variables or credentials |
| Browser | URL/title, visible text, structured controls, errors and observed downloads | Read-only on an isolated owned page |
| Browser | Open/back/forward, click, fill, scroll, screenshots | Explicit approval; exact HTTPS domain policy covers redirects, resources and popups |
| Copilot delivery | Actual current-response artifact download after inspecting Edge settings; permanent verified OneDrive target | Immutable observed-artifact approval; strict HTTPS/native-blob binding |
| Archives | ZIP manifest and hash inspection | Read-only within permitted roots |
| Archives | Complete-manifest extraction and static output verification | Reviewed hash/destination approval; create-only inside selected OneDrive; no code execution |
| Images | Supported local image queued for verified Copilot attachment/analysis | Approval bound to exact file hash; does not claim local OCR or guaranteed integrated availability |
| Created files | Baseline snapshot and stable/readable matching-output polling | Disabled until explicitly configured/enabled for the chosen OneDrive directory; no access while disabled and no cloud-delivery assumption |
| Code Runner | Restricted Python expressions, variables, conditions, loops and mediated declared-file reads/creates; downloaded `.py` source bound to its exact path, SHA-256 and script bytes | Full immutable generated proposal review; user denial/once/complete plan |

Ordinary browser tools cannot control the Copilot chat tab. `copilot.download` is a separate current-generated-artifact capability, bound to the observed link and actual event. Their context starts without existing-profile authentication; sign-in cannot be silently inherited. Website JavaScript/service workers are disabled and WebSockets blocked in this constrained context. Downloads are observed and canceled rather than silently saved. File-size/output limits are explicit. Oversized redacted tool results are retained locally and represented by a concise artifact reference. A policy or execution error is reported honestly to Copilot.

`python_subset` supports advertised basic builtins and `read_file`/`write_file`. It excludes imports, functions/classes, arbitrary attributes, reflection, general host execution, shell/subprocess/network activity and deletion. This is a functioning constrained interpreter, not an arbitrary Python sandbox. Unsupported tasks require a different explicitly reviewed implementation.
