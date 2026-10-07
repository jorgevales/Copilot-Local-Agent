# Testing Copilot replacement files

Double-click **Start Agent.cmd** and choose **1: Live repository** or **2: Copilot testing environment**. Setup remains the usual prerequisite. No Git installation or GitHub access is required for this workflow.

Drop replacements into the fixed **Copilot testing environment/Updated files/** folder. Mirrored directories are already present and are extended automatically at startup as the live project grows. Place root replacements directly in `Updated files`; put other files in their original relative directories. For example, these identically named files coexist safely:

```text
Copilot testing environment/
  Updated files/
    app.py
    copilot_agent/
      app.py
      browser.py
    tests/
      test_browser.py
    schemas/
      response-v1.schema.json
    guidance/
    docs/
    bootstrap/
  versions/                    retained complete runnable copies
```

Ask Copilot to label each delivered file with its project-relative path. Extract ZIP deliveries into `Updated files` preserving those paths. Create matching directories for new files. Flat files are accepted only when they identify a root file or one unique existing destination; ambiguous filenames stop with placement instructions.

The launcher creates a complete source copy under `Copilot testing environment/versions/<timestamp>/source`, applies all replacements, and runs that copy using the live project's configured Python environment. Imports resolve together inside the copy. Python syntax is checked before a version is created; this does not prove that the fix works. Copilot code is untrusted and executes with your normal user permissions.

The launcher applies `Updated files` automatically when testing is selected, without asking for a delivery path. Accept the latest testing version, choose an older version, or choose **L** to rebuild from live. Keep current replacements in the fixed folder and overwrite them with Copilot's next revisions. Changes accumulate on the selected version; unchanged replacements reuse that version. Removing a dropped file does not undo a previously applied change: choose **L** to rebuild using only the remaining replacements.

Graphify excludes the entire `Copilot testing environment` and `Copilot proposals` folders via `.graphifyignore`, including dropped files, copies and manifests. Only empty folder placeholders are committed; candidate files and retained versions remain ignored.

Each version retains `manifest.json` beside `source/`, including base source hashes and replacement hashes. Versions and proposals are excluded from Git. Existing versions and the live implementation are preserved. The dependency environment is shared: dependency changes require separate review/setup. Normal agent storage, allowed roots, sessions and approvals still apply, so a testing source copy does not isolate your personal files or external services. Ordinary application startup creates a fresh session.

To run a selected copy's automated tests, use the configured interpreter from a terminal with that copy as the current directory:

```powershell
& '<live-project>/.venv/Scripts/python.exe' -B -m unittest discover -s tests -v
```

After reproducing the original failure and verifying the fix in the real target environment, provide the successful version's `manifest.json`, changed files under `source/`, and reproduction/test evidence for review and incorporation. The launcher never promotes a testing version into live automatically. Further live edits do not silently alter existing testing versions; choose **L** when rebasing onto current live is required.
