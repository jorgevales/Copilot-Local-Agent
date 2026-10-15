# Centralized website navigation knowledge

The local session grant authorizes useful sanitized knowledge saves without another run/save question. The orchestrator prepares and validates each exact payload; model arguments cannot grant consent. A new session requires its own grant. Knowledge never authorizes navigation, unrelated targets or consequential actions.

After opening the approved site, retrieve/query knowledge before repeating discovery. Automatic origin/local-user organization is available under the session grant. Use `site_knowledge.bind` when the app, tenant, sharing scope or environment is demonstrably distinct: `origin`, `tenant`, `user_scope`, `environment`, and optional `application`. Explicit bindings take precedence over automatic defaults. Scope labels are user-declared organization, not authenticated identity proof. Rebind after account/app/tenant/environment changes.

Save new concise reusable findings with `site_knowledge.save`. Skip empty, noisy and duplicate updates. Preserve exact observed generic routes, locators, field labels, document areas, recovery steps, useful internal URLs/system paths and precise sanitized examples. Saved URLs exclude queries, fragments and embedded credentials; replace record route parameters with templates such as `/customers/{customer}/documents`. Never persist credentials, tokens, cookies or identifiable customer/personal records. Custom categories and `knowledge.note` do not bypass these exclusions.

Verified `navigation_methods` carry `path`, `purpose`, `label`, `steps`, and `source_call_ids` from successful completed browser calls in this current session. Steps have `path` and `strategy` (`navigate`, `role`, `label`, `test_id` or `css`); locator steps also carry `value` and a `role` when required. The final destination must match successful local output and plan steps must have executed. Never invent proof or speedups. Claimed timing is discarded; local ledger timing is used.

For example, only after the actual `open-documents` call successfully confirms `https://example.com/documents`, this describes its observed direct route:

```json
{"origin":"https://example.com","categories":["navigation_methods"],"knowledge":{"navigation_methods":[{"path":"/documents","purpose":"documents","label":"Documents navigation","steps":[{"path":"/documents","strategy":"navigate"}],"source_call_ids":["open-documents"]}]}}
```

Use the exact resolved S:/UNC `Discoveries knowledge` root supplied by the orchestrator. Never guess a mapping or redirect knowledge to C:, OneDrive, downloads or developer memory. `<root>/discovery-v1/ledger.sqlite3` is the authoritative evidence/revision store. Per-site readable files live under `<root>/sites/<host>-<origin-hash>/namespaces/<namespace>/`: `current.md` contains concise active hints and recommended methods; `methods.md` labels recommended and previous verified methods. Prefer measured faster methods, then fewer steps where timing is unavailable. Prior revisions remain in SQLite. Equivalent saves return `unchanged`; a failed derived file reports `view_unavailable` separately from a committed ledger record.

`knowledge.note` stores sanitized non-executable findings and suppresses equivalent content despite changed titles/whitespace. Site notes share the central site/namespace folder; operational notes without an active site retain the general notes folder. Artifact and index verification are reported separately. Raw crawler HTML/markdown/AX/network captures are scoped task evidence and do not become reusable knowledge merely because they were saved.

Verify current routes/locators before reuse. Expired/invalidated records are unusable; invalidation retains its applicable approval. `discovery.knowledge_save` is the distinct public static-map tool: locally generated run ID, expected revision, committed source evidence, CAS and independent successful observations remain required. The session grant removes its extra save prompt and never proves rendered navigation or authenticated access.
