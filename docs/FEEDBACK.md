# Verbose feedback and participant roles

Feedback is enabled throughout the terminal conversation. Every emitted line has a UTC time and an actor label, including multiline text; terminal control characters in untrusted content are escaped so a reply cannot erase output or impersonate another actor.

| Actor | Meaning |
|---|---|
| `User` | Human input and explicit choices, including model selection, approvals and session commands. |
| `Copilot (Agent)` | Copilot's public reply, task interpretation, concise decision summary, assumptions, action plan and risk summary. Proposed actions are distinguished from performed actions. |
| `Orchestrator` | Local coordination: submission ordinal, response validation, correction, findings acceptance, tool dispatch, denial and stopping conditions. |
| `System` | Browser/startup status, visible generation status, file upload metadata, configuration and infrastructure errors. |
| `Tool/<name>` | An actual local tool's start, arguments, authorization basis, factual result and error; for example `Tool/system.versions`. |

## Live Copilot output

The browser reports changing request-correlated assistant text during its capture loop, rather than waiting for final validation. The orchestrator incrementally reads completed top-level public JSON values after matching the current session and request identities. It displays new or changed public fields immediately and suppresses repeated identical samples. Incomplete strings remain buffered, preserving escapes and allowing secret redaction before display. Tool requests, scripts and hidden reasoning are not streamed as decision summaries.

Example output:

```text
[14:52:01] [Orchestrator] Sending message 3 (user_turn), with 0 attachment(s).
[14:52:02] [System] Copilot is generating a response.
[14:52:03] [Copilot (Agent)] Live preview (unvalidated) | Decision summary: Inspect the local version first.
[14:52:04] [Copilot (Agent)] Live preview (unvalidated) | Action plan: 1. Request system.versions (verify: use its actual result)
[14:52:06] [Orchestrator] Validated response: tool_request; findings accepted=0.
[14:52:06] [Tool/system.versions] Starting versions-one under read-only policy. Arguments: {}
[14:52:06] [Tool/system.versions] Outcome: {"ok": true, "tool": "system.versions", "result": {"python": "3.14.2"}}
```

This example explains the format; actual live evidence is in `TEST_REPORT.md`. Code approval displays its full immutable plan and script preview with the same participant labels. Final output is explicitly labelled a validated reply.

## Authority and limits

A live preview is unvalidated display data. It cannot execute a tool, change the message counter, grant approval or replace authoritative state. The existing strict complete-response validator and policy/approval gates still govern actions. Malformed responses receive bounded correction and clearly attributed diagnostics.

The app shows publicly visible response fields and generation status. It does not request private chain-of-thought or click hidden reasoning panes. Copilot may buffer code-preview rendering; feedback advances when the UI exposes readable content, rather than inventing unavailable text. This is field-level live streaming with status updates, not a promise of token-by-token access.

Feedback events are recorded in the session's redacted `events.jsonl` with request identity and preview validation status. Tool outputs are bounded and redacted; full authoritative results and retained artifact references remain in session state. Session starts, `:new`, and exits preserve records without deletion.
