# Multiple tabs

browser.tabs manages explicitly owned stable tab IDs with purpose, task and customer context. Preserve the primary workflow tab. At most six owned website tabs, including temporary download tabs, may be open; unrelated Edge tabs do not count. Unexpected script popups are blocked.

Use the intended tab and context for each operation. Closed/replaced IDs fail rather than selecting another page. Parallelise independent reads/downloads only; keep customer lookup, identity verification and consequential actions ordered. Consolidate results deterministically and close surplus owned tabs after verification.

Before switching tasks/customers, request an approved `browser.tabs` operation `reset` with a verified safe same-origin URL and new task_id. It preserves the primary page, closes surplus tabs and clears prior ephemeral plans/maps/customer/document references. A customer profile is not a safe reset destination.
