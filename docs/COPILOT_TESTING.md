# Testing Copilot replacement files

Double-click **Start Agent.cmd** and choose **1: Live repository** or **2: Copilot testing environment**. Setup remains the usual prerequisite. No Git installation or GitHub access is required for this workflow.

For your first testing run, put Copilot's replacement files in `Copilot proposals/`, or enter another delivery folder when prompted. Preserve project-relative paths, for example `Copilot proposals/copilot_agent/browser.py`. Flat files are accepted only when the live source has exactly one matching filename. New files must include their project-relative directories. Extract delivered ZIPs into a folder first.

The launcher creates a complete source copy under `Copilot testing environment/versions/<timestamp>/source`, applies all replacements, and runs that copy using the live project's configured Python environment. Imports resolve together inside the copy. Python syntax is checked before a version is created; this does not prove that the fix works. Copilot code is untrusted and executes with your normal user permissions.

On subsequent runs, choose the previous testing version and enter the folder containing the next replacements. Changes accumulate on that version. Press Enter at the delivery-folder prompt to run the selected version unchanged. Choose an older version for rollback, or **L** to create a fresh testing version from live. Use a folder containing only the intended new delivery; files left in `Copilot proposals` can otherwise be reapplied.

Each version retains `manifest.json` beside `source/`, including base source hashes and replacement hashes. Versions and proposals are excluded from Git. Existing versions and the live implementation are preserved. The dependency environment is shared: dependency changes require separate review/setup. Normal agent storage, allowed roots, sessions and approvals still apply, so a testing source copy does not isolate your personal files or external services. Ordinary application startup creates a fresh session.

To run a selected copy's automated tests, use the configured interpreter from a terminal with that copy as the current directory:

```powershell
& '<live-project>/.venv/Scripts/python.exe' -B -m unittest discover -s tests -v
```

After reproducing the original failure and verifying the fix in the real target environment, provide the successful version's `manifest.json`, changed files under `source/`, and reproduction/test evidence for review and incorporation. The launcher never promotes a testing version into live automatically. Further live edits do not silently alter existing testing versions; choose **L** when rebasing onto current live is required.
