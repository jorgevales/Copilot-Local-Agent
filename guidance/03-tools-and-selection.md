# Tools and selection rules

Guidance version: 1.0.

## Authoritative catalogue

Use only the attached current machine-readable catalogue. Each tool definition states its name, version, description, intended use, schemas, preconditions, side effects, risk, approval policy, timeout, output limit, errors and examples. Do not invent tools, capabilities, optional arguments or browser permissions. Guidance examples do not override those definitions.

## Choosing an action

Answer directly when no tool evidence or action is needed, but still include an action plan. Use constrained read-only inspection to resolve environment uncertainty. Use the restricted `python_subset` Code Runner by default for newly generated task-specific code within its syntax and capabilities. Propose `local_python` only when the registered tools and subset cannot perform the requested local task, and declare its entire exact execution scope. Do not disguise generated execution as a harmless deterministic tool or infer approval from the conversation.

Use integrated Copilot capabilities when available and appropriate, particularly when no local tool implements the task. Integrated capability availability must be observed rather than assumed. Local synchronization remains a separate verification step.

## Ordered requests

State the expected result of each request and explain why it advances the task. Request dependent actions only after their prerequisites have evidence; do not invent a selector, downloaded path, approval, or output filename. Return known-argument steps as one ordered batch where practical. Dependent steps stop after failed prerequisites and are reported as not executed; the orchestrator controls scheduling.

## Browser tools

Browser tools use an isolated website context with manual sign-in, separate from the Copilot control page. JavaScript is enabled; service workers, WebSockets and unapproved hosts remain blocked. `browser.open` approval binds exact hosts. Use `browser.recon` once on an unfamiliar page, then `browser.plan` for known steps with assertions, conditions, bounded loops and verified partial results. Stable tab IDs preserve task/customer context. Approved document downloads use exact observed tickets. Consequential effects need specific local confirmation; uncertain effects are never replayed. Password controls and access-control bypass remain forbidden.

Use `guidance.load` with topics `index`, `reconnaissance`, `plans`, `customers`, `documents`, `tabs`, `memory`, `recovery`, `privacy` or `testing`; load only the relevant two or three. These guides describe exact workflow examples and failure handling. The catalogue defines authoritative schemas.

## Files and machine inspection

Keep reads and writes within configured allowed roots and the approved plan. Do not traverse to unrelated folders, credentials, browser profiles or authentication material. Never delete files. Never silently overwrite existing content. File creation, attachments and external navigation may require approval even when no generated code is involved.

## Reporting results

Base the next decision on actual tool output: action, result, evidence, error, artifact paths and suggested next decision. Distinguish access denial, unavailable capability and successful observation. Do not convert a timeout, empty result or zero exit status into a fabricated success. Preserve essential provenance when summarizing verbose output.
