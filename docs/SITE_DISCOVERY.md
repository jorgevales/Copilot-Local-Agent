# Coordinated website discovery

After `browser.open` and any manual sign-in, request:

```json
{"name":"browser.discover","arguments":{"title":"Website navigation","max_states":12,"max_seconds":90,"explore":true,"resume":true}}
```

Use this as an ordinary tool request in the existing response envelope. The current session authorization applies. No additional crawler service, Node runtime, external model or browser is installed.

The campaign captures each frame's sanitized HTML, structured DOM (including accessible open-shadow observations), accessibility snapshot, inline scripts, delivered JavaScript/CSS sources, image metadata, action-correlated response evidence and console-independent navigation timelines. Script/style retrieval is bounded to 24 URLs per frame and 1 MiB per body; unavailable/CORS/size-limited sources remain explicit. Existing DOM collectors report their 2,000-control limit. Backend implementation and inaccessible browser content are not inferred as captured source.

Screenshots begin alongside structural reads. Sampled page scrolling preserves additional DOM observations and labeled pictures; all campaign pictures are compiled into one PDF. Main navigation links/buttons, tabs, expanded controls and summaries are explored locally. Destructive, submit and sign-out candidates are excluded. Nested panel scrolling and custom precise shots remain available through `browser.inspect`/`browser.screenshot`; this campaign does not exhaust every possible application state.

The transition observer waits through temporary server-error pages and records URL/error sequences. Stable content is an observation, not proof of reaching a requested business destination. The action graph links the next captured state to the triggering control. Failed clicks are observed before another attempt; a final action without a later observation remains uncertain. These records are candidates for later verified automation, not automatically trusted generated tools.

Checkpoints, source sections, file hashes and the PDF use the authoritative shared Discoveries website directory and existing S:/UNC resolution. A title and website origin identify a resumable campaign, including when its current route changes. `resume:false` starts fresh observations under that identity. Stop/time/state budgets retain completed checkpoints. A running frame collector may finish its bounded timeout before Stop is observed.

Copilot receives a reading guide, coverage, page evidence, network/source evidence and one PDF. Large JSON sections are split into valid indexed JSON envelopes whose `content` fields reconstruct the section in part order. Existing pending files and images count against a conservative 18-file discovery transport budget, reserving result-envelope/UI space. Oversized or excess files remain in shared storage and are explicitly listed as not attached; the tool result contains the manifest. PDF delivery permits the existing 20 MiB uploader limit; other evidence files target 8 MiB or less.

Validation: real local Chromium tests cover frame/source/DOM capture, navigation, shared artifacts, one PDF, resume, transient-error observation, schema registration and attachment budget calculation. Actual signed-in company Edge, S:/UNC and the difficult production site still require live verification. Installing Playwright MCP, a full breadth-first application-state frontier, exhaustive nested-panel exploration and automatic replay-verified tool generation are further extensions, not implemented by this first campaign.
