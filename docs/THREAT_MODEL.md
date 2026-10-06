# Threat model

## Assets and actors

Protect the user's permitted local files, existing CDD workflow, authenticated Copilot session, organization data, approval decisions and execution ledger. The human user authorizes work. The orchestrator enforces policy. Copilot output, ordinary attachments, website text, OCR, generated scripts and tool results are untrusted. A malicious document or webpage can attempt prompt injection; a benign model can also produce mistaken or malformed actions.

## Boundaries

1. Copilot output enters only through a correlated captured response and strict local validation.
2. Tool requests cross a policy/approval boundary before effects.
3. File operations cross resolved allowed-root and declared-plan checks.
4. Browser tools use a separate owned page; the Copilot control page is not a tool target.
5. Uploads/navigation transmit data and therefore require deliberate scope.
6. Code Runner defaults to a constrained evaluated language. `local_python` crosses a separate exact-script human-approval and host-process boundary.
7. State restoration crosses a replay boundary: uncertain operations are not automatically repeated.

## Threats and mitigations

| Threat | Required control | Residual limitation |
|---|---|---|
| Prompt injection in a webpage/file | Treat content as data; enforce local policy regardless of model request | Model answers may still be misleading; evidence and human review matter |
| Stale or partial response executes tools | Exact session/request correlation, schema and logical validation | UI changes can prevent capture; fail closed |
| Approval laundering or changed script | Canonical plan/script hashes and one-shot or exact-plan grants | Full preview still requires meaningful human review |
| Path traversal or linked-directory escape | Resolve actual paths, allowlisted roots and declared read/create scope | Filesystem races must be considered by capability implementations |
| Generated code reads/deletes/exfiltrates | Restricted AST default; local Python requires full exact preview, interpreter/runtime hash, scrubbed environment, declared scopes, audit hooks and explicit approval | Native libraries can bypass language-level mediation; local Python is approved host execution, not an OS sandbox |
| Child process or viewer outlives its task | Exact approved argv, PID ledger, persistent flag, verification gate and session-owned cleanup registry | OS/organizational policy may block process observation or termination; report the failure |
| Script exits zero without satisfying desktop task | Independent output hashes plus exact visible-window/title/bounds inspection on the requested display | Real physical-display proof requires a visible target Windows session, not mocks |
| Replayed side effect after crash/retry | Persist intent/outcome, immutable call hashes, reject uncertain replay | Manual reconciliation may be necessary |
| Browser action performs unexpected mutation | Separate tool tab, destination policy, classified actions and approval | Website behavior can change; clicks cannot be called inherently harmless |
| Debugging port exposes authenticated browser | Dedicated profile/session, loopback-only debugging, bounded connection | Other processes running as the same user remain outside this application's protection |
| Secrets leak through context/logs/screenshots | Minimize, redact, scope files, keep diagnostics local | Automated redaction is imperfect; do not use sensitive content for tests |
| Fake synchronized-file success | Baseline, bounded polling, stable/readable local content checks | OneDrive/organizational delivery may be unavailable |
| Resource exhaustion/endless conversation | Finite turn/retry/step/output/time limits | Legitimate large tasks may need a new reviewed scope |

## Code Runner security claims

Every approved execution must match exact reviewed bytes and its complete plan. In `python_subset`, supported expressions/statements and file capabilities are a whitelist; imports, reflection, subprocesses, arbitrary attributes, unmediated file access, network and deletion are unavailable.

`local_python` deliberately executes approved host Python when the subset cannot do the job. Its grant additionally binds interpreter identity/hash, fixed worker files, argv, direct imports, read/create/modify paths, canonical HTTPS hosts, exact subprocess vectors, desktop effects, limits and postconditions. Static checks reject dynamic code/import helpers, credential/registry modules and undeclared imports. The worker adds a scrubbed environment, Python audit hooks, exact `Popen` mediation, output/time bounds, cancellation and owned-process cleanup. These are defense-in-depth controls: native extension code and desktop APIs are not contained by a Python audit hook. Meaningful exact human review and least privilege remain mandatory. Never claim Windows Sandbox, low-integrity or privilege isolation.

A conversational statement such as “approve runs” is not authorization. Approval is obtained after the exact script and scope are displayed. A plan decision covers only the complete prepared scripts already displayed. Any material change produces a different immutable hash and requires a new decision.

## No-deletion and overwrite rules

Runtime tools, cleanup, tests and recovery must never delete files. Mutable state uses preserved versions and atomic replacement where appropriate. User file overwrite requires explicit scope and preserved originals. Retained artifacts consume space; report disk limits rather than silently removing files.

## Verification obligations

Exercise malformed/stale protocol rejection, unsafe paths, unsupported syntax, scope changes, hashes, denial, changed-script reapproval, local-Python failures/timeouts/cancellation, output limits, persistent-process cleanup, three-window display verification, replay uncertainty, retry limits, secrets filtering, findings persistence and synchronization. Record real desktop/UI evidence separately from mocks. Controls are claims to validate against implementation, not assertions that documentation alone proves safety.

## Scope limits

This application cannot protect against a compromised operating system or other processes operating with the user's privileges. It cannot ensure Copilot always honors guidance or that Microsoft/OneDrive provides a requested capability. Local policy must remain authoritative even when the model is wrong. No authentication bypass, endpoint weakening or security-policy modification is a recovery strategy.
