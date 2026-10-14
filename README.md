# Copilot Local Agent

Customer and company data work is enabled by default. Authorized customer reads,
discovery and requested artifacts use the normal local tools, with no separate
customer-category gate. Customer navigation and declared internal package hosts
reuse applicable session approvals. See [business data work](docs/BUSINESS_DATA_WORK.md).

Startup now offers **review packages** or **skip quality review and run
continuously for this session**, followed by a plain-language local Crawl4AI
website guide. Sign in manually, title each website's knowledge, explore once
or keep refreshing, then pass saved shared-storage paths to the agent. See the
[local discovery guide](docs/LOCAL_WEBSITE_DISCOVERY.md). Crawl4AI is also directly
callable through `crawl4ai.crawl` and `crawl4ai.read`, using the connected Edge
session for public or internal websites without fixed page/depth ceilings.

Edge startup now isolates native ownership queries and retries failed new-session
launches through direct installed Edge and verified S:/UNC profile spellings.
See [Edge startup recovery and validation](docs/EDGE_STARTUP_RECOVERY.md).

Long Crawl4AI and other tool responses are now compiled locally into complete,
sectioned JSON attachments before sending. The chat message stays below the
editor limit; ordinary batches use one file, with at most 19 total attachments.
See [large result transport](docs/LARGE_TOOL_RESULTS.md).

