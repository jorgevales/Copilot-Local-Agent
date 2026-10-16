# NNCY live discovery — paused 16 October 2026

Paused at the user's request. Discovery is incomplete; do not resume until the
user explicitly requests it. The local agent exited cleanly and retained Edge.

## Retained runtime

- One new isolated Edge debugging session was opened on loopback port 9222.
  Subsequent agent restarts attached to that same Edge session.
- The user completed Microsoft 365 sign-in manually. The NNCY landing page was
  already accessible without another sign-in prompt.
- Startup Y enabled validated session plan approval. Tool validation, ownership,
  scope and manual authentication boundaries remained active.
- S: was unavailable. The explicitly announced local live-test mode was used;
  this supplies no proof of VDI or production shared-drive behavior.
- Test store: `%LOCALAPPDATA%/CopilotLocalAgent/live-navigation-tests/nncy-live-20261016-132322`.
- Session: `runtime/sessions/8127d797a6b44438ad7e55d89964d40d` under that store.
- Original Edge profile: the sibling `nncy-20261016-130949/runtime/edge-profiles/`
  directory. Keep this profile and port when resuming; do not open another Edge
  debugging session merely to resume the test.
- Local runtime captures, account/profile data, screenshots and raw website
  evidence are excluded from Git. Inspect them locally when authorized.

## Observations

The agent opened the requested `/inicio` page and observed the patient,
consultation, menu, dashboard, form editor, food editor, report, solver and
settings navigation. The first campaign captured 11 routes before an outer
timeout. These are observations, not complete global coverage or independently
replayed navigation methods. No form submission or record change was requested.

An early three-exchange sample measured approximately 58.2 seconds in browser
exchanges versus 11.3 seconds in local tools. Uploads took about 7.6 seconds
inside the exchange spans; screenshot spans totaled about 2.4 seconds. These
phases overlap and must not be added into an end-to-end critical path.

Copilot sometimes omitted protocol markers or required fields and once added an
unsupported error field. Correction rounds and attachment retrieval increased
latency. The selected available model was GPT-5.6 Sol Think deeper; the live
picker showed GPT-6.1 Sol disabled. A first post-login picker attempt failed,
while later discovery succeeded without a selector change.

## Changes made during the test

- Hash-bound references replace duplicate REA availability diagnostics only when
  they match the verified startup catalogue. Startup returned to eight uploads.
- Repeated startup upload history can be omitted only with matching source path
  and hash; current user attachments, constraints and pending policy state stay.
- Discovery's outer timeout now covers its registered maximum inner budget.
- Every newly captured discovery state retains a separate viewport PNG and hash;
  the transferred PDF remains a bounded sample.
- Compact discovery retains captured HTML, DOM, accessibility and observed
  network evidence locally, returning coverage and manifest references instead
  of automatically uploading all source chunks. Additional script/CSS fetches
  are deferred in compact mode and labeled accordingly.
- Discovery reserves a visual attachment slot and avoids starting another
  transition when fewer than five seconds remain.
- Uncertain discovery results now produce failed/uncertain call status, rather
  than completed status. The last affected old call was conservatively restored
  to uncertain from its retained checkpoint; it must receive recovery without
  replay or completion credit.
- Spanish destructive/sign-out and account credential-change controls are
  excluded from automatic discovery candidates.
- Explicit local test resume accepts only an existing session directly under
  that selected test store's `runtime/sessions`; fresh runs still require an
  empty test directory.
- Compact decision guidance now applies to browser discovery continuations too.

## Verification and outstanding blocker

The pre-resume regression run passed 42 checks. Subsequent focused discovery and
local-resume checks passed 9 checks, including viewport retention, compact
artifact handling, timeout bounds, uncertainty classification and Spanish
sign-out exclusion. The complete repository suite was not rerun after the last
live changes. No claim of a successful final live speedup is made.

The final resume remained blocked before sending its new task: the private
composer guard measured 18,931 characters against a 16,000-character budget.
Current policy context and repeated metadata still need further transport
compression without private disk spill or lost constraints. The raw request was
not sent. This blocker remains unresolved in the pushed changes.

On an explicit user resume: inspect the retained session and uncertain call,
resolve the composer blocker, recover the last unverified browser operation
through the registered recovery tool without replay, then continue safe frontier
coverage. Retain the existing browser, evidence and authentication session.
