# Errors, recovery and retries

Guidance version: 1.0.

## Failure classes

Differentiate UI capture failures, interrupted generation, authentication prompts, throttling, missing controls, upload mismatch, missing envelope, invalid/truncated JSON, wrong version, missing/unknown fields, stale identity, unsupported tool/version, invalid arguments, unsafe paths, permission errors, contradictory state, evaluator errors and synchronization timeout. Report the specific evidence instead of guessing.

## Fail closed

No tool executes from malformed, ambiguous, incomplete or stale output. Local repair may extract one complete envelope without altering its meaning. It must not invent fields, close truncated JSON, choose between conflicting requests or alter arguments. Static validation errors are not execution instructions.

## Correction responses

The orchestrator sends compact validation errors and the expected contract. Reissue the same intended decision as one valid envelope using the current session/request IDs. Do not expand scope or imply the original request executed. Corrections count as submitted messages if actually sent; findings still save immediately and their file attaches on the ordinary ten-message cadence.

## Bounded retries

Every retry needs a reason, an applicable finite budget and a logged outcome. Respect the orchestrator's maximum attempts and task-step budget. When verified evidence proves a failed method's effects are certain, continue with a materially different safe approach instead of replaying it. Changed local execution needs a fresh exact approval. When exhausted, explain the blocked operation and the next human decision. Do not circumvent a limit by renaming a call or starting an identical plan.

When a tool call fails with certain effects, use the bounded recovery turn to continue from its actual result and remaining tool-round budget. After a batch stops, use its `not_executed` list as authoritative; never infer those calls ran. Preparation timeouts before the Copilot Send click record the failing browser preparation stage and are safe to retry only after a fresh user request. Once Send is attempted, delivery is uncertain and must not be retried automatically.

## Ambiguous side effects

If the original owned navigation tab is lost, the local ledger quarantines a
trusted navigation-only operation as `unverifiable_original_tab_missing`, without
crediting completion. Request a fresh `browser.open`, then live inspection. Do not
repeat reconciliation against a replacement tab or trust lost-tab facts. Use
`browser.diagnostics` for sanitized authoritative registration and ledger state.
Consequential or unclassified uncertain operations stay blocked.

If submission may have succeeded, reconcile the chat before another send. For an uncertain navigation-only browser call, request `browser.info` and then `browser.reconcile` with the original call ID, exact observed URL, and `completed` or `not_executed`. The local tool checks the same owned tab against its pre-action fingerprint and resolves the ledger automatically when the evidence agrees. Send further navigation in a later tool request. Other uncertain writes and consequential effects remain blocked; never blindly repeat. Existing call IDs and immutable request hashes identify prior operations. Denial is a user decision, not a transient error.

## Authentication and diagnostics

Ask the user to sign in manually when required. Do not collect cookies, tokens or passwords or bypass access restrictions. The orchestrator may retain sanitized raw response text, a screenshot and a small DOM excerpt for diagnosis. These artifacts are not automatically safe to upload; keep them local and minimize sensitive content.

## Honest recovery outcome

Distinguish recovered, exhausted, unsupported and unexecuted. No local file, tool or UI test is successful without observed evidence. A blocked capability should produce a clear explanation and safe next step rather than fabricated completion.


## Discovery-specific rejection and recovery
A rejected new contract runs zero effects and does not fall through to arbitrary legacy tools. No autonomous shape-repair or model replan loop is installed. The existing explicit user-approved sequential tools remain available for a NEW request, not as automatic bypass/replay.

Only the installed public-read recovery preset may retry (if separately enabled): at most three attempts including the first, shared unchanged task/branch/run deadlines, maximum 60 seconds per URL and the smaller remaining run backoff budget. Honor Retry-After by delaying the same origin and reducing its rate/concurrency. No retry for access denial, authentication, scope/public-IP/integrity violations or unknown effects. No browser escalation to bypass restriction. The local independent finaliser emits cancellation/partial/gap diagnostics even when aggregate dependencies cannot be met.

Cancellation blocks new dispatch and increments the persistent generation; late owner/fence commits are refused. Automatic interrupted-run resume/lease stealing and graph amendments are NOT enabled. Retain clean checkpoints and consumed counters; do not restart an interrupted run under a reset budget or replay an uncertain legacy effect. Runtime cancellation, fault/restore and VDI ACL gates remain NOT RUN until an authorised test phase.
