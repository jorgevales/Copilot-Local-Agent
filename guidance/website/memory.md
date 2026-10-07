# Optional website knowledge

The current task must finish when saving is declined. site_knowledge.bind requires exact current HTTPS origin, tenant, user_scope and environment reviewed locally. It records user-declared scope, not authenticated account proof. Rebind after account/tenant/environment changes. Other calls use only the bound origin.

retrieve/query knowledge, then verify current routes/locators. Expired/invalidated records are unusable. export returns a bounded summary.

Before save, explain approved categories, local per-user storage, sensitive-data exclusions and Deny. Separate immutable local approval binds prepared categories/scope/content SHA-256. A model consent=true is insufficient. Save generic route templates, locators, form field labels, document areas and recovery only. Concrete identifiers, names, values, queries and credentials are rejected. Conservative vocabulary checks may reject unfamiliar labels; ephemeral navigation still works.

Records contain consent, provenance, freshness and expiry. Storage is `%LOCALAPPDATA%/CopilotLocalAgent/site-knowledge`, separate from downloaded documents and developer memory. Invalidation marks the current record unusable; expiry does not delete it. Rebind locally after restart.
