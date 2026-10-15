# Local website discovery and session package mode

Start **Start Agent UI.cmd** (or **Start Agent.cmd**). Accept the single fast
full-access session option to skip package quality review and individual plan
approvals together. It permits ordinary file reads/edits and cross-website
navigation for this session only. File deletion remains blocked; credentials,
manual sign-in, OS permissions and valid executable contracts remain enforced.
Closing or restarting the agent resets the grant.

The startup guide then offers local Crawl4AI discovery:

1. Choose Yes and paste a website address.
2. Give that website knowledge a title.
3. In the Edge tab that opens, sign in yourself if needed, including MFA. Open the
   starting page you want explored, then continue the guide.
4. Choose one exploration or repeated refresh. Press Enter to stop a repeated
   crawl. Completed pages and unfinished routes remain saved.
5. Add another website, or finish the guide to start the agent conversation.

The guide uses the installed Crawl4AI `AsyncWebCrawler` with a custom navigation
strategy backed by the **already connected Edge context**. It shares the site's
existing sign-in, opens its own tabs and closes only those tabs. It never launches
a second crawler browser, copies cookies to files or automates sign-in. The
normal public static `discovery.manifest` path remains available separately.

Each collection lives in the authoritative **Discoveries knowledge/websites**
folder, with the chosen title and a stable identifier. `index.json` records URLs,
page file paths, depth, hashes, remaining routes, capture errors and status. Page
JSON files contain rendered HTML, markdown, links and metadata. Saved HTML
retains ordinary business field values and notes while omitting scripts, hidden
inputs, credential field values and credential-named attributes;
obvious sign-out or destructive navigation links are excluded. These filters
are not a guarantee that all sensitive content has been removed. Saves are
incremental atomic writes with retained history and extended Windows I/O paths;
the existing S: mapping, provider/UNC resolution and shared-storage rules apply.
There is no local knowledge-storage fallback. An inaccessible share is an error.

The agent receives collection titles and index paths in its startup contract.
It can call `crawl4ai.read` on indexes and page files as needed, following
`next_offset` to read every window without gaps. It can request more discovery
through `crawl4ai.crawl`; the orchestrator supplies the connected browser,
knowledge destination, session directory and Stop event. In immediate mode,
startup session authorization also covers subsequent crawler requests. In normal
mode the crawler asks for local authorization.

The crawl tool accepts multiple starting `urls`, a `title`, `concurrency`,
`max_pages`, `max_depth`, `cycles`, `refresh_seconds`,
`page_timeout_seconds`, and `follow_external`. Defaults are four concurrent
pages, unlimited pages/depth, one cycle, a 30-second refresh interval and a
60-second page timeout. Zero page/depth budgets mean unlimited; zero cycles
means keep refreshing until Stop. There is no global domain allowlist or public-IP
restriction, so internal websites can be explored. Links stay within the starting
origins unless `follow_external` is explicitly selected. Failed pages, challenges,
expired sign-ins and disconnected browsers remain gaps, never completion proof.

This discovers rendered pages and reachable links. It cannot promise every
hidden route, account, interaction or downloadable document on a website.
It does not submit forms or fill passwords. Authentication remains manual.

Crawl4AI runs locally, with its page cache disabled and no cloud crawler or LLM
extraction configured. Website content is saved on the shared store; access follows
the company's folder permissions. The agent receives file paths initially. Content
the agent later reads is returned to **Microsoft Copilot**, so “local crawling” does
not mean the entire agent workflow is local-only. Use only websites/content you
are authorized to collect and use with the organization's Copilot environment.

For supplied terminal settings, `--yes-setup` accepts the same fast full-access
session grant and skips the guide. `--discover-first` shows the guide even with
`--yes-setup`. The legacy `--package-mode` argument no longer adds a separate
startup choice.
