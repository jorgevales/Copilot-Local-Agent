# Test evidence — 6 October 2026

The setup update and original release evidence are recorded below. Earlier failed reports are preserved; they are never relabelled as passed. Evidence files stay in the operator's selected OneDrive and are excluded from the source release.

## Existing environment without pip

An isolated full Setup run started from a real Python environment created without pip while the selected base Python had working pip. Setup found the base pip, retained the original environment and its marker file, rebuilt the environment, verified pip, installed all four pinned packages, and completed OneDrive and Edge setup. A second full run selected the pip-less project environment itself; Setup resolved its reported base executable before moving it, then completed the same recovery. Both runs used a local wheelhouse and a development-drive fixture, not the private S-drive VDI. The original files and both recovered environments remain in the ignored pip-recovery fixture. The complete suite ran 287 tests: 286 passed and one skipped for unavailable Windows symlink privilege. Retained evidence: workspace/user-storage/workspace/pip-recovery-20261006/report.json.

## Mapped S-drive and UNC runtime aliases

The launcher now validates live running-executable, base-executable, base-prefix, standard-library and pinned-package paths against the current mapped S: share. Synthetic mapping tests accept matching UNC aliases, including extended UNC paths, and reject unrelated shares, share-name prefix collisions, unavailable mappings and paths that resolve outside the share. Existing environment prefix validation uses directory identity with canonical-path fallback. The complete suite ran 284 tests: 283 passed, one skipped for unavailable Windows symlink privilege. The private production S: mapping is unavailable on this development machine; these mapping cases were validated with controlled filesystem-resolution fixtures, not claimed as a live VDI result.

## Portable Python without venv or pip

The official Windows Python 3.14.2 embedded distribution was verified to lack both `venv` and `pip`. Using that unmodified interpreter, isolated Setup completed environment creation with the bundled virtualenv zipapp, offline pip seeding, installation of all four pinned packages, runtime verification, OneDrive/Edge resource selection, and saving the new environment interpreter. A second real Setup started with an incomplete `.venv`, preserved its original file in `.venv-incomplete-*`, then completed the same installation and application setup. No administrator installation was used. The four pinned versions and archived file were checked after setup. The complete automated suite ran **278 tests: 277 passed, one skipped**; the skip is unavailable Windows symlink privilege. PowerShell syntax and zipapp SHA-256 checks passed.

Retained evidence: `workspace/user-storage/workspace/portable-python-setup-20261006/report.json` and its isolated fixture. The package installation used a local wheelhouse obtained from the package index, so this proves setup behavior without base `venv`/`pip` and without live index access during setup. Private S-drive write permissions, organizational package-index access and production VDI Edge remain environment-specific.

## Setup update — automatic or pasted resources and dependency installation

The updated full suite ran **275 tests: 274 passed, one skipped, zero failures or errors**, in 38.186 seconds. The skip remains unavailable Windows symlink privilege. All 55 Python sources parsed; PowerShell syntax validation passed. Nineteen launcher checks include actual native PowerShell/Python invocation, automatic/manual path choices, environment creation/reuse, pip redirect rejection and failure propagation. Nine resource-selection checks cover registered OneDrive paths, Edge executable/folder choices, fallback, remembered per-machine settings and setup-only persistence without launching a browser.

Actual isolated setup acceptance passed all three cases: fresh `.venv` creation and installation of all four pinned packages; automatic reuse with saved settings; deliberately unavailable packages stopping setup before the application starts, with partial environment files retained. The first case used manually selected Python, OneDrive and Edge paths and verified that the saved interpreter is the newly created virtual environment. Versions verified: Playwright 1.55.0, greenlet 3.5.6, pyee 13.0.1 and typing_extensions 4.16.0.

Retained evidence: `workspace/user-storage/workspace/setup-acceptance-4990fc793064480cbb6003622bbc8009/report.json` and the case-specific stdout/stderr. This was real venv/pip/application setup in an isolated development fixture inside Valcer Strategies OneDrive. Only account-metadata discovery and scripted launcher input were injected in copied source to avoid organizational accounts and console input buffering. No browser was launched. This does not establish private S-drive/VDI deployment or its network/write permissions. Earlier attempts exposed and fixed OneDrive CLOUD metadata handling and PowerShell's scalar argument splatting; their failed reports remain retained.

## Original release environment and automated checks

Windows, Python 3.14.2, Edge 154.0.4258.53 and Playwright 1.55.0. The release suite ran **255 tests: 254 passed, 1 skipped, zero failures or errors**, in 23.682 seconds. The skip is unavailable Windows symlink creation privilege. All 53 Python source files parsed successfully. Dependency consistency, CLI help and PowerShell launcher syntax checks passed.

Retained evidence: `workspace/user-storage/runtime/automated-tests-release.json` and `.txt`. These are synthetic offline tests, not evidence of private VDI deployment. Coverage includes strict response validation, malformed-output rejection, replay and uncertain-send handling, immutable source/plan/upload approval, source hashing and byte identity, bounded resource use, path and credential protections, session isolation, findings counting, eight-file guidance integrity, attachment limits, download gates, create-only ZIP extraction, OneDrive storage and shared-runtime checks.

## Current visible acceptance

