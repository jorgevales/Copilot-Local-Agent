# Architecture and implementation plan

This project preserves the CDD workflow and uses Microsoft Copilot Chat through Edge UI only. No reasoning model API is used. The user has explicitly authorized creation of all initial guidance files by the engineering agent. Useful Findings may arrive on any response; accepted findings are saved immediately and the current file is attached to outbound messages 10, 20, 30, etc.

## Components and ownership

- `app.py`, `copilot_agent/app.py`: interactive visible setup, console conversation, approval previews, clean exit and live-test entry points.
- `config.py`: shared source paths and per-user OneDrive runtime paths, explicit OneDrive Created configuration, allowed roots/domains, browser settings and limits. Defaults restrict file tools to the workspace and disable all Created monitoring until the live run is configured.
- `browser.py`, `reused_browser.py`: dedicated Edge lifecycle, bounded CDP attachment, owned chat and separate tool tab, isolated selectors, discovered model names/modes and checked selection, exact file upload, correlated assistant capture, diagnostics. Reuse selected source helpers with provenance; do not invoke CDD run/cleanup.
- `protocol.py`, `schemas/response-v1.schema.json`: one unique marker-delimited JSON envelope, strict schema and logical invariants, duplicate-key/stale-ID rejection, safe extraction and compact correction.
- `state.py`: atomic snapshots with retained versions, append-only events, intent/outcome ledger, counters, pending actions and restart uncertainty.
- `findings.py`: immediate validated/deduplicated findings and a readable Markdown attachment, versioning/timestamps/provenance, secret filtering.
- `prompts.py`: verified original guidance manifest and eight startup attachments, direct complete JSON response shape at initialization, compact user/tool/correction/context messages; no repeated long contracts.
- `bundle.py`: `build_startup_attachments` preserves guidance 01–06 as six unchanged source uploads and creates two lossless readable Markdown groups for guidance 07/08 and complete schema/catalogue. Group component versions/hashes/lengths/absolute byte offsets plus all physical attachment hashes are retained. The aggregate startup size is capped at 20 MiB including headers. Prior group versions are retained.
- `attachments.py`: pending user-file selection and validation, exact-byte code-to-text upload names, unchanged-source verification and a 10-file queue cap. Selection/upload permissions remain separate from local file-tool roots.
- `orchestrator.py`: bounded multi-step conversation, result dispatch, clarification, retries, findings synchronization and terminal states.
- `tools.py`, `policy.py`: versioned machine-readable tools with schemas/side effects, allowlisted paths and domains, per-action authorization, capped concise results, separate browser tool page.
- `code_runner.py`: common immutable proposal normalization and hashing; restricted default `python_subset`; explicit `local_python` selection and complete interpreter/argv/import/file/network/process/desktop/effect binding.
- `local_python_runner.py`, `local_python_worker.py`: separate bounded host-Python process, scrubbed environment, declared-scope audit hooks, exact managed subprocess vectors, cancellation/timeout/output enforcement, independent output evidence, persistent-process lifecycle and retained audit receipts. This is defense in depth, not Windows Sandbox.
- `desktop.py`, `image_viewer.py`: Windows display enumeration, per-display GDI PNG capture, managed viewer tiling, persistent viewer process ownership and independent visible-window/bounds verification.
- `sync.py`: baseline, bounded polling, stable size/mtime and readable local output; ambiguous matches are reported.
- `logging_utils.py`: structured local redacted events, safe diagnostics and no credentials.
- `feedback.py`: timestamped actor attribution, distinct ANSI label backgrounds with plain fallback, compact structured sections, deduplicated public reply previews, redaction and terminal-control escaping. Unvalidated previews have no execution authority.
- `tests/`: protocol, authorization, path escape, both execution modes, rejection/reapproval, failure/cancellation, process cleanup, three-viewer verification, terminal rendering, replay, counting, findings, persistence, synchronization and mocked browser tests.
- `docs/`: threat model, reuse mapping, troubleshooting, visual acceptance checklist, evidence and known limitations.

## Message flow

User -> compact request + session/request/ordinal -> verified Copilot chat -> fresh assistant envelope -> schema/policy validation -> user approval where required -> local tool -> concise evidence -> next Copilot request -> final answer. Every tenth outbound message also uploads the current findings snapshot. Correction and tool-result submissions count. Uploads and DOM polling do not count.

