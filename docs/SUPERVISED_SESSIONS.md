# Fast scoped discovery sessions

## Startup Y and known tasks

Startup Y approves validated current-session plans, broader task-label changes
and necessary intermediate actions without another plan prompt. The current
prepared hash still binds each execution; origin, record identity, tool schemas,
actual OS access, manual authentication and uncertain-effect checks still apply.
The narrower default approval statements below apply when that session plan
grant is absent. A fresh session resets the grant.

Repeated tasks should reuse the shortest verified procedure with fresh inputs,
check the live entry state, execute bounded known segments and learn only from
the verified full goal. Compare complete timing and reliability, retain earlier
verified versions, and save useful generic procedure revisions after completion.
Small note saves return the exact verified readback body immediately; another
lookup is unnecessary when `readback_complete=true`.

Live evidence: [NNCY known-task repeat](NNCY_KNOWN_TASK_LIVE_TEST_20261016.md).

Normal startup asks once for the current investigation/session. `--yes-setup`
accepts this same grant. It is in memory and is never restored from persisted
state; restart and resume obtain a new confirmation. Revocation removes target
and automatic knowledge authority.

The grant runs read-only discovery immediately on explicit public HTTPS targets
named by the user and their approved domain/subdomain scope. Private/local
resources, unrelated origins and custom HTTP/port origins need explicit scope
approval. All requests still use ToolRegistry and the existing orchestrator.
Schemas, owned tabs, path checks, size/time limits, Stop and uncertainty remain
active. Independent read-only filesystem/artifact calls and observations on
distinct owned tabs run with bounded concurrency.

Useful new sanitized knowledge is saved automatically through knowledge tools
in the resolved S:/UNC Discoveries knowledge root, without a second writing
confirmation. Empty, noisy and duplicate notes are skipped. Other file writes,
website transactions, code execution and consequential actions retain concise
approval. Package quality/identity validation is preserved. File deletion and
credential-store access remain unavailable.

`browser.login_once` permits one uniquely identified prefilled login-button
click per exact approved origin. It uses the browser's existing session, never
extracts/types/saves credentials, and pauses for denial, failure, MFA, captcha or
unverified success. Further attempts need the user; general click/JavaScript
calls cannot claim this special authorization.

Approval option 4 approves the displayed exact action once and enables the
scoped discovery grant. It never preauthorizes future writes or changed code.
Knowledge results and webpage content cannot extend target or execution access.

REA process/cleanup uncertainty blocks further execution until resolved; a
read-only target does not prove a process has stopped. Failed or partial research
retains evidence and safe alternative recommendations. A denial cannot be
bypassed through another tool.

## Local inspection attachments

Use `files.attach` with `paths` (up to 1000 explicit supported file paths) to
attach files through the orchestrator, including files outside project roots.
Existing OS access, credential/profile protection and tool approval still apply.
Each file is bounded by the configured attachment size (100 MiB by default),
checked for exact SHA-256 and staged for upload. Duplicate basenames receive
unique send-only aliases recorded in the upload manifest. Originals are never
renamed or edited. Unsupported files and ZIP uploads retain their existing checks.
Browser upload and exact attachment verification use a configurable 600-second
timeout by default, independent of the Copilot response timeout.

Overflow is sent automatically as context-only batches of 18 files before the
final task message, reserving slots for transport/evidence within Copilot's
20-attachment cap. Batch replies never dispatch tool calls. Pending file entries
are removed only on confirmed send; an ambiguous send stops continuation for
reconciliation. Queued status alone does not prove the UI accepted an upload.

`files.read` now accepts UTF-8 files up to 20 MiB, returns up to 1 MiB characters
by default, and supports `max_chars` (up to 20 MiB) plus character `offset` and
`next_offset` for continuation. The constrained code runner's read-file ceiling
is also 20 MiB; its existing output cap remains separate.
