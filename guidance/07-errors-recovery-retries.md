# Errors, recovery and retries

Guidance version: 1.0.

## Failure classes

Differentiate UI capture failures, interrupted generation, authentication prompts, throttling, missing controls, upload mismatch, missing envelope, invalid/truncated JSON, wrong version, missing/unknown fields, stale identity, unsupported tool/version, invalid arguments, unsafe paths, permission errors, contradictory state, evaluator errors and synchronization timeout. Report the specific evidence instead of guessing.

## Fail closed

No tool executes from malformed, ambiguous, incomplete or stale output. Local repair may extract one complete envelope without altering its meaning. It must not invent fields, close truncated JSON, choose between conflicting requests or alter arguments. Static validation errors are not execution instructions.

## Correction responses

The orchestrator sends compact validation errors and the expected contract. Reissue the same intended decision as one valid envelope using the current session/request IDs. Do not expand scope or imply the original request executed. Corrections count as submitted messages if actually sent; findings still save immediately and their file attaches on the ordinary ten-message cadence.

## Bounded retries

Every retry needs a reason, an applicable finite budget and a logged outcome. Respect the orchestrator's maximum attempts and task-step budget. When exhausted, explain the blocked operation and the next human decision. Do not circumvent a limit by renaming a call or starting an identical plan.

## Ambiguous side effects

If submission may have succeeded, reconcile the chat before another send. If a write/click/script outcome is uncertain, inspect safe evidence or request user review; never blindly repeat. Existing call IDs and immutable request hashes identify prior operations. Denial is a user decision, not a transient error.

## Authentication and diagnostics

Ask the user to sign in manually when required. Do not collect cookies, tokens or passwords or bypass access restrictions. The orchestrator may retain sanitized raw response text, a screenshot and a small DOM excerpt for diagnosis. These artifacts are not automatically safe to upload; keep them local and minimize sensitive content.

## Honest recovery outcome

Distinguish recovered, exhausted, unsupported and unexecuted. No local file, tool or UI test is successful without observed evidence. A blocked capability should produce a clear explanation and safe next step rather than fabricated completion.