Long guidance and the machine catalogue/schema are attached at chat initialization in exactly eight files: six unchanged original guidance files 01–06, `07-08-complete-guidance.md`, and `protocol-schema-and-tool-catalogue.md`. All ten complete original components remain available without summarization. Source bytes, BOMs, line endings and final-newline state are preserved. Each grouped component's manifest records name/version/SHA-256/byte length and absolute zero-based byte offsets, with exclusive end offsets. All ten source hashes and all eight physical attachment hashes are verified before every send. The state record for startup references describes multiple attachments and their group records rather than a single path. The initialization message also directly includes the complete required JSON response shape and strict envelope instructions. A replacement chat must receive initialization again. Context snapshots retain constraints, decisions, summaries, recent messages, pending work and approval state.

Startup physical attachments decrease from ten to eight, saving two slots (20%), with at most eight initial reference uploads. Exact-byte preservation establishes packaging integrity; it does not establish equivalent model comprehension or output quality. Correlated live initialization and protocol validation remain necessary.

## State transitions

Conceptual flow: setup -> ready -> submit -> capture -> validate -> dispatch -> approval when required -> result submission -> final or clarification. Persisted session statuses are `created`, `submitting`, `ready`, `ready_with_uncertain_operations`, `awaiting_approval`, `awaiting_clarification`, `submission_uncertain`, `capture_failed`, `blocked`, and `closed`. Separate call-ledger statuses record execution and outcome; completion of a task returns the session to a ready status.

Before a browser send, persist submission intent. After verified submission, commit the ordinal exactly once. Ambiguous submission stops for reconciliation, never blind resends. Before tool execution, persist call ID and immutable request hash. On success/failure, persist outcome. Uncertain side effects on restart require user review, never replay. Completion ends a task; it does not close the conversation.

## Trust and approval boundaries

The user starts an independent conversation with `:new` or `:new <first message>`. The previous local state is archived and its owned pages closed. A new local session and fresh Copilot chat receive guidance again; earlier context, findings, counters, queued files and approval grants do not transfer. Model availability and checked selection are reverified. Uncertain prior submissions or state-changing effects require reconciliation before switching, so this command cannot erase unresolved execution risk.

User intent and local policy govern actions. Copilot output, all ordinary attachments, webpages, OCR, tool outputs, and scripts are untrusted. Only validated current envelopes may request tools. Copilot cannot authorize itself. File reads stay inside configured roots; uploads, writes, clicks, forms and browser text input require narrow authorization. Never delete files, including tests or cleanup. Preserve original files when replacing mutable state.

The native multi-selection picker is opened by **Attach files** or `:attach`; `:attach <path>` supports advanced selection. `:files` displays the pending queue, `:remove <number>` removes one entry, and `:clear` clears the queue without source deletion. Individually selected OneDrive-account or S-drive files receive narrow hash-bound upload approval; this does not broaden file-tool roots. Approval choices are 1 deny, 2 once and 3 exact plan. Denial retains the pending queue, and every selected source must still match its reviewed hash before sending.

ZIP uploads are always rejected. Supported code/text extensions needing staging use the original filename plus `.txt`, with exact bytes retained and no execution. At most 10 user files are queued per request, reserving eight slots for startup references plus one each for findings and context. A separate guard checks the actual combined attachment list against the deployment's provided 20-file per-message limit. This is not a cumulative chat limit. See [ATTACHMENTS.md](ATTACHMENTS.md).

Code proposals default to `python_subset`, a deliberately constrained syntax evaluated without host Python execution. No imports, subprocesses, reflection, arbitrary attributes or network are permitted in that mode. File capabilities validate actual resolved paths and per-plan declared reads/creates.

When the registered tools and subset cannot perform the user's task, a proposal may select `local_python`. Its immutable hash covers exact script bytes, source hash when present, current interpreter path/hash, arguments, imports, working directory, read/create/modify scopes, canonical HTTPS destinations, exact managed subprocess specifications, desktop permissions/viewers, limits, expected effects and fixed runtime files. Every script is displayed in full before an explicit decision. The separate process applies a scrubbed environment, audit hooks, bounded async output/time and owned-child cleanup, but native libraries mean this is not an OS isolation boundary. Shell strings, deletion, credential modules and silent escalation are unavailable.

