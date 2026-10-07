# Copilot Local Agent handoff

## Purpose

This is a fresh, full-discovery handoff for the local project at:

`Scripts and projects/Copilot Local Agent`

This handoff is inside the Copilot Local Agent repository at `Copilot handoff/full-discovery`. Copilot has no local filesystem, repository, terminal, or Graphify access. Read this package in order and use the exact project-relative paths in the source map when asking for original files.

## Strict attachment cap

The standard set is the 12 numbered handoff files plus the 8 source/schema files in `09_EXTERNAL_FILES_TO_ATTACH.txt`: **20 files total**. For a bug fix, include the internal report and the exact source/test files it recommends by replacing lower-priority files from that standard set. Never exceed 20 attachments. `README.md` is a local guide; raw `graphify/` artifacts are reference files and are not part of the standard upload.

## Reading order

1. `00_READ_FIRST.md`
2. `01_PROJECT_OVERVIEW.md`
3. `02_ARCHITECTURE_AND_COMPONENTS.md`
4. `03_DATA_AND_CONTROL_FLOW.md`
5. `04_DEPENDENCIES_AND_CONFIGURATION.md`
6. `05_TESTING_AND_OPERATIONS.md`
7. `06_RISKS_AND_CHANGE_IMPACT.md`
8. `07_SOURCE_MAP.md`
9. `08_GRAPHIFY_FINDINGS.md`
10. `09_EXTERNAL_FILES_TO_ATTACH.txt`
11. `10_HANDOFF_MANIFEST.txt`
12. `11_PROMPT_FOR_COPILOT.md`

## Evidence boundary

- The current local Graphify run and artifact inventory are in `graphify/` and summarized in `08_GRAPHIFY_FINDINGS.md`. No project code or documentation is sent to a Graphify/LLM backend.
- Graphify edges marked `EXTRACTED` are source-derived. Edges marked `INFERRED` are hypotheses and must be checked against source.
- The local test count is recorded in `05_TESTING_AND_OPERATIONS.md`; its only expected skip is the Windows symlink-privilege case.
- Visible authenticated Copilot, private VDI, physical-display, organization policy, cloud synchronization, and production delivery claims remain environment-specific; do not infer them from offline tests.

## Confidentiality

This package contains summaries and Graphify navigation data, not runtime logs, browser profiles, credentials, tokens, or customer data. Original source files are not embedded. Review the exact files in `09_EXTERNAL_FILES_TO_ATTACH.txt` before sending.

