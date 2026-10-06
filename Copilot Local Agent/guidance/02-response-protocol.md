# Structured response protocol

Guidance version: 1.0. The attached `response-v1.schema.json` is the exact machine contract.

## Envelope

Return exactly one envelope, without introductory prose or an additional competing envelope. Put the JSON object in a single fenced Markdown code block labelled `json` BETWEEN the marker lines. This preserves literal backslashes and other JSON characters in Copilot's rendered UI. Keep the markers outside that code block. The orchestrator extracts the verbatim code text; fences do not change the JSON schema.

File-delivery exception: after the END marker, publish the actual generated artifact as one clickable Markdown download link outside the JSON/code block. The local download tool requires a real UI anchor. A link only inside `user_response` is inert code; plain text and `sandbox:` references do not count. Keep exactly one response envelope; never fabricate a link. Avoid copying signed URL query tokens into JSON or summaries.

The complete no-tool example below shows the exact marker and fence placement.

Use JSON double quotes, finite numbers, and no comments, trailing commas or duplicate object keys. Never omit required fields. Unknown fields are rejected. A parser may extract one complete envelope from surrounding text as a meaning-preserving repair, but that is recovery behavior, not permission to ignore this format.

Windows paths inside JSON strings require escaped backslashes, for example `"C:\\Users\\Example"`. Forward-slash paths such as `"C:/Users/Example"` are also valid. Do not drop quotes from script string literals. The rendered response must preserve the exact proposed script and argument values.

## Required fields

| Field | Meaning |
|---|---|
| `protocol_version` | Exactly `"1.0"` |
| `session_id`, `request_id` | Exact current orchestrator-supplied identities |
| `response_id` | Distinct identifier for this emitted response |
| `response_type` | `final`, `tool_request`, `clarification`, or `error` |
| `user_response` | User-facing answer or concise progress explanation |
| `task_interpretation` | What the user is requesting |
| `decision_summary` | Concise reason for this decision; no hidden reasoning |
| `assumptions` | Array of strings; empty when none |
| `action_plan` | Nonempty ordered array of objects with `step`, `action`, `verification` |
| `tools_required` | Boolean consistent with requested tools |
| `tool_requests` | Ordered array of objects with `call_id`, `name`, `version`, `arguments`, `expected_result` |
| `approval_required` | Your declaration that authorization may be needed; local policy remains authoritative |
| `code_runner_proposal` | Proposal object, or `null`; it cannot grant approval |
| `risk_summary` | Concise side-effect/privacy/scope assessment |
| `continuation_state` | `continue`, `await_user`, `complete`, or `blocked` |
| `clarification` | Specific user question, or `null` |
| `useful_findings` | Array of objects with `key`, `content`, `provenance` |
| `completion_status` | `in_progress`, `complete`, or `blocked` |
| `recoverable_errors` | Array of objects with `code`, `message` |

Tool request names, versions and arguments must match the current catalogue. Code Runner proposal structure must match the supplied schema and tool definition; executable arguments belong in the actual tool request. A proposal alone does not schedule execution.

## Logical invariants

A final answer has no pending tool requests, `clarification: null`, and uses `complete` for continuation and completion. A tool request has at least one tool call, `tools_required: true`, `clarification: null`, `continuation_state: "continue"` and `completion_status: "in_progress"`. A clarification has an actual question, no executable requests, `continuation_state: "await_user"` and `completion_status: "in_progress"`. An error has no executable requests, at least one specific `recoverable_errors` entry, and uses `blocked` for both continuation and completion. `tools_required` must agree with whether the tool request array is nonempty.

Use positive ordered step numbers. Keep tool call IDs distinct. Do not silently repeat an operation whose previous result is uncertain. Return evidence-based findings on any response, independently of tenth-message attachment cadence.

## Valid no-tool example

The identifiers below are illustrative; replace them with the current request's actual IDs.

````text
<<<COPILOT_AGENT_V1_BEGIN>>>
```json
{
  "protocol_version": "1.0",
  "session_id": "example-session",
  "request_id": "example-request",
  "response_id": "example-response-1",
  "response_type": "final",
  "user_response": "The requested text is ready: Hello, world.",
  "task_interpretation": "Provide a short greeting.",
  "decision_summary": "This request can be answered directly.",
  "assumptions": [],
  "action_plan": [
    {"step": 1, "action": "Provide the requested greeting.", "verification": "Confirm that the answer contains the greeting."}
  ],
  "tools_required": false,
  "tool_requests": [],
  "approval_required": false,
  "code_runner_proposal": null,
  "risk_summary": "No local side effects.",
  "continuation_state": "complete",
  "clarification": null,
  "useful_findings": [],
  "completion_status": "complete",
  "recoverable_errors": []
}
```
<<<COPILOT_AGENT_V1_END>>>
````

## Corrections and correlation

On correction, preserve the intended decision but fix the listed validation errors and echo the new current request ID. Do not execute tools yourself or assume the previous malformed request ran. Submission and execution ledgers are local responsibilities. New transport messages, including corrections and tool results, receive their own request identities.
