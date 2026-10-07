# Verified action plans

Use browser.plan for known ordered steps. Required task_id, steps and success assertions follow the runtime schema. Bound max_actions and timeout_seconds. Conditions and strictly bounded repeat are supported; unknown operations fail validation.

Example:
{"task_id":"lookup","steps":[{"id":"search","op":"click","locator":{"testid":"customer-search","role":"link","name":"Customer search"},"effect":"navigation","expect":[{"kind":"url","value":"https://example.com/search"}]}],"success":[{"kind":"url","value":"https://example.com/search"}],"max_actions":10,"timeout_seconds":30}

Assert after navigation, search and profile selection. The full immutable plan is locally reviewed. Consequential controls require separate specific confirmation; model effect labels do not grant permission. Do not batch guessed customer selections.

Inspect status, completed steps, last verified state, failed objective, fallback attempts and partials. Resume binds the exact plan/checkpoint, rechecks state, and never replays uncertain effects. Failed final assertions are failures.
