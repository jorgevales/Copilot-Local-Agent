# Attach files to a request

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

Select supported regular files inside the OneDrive account chosen during setup, or individually selected files on S:. The app validates the selected source and records its name, size and SHA-256. Runtime files, browser profiles, redirected paths and unsupported files are excluded. Selection does not grant directory-wide access or expand configured local file-tool roots.

The upload review binds the actual selected files and hashes. Approval choices are **1: deny, 2: once, 3: plan** for the exact displayed scope; there is no permanent approve-all. Denial retains the pending queue so you can inspect it, remove entries or try a revised request. Before sending, the app checks that each file still matches the reviewed bytes. If a source changed, remove it and select it again for a new review rather than sending it under the old approval.

## Formats and exact content

Supported native uploads include text/Markdown, JSON/CSV, PDF, DOCX/XLSX/PPTX and common images. Other supported text and code types must be readable UTF-8. When a code extension needs text staging, the app adds `.txt` to the original filename: `report.py` becomes `report.py.txt`. It preserves the complete original bytes, including line endings and any UTF-8 BOM. This provides source content for Copilot to inspect; it does not run the file.

ZIP archives are forbidden as uploads, including archives renamed to another extension. Select their extracted supported files instead. Native DOCX/XLSX/PPTX documents are accepted as Office documents after their package structure is checked. The separate generated-file delivery workflow may download and inspect ZIPs locally; that does not permit uploading ZIPs. See [FILE_DELIVERY.md](FILE_DELIVERY.md).

## Per-request limits

At most **10 user files** can be queued for a request. Ten slots are reserved: eight for the startup references, one for the cumulative findings file and one for an authoritative context snapshot. Before every actual message, the app checks the final combined attachment list against the **20-file per-message limit provided for this deployment**. Startup references are uploaded at initialization; findings and context are attached only when due or needed. The user queue retains its 10-file cap on every request.

These are per-request and per-message limits. They do not establish a cumulative limit for the entire chat. Actual Copilot availability and organizational controls can still reject an upload. A picker selection or a local staged file alone is not proof that Copilot received it; the browser must confirm the intended uploads before submission.

## Large document collections

The orchestrator can retain up to 1000 authorised references in a document catalogue while selecting only the available document slots for a message. Website downloads remain bounded to 30 documents per batch. `files.transfer_to_copilot` ranks requested files, active workflow evidence and task-query matches, omits exact SHA duplicates and confirmed prior uploads, and reports why files were deferred. Different files with similar names remain available and only produce review warnings.

When files defer, a JSON index uses one of the available slots; existing queued files and images reduce the allowance. The final message still includes startup guidance, findings and context within the hard 20-file limit. An index is a metadata bundle with references to preserved originals; it does not replace their contents or permit ZIP upload. Use `documents.find` to locate evidence and `documents.retrieve` to reverify selected paths/hashes before approved transfer. No manual splitting of a 21-, 50- or 100-file collection is required.

Catalogues stay within the current task/customer/tenant/site namespace. A later task explicitly imports the retained index with its reviewed SHA-256 and matching customer/tenant/user/environment scope. Imported references are revalidated. Same-session download resumption additionally requires the original verified download manifest and its hash. Queued and retrieved files are not proof of Copilot receipt; successful attachment UI and submission checks remain required.

## Startup references

Initialization uploads **eight reference files** containing all ten original components:

- Guidance 01–06 remain six separate original files, unchanged byte-for-byte.
- `07-08-complete-guidance.md` contains the complete original guidance 07 and 08 in separate labelled sections.
- `protocol-schema-and-tool-catalogue.md` contains the complete current response schema and runtime tool catalogue, each in its own JSON fence.

Nothing is summarized. Each grouped component's manifest records its name, version, SHA-256, original byte length and absolute start/end byte offsets; end offsets are exclusive. Original source bytes, including BOMs, line endings and final-newline state, are preserved. All eight physical files also have locally recorded SHA-256 hashes. The aggregate startup reference size, including generated group headers and manifests, is capped at 20 MiB. The initialization message directly includes the complete required JSON response shape and envelope instructions so the requested format is explicit alongside the full schema.

The orchestrator rechecks all ten source component hashes and all eight physical attachment hashes before every send. Previous generated group versions are retained when replaced; original guidance remains unchanged. A fresh or replacement chat receives initialization again. Ten physical uploads become eight, reducing startup attachment slots by 20% while preserving exact source bytes. This does not prove that a model will use the material identically; the visible initialization response and protocol checks remain acceptance evidence.
