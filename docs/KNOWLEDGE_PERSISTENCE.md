# Local navigation and Discoveries persistence

Each visible run asks once for local filesystem navigation and verified knowledge
saving. This in-memory grant expires with the process; it does not authorize code
execution, authentication bypass, website transactions or arbitrary file changes.
File navigation probes the current local/mapped/network volume and reports sanitized
OS errors. Browser-profile access remains protected.

Knowledge uses `Discoveries knowledge` beside the project's parent on the live
S: share. It does not follow runtime, workspace, profile or OneDrive storage. On
a machine where the project is not on the mapped S: share, the agent stops before
writing rather than silently falling back. A configured `knowledge_directory`
must match this canonical folder. Startup creates a unique probe, flushes it,
checks its hash, removes it, and checks SQLite schema and integrity. The verified
S: path and resolved UNC filesystem path are included in the startup contract and
each agent save response.

For a local live navigation test only, `app.py --local-knowledge-test-directory`
can select an empty direct child of `%LOCALAPPDATA%\\CopilotLocalAgent\\live-navigation-tests`.
The test store is reported explicitly and scoped as the only agent write root for
that run. This opt-in does not change the normal S:-only production path or act as
an automatic fallback.

Website knowledge and discovery records share the SQLite ledger. Compatible JSON
records already under the selected S: Discoveries root are read through a
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
