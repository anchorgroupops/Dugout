import asyncio
from playwright.async_api import async_playwright
import json
import os
from pathlib import Path

AUTH_FILE = Path("h:/Repos/Personal/Softball/data/auth.json")

async def check_plays():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=str(AUTH_FILE))
        page = await context.new_page()

        # Go to team schedule page
        print("Navigating to Schedule...")
        await page.goto("https://web.gc.com/teams/NuGgx6WvP7TO/2026-spring-sharks/schedule", timeout=60000)
        await page.wait_for_timeout(3000)
        
        # Look for a completed game (status like Final or score)
        print("Looking for a completed game...")
        # Usually completed games have a link to the game page.
        game_links = await page.locator("a[href*='/games/']").all()
        if not game_links:
            print("No games found.")
            await browser.close()
            return
            
        first_game_url = await game_links[0].get_attribute("href")
        print(f"Navigating to game: {first_game_url}")
        
        await page.goto(f"https://web.gc.com{first_game_url}")
        await page.wait_for_timeout(3000)
        
        # Check tabs on the game page (Box Score, Plays, etc.)
        tabs = await page.locator("div[role='tablist'] button, div[role='tablist'] a").all_inner_texts()
        print(f"Tabs available: {tabs}")
        
        # Dump some body text
        content = await page.content()
        if "Plays" in content or "Pitch" in content or "pitch-by-pitch" in content.lower():
            print("FOUND evidence of Plays/Pitch data in HTML!")
            
            # Try to click Plays tab if it exists
            try:
                await page.locator("text='Plays'").click(timeout=2000)
                await page.wait_for_timeout(2000)
                plays_html = await page.locator("body").inner_text()
                print("Plays tab content snippet:")
                print(plays_html[:1000])
            except:
                pass
        else:
            print("No obvious Plays/Pitch data found on the web game page.")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(check_plays())