Public exploration now defaults to [Crawl4AI](https://github.com/unclecode/crawl4ai)
through `discovery.manifest`: continuous bounded parallel expansion, up to 1,000
pages, and reuse of saved unexplored routes. Update dependencies with `Setup.cmd`.
Read all saved routes through paginated `discovery.knowledge_lookup` in the shared
S:/UNC store. See [operation](docs/DISCOVERY_NAVIGATION.md) and the
[deep manifest example](docs/examples/deep-discovery.json). Existing approvals,
public-address checks and cancellation remain active.

A Windows/VDI repository with continuous conversation, Microsoft 365 Copilot web UI reasoning, strictly validated responses, controlled tools, explicit code approval, retained session state and Useful Findings. The original CDD workflow is preserved. No reasoning API is used.

Actionable failures create separate internal and sanitized reports with an explicit review step before external sharing. See [diagnostics and report handling](docs/DIAGNOSTICS.md).

The Copilot Chat project map and handoff files are kept in [Copilot handoff/full-discovery](Copilot%20handoff/full-discovery/README.md) and are included when this repository is pulled.

For the graphical workspace, run **Start Agent UI.cmd**; it asks whether to use the live repository or the Copilot testing environment. **Start Agent.cmd** remains the terminal fallback. The UI shares the same agent session and approval policies. See [the UI guide](agent_ui/README.md).

At normal agent startup, verified running Edge sessions are listed so you can reuse one or launch a new isolated Edge session. Reuse is the default when a verified session is available; if none is available, a new session starts without another prompt. The choice is requested on each startup; canceling stops startup, and a selected session that fails attachment verification falls back to a new isolated session. Explicit `--port` and `--attach-existing` options keep their direct targeting behavior, and `--resume` does not show the selector.

## Setup and run

**Start Agent.cmd** asks whether to run the live repository or a Copilot testing version. Drop replacements into **Copilot testing environment/Updated files/** using the original project-relative folders, then choose testing. Separate mirrored folders support identical filenames. Later deliveries accumulate in complete retained project copies. See [Copilot testing workflow](docs/COPILOT_TESTING.md). No Git or GitHub access is needed inside the VDI. Graphify excludes the testing environment.

Setup checks pip before reusing an existing project environment. If pip is missing or cannot start, it locates the selected installation's base Python and pip, preserves the old environment under a unique recovery name, recreates an isolated environment, and verifies its pip before installing project packages. This requires no manual pip path or separate repair command.

Setup now keeps correctly installed packages and only installs missing or changed
versions. It reuses a writable pip cache, avoids repeated dependency resolution
and bytecode writes, then checks package compatibility and the exploration tools.
Before unpacking, it tests an actual nested wheel-file write/read. Missing or
unusable temporary folders are followed by other S:/UNC project folders and
available Windows temporary folders; a failed unpack retries the remaining
packages. If every automatic option fails, Setup asks for **a folder where you
can save files**, accepts a quoted full folder address, and tries it before
stopping. Package scratch files are separate from the shared agent knowledge.

Put the repository on the shared **S:** drive alongside the organisation's Python installation. Double-click **Setup.cmd**, choose **1: Automatic detection** or **2: Paste a path**, and select Python. You may paste the quoted full `python.exe` path or its installation folder. Setup creates or reuses the project's `.venv` and installs the pinned packages from `requirements.lock.txt`; then use **Start Agent.cmd**. On S:, the base Python and virtual environment remain shared on S:. No browser download is needed. See [SHARED_VDI.md](docs/SHARED_VDI.md).

The app stores ordinary per-user runtime data under local app data and does not discover or select OneDrive automatically. Supply an absolute `storage_dir` in an explicit config when you want session/runtime files in another location, including OneDrive. Edge setup offers detection or a pasted `msedge.exe` path; the executable choice is remembered per machine in configured user storage. **Start Agent.cmd** reuses valid saved resources. Rerun **Setup.cmd** to review Python and Edge choices. Dependencies need network access to the organization's configured package index and permission to create/update the project environment; errors show the complete Python diagnostic. Setup uses the bundled, checksum-verified `virtualenv` archive to create `.venv`, including when the selected portable Python has neither `venv` nor `pip`. If an earlier setup left `.venv` incomplete, Setup preserves it under `.venv-incomplete-*` and creates a fresh environment.

The visible terminal shows setup, discovered exact model labels, short structured task/action/result/verification sections, full script approval previews and answers. System, Orchestrator, Copilot, User, Approval, Error and Tool labels use distinct coloured backgrounds when the terminal supports ANSI colour, with a clean plain-text fallback. Complete sign-in/MFA yourself in the dedicated Edge window. Select a displayed model or accept the documented suggested choice. Visible operation is the only accepted mode; headless Copilot operation is not established.

Use `:new` for a new topic in an independent session and fresh Copilot UI chat, or `:new <first message>` to start it immediately. Previous records are retained; user context, findings, counters, attachment queues and approvals start fresh. Ordinary application launches also create a new session unless `--resume` is explicit. Reconcile uncertain earlier submissions or state-changing calls before switching.

Use `:exit` to end the session and `:status` for counts and findings. Use **Attach files** or `:attach` to open the native Windows picker and select several files for your next message. Advanced users can enter `:attach <path>`. While a turn is running, type any message to steer that same goal; `/steer <text>` is also accepted. Use `/attach "C:\\path with spaces\\file.py"` (repeat quoted paths for multiple files) to add local files to the active run, or `/stop` to request cancellation. Terminal paths are still checked against the configured local roots and every upload remains subject to exact approval. Use `:files` to inspect the pending queue, `:remove <number>` to remove one pending entry, or `:clear` to clear it; these commands never delete source files. Up to **20 user files per message** can be queued, subject to Copilot's combined 20-file send ceiling. See [ATTACHMENTS.md](docs/ATTACHMENTS.md) for formats, approval and limits.

Tool/code approvals offer **1: deny, 2: once, 3: plan** for the exact displayed scope. Denying an upload leaves the pending queue available for review. `--yes-setup` and general willingness to approve do not grant execution permission. Code Runner keeps the restricted `python_subset` evaluator as its default. When registered tools and the subset cannot perform the requested task, Copilot may propose `local_python`; every exact script and complete execution scope is displayed and must receive an explicit decision before it runs.

## Configuration

Run the project from its S: checkout. Settings, sessions, profiles, downloads and knowledge use the `Discoveries knowledge` folder beside (one level above) the project root; S: is resolved to its live UNC filesystem identity before use. A configured C: or OneDrive `storage_dir` is redirected to that canonical S: location. File tools cannot write to C:; one run confirmation grants local reads and new-file/folder creation within Discoveries knowledge, while deletion or overwrite still requires separate confirmation. Copilot's own UI is controlled separately. Root expansion is a user configuration decision; Copilot cannot expand it.

Public operation reuse is an opt-in preview. Set `operation_reuse` to `true` only with `persistent_graph` enabled. An explicitly approved `operation.learn` call can derive one public JSON GET operation from two already-observed URLs and validate it with a third unseen input. Later `operation.call` requests use the existing pinned public-HTTPS transport without opening the browser or returning to Copilot UI. This path never accepts authentication material, cookies, headers, non-GET methods, private destinations or automatic writes. See [API Anything integration](docs/API_ANYTHING_INTEGRATION.md).

Generated files use actual Copilot download links: Office files and full coding packages are requested as ZIPs; single non-Office files use direct links with ZIP fallback. Edge download settings are inspected before delivery, and permanent artifacts plus ZIP extraction stay inside configured user storage (local app data by default). Original archives are retained, outputs are verified, and delivered code never runs automatically. See [FILE_DELIVERY.md](docs/FILE_DELIVERY.md).

You can separately request execution of a verified downloaded `.py` file through Code Runner. The proposal keeps `script` mandatory and binds paired `source_path`/`source_sha256` fields to that exact artifact; the source must also appear in declared reads with `read_files` permission. Raw UTF-8 bytes, including newline bytes, must match exactly and are checked before approval and execution. `local_python` additionally binds the current interpreter path/hash, argv, imports, read/create/modify paths, exact HTTPS destinations, exact managed child-process vectors, desktop permissions, persistent viewers, limits, expected effects and the fixed runner implementation. For several scripts, **3: plan** approves only the complete set already displayed; **2: once** approves one call. Any material change requires a fresh approval. Shell command strings, deletion, credential access, silent privilege escalation and hidden persistence remain unavailable. See [Code Runner security](guidance/04-code-runner-approval-security.md).

On a visible Windows desktop, an approved `local_python` script can use `copilot_agent.desktop` to enumerate physical displays and capture each one to a new PNG. Exact `viewer_windows` declarations launch managed persistent viewers, tile them on the approved display, and independently verify visible titles and final bounds. The run returns image size/hash evidence, window/display evidence and a retained audit receipt. Viewer processes are stopped on failed verification, cancellation or session close. A zero exit code alone never proves the desktop end condition.

Created-file synchronization stays disabled unless you explicitly configure `created_dir` and `created_sync_enabled`. A OneDrive path is inspected only when directly supplied in that configuration; the application does not discover OneDrive accounts or inspect Created folders automatically.

Advanced run: use the discovered shared Python executable with `-B app.py --config <settings-file>`. The source checkout remains separate from personal writable storage. Attach to a verified dedicated existing session using `--attach-existing --port <port> --profile <dedicated-profile-path>`. The port must belong to that exact Edge profile. Existing chats are not reused; the app owns a new chat tab and a separate tool tab. On exit those owned pages close and the existing browser/profile remain.

Resume: use that shared Python with `-B app.py --resume <your-local-runtime-session-path>`. A new chat receives the guidance again. Uncertain sends require explicit reconciliation, incomplete state-changing operations cannot silently replay, and execution grants are not inherited across restart.

## Guidance and memory

The terminal displays timestamped, attributed feedback throughout the run: `User`, `Copilot`, `Orchestrator`, `System`, `Approval`, `Error`, and `Tool/<name>`. Public reply fields are streamed as soon as the UI exposes complete values; live previews are visibly marked unvalidated and identical validated text is not printed twice. Reliable parsed responses appear as short task, action, result and verification sections. Long protocol fields and full results stay in retained logs; every proposed script still appears in full at approval. See [FEEDBACK.md](docs/FEEDBACK.md).

The eight behavioural Markdown files, response schema and current machine-readable tool catalogue are supplied once at initialization in **eight attachments**. Guidance 01–06 are uploaded unchanged as six separate files; `07-08-complete-guidance.md` contains the complete original guidance 07 and 08, and `protocol-schema-and-tool-catalogue.md` contains the full response schema and runtime catalogue. No guidance is summarized. All ten original components retain their exact bytes; grouped components have recorded names, versions, SHA-256 hashes, lengths and byte offsets. Every component hash and physical attachment hash is checked before every send. Initialization also directly supplies the complete required JSON response shape and envelope instructions. This reduces startup attachment slots from ten to eight (20%). Packaging integrity does not establish equivalent model quality; live protocol validation remains required. `guidance/09-testing-acceptance.md` governs local testing. Ordinary messages contain compact state and identifiers rather than repeated long contracts.

User uploads may come from individually selected files in configured local roots or on S:, after review of exact filenames and hashes. A OneDrive file can be attached when the user selects it or supplies its local path. This upload permission does not expand local file-tool roots. ZIP archives are never uploaded. Supported code files such as `script.py` are staged as `script.py.txt` with their exact original bytes; attachments do not execute code. Downloaded delivery ZIPs remain a separate local delivery workflow.

Validated Useful Findings may be saved on any response. The cumulative `useful-findings.md` file is attached at submitted message numbers 10, 20, 30, etc. Initialization, tool results and corrections count; uploads, local approval interactions, polling and assistant responses do not. Structured entries retain provenance, timestamps and deduplication hashes.

Session state, redacted events, response diagnostics, immutable script/approval previews and `local_python` audit receipts are retained under configured user storage at `runtime/sessions`. Replaced state versions are retained in `.history`; application file tools preserve files. Failed or cancelled code runs stop owned processes but retain output evidence rather than deleting it. Setup uses bundled virtualenv and pip package management. Retained storage grows and retention is a user responsibility. Runtime/session/profile/workspace files are excluded from source control.

## Verification and limitations

Run **Run Tests.cmd** for the automated suite. Tests retain their isolated directories rather than deleting files. Real visible acceptance is explicit: see [VISUAL_ACCEPTANCE.md](docs/VISUAL_ACCEPTANCE.md) and the execution evidence in [TEST_REPORT.md](docs/TEST_REPORT.md). Mocks and UI previews are never treated as proof of local delivery.

See [ARCHITECTURE.md](docs/ARCHITECTURE.md), [THREAT_MODEL.md](docs/THREAT_MODEL.md), [REUSE_MAPPING.md](docs/REUSE_MAPPING.md), [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md), and [KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md). `local_python` is explicit approved host execution with defense-in-depth mediation, not an OS sandbox; unavailable desktop capabilities and organizational restrictions are reported honestly.
