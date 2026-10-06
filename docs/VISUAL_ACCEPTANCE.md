# Visible end-to-end acceptance

Use a real authorized Copilot Chat session, a visible dedicated Edge window and synthetic content. Do not bypass authentication, upload restrictions or organizational controls. This checklist is not test evidence until completed with observed results. Retain all synthetic artifacts; do not delete them.

## Evidence record

For each step record UTC timestamp, submitted-message ordinal where applicable, expected result, observed result, artifact/screenshot/log path and status: passed, failed, blocked or not run. Redact unnecessary user/organization data. Keep screenshots and small diagnostic DOM excerpts local. Automated/mock results must be labeled separately.

## Setup and capture

- Start the application and observe a dedicated visible Edge debugging session with loopback-only connection.
- Verify Playwright connects and Copilot Chat opens. Perform manual sign-in if prompted.
- Discover model names exactly as displayed. Record ranking/default rationale and verify the selected model's actual UI state.
- Verify startup contains exactly eight reference files: guidance 01–06 as six unchanged originals, `07-08-complete-guidance.md`, and `protocol-schema-and-tool-catalogue.md`. Recover the four grouped components using their recorded offsets and verify all ten originals' exact bytes, lengths and SHA-256. Confirm BOM, line-ending and final-newline preservation with synthetic fixtures.
- Observe exactly eight initial reference uploads containing those complete components. Record upload confirmation rather than inferring it from local file existence. Record the ten-to-eight physical slot change (20%) separately from model-quality claims.
- Inspect the initialization message for the direct complete required JSON response shape and strict envelope instructions alongside the full attached schema and catalogue.
- Observe insertion/submission of the initial compact message, generation start, completion signals and one newly correlated assistant envelope.
- Record parsed session/request identity and successful schema validation.
- Change an original reference component or either completed group in an isolated synthetic test and verify the next send is refused. Verify all eight physical attachment hashes are checked as well as the ten original component hashes. Do not alter the real live session's approved references to perform this check.

## Conversation and tools

- Request a harmless no-tool answer; verify final response and nonempty action plan.
- Request permitted read-only inspection of a synthetic project file; observe a valid tool request, local evidence returned to Copilot and a final answer grounded in that result.
- Request a constrained Code Runner script producing a uniquely named synthetic output. Choose deny. Verify the script did not run and the expected output was not created.
- Make a new independently reviewed request. Inspect full script/plan, hashes and declared scope; approve this execution only. Verify the exact approved script executed and expected local content exists.
- Change the script or scope and verify the earlier grant cannot authorize the changed execution.
- Request a harmless `local_python` task that genuinely needs an import. Confirm the full exact script, current interpreter/hash, argv, imports, file scope, permissions, timeout/output limits and expected effects appear before approval. Deny it and verify no process/output; propose it again and approve only the exact execution. Change one byte or argument and verify a fresh decision is required.
- Exercise a failing local script, a timeout and interactive cancellation. Verify the result distinguishes failed/cancelled states, stdout/stderr are bounded, an audit receipt is retained, owned child processes are stopped and existing files are not deleted.
- Exercise a harmless managed persistent child, then close the session. Verify its PID is registered while approved and stopped during session cleanup. Do not use an unrelated process as the fixture.
- On a workstation with at least three attached active displays, ask Copilot to enumerate them, capture each physical display separately to three new approved PNGs and declare three uniquely titled persistent viewers on Windows display 2. Verify all PNG sizes/SHA-256 values, three managed viewer PIDs, and independent window evidence showing all three exact titles visible with final bounds contained on display 2. Record the display enumeration and retained audit path. If the desktop, third display, GDI, Tk or organization policy blocks the task, mark it blocked; a script exit is not a pass.
- Exit or start a new session after the display test and verify all managed viewer processes close. The PNGs and audit evidence remain retained.
- Exercise the explicit invalid-format/correction test mechanism. Preserve the invalid output, observe validation errors and a bounded correction, and verify no action executed from invalid content.
- Observe a second user turn after task completion; confirm the continuous loop remains available.
- Use `:new` to start an independent topic. Verify a different Copilot conversation URL and local session ID, repeated guidance initialization, fresh counter and exclusion of prior requirements, findings, queued attachments and approvals. Confirm the previous session files remain.

## Findings and counting

