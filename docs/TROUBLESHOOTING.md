# Troubleshooting

Start with the session's structured events and current status. Keep diagnostic data local and inspect only relevant permitted content. Never delete files as remediation or bypass organization/security controls. Retry budgets are finite; an uncertain send or side effect requires reconciliation before repetition.

| Symptom | Safe investigation and response |
|---|---|
| Edge does not start or CDP connection fails | Confirm configured Edge executable, dedicated profile and loopback port. Check the recorded launch/connection error. Do not attach an unrelated personal browser silently. |
| Copilot asks for sign-in | Sign in manually in the visible window. Do not extract browser cookies, credentials or tokens. |
| Model cannot be discovered/selected | Capture displayed names and actual UI state. Check isolated adapter selectors and permissions. Do not assume an example model exists. |
| Copilot reports daily access exhausted and switches to Auto | The selected model is unavailable. The app stops rather than silently accepting another model or sending format corrections. Start fresh setup, select an actually available model, or wait for the account allowance to return. |
| Headless/non-visible mode fails | Use tested visible operation. Authentication, file picker or download limitations must be reported, not bypassed. |
| Guidance or other file upload fails | Verify exact path, existence, size/type and policy. Inspect UI upload confirmation/error. A local existing file is not proof of upload. |
| Generation times out | Inspect new assistant container, streaming/stop state, text stability and error banners. Retain sanitized evidence. Do not use a long fixed sleep as proof of completion. |
| Submission may have succeeded | Reconcile submitted user-message containers/request identity. Do not blindly send again or roll back the count. |
| Envelope/JSON/schema validation fails | Preserve raw response; inspect classified errors. Allow only meaning-preserving extraction of one complete envelope, then bounded correction. Execute nothing from invalid content. |
| Tool name/version/input rejected | Compare with the current machine catalogue and schema. Ask Copilot to correct the same decision without expanding scope. |
| File path denied | Verify configured allowed roots, resolved path and declared plan. Do not extend access merely to make a request pass. |
| Code Runner rejects ordinary Python | The runner intentionally evaluates a limited Python AST language. Imports, shell, reflection, arbitrary attributes and network are unavailable. Rewrite within advertised capabilities or report the unsupported requirement. |
| Approval rejected or changed hash | Display a fresh complete immutable proposal and obtain new authorization when appropriate. Denial is final for that proposed execution; it is not an automatic retry failure. |
| Tool effect is uncertain after interruption | Inspect safe local evidence and intent/outcome records. Seek user review before repeating a write/click/script. |
| Findings seem absent | Check response validity, entry schema/provenance, privacy filtering and deduplication. Findings save immediately; their cumulative file is attached every tenth submitted message. |
| Counter differs from visible expectations | Count confirmed submitted user messages, including initialization/corrections/tool results. Do not count assistant responses, uploads, local approvals or polling. Inspect the persisted submission ledger. |
| Created monitoring says disabled | For the real live run only, configure `created_dir` inside your correct OneDrive account and enable `created_sync_enabled`. Engineering verification is deferred at the user's request; do not discover or inspect FNZ OneDrive folders. |
| Created file never appears locally after enabling | Check your explicitly configured OneDrive path, actual available creation capability and organizational delivery status. A preview is insufficient; bounded timeout is reported honestly. |
| Live reply preview appears before validation | Expected: it is attributed to Copilot and marked unvalidated. Only a complete validated envelope can dispatch actions. |
| Public text arrives in groups | The Copilot UI may buffer code-editor rendering. Field previews emit when readable; visible generation/status feedback continues. No hidden reasoning is requested. |
| Several synchronized files match | Request explicit disambiguation. Do not select arbitrarily or generate another duplicate file. |
| Session restart has pending work | Restore authoritative state and inspect uncertain intents. Do not treat old approvals or responses as fresh authority. A new chat must receive guidance/schema/catalogue again. |
| Retained artifacts consume disk space | Report disk usage and applicable scope. This application has no automatic deletion cleanup. |

## Reporting an issue

Provide the affected step, expected and observed behavior, session/request/call IDs, classified error, relevant version/configuration, sanitized log excerpt and local evidence paths. Do not paste credentials, cookies, full unrelated documents or sensitive screenshots. State whether the operation definitely failed, succeeded, or remains uncertain.

## Evidence limitations

A mocked test proves only the simulated path. A process exit code proves neither file delivery nor UI acceptance. Local synchronization requires a stable/readable matching file; real browser acceptance requires observed authorized UI behavior. Keep blocked and unexecuted steps explicit in the evidence report.
