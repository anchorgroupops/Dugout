"""
GameChanger Scraper for Softball (Async Version - Multi-Step Login)
Browser automation via Playwright to scrape stats from web.gc.com.
"""

import json
import os
import csv
import asyncio
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

DATA_DIR = Path(__file__).parent.parent / "data"
SHARKS_DIR = DATA_DIR / "sharks"
TMP_DIR = Path(__file__).parent.parent / ".tmp"

GC_BASE_URL = "https://web.gc.com"
GC_LOGIN_URL = f"{GC_BASE_URL}/login"

class GameChangerScraper:
    def __init__(self):
        self.email = os.getenv("GC_EMAIL", "")
        self.password = os.getenv("GC_PASSWORD", "")
        self.team_name = os.getenv("TEAM_NAME", "The Sharks")
        self.browser = None
        self.page = None

    async def login(self, playwright):
        print(f"[GC] Launching browser...")
        self.browser = await playwright.chromium.launch(headless=True)
        context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self.page = await context.new_page()

        try:
            print(f"[GC] Navigating to {GC_LOGIN_URL}...")
            await self.page.goto(GC_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            await self.page.wait_for_timeout(5000)

            print(f"[GC] Entering email: {self.email}...")
            # The field in the screenshot is for email
            await self.page.fill('input[type="email"], input[name="email"]', self.email)
            await self.page.click('button:has-text("Continue")')

            print("[GC] Waiting for password field...")
            # Wait for password input to appear
            await self.page.wait_for_selector('input[type="password"]', timeout=30000)
            await self.page.fill('input[type="password"]', self.password)
            
            # Click the next button (might be "Sign In" or another "Continue")
            submit_btn = self.page.locator('button[type="submit"], button:has-text("Sign In"), button:has-text("Continue")').last
            await submit_btn.click()

            print("[GC] Waiting for dashboard redirect...")
            await self.page.wait_for_load_state("networkidle", timeout=60000)
            print(f"[GC] Logged in. Current URL: {self.page.url}")
            
            return self.page
        except Exception as e:
            print(f"[GC] Login failed: {e}")
            TMP_DIR.mkdir(parents=True, exist_ok=True)
            await self.page.screenshot(path=str(TMP_DIR / "login_error_step2.png"))
            print(f"[GC] Screenshot saved to {TMP_DIR / 'login_error_step2.png'}")
            raise

    async def scrape_team_stats(self):
        print(f"[GC] Looking for team: {self.team_name}...")
        try:
            # Dashboards sometimes have 'My Teams' or similar
            await self.page.wait_for_timeout(5000)
            
            # Use a broader search for the team name
            # Often it's in an <a> tag or a div with text
            team_link = self.page.locator(f'a:has-text("{self.team_name}")').first
            if not await team_link.is_visible():
                team_link = self.page.locator(f'text="{self.team_name}"').first
                
            if await team_link.is_visible():
                print(f"[GC] Found team link, clicking...")
                await team_link.click()
                await self.page.wait_for_load_state("networkidle", timeout=60000)
            else:
                print(f"[GC] Team '{self.team_name}' link not found on dashboard.")
                await self.page.screenshot(path=str(TMP_DIR / "dashboard_view.png"))
                return None
            
            # Navigate to Stats
            print("[GC] Navigating to Stats tab...")
            stats_tab = self.page.locator('a:has-text("Stats"), button:has-text("Stats"), text="Stats"').first
            if await stats_tab.is_visible():
                await stats_tab.click()
                await self.page.wait_for_load_state("networkidle", timeout=60000)
            
            # Try CSV export
            print("[GC] Attempting CSV export...")
            export_btn = self.page.locator('button:has-text("Export"), a:has-text("Export")').first
            if await export_btn.is_visible():
                async with self.page.expect_download() as download_info:
                    await export_btn.click()
                download = await download_info.value
                csv_path = TMP_DIR / "gc_stats_export.csv"
                TMP_DIR.mkdir(parents=True, exist_ok=True)
                await download.save_as(str(csv_path))
                print(f"[GC] CSV saved to {csv_path}")
                return await self.parse_csv(csv_path)
            else:
                print("[GC] Export button not found.")
                await self.page.screenshot(path=str(TMP_DIR / "stats_page_view.png"))
        except Exception as e:
            print(f"[GC] Error during scraping: {e}")
        return None

    async def parse_csv(self, csv_path):
        print(f"[GC] Parsing CSV: {csv_path}")
        players = []
        with open(csv_path, "r", encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Basic mapping from standard GC season export CSV
                p_name = row.get("Player", "") or row.get("Name", "Unknown")
                p_num = row.get("#", "") or row.get("Number", "0")
                if not p_name or p_name == "Player": continue # Header row skip or empty
                
                players.append({
                    "id": f"p_{p_num}_{p_name.replace(' ', '_').lower()}",
                    "name": p_name,
                    "number": int(p_num) if p_num.isdigit() else 0,
                    "stats": {
                        "hitting": {
                            "ab": int(row.get("AB", 0) or 0),
                            "h": int(row.get("H", 0) or 0),
                            "bb": int(row.get("BB", 0) or 0),
                            "k": int(row.get("K", row.get("SO", 0)) or 0),
                            "rbi": int(row.get("RBI", 0) or 0),
                            "runs": int(row.get("R", 0) or 0),
                            "sb": int(row.get("SB", 0) or 0)
                        }
                    }
                })
        
        team = {
            "team_name": self.team_name,
            "league": "PCLL",
            "season": "Spring 2026",
            "is_own_team": True,
            "roster": players,
            "last_updated": datetime.now().isoformat()
        }
        
        SHARKS_DIR.mkdir(parents=True, exist_ok=True)
        with open(SHARKS_DIR / "team.json", "w") as f:
            json.dump(team, f, indent=2)
        print(f"[GC] Successfully parsed {len(players)} players into team.json")
        return team

    async def close(self):
        if self.browser:
            await self.browser.close()

async def main():
    scraper = GameChangerScraper()
    async with async_playwright() as pw:
        try:
            await scraper.login(pw)
            await scraper.scrape_team_stats()
        finally:
            await scraper.close()

if __name__ == "__main__":
    asyncio.run(main())
