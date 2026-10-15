# DOM, JavaScript and visual navigation

Use `browser.inspect` on a new or unfamiliar website page. It runs structural
inspection and the first screenshot concurrently in the same owned tab, returns
DOM/open shadow DOM controls with viewport coordinates, forms and app-script
metadata, and observed fetch/XHR/resource routes. All pictures are combined into one clearly labeled PDF, queued automatically
for the next Copilot message. Complete structure and an indexed JSON artifact
remain available; large chat results use the existing attachment transport.

Compare the screenshot with the structure to understand visible state and choose
observed controls. Framework hints and resource timing describe client/backend
interfaces; they do not reveal server code. Read available repository files when
actual backend implementation matters. Request/response bodies, browser storage
and cookies are not captured by the paired inspection.

Use `browser.javascript` with an explicit expression/function and optional JSON
`argument` for focused DOM/shadow queries, application state or SPA navigation.
This potentially effectful tool requires its normal concise approval. A returned JavaScript value does
not prove the user outcome: verify the resulting state with another paired
inspection. Exceptions/timeouts retain uncertain-effect status and actual error
details; inspect/reconcile before replay. Use browser.login_once for one prefilled login click; denial or MFA requires the user.

Call `browser.screenshot` (or pass the same capture options to `browser.inspect`)
for a complete batch in one tool call. By default it samples up to three distinct
positions from top to bottom; `max_shots` changes the sample count. Short pages
may need only one picture. Sampling does not guarantee complete page coverage.

For precise work, supply `shots`, each with a human-readable `label` and any of:

- `scroll_y` / `scroll_x`: move the page to these CSS-pixel positions.
- `scroll_container`: scroll one exact CSS-selected panel instead of the page.
- `selector`: automatically scroll one exact element into view and capture it.
- `clip: {x, y, width, height}`: crop a precise viewport region in CSS pixels.
- `full_page: true`: capture the full document as that picture.

Element, clip and full-page capture modes are separate per shot. Combine different
shots in the same request. Up to 30 pictures become **one PDF attachment**, with
one full-resolution picture per page. Each page clearly prints its shot number,
user label, query-free website URL, scroll position, capture mode and target.
The tool result also maps labels to exact dimensions and scroll coordinates.
Missing pictures are reported as gaps; they are never claimed as captured.

Example:

```json
{"shots":[
  {"label":"Top navigation","scroll_y":0},
  {"label":"Customer details panel","selector":"#details"},
  {"label":"Exact toolbar area","scroll_y":0,"clip":{"x":20,"y":80,"width":500,"height":180}}
]}
```

Page and panel scroll positions restore by default; `restore_scroll: false`
retains the final position. DOM inspection finishes alongside the first picture
before further scrolling. Do not run other navigation/mutations during a batch.
Concurrent DOM/image observations are not atomic: repeat on a settled page if
they disagree. Password controls are masked; ordinary business content stays
visible. No separate image attachments are sent for a batch.
