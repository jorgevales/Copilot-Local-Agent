# Local navigation and Discoveries persistence

The session confirmation authorizes automatic saving of new, concise, verified, reusable knowledge. No additional run/save question is required for that knowledge. The in-memory grant expires with the session and cannot authorize unrelated targets, arbitrary file writes, executable code or consequential website actions. The orchestrator prepares exact payloads and dispatches registered tools; model consent flags cannot grant authority.

## S: root and storage recovery

Runtime S: resolution preserves the direct path first, then tries live PowerShell DisplayRoot, CIM ProviderName and SMB RemotePath providers when strict Python resolution fails. Destinations are validated as UNC directories. Extended UNC I/O spelling is applied after logical path validation. No provider permits automatic C: or OneDrive fallback. Provider lookup is fixed, hidden, read-only and bounded at ten seconds. Setup scratch/cache fallbacks have separate rules and never relocate durable knowledge.

Knowledge uses `Discoveries knowledge` beside the project on the live mapped S: share. A configured `knowledge_directory` must match this canonical root. Startup flushes/readback-verifies a unique probe and checks SQLite schema/integrity. Prompt contracts supply exact S: and UNC paths; Copilot must use those supplied paths. If the required share cannot be resolved or written, report the actual diagnostic rather than selecting another drive.

## Ledger and centralized website views

`<root>/discovery-v1/ledger.sqlite3` is the authoritative evidence/revision store. An additive `site_knowledge_revisions` table retains prior website records before active updates. Compatible old JSON records under the root remain readable and are promoted on authorized saves. Legacy OneDrive/LocalAppData knowledge is not searched automatically. Known columns in newer ledgers may remain readable; incompatible writes report a diagnostic.

One exact canonical origin owns `<root>/sites/<host>-<origin-hash>/`. Tenant, sharing scope, environment and optional application identity select a namespace under `namespaces/`. Explicit bindings override origin/local-user defaults. Queries, fragments, credentials and caller titles never form the canonical site identity.

`current.md` contains concise active hints and one recommended verified method per destination. `methods.md` labels `recommended_verified` and `previous_verified`, preferring locally measured shorter duration, then fewer steps where timing is unavailable. Full history stays in SQLite. Derived files are readback-verified views; `view_unavailable` is reported independently if a view fails after the ledger commit.

Look up saved knowledge before broad rediscovery. Exact duplicate fresh site saves return `unchanged` without another revision. Public static-map saves retain meaningful route/fingerprint/trust changes; equivalent repeated runs skip timestamp-only revisions. Renewal halfway through TTL is meaningful. Public lookup supports bounded offset/limit pagination.

## Verified workflows and sanitized content

`site_knowledge.save` accepts generic routes, locators, form labels, document areas, recovery and `navigation_methods`. Methods require current-session `source_call_ids`; local validation checks successful completed browser calls, executed plan steps and the confirmed final destination. Failed, partial, observation-only and uncertain calls cannot verify a method. Untrusted call labels are hashed before persistence. Claimed duration is replaced with measured local ledger timing. A faster verified method becomes recommended while previous methods remain labeled. See `guidance/website/memory.md` for the exact conditional example.

The session grant replaces the extra save question while exact prepared-payload hashes, scope, evidence integrity, CAS, freshness and independent trust checks remain enforced. Knowledge never grants execution permission. A new process/session obtains a fresh grant.

Preserve useful internal URLs, system paths, generic workflows and precise sanitized successful examples. Strip URL queries/fragments and template concrete record parameters. Never save credentials, tokens, cookies or identifiable customer/personal records as reusable knowledge. Structural checks reject common secret/record keys and obvious sensitive text; they supplement the model's sanitization duty and do not claim exhaustive PII classification. Skip empty, noisy or duplicate content.

`knowledge.note` saves bounded immutable sanitized findings in the active site/namespace's `notes` folder. Pre-bind site notes use that site's `unbound/notes`; non-site operational notes retain `<root>/notes`. Equivalent content reuses its note despite changed titles/whitespace. Bytes are verified and ledger indexing is attempted. An index failure reports `indexed: false` while retaining the verified artifact. `knowledge.lookup` reads hash-verified notes, which are non-executable evidence.

Raw crawler HTML/markdown/AX/network captures and requested business artifacts remain separately authorized task evidence. Saving them never labels them sanitized reusable navigation knowledge or authorizes automatic next-session intake.

## Recovery and environment limits

Uncertain knowledge operations are inspected against retained hashes. Proven outcomes become completed/not-executed; unknowable operations are quarantined without success credit or replay. Damaged active rows are transactionally retained before releasing their namespace. Materially different safe saves can then proceed.

An explicit `app.py --local-knowledge-test-directory` run may select an empty direct child of `%LOCALAPPDATA%\\CopilotLocalAgent\\live-navigation-tests`. This reported test store never becomes a production fallback. Real VDI mappings, authenticated navigation, permissions and shared-drive persistence require fresh target evidence; offline tests do not establish those outcomes.