- Include an evidence-supported synthetic finding before the first tenth-message boundary. Verify immediate accepted storage and readable cumulative Markdown update.
- Repeat an unchanged finding and verify no duplicate accepted entry.
- Track confirmed submitted message ordinals; include initialization, tool results and corrections, excluding assistant responses, uploads and polling.
- At ordinals 10 and 20 observe upload of the current cumulative findings snapshot before submission. Verify ordinary non-boundary messages do not trigger that cadence upload.
- Verify findings produced in a boundary response save immediately and appear in the next applicable snapshot.

## User attachments

- Choose **Attach files** or enter `:attach`. Observe the native Windows picker and select several harmless supported files from the selected OneDrive account. Verify `:files` lists exactly the intended pending entries.
- Test advanced `:attach <path>` with an explicitly selected synthetic S-drive file when that drive is available. Verify this does not expand local file-tool roots. If S: is unavailable, record this step as not run.
- Use `:remove <number>` and `:clear`. Verify only pending entries change and every source file remains intact.
- Submit a request with pending files. Inspect filenames, sizes and SHA-256 in the approval preview, choose **1: deny**, and verify no upload/send executes and the queue remains. Review again and choose **2: once**; exercise **3: plan** only for the exact displayed scope in a separate reviewed test.
- Verify a harmless `.py` source is uploaded as its original filename plus `.txt`. Compare the staged and original bytes and hashes, including synthetic BOM/CRLF/no-final-newline cases, and verify no code executed.
- Change a selected source after queuing in a retained synthetic fixture. Verify sending is refused until that entry is removed and selected again for review.
- Select a ZIP archive and a ZIP renamed to a supported non-Office extension. Verify both are denied without upload. Separately verify a structurally valid synthetic native Office document is treated as that document type.
- Queue 10 distinct supported synthetic user files; verify an eleventh is refused. In the automated boundary test, combine 10 user files with eight startup references, one findings snapshot and one context snapshot; verify 20 is permitted and a 21st physical attachment blocks the send. Record any actual UI limit rejection separately. These tests concern per-message limits, not a cumulative chat limit.
- After an approved upload, verify the browser confirms the exact intended filenames before submission. A picker selection or staged file alone is insufficient evidence.
- Start `:new` and confirm an empty pending queue, new session identity and retained prior source/session files.

## Files and synchronization

- Complete the user-attachment checks above before relying on uploaded content.
- Inspect the actual Edge download settings without changing them. Request a single harmless non-Office file with an explicit downloadable link, then request a complete coding package and a single Office document as downloadable ZIPs. Plaintext and sandbox references require bounded conversational correction; ZIP is the single-file fallback.
- Observe the actual browser download event and approved permanent OneDrive copy. Record the suggested name, byte count, readability and hash. Distinguish this from proof of a default Downloads-directory save or a user-controlled Save As prompt.
- Inspect each ZIP before approving create-only extraction to a new directory inside the selected OneDrive. Verify every expected file, content/structure and hash; retain the original archive. Download and extraction never authorize code execution.
- Separately request one source-bound downloaded `.py` execution that fits `python_subset`. Review the exact immutable bytes, source hash, read permissions and full scope; obtain explicit user approval. Verify stdout, stderr, exit code and expected outputs, and return the result through the real UI. In a distinct test, a downloaded script may use `local_python` only after a new exact host-execution proposal and approval; delivery/extraction never grants execution.
- Exercise read-only reporting of a completed execution without creating or downloading another artifact. Verify no execution is repeated and no delivery retry is triggered by filenames or negated requests.
- Created-folder monitoring is optional and deferred by the user. Leave it disabled during the current acceptance; do not access the organizational FNZ OneDrive. Only after explicit enablement in the intended deployment, request a synthetic Created output and observe bounded polling of the configured OneDrive `Documents\Copilot\Created` directory. Verify stable readable matching bytes before claiming synchronization success. A cloud preview does not establish that optional local synchronization.

## Exit and delivery

- Exit through the supported user command. Verify session state was preserved, pending uncertainty was recorded, all managed persistent processes/viewers were stopped, and the owned browser/session closed cleanly according to configured lifecycle.
- Review retained synthetic files, sanitized logs and screenshots. Verify no files were deleted and no existing CDD workflow files were modified.
- Report total passed/failed/blocked/not-run steps, automation results separately, limitations and any required follow-up. Full acceptance cannot be claimed while required visible steps remain unexecuted or blocked.
