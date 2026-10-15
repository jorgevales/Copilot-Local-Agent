# REA availability deployment repair

## Cause and fix

The original default searched only the developer sibling `Copilot Local Agent Research/rea`.
That external checkout was not delivered by Git, and normal setup did not install REA.
The single generic manifest error hid both the searched path and subsequent dependency checks.
This deployment defect explains the reported pre-selection failure; the VDI filesystem itself
was not accessed during this repair.

Setup and the selected live/testing startup now provision the integrity-pinned published
runtime before creating the session catalogue. They reuse complete installations, try
multiple writable runtime locations, and try cached dependencies before the registry.
An explicit trusted installation and disconnected archive/cache repair are alternatives.
See [exact recovery commands](REA_INTEGRATION.md#recovery-options).

Availability now reports package.json paths and per-candidate failures, compiled CLI files,
production dependencies, compatible Node version and matching Windows native integrity.
The ToolRegistry owns one immutable session snapshot shared by prompt research metadata,
all three REA tools and research.route. Fresh session creation refreshes it. Execution
still validates the current runtime before invoking a target.

## Validation

- New health regressions reproduce the missing developer-checkout case and verify managed
  fallback, explicit overrides, malformed/unreadable manifests, dependencies and Node cases.
- Three session tests verify identical metadata/catalogue/router availability and recovery
  from a prior unavailable session.
- Real clean install from the published 6.5.0 archive, production dependency installation,
  exact native integrity and CLI help: passed.
- Fresh local session using that managed install with no repository override: available;
  all three catalogue entries matched; research.route preferred rea.inspect_page;
  actual synthetic HAR analysis completed.
- Final startup/session/protocol/health-contract/setup regression run:103 tests passed.
  Additional setup/version/installer run:38 passed; final setup/version run:22 passed.
  Counts overlap. REA unit and actual gated integrations passed during the 100-test run;
  its one launcher-call-count regression was resolved by provisioning the selected version
  at the correct launch boundary and covered by the subsequent passing launcher tests.
- Initial larger diagnostics caused a ninth startup attachment; redundant first-task advice
  was deferred, retaining full diagnostics and the eight complete contract attachments.
- Python compilation, exact91-tool inventory regeneration and whitespace checks passed.

## VDI acceptance

Pull the fix and launch the current live version, or run Setup.cmd. If needed run the
repair command in the linked guide, then start a new session. Confirm available:true in
research_routing.rea and each REA entry, then request a supported approved investigation
and confirm research.route prefers rea.inspect_page. Existing sessions retain their
contract snapshot. Supported Node/npm must be installed or explicitly configured.

Live VDI, S:/UNC installation and production authenticated Copilot were not exercised here.
Durable discovery storage and target/effect approvals remain unchanged.
