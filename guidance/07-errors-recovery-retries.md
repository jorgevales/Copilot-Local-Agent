# Errors, recovery and retries

Guidance version: 1.0.

## Failure classes

Differentiate UI capture failures, interrupted generation, authentication prompts, throttling, missing controls, upload mismatch, missing envelope, invalid/truncated JSON, wrong version, missing/unknown fields, stale identity, unsupported tool/version, invalid arguments, unsafe paths, permission errors, contradictory state, evaluator errors and synchronization timeout. Report the specific evidence instead of guessing.

## Fail closed

No tool executes from malformed, ambiguous, incomplete or stale output. Local repair may extract one complete envelope without altering its meaning. It must not invent fields, close truncated JSON, choose between conflicting requests or alter arguments. Static validation errors are not execution instructions.

## Correction responses

The orchestrator sends the observed validation errors and expected contract. For malformed JSON, inspect the reported parser position and reissue the whole envelope with valid JSON; escape quotes, backslashes and line breaks inside string values, and keep script content as ordinary text. For a missing field, add the listed field without changing the intended action. No tool from the rejected response ran. For a local preflight rejection, preserve the user's outcome and authorized scope, use the exact rejection and prior result, and correct its specific failing selector, argument, path, timeout or code. A small justified repair to the same approach is sufficient. Changing only a call ID is not a recovery. If no safe alternative exists, return a blocked error that names the actual barrier and next step. Never label a policy rejection as a formatting problem or imply a rejected request executed. Corrections count as submitted messages if actually sent; findings still save immediately and their file attaches on the ordinary ten-message cadence.

## Answer completion

After each result, choose one next state: continue with the next useful bounded tool batch, ask one necessary question, give a final answer when the goal is verified, or report a real blocker. A progress update alone is not completion. Base every claim on the returned outcome; separate completed, failed and not-executed work. Continue independent safe work after a certain failure. A `not_started` result is not denial, and a denial must not be retried or bypassed.

For an artifact download that returns `not_started`, provide a real clickable artifact link in the next response after the END marker and request `copilot.download` in that same response. Include the exact visible link label as `link_text` and the basename as `expected_name`. Do not substitute a guessed URL, a prior-turn link or a local file. If a usable UI link cannot be provided, report that observed delivery limitation plainly.

## Bounded retries

Every retry needs a reason, an applicable finite budget and a logged outcome. Respect the orchestrator's maximum attempts and task-step budget. When verified evidence proves a failed method's effects are certain, continue with a targeted correction to the same approach when useful. Preserve successful work and explain why the correction addresses the observed failure. Supervised session authorization covers valid revisions; other sessions use their applicable approval flow. When exhausted, explain the blocked operation and the next human decision. Do not circumvent a limit by renaming a call or starting an identical plan.

When a tool call fails with certain effects, continue from its actual result using a targeted repair when useful; tool usage has no round-count limit. After a batch stops, use its `not_executed` list as authoritative; never infer those calls ran. Preparation timeouts before the Copilot Send click record the failing browser preparation stage and are safe to retry only after a fresh user request. Once Send is attempted, delivery is uncertain and must not be retried automatically.

## Ambiguous side effects

If the original owned navigation tab is lost, the local ledger quarantines a
trusted navigation-only operation as `unverifiable_original_tab_missing`, without
crediting completion. Request a fresh `browser.open`, then live inspection. Do not
repeat reconciliation against a replacement tab or trust lost-tab facts. Use
`browser.diagnostics` for sanitized authoritative registration and ledger state.
For an uncertain non-navigation browser action that cannot be reconciled safely, request `browser.recover_uncertain` with the unresolved call ID and a fresh approved same-origin checkpoint URL. After separate approval, the local tool quarantines the unresolved action as `abandoned_unverifiable`, gives it no completion or not-executed credit, opens and verifies a new owned checkpoint, clears only the blocking ephemeral browser-plan/customer state, and returns control to the same run automatically. Never repeat the uncertain action. Unrelated sanitized `site_knowledge.save` proposals may proceed under their normal separate approval after this recovery. Consequential non-browser or otherwise unclassified uncertain operations stay blocked.

If submission may have succeeded, reconcile the chat before another send. For an uncertain navigation-only browser call, request `browser.info` and then `browser.reconcile` with the original call ID, exact observed URL, and `completed` or `not_executed`. The local tool checks the same owned tab against its pre-action fingerprint and resolves the ledger automatically when the evidence agrees. Send further navigation in a later tool request. Other uncertain writes and consequential effects remain blocked; never blindly repeat. Existing call IDs and immutable request hashes identify prior operations. Denial is a user decision, not a transient error.

## Authentication and diagnostics

Ask the user to sign in manually when required. Do not collect cookies, tokens or passwords or bypass access restrictions. The orchestrator may retain sanitized raw response text, a screenshot and a small DOM excerpt for diagnosis. These artifacts are not automatically safe to upload; keep them local and minimize sensitive content.

## Honest recovery outcome

Distinguish recovered, exhausted, unsupported and unexecuted. No local file, tool or UI test is successful without observed evidence. A blocked capability should produce a clear explanation and safe next step rather than fabricated completion.


## Discovery-specific rejection and recovery
A rejected new contract runs zero effects and does not fall through to arbitrary legacy tools. No autonomous shape-repair or model replan loop is installed. The existing explicit user-approved sequential tools remain available for a NEW request, not as automatic bypass/replay.

Only the installed public-read recovery preset may retry (if separately enabled): at most three attempts including the first, shared unchanged task/branch/run deadlines, maximum 60 seconds per URL and the smaller remaining run backoff budget. Honor Retry-After by delaying the same origin and reducing its rate/concurrency. No retry for access denial, authentication, scope/public-IP/integrity violations or unknown effects. No browser escalation to bypass restriction. The local independent finaliser emits cancellation/partial/gap diagnostics even when aggregate dependencies cannot be met.

Cancellation blocks new dispatch and increments the persistent generation; late owner/fence commits are refused. Automatic interrupted-run resume/lease stealing and graph amendments are NOT enabled. Retain clean checkpoints and consumed counters; do not restart an interrupted run under a reset budget or replay an uncertain legacy effect. Runtime cancellation and fault/restore gates remain NOT RUN until an authorised test phase.

## Retained-operation recovery

`operation.call` classifies failures as `drift`, `auth`, `rate`, `blocked`, `input` or `error` and performs no automatic retry. A shape or route drift marks only the current operation version degraded; prior versions and audit events remain retained. Recovery is a new, separately approved `operation.learn` proposal based on fresh public browser evidence and the current revision. Authentication cannot be recovered through the public adapter, and rate or access failures must not be bypassed by browser fallback.
