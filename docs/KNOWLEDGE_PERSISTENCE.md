# Local navigation and Discoveries persistence

Each visible run asks once for local filesystem navigation and verified knowledge
saving. This in-memory grant expires with the process; it does not authorize code
execution, authentication bypass, website transactions or arbitrary file changes.
File navigation probes the current local/mapped/network volume and reports sanitized
OS errors. Browser-profile access remains protected.

Knowledge uses the current environment's canonical `Discoveries knowledge` store. Mapped S: is preferred: a checkout on that share uses its sibling store, and other checkouts use `S:\CopilotLocalAgent\Discoveries knowledge`. Without mapped S:, accessible UNC checkouts use their sibling store; local checkouts use `%LOCALAPPDATA%\CopilotLocalAgent\Discoveries knowledge`. Remembered host paths do not choose the destination on a different machine. Startup verifies a unique probe, its hash, and SQLite schema/integrity. The actual storage mode and filesystem path are included in the startup contract and save responses.

For an isolated live test, `app.py --local-knowledge-test-directory` can select an empty direct child of `%LOCALAPPDATA%\CopilotLocalAgent\live-navigation-tests`. This explicit test store remains separate from normal environment-selected storage.

Website knowledge and discovery records share the SQLite ledger. Compatible JSON
records already under the selected Discoveries root are read through a
compatibility path and promoted on approved saves. The app no longer searches
legacy OneDrive or LocalAppData knowledge stores automatically.
Known columns in newer stores remain readable; incompatible writes return a
specific diagnostic. Executable website hints retain privacy and authentication
checks. Custom bounded JSON categories support ordinary knowledge.

`knowledge.note` saves ordinary findings in immutable files under Discoveries,
verifies the bytes, and attempts indexing in the shared ledger. A schema/index
failure does not invalidate an already verified note: the receipt reports both
statuses. `knowledge.lookup` lists note identifiers or reads verified content for
the reasoning agent. Notes are evidence, never execution authority.

Uncertain optional knowledge operations are inspected against retained hashes.
Proven outcomes become completed/not-executed; unknowable operations are quarantined
without success credit or replay. Damaged active rows are retained transactionally
before removal from the active namespace. Materially different safe knowledge
writes can then proceed. Recovery tools do not depend on operation-learning flags.

The local UI journals run events across launches, including failed, cancelled,
blocked and recovered runs. A visibility choice is no longer offered. Real VDI
drive mappings, permissions and authentication still require target-environment
confirmation; synthetic tests do not establish those conditions.
