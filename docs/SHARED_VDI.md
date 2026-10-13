# Windows laptop and VDI deployment

Pull the source into any accessible local, mapped-drive or UNC checkout. Run `Setup.cmd` with an accessible Python 3.10+ installation; the interpreter may be local or shared and need not reside on the checkout drive. No environment-specific grant is added to the Copilot guidance.

Setup creates or reuses the checkout's `.venv`, validates the interpreter and pinned dependencies, and serializes installation. If a copied environment refers to a changed or unavailable base interpreter, Setup preserves it under a recovery name before rebuilding. Ordinary Start reports when Setup is needed. The checksum-verified bundled virtualenv archive can bootstrap installations without base pip or venv. Package installation requires access to the configured package index and filesystem write access. Production Python entrypoints retain `-E -s` isolation.

Durable state prefers the current mapped S: share. A checkout on that share uses `Discoveries knowledge` beside the project; other checkouts use `S:\CopilotLocalAgent\Discoveries knowledge`. Without mapped S:, accessible UNC checkouts use the sibling store, while local checkouts use `%LOCALAPPDATA%\CopilotLocalAgent\Discoveries knowledge`. Copied absolute source/storage/profile settings are rebased to current resources. Startup verifies writes and readback using the resolved filesystem identity.

ZIP authors receive the current registered tools and runtime directories. Package creation and execution have no laptop, VDI or drive-letter gate. Packages retain fresh hash-bound inspection, local session approval, path policy, protected-path checks, bounded concurrency and verified outputs. Existing OS and organizational controls still apply.

Edge profiles and sessions are selected for the current machine and user. Complete sign-in/MFA in the visible browser. Authentication and browser security controls are unchanged. Persistent S: storage is preferred because local VDI storage may not survive logoff.

This portability update is verified with offline tests. No new live VDI or browser test was performed.
