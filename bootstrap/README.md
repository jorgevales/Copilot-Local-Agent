# Portable Python environment bootstrap

`virtualenv.pyz` is the official self-contained virtualenv zipapp downloaded from
`https://bootstrap.pypa.io/virtualenv.pyz` on 6 October 2026. It reports
virtualenv 21.14.5 and supports Python 3.9 and later. Its SHA-256 is
`9096efa6e3a8457cc3ec56e749a2d1e17505b756ee3cb2b7e889526367efc187`.
`Launcher.ps1` verifies that hash before executing it. The archive contains
virtualenv's license and third-party notices in its `.dist-info/licenses` folder.

Setup runs this archive with the selected Python using `--no-download` and
`--no-periodic-update`. This creates `.venv` and seeds its pip without modifying
the base Python installation or requiring administrator rights. Project packages
are subsequently installed into `.venv` from the configured package index.

`setup_dependencies.py` checks pinned packages before downloading and retains
successful partial installs on retry. It tests real nested wheel writes and
readback instead of trusting a drive's reported free space. Existing explicit,
environment, project, resolved-path, LocalAppData and Windows temporary candidates
remain first. If they fail, bounded discovery consults the actual S: mapping
through PowerShell drive data, CIM and SMB mapping, and tries its proven UNC/S:
aliases and shorter scratch paths. Additional local scratch is allowed for setup
unpacking and cache only; durable discovery knowledge remains on S:.

Path, access, quota and invalid-cache failures retry remaining packages in another
verified folder; invalid cached wheels switch to uncached downloads. Package-source
errors stop promptly. Exhausting all automatic folders produces sanitized path
and failure categories without asking for a manual unpacking folder. Correct share
connectivity/permissions or set `COPILOT_SETUP_TEMP` to a writable absolute scratch
folder, then rerun Setup. Live S:/UNC availability still needs validation on the
target Windows/VDI environment.

## Portable REA runtime repair

Normal dependency setup also provisions the optional pinned `rea-agents` 6.5.0
runtime. A developer's sibling research checkout is not required in the VDI.
Setup reuses a complete verified installation, or obtains the published npm
archive with a fixed SHA-512 digest and installs production dependencies without
package lifecycle scripts. The Windows native addon is included and its exact
version/hash checked. `node scripts/rea.mjs --help` must load successfully before
an install is accepted. Node 24.11+ LTS (or supported 22.19+/26+) and npm are needed.

Repair independently from the project folder:

```powershell
.venv\Scripts\python.exe bootstrap\setup_rea.py
```

Fallback locations are `.runtime/rea` under the project, then
`%LOCALAPPDATA%/Copilot Local Agent/runtimes/rea/6.5.0`, then the corresponding
`%TEMP%` path. Existing runtimes and partial installations are preserved; every
new install is staged separately and verified before publishing. Setup tries the
npm offline cache before the registry and bounds the overall installation work.
For disconnected setup, set `COPILOT_REA_ARCHIVE` to the absolute path of the
unchanged published 6.5.0 tarball and populate the npm cache in advance. A complete
existing installation can instead be selected with `rea_repository` in
`config.local.json`. `COPILOT_REA_NODE` selects a Node executable during repair;
set `rea_node_executable` in local configuration too when Node is not on PATH.
Failures explicitly identify REA as unavailable while retaining working Python
tools. Runtime setup never changes durable S:-backed discovery storage.
