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
