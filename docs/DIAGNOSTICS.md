# Bug diagnostics and review

When the agent catches an actionable browser, protocol, operating-system, or application failure, it sets the session's `bug_fix` flag and writes two JSON reports under the selected personal storage folder. Reporting runs quietly so the user can continue the conversation and other work:

- `runtime/diagnostics/internal/` contains `internal_bug_report_<id>.json`. It includes the filtered exception message, project-relative stack locations, and a short evidence-based file recommendation. Send this report only to an authorized internal Copilot environment. Review each recommended source file before attaching it.
- `runtime/diagnostics/external_review/` contains `sanitized_bug_report_<id>.json`. It uses a fixed allowlist and file/function aliases. The raw error message, source paths, repository identity, and session identifier are omitted. The report is validated before it is written.

When the user ends the agent, the terminal gives a short handoff reminder. Send internal reports only to an authorized Copilot environment. Review the sanitized report manually before any external sharing. The agent never uploads or sends either report.

Reports are uniquely named and stored separately. The default retention period is 30 days; set `COPILOT_AGENT_DIAGNOSTIC_RETENTION_DAYS` to an integer from 1 to 3650 to change it. Expiration removes only matching generated bug-report JSON files from these two diagnostic folders. On non-Windows systems, report files are created with owner-only permissions. On Windows, they inherit the selected storage directory's access controls.

Diagnostics intentionally omit prompts, document contents, environment values, clipboard data, network traffic, and open-file inventories. Unknown values are left null where the report schema supports them.
