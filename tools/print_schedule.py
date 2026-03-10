import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
AUTH_FILE = ROOT_DIR / "data" / "auth.json"
OUT_FILE = ROOT_DIR / "data" / "schedule_links.txt"

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=str(AUTH_FILE))
        page = await context.new_page()
        
        url = "https://web.gc.com/teams/NuGgx6WvP7TO/2026-spring-sharks/schedule"
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        
        # Get purely href attributes
        links = await page.evaluate("Array.from(document.querySelectorAll('a')).map(a => a.href)")
        
        schedule_links = [link for link in links if "/schedule/" in link]
        OUT_FILE.write_text("\n".join(schedule_links), encoding="utf-8")
        print(f"Wrote {len(schedule_links)} links to {OUT_FILE}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
