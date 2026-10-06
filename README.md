# Copilot Local Agent

A Windows/VDI repository with continuous conversation, Microsoft 365 Copilot web UI reasoning, strictly validated responses, controlled tools, explicit code approval, retained session state and Useful Findings. The original CDD workflow is preserved. No reasoning API is used.

## Setup and run

Put the repository on the shared **S:** drive alongside the organisation's Python installation. Double-click **Setup.cmd**, choose **1: Automatic detection** or **2: Paste a path**, and select Python. You may paste the quoted full `python.exe` path or its installation folder. Setup creates or reuses the project's `.venv` and installs the pinned packages from `requirements.lock.txt`; then use **Start Agent.cmd**. On S:, the base Python and virtual environment remain shared on S:. No browser download is needed. See [SHARED_VDI.md](docs/SHARED_VDI.md).

First-run OneDrive selection also offers detection or pasting a registered account folder. Edge setup offers detection or pasting `msedge.exe` or its installation folder; failed detection falls back to a path prompt. Choices are remembered in your selected OneDrive, with Edge paths stored per VDI machine. **Start Agent.cmd** reuses valid saved resources. Rerun **Setup.cmd** to review Python and Edge choices. Dependencies need network access to the organization's configured package index and permission to create/update the project environment; errors stop setup with their actual cause.

The visible terminal shows setup, discovered exact model labels, plans, approval previews and answers. Complete sign-in/MFA yourself in the dedicated Edge window. Select a displayed model or accept the documented suggested choice. Visible operation is the only accepted mode; headless Copilot operation is not established.

Use `:new` for a new topic in an independent session and fresh Copilot UI chat, or `:new <first message>` to start it immediately. Previous records are retained; user context, findings, counters, attachment queues and approvals start fresh. Ordinary application launches also create a new session unless `--resume` is explicit. Reconcile uncertain earlier submissions or state-changing calls before switching.

Use `:exit` to end the session and `:status` for counts and findings. Use **Attach files** or `:attach` to open the native Windows picker and select several files for your next message. Advanced users can enter `:attach <path>`. Use `:files` to inspect the pending queue, `:remove <number>` to remove one pending entry, or `:clear` to clear it; these commands never delete source files. At most **10 user files per request** can be queued. See [ATTACHMENTS.md](docs/ATTACHMENTS.md) for formats, approval and limits.

Tool/code approvals offer **1: deny, 2: once, 3: plan** for the exact displayed scope. Denying an upload leaves the pending queue available for review. `--yes-setup` does not grant execution permission. Code Runner uses the documented `python_subset` interpreter, not arbitrary Python or shell execution.

## Configuration

Ordinary users start the shared launcher and use the settings remembered in their OneDrive. Operators may supply a configuration based on `config.example.json`; `storage_dir` must belong to a discovered OneDrive account. Defaults allow file tools inside your selected OneDrive workspace and delivery folder, and third-party browsing only on `example.com`. Copilot's own UI is controlled separately. Root expansion is a user configuration decision; Copilot cannot expand it.

Generated files use actual Copilot download links: Office files and full coding packages are requested as ZIPs; single non-Office files use direct links with ZIP fallback. Edge download settings are inspected before delivery, and permanent artifacts plus all ZIP extraction stay inside your selected OneDrive. Original archives are retained, outputs are verified, and delivered code never runs automatically. See [FILE_DELIVERY.md](docs/FILE_DELIVERY.md).

You can separately request execution of a verified downloaded `.py` file through Code Runner when its contents fit `python_subset`. The proposal keeps `script` mandatory and binds paired `source_path`/`source_sha256` fields to that exact artifact; the source must also appear in declared reads with `read_files` permission. Raw UTF-8 bytes, including newline bytes, must match exactly and are checked before approval and execution. For several supported scripts, review the full immutable prepared plan and choose **3: plan** for that exact set, or **2: once** for one call. Changed code, source hashes or scope require renewed approval. General Python projects with imports, dependencies or shell commands remain unsupported. The manual [download/run harness](tests/live_download_run.py) requires explicit live mode and a matching user-approved once ledger; it never authorizes execution itself. Its observed result belongs in [TEST_REPORT.md](docs/TEST_REPORT.md).