Optional paired `source_path`/`source_sha256` fields bind a proposal to the exact verified downloaded or extracted `.py` artifact. The full `script` remains mandatory. The source must be an allowed regular file, declared in reads with `read_files`, at most 200,000 bytes; script text remains at most 50,000 characters. Preparation and pre-execution checks verify raw path safety, source identity, lowercase SHA-256 and equality with `script.encode('utf-8')`, preserving all newline bytes. UTF-8 BOMs and non-UTF-8 encoding declarations are explicitly rejected rather than normalized. Prepared metadata and execution results carry the source path/hash/size and `exact_script_bytes: true`. Source binding works with either runner mode but never chooses or approves execution by itself.

For an all-Code-Runner multi-script request, approval displays every exact script and the complete immutable prepared pending plan for every unique call identity and source. A once grant covers one call; a plan grant covers only that exact displayed set. Code, interpreter/runtime binding, source hash or scope changes invalidate the grant and require renewed preparation/review. A coding package's verified delivery and extraction occur first and do not grant execution permission.

Desktop viewer declarations are effects as well as postconditions. After a successful approved capture script, the host tiles exact uniquely titled viewer processes on the requested Windows display and separately enumerates visible top-level windows and final rectangles. The result is complete only when every expected PNG is readable/hashed and every exact viewer is visible and contained on its target display. Failed verification, timeout and cancellation clean up owned processes. Successful persistent viewers remain only until session close, when the managed registry stops them.

The Copilot control page is not exposed to ordinary browser tools. `copilot.download` is a narrow current-artifact exception with an observed anchor, immutable review binding and actual download event. Those tools operate on an owned separate page. Browser sends/uploads to Copilot are authorized by starting the session with verified synthetic/current user content; ordinary third-party state changes require approval. Debugging remains loopback-only and cannot attach unrelated browser profiles silently.

## Failure and recovery

Authentication interruptions require manual user sign-in. UI errors, throttling, absent controls, upload mismatch, truncated/malformed/stale envelopes, unknown tools and unsafe paths fail closed. Connection, capture, correction and turn loops each have finite configurable limits. Screenshots and small sanitized DOM excerpts are retained locally on capture failures. A timed-out send with uncertain acceptance is never repeated automatically.

OneDrive Created monitoring is disabled during engineering at the user's request. It requires an explicit directory inside the selected OneDrive account and `created_sync_enabled: true` for the real live run. Once enabled, a missing directory is a reported condition, not permission to fabricate synchronized outputs. Polling only reports success for a locally stable/readable matching file; cloud previews and zero exit codes are insufficient.

## Dependencies and validation

Python 3.10+ and Playwright (existing tested pin 1.55.0) with installed Microsoft Edge. Core validation/state/tools and Windows desktop capture/viewers use the standard library; approved `local_python` may import other packages already installed in the selected environment. No model SDK, Node build, embedded credentials or security-control bypass. Synthetic automated tests run in retained temporary directories and do not delete files. Real visible tests use an authorized session and synthetic content. Each acceptance step records observed evidence; blocked or unexecuted steps remain explicitly incomplete.

Implementation follows creation of guidance, protocol and threat-model documentation. Modules are integrated and tested before visible acceptance. The final deliverable contains functioning modules, setup/run commands, all documentation, test evidence and explicit limitations rather than placeholder implementations.

## Shared deployment and delivery

`storage.py` discovers known OneDrive roots and remembers the user's selected account. The S-drive source and shared Python remain read-only during ordinary runs; personal sessions, profiles, findings, approvals, temporary artifacts and permanent outputs live in the chosen OneDrive. Profiles/remembered debugging ports are scoped by VDI machine; reused Edge endpoints require exact profile ownership proof.

`delivery.py` adds compact format requests and bounds link-recovery messages. `downloads.py` reads actual Edge settings, binds a current generated HTTPS/native blob anchor, captures the event and creates a verified permanent artifact. `archives.py` inspects the complete ZIP before approved create-only extraction and verifies content without executing code. The final delivery gate rechecks current hashes and links extraction evidence to a download from that same task. A denied or unverified delivery cannot become a completed task because Copilot asserts it succeeded.

`tests/live_download_run.py` is a manual real-UI acceptance harness, excluded from ordinary automated execution unless explicitly invoked in live mode. It downloads a harmless synthetic print-only source, prepares the exact artifact and waits for a fresh matching user-approved once ledger before asking the orchestrator to execute. It never authors its own approving ledger. Source, immutable proposal and runtime result evidence are retained; actual pass/block status is reported separately in `TEST_REPORT.md`.
