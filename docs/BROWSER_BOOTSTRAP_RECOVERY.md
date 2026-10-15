# Browser bootstrap and operation-ledger recovery

`browser.tabs` with `operation: list` is a read-only inventory. It is allowed
before `browser.open`, requires no execution approval, and returns an empty list
with `next_action: browser.open` when no owned page exists. An empty inventory is
normal startup state. Open the requested website rather than recovering the read.
`browser.info` similarly reports `no_owned_page` without inventing an original URL.
Open, close and reset operations retain their applicable execution authorization.

The orchestrator and session ledger classify listing by operation rather than
the catalogue's default mutation policy. Listing may be repeated even when a
previous inventory was incorrectly failed or quarantined. Interrupting a list
cannot lock the browser domain, including after private-session resume: a local
observation marker survives without retaining the request's private arguments.

Recovery validates the checkpoint before creating a page. A validation refusal
returns `not_started` and `side_effects_uncertain: false`, leaving only the
original unknown operation unresolved. When its original tab is missing, closed
or blank, a fresh approved checkpoint can be established without that original
website. A live original tab still follows the current session's origin policy.
Verified recovery quarantines the original outcome without replay or completion
credit and closes obsolete owned tabs.

Startup and exchanges repair identifiable legacy inventory failures and the exact
old recovery-origin preflight refusal. The repair is recorded and idempotent;
unknown writes and pending Copilot submissions remain unresolved. Old private
records whose operation/evidence was already omitted are not guessed to be reads;
use a fresh approved checkpoint for their explicitly identified uncertain call.

Regression checks reproduce listing before open, repeated/quarantined inventories,
missing-page recovery, rejected recovery without a second uncertain entry,
legacy-ledger repair, private resume and preservation of actual unknown effects.