All live submissions used harmless synthetic content in the actual authenticated Microsoft 365 Copilot UI, through the authorized dedicated Edge profile. The model was the observed available **GPT-6 Sol**. No reasoning API, organizational Created-folder access or authentication bypass was used. The exhausted GPT-6.1 allowance and Auto fallback were detected in an earlier run rather than silently accepted.

| Retained report | Observed result |
|---|---|
| `workspace/user-storage/runtime/acceptance/new-session-20261006T160732Z-d69875/report.json` | Two different actual Copilot chats and local session IDs. Both initialized on the first response with eight attachments. Fresh context, findings, counter, grants and attachment queue; real no-tool answer and `system.versions`; clean owned-page exit. Twenty public reply/plan preview events, nineteen during generation, with attributed tool feedback. |
| `workspace/user-storage/runtime/acceptance/attachments-20261006T161019Z-5af311f9/report.json` | First-response eight-document initialization, followed by two actual approved user-file uploads. Copilot read file-only sentinels from text and staged code. Original and staged bytes matched; no tool execution. The native picker backend was injected for this test; an interactive Windows dialog was not exercised live. |
| `workspace/user-storage/runtime/acceptance/delivery-20261006T161212Z-f26c79/report.json` | All three delivery cases passed: a direct text download, a two-file coding ZIP, and an outer ZIP containing one Excel workbook. Actual browser download events, readable retained OneDrive files and hashes; approved create-only extraction inside OneDrive. Twelve confirmed submissions, including the findings upload at message 10. No delivered code was executed. |
| `workspace/user-storage/runtime/acceptance/download-run-20261006T162653Z-66b212b6/report.json` | Direct `.py` download and the explicitly approved exact local execution succeeded. The overall report remains **blocked** because a delivery-intent classification bug caused unnecessary retries after execution. Its original records remain unchanged. |
| `workspace/user-storage/runtime/acceptance/completed-run-recovery-20261006T164504Z-b4f546c0/report.json` | A fresh actual Copilot chat received a compact locally verified execution receipt and completed the factual stdout/exit/interpreter report. All tool execution was blocked. No second execution or grant reuse; original source and blocked-report hashes remained unchanged. |

The eight physical startup files preserve all ten original guidance/schema/catalogue components byte for byte. Six Markdown files remain separate; two pairs are grouped with full component hashes and offsets. Current initialization also includes the exact response shape. First-response startup succeeded in six fresh chats across these runs; this does not promise that every later response is valid.

The direct text case retained 14 UTF-8 bytes (`delivery-test` plus newline). The coding ZIP contained exactly `README.md` and `main.py`; contents were read and checked, with no execution. The workbook was structurally validated, hashed and independently inspected as ZIP/XML: worksheet A1 contains `delivery-test`. This is not Office rendering or complete semantic/macro validation.

Edge's actual Downloads setting was inspected before downloads. Completed browser artifacts were copied exclusively into the approved OneDrive delivery folder. The reports explicitly say that saving through the configured default Downloads directory was **not proven**, and the modern prompt-switch state was unknown. No Edge setting was changed. Save As interaction is covered with offline fixtures, not a live prompted download.

## Approved downloaded-script execution

The exact preserved download was 27 UTF-8 bytes:

```python
print('download-run-test')
```

SHA-256: `051193104ae2eb28123a6fc755653928f1b7340d862ce3388576b35f4bda95bd`. The user's actual **Approve this execution once** decision matched the immutable full proposal, source path/hash and nonce ledger. The raw source was checked before approval and immediately before execution. Observed stdout was `download-run-test\n`, stderr empty, exit 0; no created files, imports, subprocesses or network. The interpreter was the restricted `python_subset`, not host Python. The one-use grant was consumed, and recovery did not run the script again.

One malformed execution request required a real UI correction; no action was taken from invalid output. After the completed execution, the detector incorrectly treated `download` inside a filename as a new artifact request. A subsequent read-only recovery also exposed a negated request being misclassified. Both detector cases now have regressions. The successful recovery used the production detector and reports only the earlier verified execution. The failed recovery attempts remain retained separately.

Several supported scripts can be approved as one complete immutable prepared plan; this has offline approval/integration coverage. A real multi-script execution was not performed, and ordinary projects using imports or external dependencies remain unsupported.

## Earlier retained evidence and acceptance limits

`runtime/acceptance/conversation-20261006T143125Z-35d181/report.json` records 15 passed conversation steps and one blocked legacy Created-delivery check. It includes actual deterministic tools, denial without execution, correction, durable findings and the separate explicitly approved `print('approval-test')` run. The old local Documents location was incorrect for the clarified OneDrive workflow; that historical check is not evidence of a failure in the correct account.

The user deferred `Documents/Copilot/Created` verification and instructed no organizational FNZ OneDrive access. Monitoring remains disabled. Local Valcer Strategies OneDrive retention/extraction was exercised; cloud synchronization to another device was not inferred. Private S-drive/VDI paths, production-scale sessions, lock/offline behavior, fresh-profile sign-in, live OCR quality, message-20 findings upload, headless operation and general Python/package execution have not been established. See `KNOWN_LIMITATIONS.md`.

The original CDD repository remains unchanged. The release contains source, guidance, schemas, documentation and tests; personal settings, browser profiles, execution evidence and generated files remain outside source control.
