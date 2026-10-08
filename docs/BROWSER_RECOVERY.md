# Browser recovery, navigation approval and visible exchanges

The authoritative ledger is `SessionState.data['calls']`, persisted through
`SessionState.save`. Compact model context is a summary, never execution authority.

## Architecture and root cause

`BrowserAdapter.start` verifies the Edge profile/CDP endpoint and registers the
shared signed-in context. `_configure_tool_context` registers owned website tabs;
`new_tool_page` creates guarded replacement tabs. An attached Edge context has no
agent-launched PID; that alone does not mean the browser is missing.

`Orchestrator.turn` records a pre-action fingerprint, calls `begin_call`, executes
the registered tool, and records `finish_call`. Failed effects become uncertain
unless the tool establishes certainty. `_preflight` and `begin_call` enforce the
ledger's block on further state changes.

The deadlock had two sources: `capture_baseline` called `_owned_page` before
`browser.open` could create a replacement tab, even when there was no pending
operation; and reconciliation required an unavailable original tab forever.
Fresh approved opens now establish a replacement owned tab before fingerprinting.
`recover_missing_navigation` closes only the blocking requirement for lost
navigation-only records, preserving their unverified outcome.

## Recovery matrix

| Situation | Ledger outcome | Next action |
| --- | --- | --- |
| Original navigation tab available, matching fresh evidence | Reconciled completed/not executed | New approved action or approved session navigation |
| Original navigation tab unavailable or connection lost | `unverifiable_original_tab_missing`, completion not credited | Fresh approved open, then live observation |
| Fresh tab has the same URL as the missing original | Original remains uncredited | Never use replacement state as proof of the old operation |
| Form, search, write, download or consequential uncertainty | Uncertain and blocking | Independent evidence/review; never replay automatically |
| Profile, CDP or context binding changed | Reconciliation rejected | Diagnose the binding; never substitute another browser |
| Evidence conflicts with a proposed outcome | Uncertain and blocking | Inspect the actual original tab before correcting the request |

Quarantine preserves the original request/result hashes and adds its reason and
timestamp atomically. Repeated recovery is idempotent. Live pre-action
classification excludes forms, searches, customer-bound plans, and consequential
grants. A multi-transition navigation plan can be quarantined when its tab is lost;
a final URL alone cannot credit every step as completed.

## Navigation freedom after approval

Every locally reviewed browser approval displays a continued-navigation scope.
It grants the current agent session navigation within approved HTTPS websites and
their subdomains: opens, history navigation, navigation-only plans, inspection,
and bounded same-origin new tabs. The orchestrator supplies the actual scope to
Copilot on subsequent messages. Runtime origin, tab ownership and consequential
control checks continue to apply. Navigation still enters the effect ledger even
when no additional approval prompt is needed.

Forms, searches, customer-bound actions, writes, downloads and scripts retain
their normal exact approval. New websites and dependency hosts need approval.
Closing/resetting tabs retains approval. Scope expires with the orchestrator
session and is never restored silently from disk.

## Diagnostics and compatibility

Copilot may request the read-only `browser.diagnostics` tool for registration
type, connection state, owned-tab count, binding hashes and authoritative uncertain
or quarantined ledger states. It returns no URLs, titles, cookies or page content.
Its hashed operation IDs can be supplied directly to `browser.reconcile`.
Query-free URLs returned by ordinary inspection can be matched against the
original tab's fresh URL locally; private query values remain hashes in the audit.

Existing ledgers with a retained navigation-only baseline support recovery after
restart: unavailable live tokens are quarantined, never credited. Legacy uncertain
entries without a trusted baseline remain blocked because their effect class
cannot safely be reconstructed from redacted arguments. Browser context identity
and profile/CDP fingerprints prevent changed bindings from reconciling live calls.

## Visible interaction and knowledge

The terminal and graphical workspace display every validated Copilot response as
**Copilot process summary (delivered)**, including its understanding, decision,
assumptions, action plan, risk and user message. Each outgoing task, tool-result
message and correction is labelled **Orchestrator → Copilot**. The graphical
transcript includes expandable delivered-envelope details. These are delivered
public summaries; hidden private model reasoning is not requested or displayed.
Malformed responses execute nothing and are corrected through the visible flow.

Website transcript content is live local session content; persistent audit logs
retain hashes. Existing `site_knowledge.bind/retrieve/save` provide scoped,
expiring, revisioned and sanitized knowledge. Use fresh retrieved routes for a
narrow live check; stale or contradicted knowledge requires fresh reconnaissance.
Lost-tab facts must be re-observed and must never be promoted to verified knowledge.
