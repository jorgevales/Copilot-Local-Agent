# Shared S-drive VDI use

Keep one copy of the source repository on S: and use an organisation-managed Python 3.10+ installation on S:. The launchers discover the repo from their own location and discover Python without embedding private paths. A saved user choice is reused; discovery is bounded and excludes linked directories. If several interpreters are available, choose the intended shared installation once. Setup checks prerequisites; dependency installation is an operator task, performed once for that shared interpreter.

For production, the operator installs `requirements.lock.txt` into that shared interpreter. Every launcher entrypoint ignores `PYTHONPATH`/other Python environment overrides and per-user package directories using `-E -s`. Setup verifies the base interpreter, standard library and each pinned dependency distribution are on S:, so another user's local package installation cannot satisfy the shared check. Development launches retain their local interpreter behavior.

Each user chooses an available OneDrive account on first run. Selection is remembered in that account. Their `Copilot Agent` folder holds settings, workspace, deliveries, sessions, findings, approvals and diagnostics. The source repository is read-only during ordinary runs. User grants and chat state are never placed in shared repo state or inherited by another user.

Downloads may first pass through Edge's configured Downloads location. The orchestrator inspects that setting, captures the actual event and retains the approved artifact in OneDrive before claiming delivery. Every ZIP extraction stays within the user's OneDrive permitted folders, never S: or a transient local folder. This does not assume that any ordinary VDI local directory will survive logoff.

Edge profiles are per user and VDI machine. Sessions have independent UUID directories and new topics use independent Copilot UI chats. The authenticated user completes sign-in/MFA. Existing managed-browser settings are respected; the agent never changes download security or authentication controls to make a test pass.

The S: drive and private shared Python installation cannot be exercised on the current development machine. The same source can be checked here using its existing development interpreter and the authorised Valcer Strategies OneDrive. Automated checks cover discovery, storage isolation and destination restrictions; report actual VDI deployment separately from those tests.
