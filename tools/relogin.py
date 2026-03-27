import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"
AUTH_FILE = ROOT_DIR / "data" / "auth.json"

async def run():
    load_dotenv(ENV_FILE)
    email = os.environ.get("GC_EMAIL")
    password = os.environ.get("GC_PASSWORD")
    
    if not email or not password:
        print("Missing GC_EMAIL or GC_PASSWORD in .env")
        return

    print("Logging into GameChanger as", email)
    
    async with async_playwright() as p:
        # Run HEADED to avoid Cloudflare bot blocking
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        print("Navigating to login...")
        await page.goto("https://web.gc.com/login", wait_until="domcontentloaded", timeout=60000)
        
        try:
            await page.locator('input[type="email"]').wait_for(state="visible", timeout=20000)
            print("Login form visible. Entering credentials...")
            await page.fill('input[type="email"]', email)
            await page.fill('input[type="password"]', password)
            await page.click('button[type="submit"]')
        except Exception as e:
            print("Could not find login form, might be on Captcha: ", e)
            print("Waiting 15 seconds for user to potentially solve Captcha...")
            await page.wait_for_timeout(15000)
        
        print("Waiting for redirect to teams page...")
        try:
            await page.wait_for_url("**/teams**", timeout=30000)
            print("Redirected to teams page successfully.")
        except Exception as e:
            print("Did not detect redirect via URL. Checking if logged in...", e)
        
        await page.wait_for_timeout(5000)
        await context.storage_state(path=str(AUTH_FILE))
        print("Successfully saved new auth.json")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