The earlier Created-file synchronization is deferred to your real live run. Set `created_dir` to `Documents\Copilot\Created` inside the correct FNZ OneDrive account and set `created_sync_enabled` to `true` when ready. Until then it stays disabled, including per-turn baselines and Created tools; the application does not discover or inspect Created folders. Account-root discovery for user storage is separate.

Advanced run: use the discovered shared Python executable with `-B app.py --config <settings-file>`. The source checkout remains separate from personal writable storage. Attach to a verified dedicated existing session using `--attach-existing --port <port> --profile <dedicated-profile-path>`. The port must belong to that exact Edge profile. Existing chats are not reused; the app owns a new chat tab and a separate tool tab. On exit those owned pages close and the existing browser/profile remain.

Resume: use that shared Python with `-B app.py --resume <your-OneDrive-runtime-session-path>`. A new chat receives the guidance again. Uncertain sends require explicit reconciliation, incomplete state-changing operations cannot silently replay, and execution grants are not inherited across restart.

## Guidance and memory

The terminal displays timestamped, attributed verbose feedback throughout the run: `User`, `Copilot (Agent)`, `Orchestrator`, `System`, and `Tool/<name>`. Public reply fields are streamed as soon as the UI exposes complete values; live previews are visibly marked unvalidated. Plans, approval decisions, execution starts, results, corrections and final answers are separately labelled. See [FEEDBACK.md](docs/FEEDBACK.md) for role definitions and rendering limits.

The eight behavioural Markdown files, response schema and current machine-readable tool catalogue are supplied once at initialization in **eight attachments**. Guidance 01–06 are uploaded unchanged as six separate files; `07-08-complete-guidance.md` contains the complete original guidance 07 and 08, and `protocol-schema-and-tool-catalogue.md` contains the full response schema and runtime catalogue. No guidance is summarized. All ten original components retain their exact bytes; grouped components have recorded names, versions, SHA-256 hashes, lengths and byte offsets. Every component hash and physical attachment hash is checked before every send. Initialization also directly supplies the complete required JSON response shape and envelope instructions. This reduces startup attachment slots from ten to eight (20%). Packaging integrity does not establish equivalent model quality; live protocol validation remains required. `guidance/09-testing-acceptance.md` governs local testing. Ordinary messages contain compact state and identifiers rather than repeated long contracts.

User uploads may come from individually selected files in your chosen OneDrive account or on S:, after review of the exact filenames and hashes. This upload permission does not expand local file-tool roots. ZIP archives are never uploaded. Supported code files such as `script.py` are staged as `script.py.txt` with their exact original bytes; attachments do not execute code. Downloaded delivery ZIPs remain a separate local delivery workflow.

Validated Useful Findings may be saved on any response. The cumulative `useful-findings.md` file is attached at submitted message numbers 10, 20, 30, etc. Initialization, tool results and corrections count; uploads, local approval interactions, polling and assistant responses do not. Structured entries retain provenance, timestamps and deduplication hashes.

Session state, redacted events, response diagnostics and immutable script/approval previews are retained under your OneDrive `Copilot Agent/runtime/sessions`. Replaced state versions are retained in `.history`; application file tools preserve files. Setup uses standard venv/pip package management. Retained storage grows and retention is a user responsibility. Runtime/session/profile/workspace files are excluded from source control.

## Verification and limitations

Run **Run Tests.cmd** for the automated suite. Tests retain their isolated directories rather than deleting files. Real visible acceptance is explicit: see [VISUAL_ACCEPTANCE.md](docs/VISUAL_ACCEPTANCE.md) and the execution evidence in [TEST_REPORT.md](docs/TEST_REPORT.md). Mocks and UI previews are never treated as proof of local delivery.

See [ARCHITECTURE.md](docs/ARCHITECTURE.md), [THREAT_MODEL.md](docs/THREAT_MODEL.md), [REUSE_MAPPING.md](docs/REUSE_MAPPING.md), [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md), and [KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md). Unsupported unrestricted scripts, unavailable integrated capabilities and synchronization restrictions are reported honestly.
