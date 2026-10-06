# Code Runner approval and security

Guidance version: 1.1.

## Modes and selection

`python_subset` remains the default. It evaluates a restricted AST with bounded computation, `print`, `range`, `len`, `str`, `int`, `sum`, `min`, `max`, `sorted`, `read_file` and create-only `write_file`. It has no imports, host execution, arbitrary attributes, subprocesses or network.

Use `local_python` only when registered tools and `python_subset` cannot perform the user's requested local task. It launches the agent's exact current Python interpreter in a separate bounded process and can use declared standard-library or installed imports, approved file access, exact managed subprocesses, approved HTTPS destinations and declared desktop capabilities. It is defense in depth on a trusted local machine, not an operating-system security sandbox. Never describe it as safely running arbitrary untrusted code.

## Exact proposal contract

Both modes require the complete `script`, `purpose`, `language`, existing `working_directory`, `read_paths`, `create_paths`, `expected_outputs`, empty `commands`, `subprocesses`, `network_destinations`, `permissions`, `risk_summary` and `recovery_notes`. Optional paired `source_path` and `source_sha256` bind an actual downloaded `.py` file; its raw UTF-8 bytes must exactly equal `script`, and it must be an approved read.

Every `local_python` proposal additionally requires:

- `interpreter`: the exact current agent Python executable returned by `system.versions`;
- `arguments`: the exact script argument vector;
- `imports`: every module imported directly by the script;
- `modify_paths`: exact existing files that may be changed, normally empty;
- `timeout_seconds` and `max_output_chars`, within the catalogue limits;
- `expected_effects`: short, complete descriptions of externally observable effects;
- `viewer_windows`: exact image/title/display declarations for managed persistent viewers, normally empty.

Use permissions only when required: `read_files`, `create_files`, `modify_files`, `network`, `subprocesses`, `desktop_capture`, `window_management`, and `persistent_processes`. Network destinations are exact canonical HTTPS hosts on port 443. `commands` must remain empty because shell command strings are unavailable. Each managed subprocess is an object containing an absolute `executable`, exact `arguments`, boolean `persistent`, and `purpose`. Persistent children require both `subprocesses` and `persistent_processes`. The runner stops nonpersistent children after the run and registers approved persistent children for session-close cleanup.

`viewer_windows` entries contain an exact unique `title`, an `image_path` that is also a declared expected PNG output, and the Windows `display_index`. Viewer launch and placement happen only after the script succeeds. The orchestrator independently inspects visible top-level window titles and final bounds; a missing, hidden or off-display window makes the run fail and cleans up the viewers.

## Human authorization

Every proposed script must be displayed in full with its SHA-256 before execution. The choices are deny, approve this exact execution once, or approve the exact fully displayed pending plan. The plan choice is not standing permission: it covers only the scripts, call identities and prepared metadata already displayed. Local grants bind canonical plan data, script bytes/hash, source hash, interpreter identity/hash, arguments, imports, directory, file scope, destinations, subprocesses, desktop effects, permissions, limits, expected effects and fixed runner implementation. Any material change requires a fresh preview and explicit decision. `--yes-setup`, an attachment, a prior approval, or conversational willingness never authorizes a new script.

Denial prevents execution and dependent steps. Do not retry denied code through another mechanism. Downloading or extracting code never authorizes it.

## Desktop capture and viewer verification

For an explicitly requested physical-display task, `local_python` may import `copilot_agent.desktop`. Its `enumerate_displays()` result supplies Windows display numbers and bounds. `capture_display(display_index, output_path)` creates one new PNG for that complete display. Declare every PNG as both a create and expected output and request `create_files` plus `desktop_capture`. Declare each requested persistent image viewer in `viewer_windows` and request `window_management` plus `persistent_processes`.

For three physical displays, first require evidence that three displays were enumerated, capture each display separately, then declare three uniquely titled viewers targeting display 2. Completion requires all three PNGs to be independently readable and hashed and all three exact viewer windows to be visible with bounds contained on display 2. A zero exit code alone is insufficient. If the desktop is unavailable, fewer than three displays exist, Tk/Windows APIs are restricted, or organization policy blocks capture/window placement, report the observed blocker; never bypass it.

## Runtime controls and evidence

The host process uses bounded asynchronous stdout/stderr reads, an approved timeout, cancellation handling, a scrubbed environment, import checks, Python audit hooks for declared file/network/process scope, exact managed-child matching and retained run receipts. Dynamic code/import functions, wildcard/relative imports, registry/credential modules, shell execution, deletion, rename and listening sockets are unavailable. Native libraries can weaken language-level mediation, which is why their exact imports, script bytes and desktop permissions require meaningful human review.

After execution, report actual stdout/stderr, exit code, duration, created/modified evidence, readable output sizes and SHA-256 values, managed process state, cleanup actions, verification results and the retained audit path. A successful process exit proves only process completion. Verify every user-stated end condition independently. Failed, timed-out and cancelled runs stop owned processes and retain evidence; output files are retained rather than deleted.

## Prohibited activity

Never request file deletion, destructive corruption, credential collection, exfiltration, security-control changes, authentication bypass, hidden persistence, privilege escalation, concealed activity, unrelated system changes, or downloading/executing unreviewed binaries. User-requested visible viewer persistence is allowed only through the declared managed lifecycle above. Never expand scope after approval or treat static screening as an OS sandbox.
