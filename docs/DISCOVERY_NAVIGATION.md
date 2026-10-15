# Live discovery and navigation

Crawl4AI 0.9.5 ([upstream](https://github.com/unclecode/crawl4ai)) is the default
navigation extractor for `discovery.manifest`. Run `Setup.cmd` to install the
updated pinned dependencies. No extra crawler browser installation is needed.
The adapter uses Crawl4AI's LXML scraping tools on sanitized observed navigation
HTML; the existing public-IP-pinned HTTPS reader owns all network access. Page
text, values, scripts, media and credentials never enter the reusable map.
Evidence remains static; use approved visible Edge tools for JavaScript rendering
or manual sign-in.

For broad exploration, prefer one manifest with `expand_urls: true` over one
Copilot turn per page. The local loop investigates successive frontiers with
up to eight concurrent reads and four per origin. Suggested deep budgets are
1,000 pages, depth 10, 5,000 tasks/requests, 512 MiB, 1,800 run seconds, 1,500
task/branch seconds, 30-second reads, three attempts and two requests per second
per origin. See `docs/examples/deep-discovery.json`; replace the exact origin,
seeds and nested request ID. Each full manifest is validated locally against the
current approved target/session scope; any required expansion is approved before
dispatch. Queue
exhaustion, resource limits, cancellation and safety boundaries end the loop.

Bind the exact namespace and look up saved knowledge first. Expansion prioritizes
previously observed unexplored links from a saved map with matching
scope, intact evidence and unexpired provenance. Each reused candidate receives
a fresh authorized GET. Each run retains its own exact scope and budgets. Save
useful runs with `discovery.knowledge_save` under the session knowledge grant,
without another save confirmation. Prepared payload/evidence integrity, exact
namespace, expected-revision CAS and independent-observation trust checks remain
mandatory. An automatic origin namespace can be used under the session grant;
explicit app/tenant/environment bindings take precedence and must precede a source
run if its evidence belongs to that distinct namespace.
`discovery.knowledge_lookup` accepts `offset` and `limit` (1–40), returns
`next_offset`, and retrieves all 1,000 saved routes without recrawling. Missing,
invalidated or stale maps require discovery; integrity failures stop reuse.

Deep runs retain full sanitized results up to 8 MiB while Copilot receives a
compact projection. The shared SQLite ledger is bounded at 256 MiB and individual
structural artifacts at 2 MiB. Oversized maps are explicitly partial. Operators
can select `discovery_extractor: "structure"` for the legacy parser; missing
Crawl4AI dependencies stop preparation without silently changing engines.

The bounded public-site discovery and static navigation tools are installed in the live agent. The supported flags (`manifest_path`, `persistent_graph`, `bounded_parallelism`, `local_recovery`, `knowledge_write`, `knowledge_reuse`) are enabled by default. `targeted_repair` stays unavailable because no safe browser repair adapter exists. An operator can set these booleans in an explicit configuration file or select a smaller set with `COPILOT_AGENT_DISCOVERY_FLAGS`. Flags expose tools; they never approve a request.

`discovery.shadow` compiles a manifest without network access. `discovery.manifest` runs one bounded authorized public HTTPS GET/HEAD manifest with local bootstrap, HTTP, structure, validation, and aggregation workers. It uses exact origins, public DNS and pinned peers, installed route patterns, task/request/byte/deadline limits, and the shared S:/UNC ledger. It does not use authenticated browser sessions, generated code, network observers, or autonomous browser actions. A failed or interrupted run retains only committed evidence and marks unfinished tasks terminal.

Knowledge writes use the in-memory session knowledge grant and exact revision/evidence checks; they do not ask for separate save consent. One independent public observation remains a candidate, and two matching successful runs are required for trusted static knowledge. Equivalent fresh maps return `unchanged` without timestamp-only revisions; meaningful route/fingerprint/trust changes and TTL renewal are retained. Parameter-bearing page captures are omitted from durable map candidates so saved source URLs remain free of queries/fragments without falsifying cryptographic evidence.

`navigation.intent` compiles a read-only route from bound, trusted public evidence and verifies fresh public fingerprints/links. It does not claim an interactive browser transition or authenticated access. Authenticated or internal UI discovery instead uses the separately registered visible-browser/Crawl4AI tools. Browser workers and targeted repair remain unavailable inside the public manifest engine.

Reusable site hints, including internal URLs, system paths and verified navigation methods, use `site_knowledge.save`; see `docs/KNOWLEDGE_PERSISTENCE.md` and `guidance/website/memory.md`. The authoritative ledger is `<resolved Discoveries knowledge>/discovery-v1/ledger.sqlite3`. Canonical site/namespace folders hold concise `current.md`, labeled `methods.md` history and the public `public-static-map.md` view. Reuse current recommended methods before repeating broad discovery. Raw HTML/markdown/DOM/AX/network captures remain scoped task evidence and are never automatically classified as sanitized reusable knowledge. Credentials, tokens, cookies and identifiable customer/personal records must not enter the reusable store.

Copilot replies use one marker pair with plain-text JSON between the markers. The local adapter captures the current assistant chat text after generation ends, validates the complete envelope, and sends a bounded correction request promptly when a finished reply is malformed. It never resends a submission whose delivery is uncertain.

The signed-in Copilot checks on 2026-10-08 confirmed a committed synthetic request, current-turn plain-text capture, rejection of a Copilot refusal, and a later valid marker-delimited JSON response. A fresh full-orchestrator run uploaded the eight startup references and validated initialization, but its first page request could not be proven submitted; the agent blocked without retry or tool execution. The page-understanding chat reported that Copilot could not access the supplied authenticated URL. Read-only inspection of the already open Edge page identified its major sections and navigation; a discovery shadow now accepts the generic `/inicio` route while still rejecting patient-ID routes. These observations do not establish a successful live browser tool cycle or authenticated discovery.
