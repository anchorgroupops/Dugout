import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data" / "sharks"
AUTH_FILE = ROOT_DIR / "data" / "auth.json"

async def run():
    print("[HAR Capture] Starting Playwright...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    har_file = DATA_DIR / "gc_session.har"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # We must use a context to record HAR
        context = await browser.new_context(
            storage_state=str(AUTH_FILE),
            record_har_path=str(har_file),
            record_har_mode="full"
        )
        page = await context.new_page()
        
        # Go to Box Score (use domcontentloaded instead of networkidle)
        game_box_url = "https://web.gc.com/teams/NuGgx6WvP7TO/2026-spring-sharks/schedule/7b61aa7b-cde9-40c3-937f-48e2a9cdb0a2/box-score"
        print(f"[HAR Capture] Loading Box Score: {game_box_url}")
        await page.goto(game_box_url, wait_until="domcontentloaded", timeout=60000)
        
        # Wait for the "Plays" tab to appear
        print("[HAR Capture] Waiting for Plays tab...")
        plays_tab = page.locator('a:has-text("Plays")').first
        await plays_tab.wait_for(state="visible", timeout=15000)
        
        # Click Plays
        print("[HAR Capture] Clicking Plays tab...")
        await plays_tab.click()
        
        # Wait for play data to actually render (look for "Top 1" or "Bottom 1")
        print("[HAR Capture] Waiting for plays data to render on screen...")
        try:
            # Wait until at least one inning header is visible
            await page.locator("text=/Top 1|Bottom 1|Inning/i").first.wait_for(state="visible", timeout=10000)
            print("[HAR Capture] Plays data is visible!")
        except Exception as e:
            print(f"[HAR Capture] Timeout waiting for plays text: {e}")
            
        # Give it a few more seconds just to finish writing to HAR
        await page.wait_for_timeout(3000)

        # Extract text to ensure data is actually on screen
        body_text = await page.locator("body").inner_text()
        print(f"[HAR Capture] First 150 chars: {body_text[:150].replace(chr(10), ' ')}")

        await context.close()
        await browser.close()
        print(f"[HAR Capture] Saved full HAR to {har_file}")

if __name__ == "__main__":
    asyncio.run(run())
