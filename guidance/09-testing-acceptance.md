# Testing and acceptance behavior

Guidance version: 1.0. This document describes honest validation behavior; the local visual checklist is `docs/VISUAL_ACCEPTANCE.md`.

## Evidence standard

Distinguish a proposed test, an automated/mock result, a real UI observation, a blocked step and an unexecuted step. Never report a pass without supporting evidence. Tests must use harmless synthetic content, scoped retained output files and explicit runtime script approval. Never delete test files or bypass authentication/organizational controls.

## Protocol and tool validation

Demonstrate a no-tool answer, a read-only tool request, return of its result, and a subsequent final answer. Always follow protocol identity and schema. A deliberate invalid-format test must be confined to the test harness/explicit test request; ordinary operation remains strict. After correction, return a valid current-identity envelope without new side effects.

## Approval validation

Propose a small script within the advertised constrained Python subset. Denial must prevent execution and output creation. A separately reviewed approved execution must use the exact hashed plan/script and produce verifiable harmless output. A changed script or scope needs renewed approval. Unsupported imports, shell, deletion and escape attempts must be rejected locally, not executed as tests on the host.

## Findings validation

Emit an evidence-supported reusable synthetic finding on an early response; accepted data should be saved immediately. Repeat the unchanged finding to exercise deduplication. Check that the cumulative findings file attaches on submitted ordinals 10 and 20 and not on ordinary non-boundary messages. Assistant responses, upload events and polling do not advance the counter. This tests revised attachment cadence, not a boundary-only emission rule.

## UI and files

Verify actual model discovery/selection, guidance upload, generation start/completion, correlated response capture and local attachment confirmation. Verify created-file synchronization only when a real local stable/readable file is observed. If the capability, organizational delivery flow or authentication is unavailable, report the exact blocked step. Mocks do not prove real Edge/Copilot behavior.

## Completion

The complete system requires automated checks and a real visible end-to-end run with evidence. A task may be complete while delivery acceptance still has blocked items; do not confuse those states. Report known limitations and retain sanitized logs/screenshots and expected-versus-actual observations.
