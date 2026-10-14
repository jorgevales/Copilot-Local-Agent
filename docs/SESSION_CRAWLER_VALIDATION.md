# Session package mode and local crawler validation — 14 October 2026

Windows Python 3.14.2, pinned Crawl4AI 0.9.5 and Playwright 1.55.0.

203 focused tests passed in the final combined run: ZIP delivery, orchestrator,
automation packages, approval lifetime, startup flow, protocol/state and the new
local crawler. The separate nine-test existing Crawl4AI discovery/mapping suite
also passed. This is 212 distinct tests; the full repository suite was not run.

The reproduced delivery failures now have regression tests: an inspection that
omits the optional expected hash, reused review receipts, and identical ZIPs
downloaded to a different path. Each completes without another link request.
Changed files, contradictory hashes, mismatched names and Office archives still
fail the delivery gate. The old automatic-run fixture was corrected to actually
create the output its manifest promises, using the runner-provided outputs root.

Immediate mode executed a real package Python stage and produced its promised
output. The optional quality reviewer was patched to fail if called, and the
approval callback would deny any prompt; the package still ran successfully.
Separate tests verify that session authority expires on close and does not
authorize unrelated path-grant tools. Normal reviewed execution remains covered.

Crawler tests call the actual installed AsyncWebCrawler processing pipeline,
save titled HTML/markdown/links/metadata, read escaped content without pagination
gaps, resume the pending frontier, refresh across cycles, and reject login-page
content. A Stop cancels an in-flight page promptly and preserves remaining routes.
Long local knowledge/runtime paths over 260 characters passed save/readback.

A real Edge/Playwright test used intercepted synthetic HTTPS pages with a seeded
synthetic session cookie. Both signed-in fixture pages were captured; the existing
chat tab remained open and unchanged, and the context retained its session cookie.
The browser was headless only for this isolated test; production uses the connected
visible Edge session. No real customer site, account, sign-in or Copilot service
was exercised. A local orchestrator integration issued crawl4ai.crawl through the
normal tool envelope and received saved knowledge paths. The startup guide is
tested for manual-login readiness, titles, multiple sites and continuous Stop.

No live company VDI, S: share or redirected UNC deployment was available for this
proof. Their existing resolver/storage contracts remain active. Verify the actual
company website sign-in and shared-store readback after deployment. A crawl only
proves the rendered reachable pages it observed, not complete website coverage.

The handoff documentation, current AST index and source hashes were refreshed;
the existing Graphify graph is retained as an older graph snapshot rather than
reported as a new runtime or graph-analysis proof.
