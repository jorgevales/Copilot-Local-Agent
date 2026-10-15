# Customer and company data work

`customer_data_work: true` is the default for this installation. Customer/company
classification does not prohibit local discovery, reads, analysis, document
work or requested business artifacts. All authorized customers use the same
processing rules. This configuration adds no customer allowlist or category
approval prompt and requires no additional setup question.

Use local `crawl4ai.crawl` for authenticated/internal/customer-specific sites and
`crawl4ai.read` for titled saved knowledge. The public-only `discovery.manifest`
adapter remains available for its original generic public route contracts;
choose the local crawler for work outside that adapter's format. These are
different transports, not different permissions to process customer data.

Ordinary customer-bound browser reads no longer require a durable research
grant or redirect unconditionally to `research.perform`.
`browser.customer_summary` is an identity-checked read. It can read requested
ordinary input/textarea values and complete business text, preserving observed
facts. Customer selection and record identity still have to match the task.
Credential, hidden and file controls are excluded from business field extraction.
Rendered Crawl4AI knowledge retains business form values and notes while removing
credential values, hidden inputs, executable scripts and token attributes.

Complete redacted/schema-validated tool results reach the orchestrator rather
than being shortened to three entries or a 12,000-character projection merely
because a session handles website/customer data. The
[large-result transport](LARGE_TOOL_RESULTS.md) creates complete indexed JSON
attachments before Copilot submission. Existing file/attachment/resource limits
still apply; exceeding a real transport budget reports an unsent result rather
than claiming completion from a truncated preview.

A fast scoped discovery session authorizes reads only within approved target
scope and preserves exact record-identity checks. New unrelated/private/local
scope and target mutations require approval. Sanitized reusable knowledge updates
are automatic; raw business records belong only to explicitly approved task
artifacts and are never automatically promoted into reusable knowledge.

One prefilled login-button click is permitted through browser.login_once; denial
or MFA pauses for the user. Credentials are never extracted or retained. Package
validation, code approval, protected paths, Stop and uncertainty remain active.

Synthetic tests cover direct customer-tool dispatch, complete long results,
customer session navigation, internal package hosts and continuing secret
redaction. Browser fixtures cover actual field reads and identity mismatches.
Live production data and the company's Copilot/VDI session are not exercised by
these tests.
