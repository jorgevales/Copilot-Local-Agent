"""Keep a Playwright-launched Edge profile alive while agent sessions attach over CDP."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys


async def own_edge(port: int, profile: Path, executable: Path) -> None:
    if not 1024 <= port <= 65535:
        raise ValueError("Choose an unprivileged local debugging port.")
    if not profile.is_absolute() or not executable.is_file():
        raise ValueError("Edge owner paths must be absolute and the executable must exist.")
    profile.mkdir(parents=True, exist_ok=True)
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(profile),
            executable_path=str(executable),
            headless=False,
            viewport=None,
            args=[
                f"--remote-debugging-port={port}",
                "--remote-debugging-address=127.0.0.1",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            # Keep organization-installed extensions active. Playwright disables
            # them by default when it launches Chromium; this explicit allowlist
            # removes only those two switches and leaves its other launch defaults.
            ignore_default_args=[
                "--disable-extensions",
                "--disable-component-extensions-with-background-pages",
            ],
        )
        try:
            # Playwright's default event wait is only 30 seconds. Keep the
            # profile owner alive for the lifetime of the user's visible Edge
            # window so subsequent agent sessions can attach over CDP.
            await context.wait_for_event("close", timeout=0)
        finally:
            if context.pages:
                try:
                    await context.close()
                except Exception:
                    pass


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from copilot_agent.edge_native_probe import suppress_fault_dialogs
    suppress_fault_dialogs()  # A failed owner exits; the parent can try direct Edge.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--edge-executable", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(own_edge(args.port, args.profile, args.edge_executable))


if __name__ == "__main__":
    main()
