# Upstream REA runtime discovery and repair

## Confirmed layout and invocation

The source repository and executable package are distinct. The tested executable
is the installed `rea-agents` package, invoked directly by portable Node:

```powershell
& "<NODE_ROOT>\node.exe" "<REA_RUNTIME_ROOT>\scripts\rea.mjs" <REA_COMMAND> <ARGUMENTS>
```

Reports use the operator's mirrored references below. Configuration, tool arguments
and internal diagnostics retain resolved paths so the orchestrator can execute.

| Concept | Mirrored reference |
| --- | --- |
| Projects parent | `<PROJECTS_ROOT>` |
| REA source repository | `<PROJECTS_ROOT>\REA` |
| Copilot Local Agent | `<PROJECTS_ROOT>\Copilot-Local-Agent` |
| Portable Node | `<NODE_ROOT>` |
| npm storage | `<NPM_DATA_ROOT>` |
| Executable REA package | `<REA_RUNTIME_ROOT>` |
| REA evidence/results | `<REA_OUTPUT_ROOT>` |
| Isolated browser profile | `<BROWSER_PROFILE_ROOT>` |

The supplied layout has `<NODE_ROOT>` beside `npm-data`, with the executable
package at `<NPM_DATA_ROOT>\global\node_modules\rea-agents`. Discovery derives
that location from the selected Node executable, then checks the sibling REA
source repository and managed runtime locations. It performs bounded candidate
checks without scanning drives or requiring the real company root in a report.
An explicit `rea_repository` remains authoritative.

## Defects corrected

- Setup could report Python fallback success after upstream installation failed.
  Normal Setup in auto/node_cli mode now requires verified Node REA. The focused
  **Setup REA.cmd** entry repairs upstream REA without repeating Edge setup.
- Discovery omitted the known sibling/global npm layouts. Setup and runtime now
  share those candidates and prefer the already tested global package.
- A structurally complete candidate with a failing CLI hid later working
  candidates. CLI checks now continue within one shared 180-second readiness
  budget. Uncertain cleanup still stops further attempts.
- Testing copies excluded live private settings and runtime folders. Their
  launches inherit only the verified REA preferences, respecting local overrides.
- Successful setup now saves and reads back the exact runtime and Node paths.
  General `available:true` is separate from `upstream_available`; Python results
  are never presented as upstream execution.

## Recovery paths

1. Pull the update and run **Setup REA.cmd**, then start a new session. Existing
   verified packages are reused without npm or downloads. The existing portable
   Node path is reused, or setup accepts its executable/folder/ZIP when needed.
2. If automatic location derivation cannot find a custom layout, select it:

   ```powershell
   .venv\Scripts\python.exe bootstrap\setup_rea.py --require-node --repository "<REA_RUNTIME_ROOT>" --node-path "<NODE_ROOT>\node.exe"
   ```

3. Managed repair obtains the pinned official 6.5.0 distribution, production
   dependencies and native addon. Verified local writable candidates are preferred
   over redirected drives; shared candidates remain fallbacks. A discovered
   `<NPM_DATA_ROOT>\cache` is reused only after a write/read check; npmrc is not read
   into reports. Durable discovery evidence remains in its existing S:/UNC store.
4. For unavailable registry/npm, export a complete verified runtime using
   `python -m bootstrap.rea_delivery --source "<REA_RUNTIME_ROOT>" --output <ZIP>`.
   Transfer its separately supplied SHA256 and import with `setup_rea.py
   --require-node --offline --runtime-archive <ZIP> --runtime-archive-sha256 <SHA256>`.
   Import verifies archive membership, file hashes, production dependencies and
   exact native identity. It loads the actual CLI before and after publication.
   Export excludes developer files and credential/config files.

Ordinary startup and tool selection never install packages. Explicit Python-only
or disabled settings remain intentional for normal Setup; **Setup REA.cmd**
specifically requires upstream verification. Python remains an honest fallback
for ordinary investigations when upstream cannot run.

## Evidence and remaining environment checks

Local verification exercised the actual upstream runtime, not the Python backend:

- Fresh registry installation: upstream Node CLI verified in about 42 seconds.
- Complete offline installation plus HAR analysis: `backend:node_cli`, completed,
  in about 17 seconds, including installation, readiness and analysis.
- Fresh session: metadata, all three REA catalogue entries and routing agreed on
  `node_cli`; website investigation preferred `rea.inspect_page`.
- The real CLI also passed capture, JavaScript, owned Edge page and registry
  dispatch integration checks in the focused 71-test run.
- Final combined upstream/setup/discovery/backend/availability regression run:
  **151 passed**, including actual CLI/owned Edge integrations.
- Earlier setup/portable/runtime/launcher run:130 passed; session/routing run:17
  passed (counts overlap).
- Recreated the supplied relative source/global/npm/portable-Node layout with a
  real upstream package: automatic discovery reused the global runtime without
  npm/downloads, completed HAR analysis through node_cli, and produced matching
  fresh-session metadata/catalogue/routing. Windows short/long-path aliases were
  compared by resolved file identity.

These checks do not establish live VDI, live S:/UNC capacity, production browser
profile or authenticated Copilot behavior. In the target environment, a new
session must show `selected_backend:node_cli`, `upstream_available:true`, and the
actual `node_cli` backend on a supported approved observation.
