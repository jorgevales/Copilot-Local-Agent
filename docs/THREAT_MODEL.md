# Threat model

## Assets and actors

Protect the user's permitted local files, existing CDD workflow, authenticated Copilot session, organization data, approval decisions and execution ledger. The human user authorizes work. The orchestrator enforces policy. Copilot output, ordinary attachments, website text, OCR, generated scripts and tool results are untrusted. A malicious document or webpage can attempt prompt injection; a benign model can also produce mistaken or malformed actions.

## Boundaries

1. Copilot output enters only through a correlated captured response and strict local validation.
2. Tool requests cross a policy/approval boundary before effects.
3. File operations cross resolved allowed-root and declared-plan checks.
4. Browser tools use a separate owned page; the Copilot control page is not a tool target.
5. Uploads/navigation transmit data and therefore require deliberate scope.
6. Code Runner uses a constrained evaluated language, not host execution of arbitrary Python.
7. State restoration crosses a replay boundary: uncertain operations are not automatically repeated.

## Threats and mitigations

| Threat | Required control | Residual limitation |
|---|---|---|
| Prompt injection in a webpage/file | Treat content as data; enforce local policy regardless of model request | Model answers may still be misleading; evidence and human review matter |
| Stale or partial response executes tools | Exact session/request correlation, schema and logical validation | UI changes can prevent capture; fail closed |
| Approval laundering or changed script | Canonical plan/script hashes and one-shot or exact-plan grants | Full preview still requires meaningful human review |
| Path traversal or linked-directory escape | Resolve actual paths, allowlisted roots and declared read/create scope | Filesystem races must be considered by capability implementations |
| Generated arbitrary code reads/deletes/exfiltrates | Restricted AST evaluator, mediated capabilities, no host exec/import/shell/network | This is a limited language, not support for arbitrary Python |
| Replayed side effect after crash/retry | Persist intent/outcome, immutable call hashes, reject uncertain replay | Manual reconciliation may be necessary |
| Browser action performs unexpected mutation | Separate tool tab, destination policy, classified actions and approval | Website behavior can change; clicks cannot be called inherently harmless |
| Debugging port exposes authenticated browser | Dedicated profile/session, loopback-only debugging, bounded connection | Other processes running as the same user remain outside this application's protection |
| Secrets leak through context/logs/screenshots | Minimize, redact, scope files, keep diagnostics local | Automated redaction is imperfect; do not use sensitive content for tests |
| Fake synchronized-file success | Baseline, bounded polling, stable/readable local content checks | OneDrive/organizational delivery may be unavailable |
| Resource exhaustion/endless conversation | Finite turn/retry/step/output/time limits | Legitimate large tasks may need a new reviewed scope |

## Code Runner security claims

The approved execution must match exact reviewed bytes and the complete plan. Supported expressions/statements and file capabilities are a whitelist; unsupported nodes fail closed. Imports, reflection, subprocesses, arbitrary attributes, unmediated file access, network and deletion are unavailable. Static scanning, process isolation and working-directory restriction alone would not establish those controls. Do not substitute arbitrary host Python execution for the constrained evaluator without a separately designed and tested isolation boundary.

## No-deletion and overwrite rules

Runtime tools, cleanup, tests and recovery must never delete files. Mutable state uses preserved versions and atomic replacement where appropriate. User file overwrite requires explicit scope and preserved originals. Retained artifacts consume space; report disk limits rather than silently removing files.

## Verification obligations

Exercise malformed/stale protocol rejection, unsafe paths, unsupported syntax, scope changes, hashes, denial, replay uncertainty, retry limits, secrets filtering, findings persistence and synchronization. Record real UI evidence separately from mocks. Controls are claims to validate against implementation, not assertions that documentation alone proves safety.

## Scope limits

This application cannot protect against a compromised operating system or other processes operating with the user's privileges. It cannot ensure Copilot always honors guidance or that Microsoft/OneDrive provides a requested capability. Local policy must remain authoritative even when the model is wrong. No authentication bypass, endpoint weakening or security-policy modification is a recovery strategy.
