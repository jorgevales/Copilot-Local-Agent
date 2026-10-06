# Generated-file delivery

This document defines the current delivery policy and the implemented integration of `copilot.download`, `archives.inspect` and `archives.extract`. Their exact versions, arguments, schemas, limits and availability come from the current generated machine catalogue. A documented flow is not proof that its live UI acceptance has passed; the evidence report must record observed outcomes separately.

## Format requested from Copilot

| Requested result | Required request and fallback |
|---|---|
| One or several Office files | Always ask for one downloadable ZIP containing the requested files. One file still requires a ZIP. |
| Complete coding project/package | Always ask for a downloadable ZIP preserving the required project structure. |
| One non-Office `.py`, `.md`, `.txt`, `.json`, `.csv` or similar file | Ask explicitly for an actual downloadable file in the Copilot UI. If the result is plaintext, a code block or only a sandbox reference, ask for a downloadable ZIP containing that single file. |

Office includes Word/Excel/PowerPoint documents, workbooks, presentations, related templates, macro-capable variants and legacy formats. Request the exact original output types inside the ZIP; do not replace an Excel workbook with CSV or a Word document with plain text without a new user decision. Never report a model-provided `sandbox:/...` path, suggested filename or rendered preview as a local file.

Setup discovers known OneDrive account roots and remembers the user's choice. Do not inspect unrelated account content or any deferred Created directory. All permanent delivery artifacts and ZIP extraction stay in that selected OneDrive; the S-drive source repo holds no user session state. That earlier synchronization path is outside the current delivery workflow. No reasoning API, fabricated endpoint or bypass of organizational download controls is part of this flow.

## Clickable-link presentation

The strict response JSON remains in one fenced code block between its marker lines. One useful actual Markdown artifact download link may follow the END marker outside that code block. This is the sole delivery exception to envelope-only presentation. A Markdown URL inside the JSON `user_response` is inert code rather than a clickable anchor. A link after the marker must represent the actual generated artifact, not a guessed URL, sandbox reference or second response envelope.

The browser binds a unique actual artifact anchor: allowlisted HTTPS or an observed native same-origin Microsoft 365 UUID blob with an exact `download` filename in the current correlated assistant container, checks configured download hosts and records a source-response hash and safe link identity for approval. The `copilot.download` request uses `expected_name` (plain basename), optional `link_text` and optional independently supported `expected_sha256`. It accepts no raw URL argument. Signed URLs remain transient browser data; their authentication-bearing query tokens must be excluded from logs, persisted response/context content and approval metadata.

## Message and artifact flow

1. Record the user's intended outputs, formats and names. Build a compact Copilot request using the required delivery format. Keep long delivery guidance in the attached contract file.
2. Capture and validate the assistant response. Distinguish an artifact claim from an actual observed generated-file control/link in that response's Copilot UI container.
3. Discover the actual current artifact controls with the browser adapter. Resolve ambiguity before interaction. Do not let Copilot invent an arbitrary external URL or substitute an unrelated earlier artifact.
4. Obtain narrow download authorization when required by local policy. Display artifact identity, safe observed link identity, source-response hash, browser download settings/destination, retained local target, anticipated file format and effects. An existing explicit task grant may apply only if it already covers those exact generated artifacts; it never becomes a permanent download grant.
5. Use `copilot.download` to activate the observed actual UI control and await a bounded Edge download event. Inspect relevant download event metadata and browser download location/settings when needed. Do not read cookies, credentials, profile contents or unrelated browser downloads.
6. Retain the downloaded artifact in a configured permitted delivery directory with a new name if a collision exists. Verify local existence, stable/readable content, size, SHA-256 and plausible format. A click, UI filename or zero-error message is insufficient.
7. For a ZIP, retain the original and use `archives.inspect` to obtain a bounded manifest and safety result. Match the proposed member set to the user's requested files/package.
8. Display an extraction proposal containing the inspected archive SHA-256, complete inspected manifest and required expected files, destination and expected output paths. Obtain extraction approval for that scope before calling `archives.extract`. Inspection alone grants no extraction permission.
9. Extract exclusively into a new scoped directory. Verify actual local outputs, their hashes, expected names and format/structure; return concise evidence to Copilot.
10. Give the user the retained ZIP path and verified extracted artifact paths. Report any unverified content quality or unavailable capability honestly. Do not execute a delivered project or launch Office automatically. A later execution request follows the separate source-bound approval flow below.

## Download boundary

The Copilot control page remains unavailable to ordinary browser tools. `copilot.download` is a specific mediated delivery capability, not arbitrary access to that page or all links. It acts only on a currently observed generated-artifact control under the user's authorized task. Its policy must cover the actual destination and retain the original artifact; redirects or organizational restrictions must not be circumvented.

Edge's observed download event and a verified local file supply evidence. If browser download settings select a different location, resolve the relevant actual event/location without guessing a OneDrive directory. Preserve a record of current session/request identity, artifact name, observed control, download result and retained target/hash. Do not collect authentication-bearing URLs or tokens in logs.

## Archive boundary

Inspection is read-only and bounded. Reject an unsafe/unsupported archive rather than partially extracting it. Check actual normalized Windows destinations, not only raw archive names. Required rejection categories include:

- `..` traversal; absolute, drive, UNC and alternate-data-stream paths; reserved device names and ambiguous trailing spaces/dots.
- Symlinks, special file entries, path escapes through existing links/reparse points, or extraction outside approved roots.
- Duplicate names, case-insensitive/normalization collisions, and file-versus-directory collisions.
- Unsupported encryption, corrupt ZIP structure, excessive members, excessive compressed/uncompressed size or expansion ratio.

