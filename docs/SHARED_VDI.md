# Shared S-drive VDI use

Package setup uses `bootstrap/setup_dependencies.py` after the existing Python,
environment and pip-policy checks. It scans the selected environment's package
metadata once, retains exact installed versions, and installs only missing or
changed pins. The complete lock supplies dependencies, so pip runs with
`--no-deps --prefer-binary --no-compile`, followed by `pip check` and actual
Crawl4AI/Playwright import checks. A ready environment needs no package downloads.
Pip's configured package source, certificate/security settings and writable cache
remain in use. Temporary/cached downloads may use local Windows scratch folders;
the selected project environment and durable agent knowledge keep their existing
S: boundary. No system Python packages are copied or adopted as project packages.

Before installing, setup tests nested `pip-unpack` wheel-file creation, flush,
readback and cleanup. It tries existing TEMP/TMP/TMPDIR folders, separate project
`.setup-cache` folders, equivalent verified S:/UNC spellings and available Windows
scratch locations. `COPILOT_SETUP_TEMP` can specify an operator-selected folder.
Each install retry recomputes missing versions, preserving completed work. A
verified cache is reused; a cache fault or repeated failure permits an uncached
retry. Missing package versions or package-source errors stop with their real
diagnostic rather than retrying the same downloads in every folder.

If automatic folder choices are exhausted, setup asks:

> Setup needs a folder where you can save files to unpack its downloads. Paste
> the full folder address (for example S:\\Setup files), or press Enter to stop.

The selected folder is checked and tried before failure. Existing files are
retained; only uniquely owned probe files are removed. The shared environment
setup lock continues to serialize installation. Dependency names with hyphens,
underscores or dots are normalized for the launcher's pinned-package validation.

On 14 October 2026, 50 focused setup/launcher/temp-storage tests passed, including
an actual offline wheel installation with broken temporary settings and spaces in
the paths, followed by a repeat that downloaded nothing. Checking an existing
96-package development environment completed in 4.9 seconds. This is the package
step on the development laptop, not a full first-install or VDI/UNC timing claim.
The exact reported VDI error and shared-drive performance remain unverified.

An existing project environment is reused only if its interpreter and pip both work. If pip is missing, Setup discovers pip in the selected base installation automatically and preserves the old environment before rebuilding it with the bundled bootstrap. If automatic selection picked the project environment itself, Setup obtains the base executable from the running Python before moving that environment. The replacement's pip is verified before package installation; pinned application packages remain in the project environment.

Windows may report a running environment's base executable, other runtime paths, or installed-package locations as UNC paths even when the installation was launched through S:. The launcher accepts a UNC path only after resolving it to the currently mapped S: share; unrelated UNC shares and local drives still fail validation. An existing environment's prefix is checked by directory identity, so S: and UNC spellings of the same environment can be reused. If a runtime path fails validation, the error includes the live Python-reported values; the environment configuration file alone does not establish what Python reported.

Keep one copy of the source repository on S: and use an organisation-managed Python 3.10+ installation on S:. Setup offers automatic detection or a pasted absolute Python executable/installation-folder path. Quoted File Explorer paths are accepted; the same S-drive and link checks apply to both choices. If detection fails, paste a path locally without sharing private paths in chat. Start and Tests reuse a valid saved environment.

Setup creates/reuses the repository's `.venv` and installs `requirements.lock.txt` directly into it. It uses the bundled `bootstrap/virtualenv.pyz` archive, verified against a pinned SHA-256 before execution, so the selected portable Python does not need `venv`, `ensurepip`, or base-installation `pip`. The archive seeds pip offline in `.venv`; pinned project packages still require the organization's package index. An incomplete `.venv` from an interrupted setup is moved to `.venv-incomplete-*` within the repository before a new environment is created. The selected base interpreter and shared virtual environment both stay on S:. Setup needs write permission there and access to the organization's package index. Environment installation is serialized; another concurrent setup fails clearly rather than racing shared package writes. Ordinary Start does not install packages. Every production Python entrypoint ignores `PYTHONPATH`/other Python environment overrides and per-user package directories using `-E -s`. Setup verifies the base interpreter, standard library and each pinned dependency distribution are on S:. Development launches retain their local interpreter behavior.

The app resolves `Discoveries knowledge` beside the project root's parent on S: and verifies the final UNC identity. Per-user settings, workspace, deliveries, temporary files, session records and persistent website/discovery knowledge stay under that S: folder. An older configured C: or OneDrive storage path is redirected to the canonical S: location. The project source remains separate from mutable state; Setup writes the shared environment and retained setup lock. User grants and chat state are not inherited by another user.

The checkout and Python paths may be entered as S: paths or their equivalent UNC paths on the currently mapped share. Startup retains its previously working drive-based selection; UNC Python aliases are accepted using the PowerShell drive mapping, with CIM and SMB mapping fallbacks when the first provider is unavailable. Runtime checks still verify shared paths before execution.

Downloads may first pass through Edge's configured Downloads location, including a redirected UNC directory. The orchestrator inspects that setting, captures the actual event and retains the approved artifact in S: Discoveries storage before claiming delivery. Download verification accepts both direct and redirected filesystem paths; S: and its live UNC alias identify the same directory. ZIP retention, inspection, extraction, package outputs and knowledge read/write use the resolved shared identity. ZIP extraction stays within that storage. This does not assume that any ordinary VDI local directory will survive logoff.

Edge profiles are per user and VDI machine. Sessions have independent UUID directories and new topics use independent Copilot UI chats. The authenticated user completes sign-in/MFA. Existing managed-browser settings are respected; the agent never changes download security or authentication controls to make a test pass.

The private S: drive and shared Python installation cannot be exercised on the current development machine. Automated checks use isolated temporary paths and validate that the default knowledge root follows the project under a simulated mapped S: share. Actual VDI mapping, write permission and deployment still require target-environment confirmation.

Atomic approval previews and other retained JSON records use extended Windows filesystem paths internally, including extended UNC spelling, so hashed filenames and temporary-write suffixes do not depend on the VDI enabling legacy long-path support. The operator-visible destination and S: storage boundary remain unchanged.
