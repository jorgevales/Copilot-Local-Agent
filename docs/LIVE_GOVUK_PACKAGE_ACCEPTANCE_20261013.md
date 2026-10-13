# Live GOV.UK automation package acceptance — 2026-10-13

The final fresh local proof passed against the reviewed worktree on `main`. Microsoft 365 Copilot Chat generated and delivered a new schema 1.1 ZIP; the local agent verified its download, inspected it, executed it, and completed the final delivery gate. The agent then exited normally.

## Observed result

| Check | Evidence |
| --- | --- |
| Exact browser endpoint | Edge `155.0.4283.45`, loopback CDP port `63741`; dedicated profile ownership verified before the run |
| Package | `govuk-final-live-run18`, version `1.1.0`; only `manifest.json` and `README.md`, 14 registered-tool stages, no Python stages |
| Fresh execution | Run `1ecefe5bc41d419989a1ddf3f367d91e`; full rebuild, no prior run or reused stage |
| Stage completion | 14/14 completed, each on attempt 1; no failed, skipped or uncertain stages; validation passed both checks |
| Navigation | Five new owned same-origin GOV.UK tabs, independently distinguished from the 10 pre-existing public page targets |
| Parallel discovery | Five reconnaissance stages; recorded start/end intervals prove a maximum overlap of four |
| Persistence | Exactly five approved generic routes saved to the explicit local C: test store, then retrieved and queried |
| Final delivery | Verified retained ZIP credited by its exact local inspection receipt; final response completed without redelivery |

The visited and saved routes were `/browse/benefits`, `/browse/benefits/families`, `/child-benefit`, `/browse/benefits/disability`, and `/pip`. No forms were submitted or personal data collected.

## Measured execution time

Times are measured from retained stage timestamps, excluding Copilot generation and approval latency.

| Interval | Seconds |
| --- | ---: |
| Primary navigation start to fifth page open | 2.378231 |
| Primary navigation start to verified knowledge save | 3.334734 |
| Last reconnaissance finish to verified knowledge save | 0.064485 |

## Integrity and readback

An independent reviewer opened the ZIP and SQLite ledger read-only, verified the manifest and payload hashes, and reconstructed the actual save/retrieve/query result objects from the persisted record. Their canonical hashes and byte counts match the retained tool checkpoints. Both readbacks contain the five saved routes, with `age_seconds=0` consistent with their stage intervals.

| Artifact | SHA-256 |
| --- | --- |
| Delivered ZIP | `47e7c1cbef60cb9bc12fb99a80009c5ed55d0a6690e18e35c9665b3b9af2c30d` |
| Canonical manifest | `974b475ea0050b66f9628f91ba35184b99d4168d58d5dab4d33dfa6b2f1373a6` |
| README payload | `e50658af85fd2cb0ab0ec87909e18502c5299db64f709e88d29d30c14d17efc7` |
| Knowledge payload | `0520e955c9bc6fd20b0ae8dd9dd6cb14af14abcd0cbcc91cbbf29c0b47d1ac25` |
| Save result, 333 bytes | `c68ddaad8f47590f10b46b9a46667024b1479b47f3d927fab492776dc511b392` |
| Retrieve and query results, 1194 bytes each | `230d7f12d1d20502d5f47a5c82aed0159d2f78b47d01930e1e77ed561d9e5bd4` |

## Regression and review gates

The complete `unittest` suite passed: **758 tests in 234.475 seconds, two skipped**. Compilation and `git diff --check` passed. Independent review found no blocking findings.

The live work identified and fixed the missing primary `browser.open` tab ID, aligned package schemas with the runtime's major.minor Python version rule, and corrected delivery credit for an explicitly requested automation ZIP. Regression tests exercise the actual tool and orchestrator interfaces. Stage timestamps provide direct concurrency evidence. Office and named inner-file delivery retain their extraction verification requirements.

## Retained local evidence and scope

Evidence stays beneath `%LOCALAPPDATA%/CopilotLocalAgent/live-navigation-tests/final-20261013-run18`:

- `deliveries/86e7db8156074923b29e4c040ad4a1a9/govuk-final-live-run18-1.1.0.zip`
- `automation-runs/govuk-final-live-run18-new-1/runs/1ecefe5bc41d419989a1ddf3f367d91e/state.json`
- `Discoveries knowledge/discovery-v1/ledger.sqlite3`
- `validation/full-unittest.log`, `validation/edge-endpoint.json`, and `validation/before-govuk-targets.json`

Production storage remains S:-anchored in VDI. This proof used only the explicitly selected C: store; S:/VDI behavior was covered by design and offline tests, without a real VDI run. Public hostname policy checks do not resolve or pin DNS answers. Browser profiles, authentication data, runtime logs and raw website observations are excluded from publication.
