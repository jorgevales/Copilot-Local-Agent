# Rapid reconnaissance

Use browser.recon on the approved current page. Example arguments: {"goal":"Find customer search and documents","max_elements":50,"max_text_chars":1500}. Results include headings, semantic controls, forms, routes, document candidates, boundaries and blocked-state indicators; field values are excluded.

Use browser.route to rank observed same-origin paths. Candidate routes require navigation and assertions. Recon inspects the current page and does not crawl every route. Use observed same-origin frames; closed shadow roots remain unavailable.

Prefer stable IDs/test IDs, roles and names, labels, durable text, then scoped CSS. Require uniqueness. Loading/authentication/CAPTCHA states require bounded recovery or manual input. Reduce observation limits if truncated. Avoid repeated screenshots and complete DOM dumps.
