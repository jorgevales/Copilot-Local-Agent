# Dependencies and configuration

## Runtime dependencies

- Python `3.10+`; the verified development environment is Python `3.14.2`.
- `playwright==1.55.0`.
- Locked transitive/runtime packages: `greenlet==3.5.6`, `pyee==13.0.1`, `typing_extensions==4.16.0`.
- Installed Microsoft Edge is required for visible operation.
- Core policy/state/protocol logic uses the Python standard library; Playwright is the external runtime package.
- `bootstrap/virtualenv.pyz` supports environment creation when the selected Python lacks `venv` or `pip`.

## Configuration contract

`config.example.json` is the safe template. `Config` in `copilot_agent/config.py` validates types and rejects unknown settings. Important keys and defaults:

| Key | Purpose/default |
|---|---|
| `debug_port` | Loopback CDP port; example `9443`. |
| `attach_existing` | Whether to attach to an explicitly owned existing Edge endpoint; default false. |
| `visible` | Visible Edge mode; required supported mode. |
| `allowed_roots` | File roots such as `workspace` and `deliveries`. |
| `allowed_domains` | Third-party browser allowlist; example only `example.com`. |
| `response_timeout` | Copilot response bound; example `180` seconds. |
| `max_corrections` / `max_tool_rounds` | Recovery and tool-loop bounds; example `12` each. |
| `sync_timeout` | Created-file polling bound; example `120` seconds. |
| `created_dir` / `created_sync_enabled` | Explicit deferred Created configuration; example null/false. |
| `download_timeout` / `max_download_bytes` | Download bounds; example `90` seconds/20 MiB. |
| `max_delivery_retries` | Delivery retry bound; example `3`. |
| `copilot_download_hosts` | Exact generated-artifact host allowlist. |

## Configuration precedence and storage

The ordinary path is Setup/Start with settings remembered under the selected OneDrive. Advanced runs can pass `-B app.py --config <settings-file>`, `--attach-existing --port <port> --profile <dedicated-profile>`, or `--resume <session-path>`. The source checkout and mutable runtime are intentionally separate. Runtime/session/profile/workspace files and local settings are ignored by `.gitignore`.

Environment-variable values are not included in this handoff. Any names required by a future change must be identified from source and documented without values before use.

## Important limits

The ordinary user-file queue is capped at ten; the deployment message cap is twenty attachments. Startup uses eight physical reference files. Script text, source, output, timeout, process, archive, and file-size limits are enforced through the code/tool contracts. `local_python` is approved host execution with defense in depth, not an OS sandbox.

