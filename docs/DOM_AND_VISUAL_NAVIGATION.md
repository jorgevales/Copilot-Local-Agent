# DOM, JavaScript and visual navigation

Use `browser.inspect` on a new or unfamiliar website page. It runs structural
inspection and screenshot capture concurrently in the same owned tab, returns
DOM/open shadow DOM controls with viewport coordinates, forms and app-script
metadata, and observed fetch/XHR/resource routes. The PNG is queued automatically
for the next Copilot message. Complete structure and an indexed JSON artifact
remain available; large chat results use the existing attachment transport.

Compare the screenshot with the structure to understand visible state and choose
observed controls. Framework hints and resource timing describe client/backend
interfaces; they do not reveal server code. Read available repository files when
actual backend implementation matters. Request/response bodies, browser storage
and cookies are not captured by the paired inspection.

Use `browser.javascript` with an explicit expression/function and optional JSON
`argument` for focused DOM/shadow queries, application state or SPA navigation.
The current session grant supplies approval. A returned JavaScript value does
not prove the user outcome: verify the resulting state with another paired
inspection. Exceptions/timeouts retain uncertain-effect status and actual error
details; inspect/reconcile before replay. Login remains manual.

Do not navigate or mutate while observing a page. Concurrent DOM/image captures
are not atomic: the result records capture times, URL changes, partial failures,
viewport/scroll and coordinate space. Repeat on a settled page if they disagree.
Default captures use the viewport; `full_page: true` is available. Password inputs
are masked; ordinary business content remains visible. The image queue holds up
to ten pending screenshots; additional images stay saved with a reported gap for
a later attachment exchange.
