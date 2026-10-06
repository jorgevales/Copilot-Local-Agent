# Terminal feedback and participant roles

Feedback is enabled throughout the terminal conversation. Every emitted line has a UTC time and actor label. Interactive terminals receive distinct readable ANSI foreground/background colours; redirected output, unsupported terminals, `NO_COLOR`, and `TERM=dumb` receive the same labels in plain text. Terminal control characters in untrusted content are escaped, repeated blank lines are collapsed, and common Markdown chrome is removed from the normal view.

| Actor | Meaning |
|---|---|
| `User` | Human input and explicit choices, including model selection, approvals and session commands. |
| `Copilot` | Copilot's public reply, task interpretation, concise decision summary, assumptions, action plan and risk summary. Proposed actions are distinct from performed actions. |
| `Orchestrator` | Local coordination: submission ordinal, response validation, findings acceptance, dispatch, denial and stopping conditions. |
| `System` | Browser/startup status, visible generation status, upload metadata and ordinary infrastructure information. |
| `Approval` | Exact immutable approval scope and every full proposed script with SHA-256. |
| `Error` | Rejected protocol, stopped action or other failure needing attention. |
| `Tool/<name>` | Concise actual start, authorization basis, status, output paths, verification summary, error and audit reference. |

## Structured normal view

When a validated response parses reliably, the terminal renders short sections such as `PROPOSED ACTION`, `EXPLICIT APPROVAL REQUIRED`, `STARTING`, `RESULT`, and `FINAL RESULT`. Fields are limited to the task, action, purpose, authority, status, output paths, verification and errors. Long protocol arguments and complete results remain in the session state/events and immutable approval/audit files instead of flooding the normal view.

Code is the deliberate exception: the approval view prints every exact script in full between clear begin/end lines and shows its SHA-256. It also shows the interpreter, argv, permissions, file/network/process/desktop scope, expected effects, plan hash and retained full-preview path. Choosing a plan approves only the complete scripts already displayed.

## Live Copilot output

The browser reports changing request-correlated assistant text during capture. The orchestrator reads only completed top-level public JSON values after matching the current session and request identities. New values are visibly prefixed `UNVALIDATED PREVIEW`; incomplete strings remain buffered, malformed/incomplete envelopes execute nothing, and tool requests/scripts/hidden reasoning are never streamed as authority. Identical preview text is not printed again when the final envelope validates; the terminal says that the preview is validated.

Example plain-text output:

```text
[14:52:01] [Orchestrator] Sending message 3 (user_turn), with 0 attachment(s).
[14:52:02] [System] Copilot is generating a response.
[14:52:03] [Copilot] UNVALIDATED PREVIEW — Task
[14:52:03] [Copilot]   Capture three physical displays and keep three viewers on display 2.
[14:52:06] [Copilot] PROPOSED ACTION
[14:52:06] [Copilot]   Action: 1. Inspect versions | verify: use the actual result
[14:52:07] [Tool/system.versions] RESULT
[14:52:07] [Tool/system.versions]   Status: completed
```

## Authority and retention

A live preview is display data only. It cannot execute a tool, change the message counter, grant approval or replace authoritative state. Only one complete current validated envelope can dispatch actions. Malformed responses receive bounded correction and an `Error` entry.

The app shows public fields and generation status, not private chain-of-thought. UI buffering can delay fields. Feedback events are recorded in redacted `events.jsonl`; full authoritative tool results, approval JSON and local-Python audit receipts remain in session storage. Session changes and exit preserve records without deleting files.
