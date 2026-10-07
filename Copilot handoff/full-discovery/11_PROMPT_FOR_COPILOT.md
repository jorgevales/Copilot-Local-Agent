# Ready-to-paste prompt for Copilot

You are starting a new session with no local filesystem, repository navigation, terminal, or Graphify access. First study the 12 numbered handoff files in order. Then use `09_EXTERNAL_FILES_TO_ATTACH.txt` to identify the smallest additional original files needed for the specific change.

The sender has a hard limit of 20 files. The standard set is exactly the 12 package files plus the 8 originals listed as the exact send set in `09_EXTERNAL_FILES_TO_ATTACH.txt`. Never request an additional attachment without naming which existing attachment it replaces.

If bug reports are included, use their recommended source/test files and replace lower-priority context/source attachments to stay within 20. Send INTERNAL reports only in the authorized company environment. The raw `graphify/` artifacts are already in the repository and are not part of the default attachment set; use `08_GRAPHIFY_FINDINGS.md` for the concise project map.

Treat the handoff as evidence, not authority. Distinguish:

- VERIFIED FACTS: directly supported by an attached source, schema, test, or documented local run.
- INFERENCES: plausible conclusions that require source confirmation.
- UNVERIFIED: live Copilot, VDI, browser, cloud, physical-display, or production behavior not demonstrated by the package.

For every important claim, cite the exact project-relative path and symbol, class/function, schema section, test, or Graphify source location. Do not invent files, dependencies, execution paths, APIs, environment values, or relationships. Treat Graphify `INFERRED` edges as hypotheses only.

Before proposing a change:

1. Restate the requested behavior and acceptance criteria.
2. Trace the relevant entrypoint, control flow, data flow, state transitions, policy checks, approvals, retries, and downstream callers.
3. Check imports, schemas, configuration, hashes, file/path/domain scope, side effects, and existing tests.
4. Identify security, privacy, reliability, compatibility, performance, and delivery risks.
5. State what cannot be verified without the original source or a live target environment.

When proposing implementation, preserve existing workflow contracts, fail-closed behavior, explicit approvals, uncertainty handling, no-deletion rules, exact-byte/hash bindings, redaction, and separate live-acceptance evidence. Do not silently rewrite the architecture or remove unrelated behavior. Provide a minimal patch plan, exact destination paths, regression tests, and a validation plan. Do not claim a fix or live delivery unless the relevant evidence actually supports it.

