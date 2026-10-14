# Large tool results in Copilot Chat

The orchestrator measures the complete outbound JSON envelope, including its
instructions and current context, before filling the composer. This covers
Crawl4AI reads, other tools, repairs, user turns and startup preparation.

`max_composer_chars` defaults to a hard ceiling of 20,000 UTF-16 code units.
The owned editor's `maxlength` or equivalent exposed data attribute takes
precedence when smaller. If no limit is exposed, use 16,000 conservatively,
with 128 characters reserved below the chosen limit. Microsoft documented a
16,000-character Microsoft 365 Chat paste limit in its historical
[August 2024 release notes](https://blogs.windows.com/japan/2024/09/12/what-s-new-in-copilot-august-2024/).
This is historical evidence, not a guarantee for every current tenant.
Browser submission independently checks the editor limit before filling it.

If ordinary or compact JSON still exceeds that budget, local Python immediately
creates `tool-results/tool-results-<request_id>-01.json` inside the existing
session folder. No new process, LLM, dependency install or summarization call
is involved. An ordinary multi-tool batch becomes one readable JSON document:

- `reading_guide`: how to read the document and treat page text as evidence.
- `summary`: result count, counts by tool and failed-result count.
- `result_index`: ordered sections, call IDs, tool names, success and status.
- `response_metadata`: current orchestration instructions, manifests and controls.
- `content`: complete current response, preserving results, errors, source paths,
  offsets and continuation fields.

Large individual documents use ordered valid JSON parts, normally up to 8 MiB
each, or the smaller configured attachment limit. For segmented documents,
join decoded `content_segment` strings in `part` order and parse the resulting
JSON; offsets and total lengths permit completeness checks. The small chat
message identifies every filename, part and SHA-256, tells Copilot to read all
parts, and preserves session/request identity and the response-envelope contract.
Short current user requests remain visible in the compact message.

The combined count includes existing contract, user and findings files and
cannot exceed 19. Startup's eight unchanged contract files may therefore have
one additional response document. Result attachments use atomic S:/UNC-capable
writes and exact readback, then the existing hash, upload-readiness and submission
checks. The preload and send use the same text and attachment bytes. If the
complete response cannot fit available slots, file limits or the message header,
stop before sending and report the reason; never truncate evidence or silently
drop user files.

These response files deliberately retain the current tool data for upload to
Microsoft Copilot. They inherit the existing session location and access
controls. Historical private context is not exported by this packer, and
existing secret redaction and approval boundaries remain active. This transport
does not authorize processing additional customer data.

Validation: `tests.test_outbound_results` reproduces ten long crawler reads with
a composer that rejects more than 20,000 characters, verifies exact payload
recovery, exercises smaller editor limits and multipart Unicode/error/offset
preservation, and verifies unsent attachment-budget failures. Existing browser,
attachment, protocol and orchestrator tests cover the normal delivery paths.
These checks do not establish live tenant or VDI success.