Extraction approval binds the exact archive hash, complete inspected member set (all members are extracted; `expected_files` asserts required outputs) and destination. Recheck the archive before extraction. Use exclusive creation; existing targets fail without overwrite. Retain the original ZIP and any safely created partial artifacts if extraction fails. Never delete outputs as rollback, silently change approved member names, recursively unpack a nested archive or run an extracted script during extraction. An uncertain partial extraction requires inspection and user reconciliation before another state-changing attempt.

## Delivered-format verification

Record output names, sizes, readable access and SHA-256 hashes. Check expected text encoding or JSON structure where applicable without executing content. A coding package may be inspected for expected files and directory layout, but its code remains untrusted and any later execution requires a separate Code Runner proposal and authorization.

For OOXML `.docx`, `.xlsx` and `.pptx`, inspect their internal ZIP structure for `[Content_Types].xml`, `_rels/.rels` and the appropriate `word/document.xml`, `xl/workbook.xml` or `ppt/presentation.xml`. Related OOXML formats require their corresponding package structure. For legacy Office or other supported formats, validate applicable signatures and state when deeper structure validation is unavailable. File extension alone is insufficient. Structural plausibility is not proof of visual rendering, formulas, business correctness, macro safety or absence of malicious content. No application or macro is opened automatically.

## Approved execution of delivered Python source

Downloading or extracting a file does not authorize execution. After a separate user request to run it, a supported `.py` artifact can be bound to a Code Runner proposal. A package must first complete actual ZIP download, safe inspection, approved extraction and local artifact verification. Each script proposed for execution is then reviewed individually as part of the complete pending plan.

The normal complete Code Runner fields remain required, including the full `script` text and `language: python_subset`. Optional `source_path` and `source_sha256` must be supplied together. `source_path` must resolve to an allowed regular `.py` file and be declared in `read_paths`, with `read_files` permission. The lowercase SHA-256 binds its raw downloaded/extracted bytes. `script.encode('utf-8')` must equal those bytes exactly, including CRLF/LF and final-newline state. No silent rewriting, newline normalization or source substitution is permitted.

Source files are capped at 200,000 bytes; script text remains capped at 50,000 characters. UTF-8 BOMs and non-UTF-8 Python encoding declarations are explicitly rejected. The implementation rechecks raw path safety, regular-file identity, size, hash and exact script-byte equality during preparation and again before execution. The prepared metadata and execution result include `source_verification` with `path`, `sha256`, `size` and `exact_script_bytes: true`, including runs that only print and create no outputs. A changed source or materially changed proposal cannot use the earlier approval.

For several supported scripts, the orchestrator prepares and displays the complete immutable all-Code-Runner plan: every call identity, complete script, source verification, declared reads/creates, permissions, expected outputs, risks and proposal hashes. Choose **1: deny**, **2: once** for one call, or **3: plan** for that exact displayed set. A plan grant binds all prepared calls, not an open-ended project directory or future generated scripts. Material code, source-hash or scope changes require renewed preparation and approval. Download and extraction approvals remain separate from execution approval.

Source binding does not make Code Runner a general Python runtime. It evaluates the existing constrained AST subset with mediated capabilities; it does not launch the downloaded `.py` through host Python. Imports, third-party dependencies, arbitrary attributes, subprocesses, shell commands and network access remain unsupported. A common full coding package may be delivered and inspected while its normal Python entry point remains unsupported for local execution.

The manual `tests/live_download_run.py` harness exercises a real synthetic source download followed by exact-byte approval-bound execution. It requires explicit `--live`, prepares the downloaded print-only script, displays pending approval and waits within a bound for a fresh matching once ledger. The supervising operator must obtain explicit user approval of the displayed script and scope before creating that ledger; the harness never creates an approving decision itself. The ledger binds its nonce, source path/hash and immutable proposal. No live success is established by this document: consult `TEST_REPORT.md` for observed download, approval and execution evidence.

## Recovery and honest completion

Use finite generation, control-discovery, download and extraction retry budgets with recorded reasons. A missing actual link, download timeout, unsafe archive, missing expected member or format mismatch returns evidence to Copilot for a bounded correction of the same requested output. For a single non-Office plaintext/sandbox-only result, request ZIP fallback. For Office or complete projects, request the required ZIP again within the budget, or report that the capability is unavailable.

Do not repeat an action whose acceptance/effects are uncertain, expand the task to unrelated files, or claim delivery from a model assertion. Ambiguous matching artifacts/members require disambiguation. Final delivery evidence distinguishes each completed step from blocked/unexecuted steps, preserves the original ZIP and verifies the actual extracted files.

## Visible acceptance evidence required

Use harmless synthetic artifacts in the real authorized UI. Record an Office-in-ZIP request, actual UI download control and Edge event, retained ZIP/hash, safe archive inspection, explicit extraction approval and verified Office structure. Separately exercise a full coding-package ZIP and a single non-Office downloadable file or observed ZIP fallback. Verify denial performs no download/extraction, unsafe ZIPs fail closed, existing targets are preserved, and downloaded/extracted scripts never run automatically. Mock tests cannot establish real Copilot generation or download availability. No Created-folder access is needed for these tests.

Edge settings are read through its actual settings UI before link selection. The verified artifact is retained under the selected OneDrive `deliveries` folder, even if the observed browser artifact is temporarily elsewhere. The report distinguishes the configured Edge Downloads directory from the actual event-backed artifact and permanent target; it does not claim a normal default-directory save unless proven. Native Save As prompts remain under the user's control within a bounded wait. Neither sandbox text nor a guessed URL is converted into a download.
