import asyncio
import json
import uuid
from pathlib import Path

from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as playwright:
        profile = Path.home() / "AppData/Local/Temp/copilot-playwright-live"
        context = await playwright.chromium.launch_persistent_context(
            str(profile),
            executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            headless=False,
            args=["--start-maximized"],
            viewport=None,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://m365.cloud.microsoft/chat", wait_until="domcontentloaded", timeout=60_000)
        await context.grant_permissions(["clipboard-read", "clipboard-write"], origin="https://m365.cloud.microsoft")
        print("LOGIN_REQUIRED " + page.url, flush=True)
        deadline = asyncio.get_running_loop().time() + 900
        while asyncio.get_running_loop().time() < deadline:
            if "m365.cloud.microsoft/chat" in page.url and "login.microsoftonline.com" not in page.url:
                print("LOGIN_DETECTED " + page.url, flush=True)
                break
            await asyncio.sleep(2)
        else:
            print("LOGIN_TIMEOUT", flush=True)
            await context.close()
            return

        existing = page.locator('#copy-button[aria-label="Copy code"]')
        print(json.dumps({"stage": "inspect", "copy_buttons": await existing.count(),
                          "body_tail": (await page.locator("body").inner_text())[-4000:]}), flush=True)

        request_id = "live-copy-" + uuid.uuid4().hex[:12]
        expected = json.dumps({"request_id": request_id, "status": "ok"}, separators=(",", ":"))
        prompt = f"Return exactly one fenced JSON code block and no other text. The JSON must be: {expected}"
        editors = page.locator('[contenteditable="true"]:visible')
        print(json.dumps({"stage": "editor", "count": await editors.count(), "request_id": request_id}), flush=True)
        if await editors.count() != 1:
            raise RuntimeError("Expected exactly one visible Copilot editor")
        await editors.fill(prompt)
        await page.get_by_role("button", name="Send", exact=True).click()
        button = page.locator('#copy-button[aria-label="Copy code"]').last
        await button.wait_for(state="visible", timeout=60_000)
        await button.click()
        await page.wait_for_timeout(500)
        copied = await page.evaluate("navigator.clipboard.readText()")
        parsed = json.loads(copied)
        passed = parsed == {"request_id": request_id, "status": "ok"}
        print(json.dumps({"stage": "copied", "request_id": request_id, "copied": copied, "passed": passed}), flush=True)
        if not passed:
            raise RuntimeError("Copied JSON did not match the requested response")
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
