# Attach files to a request

Website investigations automatically receive visual context through the orchestrator,
including REA, Crawl4AI and API investigation when an approved owned page is available.
Each discovery batch produces one merged, labeled PDF. Browser actions receive actual
BEFORE and AFTER captures labeled with the action and capture time. The twelve-picture
passive discovery sample limit does not discard action pairs. Discovery samples include
page overviews, readable control closeups and sampled scroll positions.
Scrolls during concurrent analysis use an independently opened authenticated page;
captions identify these revisits because transient application state can differ.
Capture runs alongside passive investigation. Navigation results are captured after
the navigation completes. Missing pages, unavailable capture and incomplete coverage
are reported in `visual_context` without replacing the investigation result.

The PDF is attached automatically on every outgoing message once visual evidence exists.
Messages without a new browser action repeat the last evidence PDF and explicitly identify
it as a previous observation. Visual evidence reserves an attachment slot; a user batch
that exceeds the 20-file limit must be reduced before sending. PDFs and source pictures
are retained under the session's `screenshots` folder. Capture or size failures are
explicit coverage gaps, never a claim that an unseen before/after state was verified.

**New session** is available during an active run. It cancels that run, opens a fresh
conversation and asks for fresh session access approval. Previous records and unresolved
effects remain in the old session. The configured browser and tools are reused.
Startup **Y** authorizes validated tool plans for that session, including writes,
code and inspected packages, without further plan prompts. Each exact proposal is
still prepared, validated and audited by the orchestrator. Revocation and New session
end the grant. OS permissions and sign-in/MFA handoffs remain separate.

Choose **Attach files** or enter `:attach` in the visible conversation console. The native Windows file picker supports selecting several files at once. Review the pending queue, then write the message that should use those files. Selecting a file queues it; the next request requires approval of the actual upload.

| Command | Effect |
| --- | --- |
| `:attach` | Open the native multi-selection file picker. |
| `:attach <path>` | Queue one explicitly named file; useful for advanced users. |
| `:files` | List pending entries with their numbers and recorded file details. |
| `:remove <number>` | Remove that entry from the pending queue only. |
| `:clear` | Clear pending entries only. |
| `:new` or `:new <first message>` | Start an independent session with an empty attachment queue. |

Removing or clearing entries never deletes or changes source files. Starting a new session preserves the previous session's records and files. Earlier attachments and approval grants do not transfer to the new conversation.

## Sources, review and approval

Select supported regular files from the configured local roots or S:, including a OneDrive path when you explicitly select or name it. The app validates the selected source and records its name, size and SHA-256. Runtime files, browser profiles, redirected paths and unsupported files are excluded. Selection does not grant directory-wide access or expand configured local file-tool roots.

The upload review binds the actual selected files and hashes. Approval choices are **1: deny, 2: once, 3: plan** for the exact displayed scope; there is no permanent approve-all. Denial retains the pending queue so you can inspect it, remove entries or try a revised request. Before sending, the app checks that each file still matches the reviewed bytes. If a source changed, remove it and select it again for a new review rather than sending it under the old approval.

## Formats and exact content

Supported native uploads include text/Markdown, JSON/CSV, PDF, DOCX/XLSX/PPTX and common images. Other supported text and code types must be readable UTF-8. When a code extension needs text staging, the app adds `.txt` to the original filename: `report.py` becomes `report.py.txt`. It preserves the complete original bytes, including line endings and any UTF-8 BOM. This provides source content for Copilot to inspect; it does not run the file.

ZIP archives are forbidden as uploads, including archives renamed to another extension. Select their extracted supported files instead. Native DOCX/XLSX/PPTX documents are accepted as Office documents after their package structure is checked. The separate generated-file delivery workflow may download and inspect ZIPs locally; that does not permit uploading ZIPs. See [FILE_DELIVERY.md](FILE_DELIVERY.md).

Files with the same basename from different folders remain attachable. The approval preview keeps each original name and assigns a distinct upload name (for example, `report.py.txt` and `report (2).py.txt`) so neither file overwrites or hides the other.

## Per-request limits

At most **20 user files** can be queued for one message by both the terminal and workspace upload service. Before every actual message, the app checks the final combined attachment list against the **20-file per-message limit provided for this deployment**. Startup references are uploaded at initialization; findings and context are attached only when due or needed, so the final check may leave fewer than 20 slots for user files. The cap applies per message, not cumulatively across the chat.

These are per-request and per-message limits. They do not establish a cumulative limit for the entire chat. Actual Copilot availability and organizational controls can still reject an upload. A picker selection or a local staged file alone is not proof that Copilot received it; the browser must confirm the intended uploads before submission.

## Large document collections

The orchestrator can retain up to 1000 authorised references in a document catalogue while selecting only the available document slots for a message. Website downloads remain bounded to 30 documents per batch. `files.transfer_to_copilot` ranks requested files, active workflow evidence and task-query matches, omits exact SHA duplicates and confirmed prior uploads, and reports why files were deferred. Different files with similar names remain available and only produce review warnings.

When files defer, a JSON index uses one of the available slots; existing queued files and images reduce the allowance. The final message still includes startup guidance, findings and context within the hard 20-file limit. An index is a metadata bundle with references to preserved originals; it does not replace their contents or permit ZIP upload. Use `documents.find` to locate evidence and `documents.retrieve` to reverify selected paths/hashes before approved transfer. No manual splitting of a 21-, 50- or 100-file collection is required.

Catalogues stay within the current task/customer/tenant/site namespace. A later task explicitly imports the retained index with its reviewed SHA-256 and matching customer/tenant/user/environment scope. Imported references are revalidated. Same-session download resumption additionally requires the original verified download manifest and its hash. Queued and retrieved files are not proof of Copilot receipt; successful attachment UI and submission checks remain required.

## Startup references

Initialization uploads **eight reference files** containing all twelve original components:

- Guidance 01–06 remain six separate original files, unchanged byte-for-byte.
- `07-08-complete-guidance.md` contains the complete original guidance 07 and 08 in separate labelled sections.
- `protocol-schema-and-tool-catalogue.md` contains the complete response schema, runtime tool catalogue, automation package schema 1.0 compatibility version, and current automation package schema 1.1 with typed result bindings, each in its own JSON fence.

Nothing is summarized. Each grouped component's manifest records its name, version, SHA-256, original byte length and absolute start/end byte offsets; end offsets are exclusive. Original source bytes, including BOMs, line endings and final-newline state, are preserved. All eight physical files also have locally recorded SHA-256 hashes. The aggregate startup reference size, including generated group headers and manifests, is capped at 20 MiB. The initialization message directly includes the complete required JSON response shape and envelope instructions so the requested format is explicit alongside the full schema.

The orchestrator rechecks all twelve source component hashes and all eight physical attachment hashes before every send. Previous generated group versions are retained when replaced; original guidance remains unchanged. A fresh or replacement chat receives initialization again. Ten physical uploads become eight, reducing startup attachment slots by 20% while preserving exact source bytes. This does not prove that a model will use the material identically; the visible initialization response and protocol checks remain acceptance evidence.
