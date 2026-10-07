# Testing and operations

## Setup and run

From `Scripts and projects/Copilot Local Agent`:

```powershell
.\Setup.cmd
.\Start Agent.cmd
.\Run Tests.cmd
```

Setup prompts for shared Python and OneDrive/Edge resources, validates/reuses or safely preserves an incomplete `.venv`, installs the locked packages, and stores mutable settings outside source. Start requires visible Edge/Copilot operation; complete sign-in/MFA manually in the dedicated window.

Direct advanced forms use the selected shared interpreter:

```powershell
python -B app.py --config <settings-file>
python -B app.py --resume <OneDrive-runtime-session-path>
python -B app.py --attach-existing --port <port> --profile <dedicated-profile-path>
```

## Verified local validation

Verified locally on 7 October 2026: `349` tests passed, `1` skipped, `0` failed. The skip is the Windows symlink-privilege case. Coverage includes protocol/state, browser correlation, Edge startup, attachments, bundle integrity, tools/policy, approvals, both code-runner modes, delivery/download/archive verification, launcher/setup fixtures, findings, synchronization, feedback, diagnostics, and cleanup.

Live harnesses are explicitly named `tests/live_*.py` and are not equivalent to ordinary offline tests. `docs/VISUAL_ACCEPTANCE.md` is the acceptance checklist; `docs/TEST_REPORT.md` contains retained evidence and environment limits.

## Repeatable local handoff refresh

The central refresh tool is:

`FNZ/.tools/graphify/Refresh-CopilotHandoff.py`

For the default Copilot Local Agent package, double-click:

`FNZ/.tools/graphify/Refresh Copilot Handoff.cmd`

Examples from `FNZ`:

```powershell
& .\.tools\graphify\.venv\Scripts\python.exe .\.tools\graphify\Refresh-CopilotHandoff.py --target-path 'Scripts and projects\CDD Audit' --target-path 'Scripts and projects\Copilot Local Agent' --include-tests
& .\.tools\graphify\.venv\Scripts\python.exe .\.tools\graphify\Refresh-CopilotHandoff.py --all-scripts-and-projects --include-tests --archive-current
```

For one project, the canonical form is:

```powershell
& .\.tools\graphify\.venv\Scripts\python.exe .\.tools\graphify\Refresh-CopilotHandoff.py --target-path 'Scripts and projects\Copilot Local Agent' --include-tests --archive-current
```

Useful options: `--output-mode full-discovery|issue-continuation`, `--clean`, `--archive-current`, `--max-files 20`, `--exclude-pattern`, `--include-tests`, `--include-source-excerpts`, `--regenerate-changed-only`, `--dry-run`, and `--verbose`. It runs Graphify extraction and clustering with `--code-only`, keeps working data under `.tools/graphify/runs`, and writes the selected project's package to that project's `Copilot handoff/<mode>/` folder. The complete Graphify artifacts are included under `graphify/`. The package is limited to 20 files recursively. Graphify does not upload project code.

For direct Graphify-only operation, use the isolated interpreter:

```powershell
& .\.tools\graphify\.venv\Scripts\python.exe -m graphify extract 'Scripts and projects\Copilot Local Agent' --code-only --out '.tools\graphify\runs\copilot-local-agent' --max-workers 4
```

For multiple projects, run one extraction per project and combine their `graph.json` files with `graphify merge-graphs`. For the complete `Scripts and projects` scope, use that folder as the extraction target; review exclusions first.

