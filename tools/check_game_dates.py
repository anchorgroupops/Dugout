import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
AUTH_FILE = ROOT_DIR / "data" / "auth.json"
LINKS_FILE = ROOT_DIR / "data" / "schedule_links.txt"
OUT_FILE = ROOT_DIR / "data" / "schedule_titles.txt"

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=str(AUTH_FILE))
        page = await context.new_page()
        
        links = LINKS_FILE.read_text(encoding="utf-8").splitlines()
        
        results = []
        for link in links[-6:]:
            url = link.strip()
            res = f"Checking: {url}"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)
                title = await page.title()
                header = await page.evaluate("() => { const el = document.querySelector('h1, h2, .matchup, .date'); return el ? el.innerText : ''; }")
                res += f"\n -> Title: {title} | Header: {header}"
            except Exception as e:
                res += f"\n -> Error: {e}"
            results.append(res)
            
        OUT_FILE.write_text("\n".join(results), encoding="utf-8")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
