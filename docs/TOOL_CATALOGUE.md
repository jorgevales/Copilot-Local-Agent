# Tool catalogue

The complete versioned machine-readable definitions are in `schemas/tool-catalogue-v1.json`; runtime setup regenerates the current catalogue from `ToolRegistry` and verifies its attachment hash. Each definition includes intended use, input/output schemas, preconditions, side effects, risk, approval, timeout, output limits, errors and examples.

| Family | Capabilities | Authorization |
|---|---|---|
| Files | List, existence, bounded text read, metadata, SHA-256 | Read-only within configured resolved roots |
| Files | Create, append, copy, mkdir | Displayed per-execution or immutable plan approval; create/copy never overwrite |
| System | Exact current Python executable/version, OS/package/browser versions, allowed-path disk capacity, current agent process | Read-only; no unrelated environment variables or credentials |
| Browser | URL/title, visible text, structured controls, errors and observed downloads | Read-only on an isolated owned page |
| Browser | Open/back/forward, click, fill, scroll, screenshots | Explicit approval; exact HTTPS domain policy covers redirects, resources and popups |
| Copilot delivery | Actual current-response artifact download after inspecting Edge settings; permanent verified OneDrive target | Immutable observed-artifact approval; strict HTTPS/native-blob binding |
| Archives | ZIP manifest and hash inspection | Read-only within permitted roots |
| Archives | Complete-manifest extraction and static output verification | Reviewed hash/destination approval; create-only inside selected OneDrive; no code execution |
| Images | Supported local image queued for verified Copilot attachment/analysis | Approval bound to exact file hash; does not claim local OCR or guaranteed integrated availability |
| Created files | Baseline snapshot and stable/readable matching-output polling | Disabled until explicitly configured/enabled for the chosen OneDrive directory; no access while disabled and no cloud-delivery assumption |
| Code Runner | Restricted default `python_subset`; or explicit `local_python` with declared imports, installed libraries, scoped files/HTTPS/processes/desktop effects, bounded runtime and independent output/window verification | Full immutable generated proposal review; user denial/once/exact displayed plan; no standing approval |

Ordinary browser tools cannot control the Copilot chat tab. The separate website context enables JavaScript, blocks service workers/WebSockets and requires manual sign-in. Downloads need exact observed-source grants; other download events are canceled. Oversized private observations stay ephemeral with scoped follow-up references. Policies and verification failures are returned honestly.

Website capabilities include `browser.recon`, `browser.route`, `browser.plan`, `browser.tabs`, `browser.customer_summary`, `browser.documents` and `browser.download_batch`. `documents.catalogue/find/retrieve` keep large collections accessible; `files.transfer_to_copilot` ranks and queues relevant hash-bound files within the 20-total-file transport cap. `site_knowledge.bind/retrieve/query/save/invalidate/export` isolate optional approved navigation memory. `guidance.load` routes to concise workflow instructions. See [upgrade evidence](WEBSITE_UPGRADE_REPORT.md).

`python_subset` supports advertised basic builtins and `read_file`/`write_file`. It excludes imports, functions/classes, arbitrary attributes, reflection, host execution, shell/subprocess/network activity and deletion.

`local_python` is the separately approved mode for tasks the registered tools and subset cannot perform. Its proposal binds the current interpreter, exact script/argv/imports, read/create/modify scope, canonical HTTPS destinations, exact child vectors, desktop permissions/viewers, limits and expected effects. The worker applies a scrubbed environment, Python audit hooks, bounded asynchronous output, timeout/cancellation cleanup and retained audit records. Native libraries mean this is not an OS sandbox. The Windows desktop helper can enumerate displays, create separate PNG captures, launch managed viewers and independently verify exact visible titles/bounds on a target display.
