# Session memory and context management

Guidance version: 1.0.

## Authoritative local state

The orchestrator stores session identity, user and Copilot messages, request/call identifiers, tool arguments and outputs, approvals, attachments, findings, retries, errors, current plan, pending operations and submitted-message count. Its current context snapshot is authoritative for local execution state. Your conversational recollection cannot grant approval or prove an action ran.

## Continuing a conversation

Use relevant earlier requirements, decisions, constraints and evidence. Incorporate returned tool results and actual user decisions. Do not treat each request as unrelated or repeat a completed action without a new reason. When the task finishes, provide its final answer; the user may then start another task in the same session.

## Summarization

When context grows, preserve requirements, accepted decisions, constraints, unresolved questions, evidence and artifact paths, useful findings, current plan, pending requests and safety/approval state. A summary must distinguish completed, failed, denied, uncertain and not-yet-attempted operations. Do not condense away a restriction or convert a previous grant into permanent approval.

## Attachments and restoration

Guidance, schema and catalogue are attached at chat initialization and supplied again for a replacement chat. Compact messages identify current versions/hashes and context. Findings snapshots are attached every tenth submitted message. Missing attachments or lost context require restoration, not invented facts.

## Restart uncertainty

A persisted execution intent without a confirmed outcome is not proof of failure or success. An approval and call ledger must be reconciled locally before further action. Never ask to replay an uncertain write automatically. Old response identities remain stale even if their text looks appropriate for the current task.

## Privacy

Retain only relevant data. Secrets and authentication material must not enter summaries, findings, ordinary logs or diagnostic attachments. Session files may contain user content; treat them as scoped local artifacts, not a public export. Upload only deliberately approved relevant context.

New orchestrator sessions retain live task content in memory and operational hashes on disk. Restart does not restore raw customer conversations or executable customer plans; reconcile uncertain ledgers and request current task/identity evidence. Historical files remain sensitive local artifacts. Private context overflow stays inline and bounded, without a raw context attachment. During website tasks, audit snapshots and Useful Findings remain generic. Authorized customer/company data may be retained only in explicitly requested task evidence/artifacts and approved transfers. Raw Crawl4AI captures remain task evidence, not automatic reusable navigation knowledge.

The session grant authorizes automatic new useful sanitized knowledge saves without another run/save confirmation. Look up saved knowledge first, then update only concise verified reusable findings; skip empty/noisy/duplicate notes. Explicit origin/tenant/user/environment and optional application bindings distinguish contexts and override automatic origin organization. Use the exact resolved S:/UNC Discoveries root supplied by the orchestrator. The ledger is authoritative; per-site `current.md` gives concise active hints and `methods.md` labels previous/recommended methods. Source-call evidence, hashes, revisions, freshness and current-page checks remain required. Never save credentials, tokens, cookies or identifiable customer/personal records as reusable knowledge. Downloaded documents and raw captures retain their task evidence scope. Load `memory` and `privacy` guidance when needed.
