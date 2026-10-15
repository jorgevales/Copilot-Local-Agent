> Current repair instructions: [upstream Node deployment](REA_UPSTREAM_RUNTIME_FIX.md).

# REA availability deployment repair

## Cause and fix

The original default searched only the developer sibling `Copilot Local Agent Research/rea`.
That external checkout was not delivered by Git, and normal setup did not install REA.
The single generic manifest error hid both the searched path and subsequent dependency checks.
This deployment defect explains the reported pre-selection failure; the VDI filesystem itself
was not accessed during this repair.

Explicit setup provisions the integrity-pinned published runtime before the next
session catalogue is created. Ordinary live/testing startup never installs software. They reuse complete installations, try
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

Pull the fix and run **Setup REA.cmd** (or normal Setup.cmd for auto/node_cli). If needed run the
repair command in the linked guide, then start a new session. Confirm selected_backend:node_cli and upstream_available:true in
research_routing.rea and each REA entry, then request a supported approved investigation
and confirm research.route prefers rea.inspect_page. Existing sessions retain their
contract snapshot. Supported Node/npm must be installed or explicitly configured.

Live VDI, S:/UNC installation and production authenticated Copilot were not exercised here.
Durable discovery storage and target/effect approvals remain unchanged.

## Portable Node path setup follow-up

Setup now accepts a pasted executable, extracted folder or Windows Node ZIP,
including quoted paths and redirected S:/UNC aliases. ZIPs are safely extracted
into writable managed candidates; the source is retained. The validated Node
path is atomically saved in local configuration and automatically loaded at the
next startup. npm is resolved beside portable Node. Setup continues through
REA and automatically detected Edge without further routine resource questions.
Missing resources and unavailable shares still produce actionable failures.

Validation:102 focused setup/health/installer tests passed, followed by27 final
portable-path/ZIP/setup tests after the automatic Edge continuation change
(counts overlap). A real Node24.13.0 executable and npm tree were packed into a
portable-layout ZIP, selected through the setup API, extracted, version checked,
persisted and successfully used to finish REA setup. S:/UNC mapping contracts
passed Windows fixture tests; live VDI/share behavior remains unverified.
