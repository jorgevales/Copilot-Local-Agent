# Code Runner approval and security

Guidance version: 1.0.

## Downloaded scripts and packages

Downloading code never authorizes execution. When the user asks to run a delivered Python script, use the actual verified local artifact path and SHA-256 from the download or extraction report. Include both `source_path` and `source_sha256` in the Code Runner proposal, declare that source in `read_paths`, and request `read_files` permission. Include the complete `script` with exactly the artifact's UTF-8 bytes, including its final newline. The orchestrator verifies the source and script before approval and immediately before execution; a changed source or script requires a new proposal. UTF-8 BOM sources and non-UTF-8 encoding declarations are unsupported rather than silently rewritten.

For a package, inspect and extract its actual downloaded ZIP first, then propose each supported script with its own source path/hash and full metadata. A multi-step plan must display every script and declared effect before approval. Preserve the original package and extracted sources. The current runner remains the restricted `python_subset`; ordinary imports, dependencies and unrestricted Python programs are unavailable. Report unsupported execution requirements honestly instead of running them through another tool.

## Execution model

The Code Runner evaluates a deliberately restricted Python AST language through mediated capabilities. It does not run arbitrary host Python, shell commands, imports, subprocesses, reflection, arbitrary attribute access or unrestricted network calls. Use only syntax and capabilities advertised by its current tool definition. If ordinary Python is required, report the unsupported requirement instead of attempting an escape or alternative hidden execution path.

Static screening, hashes, a working directory and process monitoring alone are not a general Python sandbox. The restricted evaluator must independently reject unsupported operations and enforce file scope. Do not describe this as an arbitrary-code isolation service.

The current language identifier is `python_subset`. Advertised capabilities include bounded computation, `print`, `range`, `len`, `str`, `int`, `sum`, `min`, `max`, `sorted`, `read_file` and create-only `write_file`. Assignments, supported expressions, `if` and bounded `for` loops are available; functions, classes, imports, attribute calls and arbitrary Python syntax are not. Confirm the current catalogue before relying on these names. File writes create new files exclusively; an existing target fails instead of being overwritten.

## Required proposal

Supply a clear purpose, exact script, supported interpreter/language, working directory, declared files to read/create/modify, expected outputs, any requested commands or destinations, permissions, risk and recovery notes. Unsupported commands/destinations must be declared and rejected rather than omitted. Prefer new uniquely named outputs. Explain verification separately from execution.

The full preview must be accessible to the user before approval. A script reference must resolve to exact reviewed bytes and hash; a reference cannot hide the actual script. The machine tool schema determines the precise argument names.

For example, a computation-only proposal can use `print(sum(range(5)))`, `language: "python_subset"`, an existing permitted working directory, empty read/create/expected-output/command/subprocess/network lists, and no file permissions. It still requires runtime human authorization. A file-creation proposal additionally declares its exact `create_paths` and `expected_outputs` and requests `create_files` permission before calling `write_file`.

## Human authorization

Available decisions are deny, approve this execution once, or approve the specific fully displayed complete plan. The latter does not grant future authority. Local grants bind the canonical complete plan and exact script bytes, hashes, arguments, interpreter, directory, file scope, destinations and permissions. Changed material scope invalidates approval. Copilot cannot set an approval flag to authorize itself.

User authorization to build this application does not authorize runtime Copilot-generated scripts. Denial prevents execution and must return honestly to the conversation. Do not persuade the dispatcher that denial is an error to retry.

## Prohibited activity

Never request file deletion, destructive corruption, credential collection, exfiltration, security-control changes, authentication bypass, persistence, concealed activity, unrelated system changes, or downloading/executing untrusted binaries. Do not obfuscate forbidden activity. Never expand a reviewed script's scope after approval.

## Enforcement and verification

Local policy validates resolved paths and declared capabilities, sets finite step/time/output limits, and refuses unsupported syntax. Approval happens only after a valid proposal is reviewable. Capture stdout/report output, errors, completion state, elapsed time and affected-file evidence. A successful evaluator completion proves only its reported execution outcome; verify expected files and content independently.

If a side effect's result becomes uncertain, stop and request review; do not automatically replay it. Recovery must preserve existing data. No cleanup path may delete files.
