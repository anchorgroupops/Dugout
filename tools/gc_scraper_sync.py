"""
GameChanger Scraper for Softball (Sync Version - Robust)
Browser automation via Playwright to scrape stats from web.gc.com.
"""

import json
import os
import csv
import time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

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

    def login(self, playwright):
        print(f"[GC] Launching browser (sandboxed)...")
        self.browser = playwright.chromium.launch(
            headless=True, 
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        context = self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self.page = context.new_page()

        try:
            print(f"[GC] Navigating to {GC_LOGIN_URL}...")
            self.page.goto(GC_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            self.page.wait_for_timeout(5000)
            self.page.screenshot(path=str(TMP_DIR / "step1_landing.png"))

            print(f"[GC] Entering email: {self.email}...")
            self.page.fill('input[type="email"], input[name="email"]', self.email)
            self.page.click('button:has-text("Continue")')
            self.page.wait_for_timeout(5000)
            self.page.screenshot(path=str(TMP_DIR / "step2_password_field.png"))

            print("[GC] Entering password...")
            self.page.wait_for_selector('input[type="password"]', timeout=30000)
            self.page.fill('input[type="password"]', self.password)
            
            submit_btn = self.page.locator('button[type="submit"], button:has-text("Sign In"), button:has-text("Continue")').last
            submit_btn.click()

            print("[GC] Waiting for redirect...")
            self.page.wait_for_timeout(10000)
            self.page.screenshot(path=str(TMP_DIR / "step3_dashboard.png"))
            print(f"[GC] Logged in. Current URL: {self.page.url}")
            
            return self.page
        except Exception as e:
            print(f"[GC] Login failed: {e}")
            self.page.screenshot(path=str(TMP_DIR / "login_final_error.png"))
            raise

    def scrape_team_stats(self):
        print(f"[GC] Looking for team: {self.team_name}...")
        try:
            self.page.wait_for_timeout(5000)
            
            team_link = self.page.locator(f'text="{self.team_name}"').first
            if team_link.is_visible():
                print(f"[GC] Clicking team link...")
                team_link.click()
                self.page.wait_for_timeout(5000)
                self.page.screenshot(path=str(TMP_DIR / "step4_team_page.png"))
            else:
                print(f"[GC] Team link not visible.")
                return None
            
            stats_tab = self.page.locator('a:has-text("Stats"), text="Stats"').first
            if stats_tab.is_visible():
                stats_tab.click()
                self.page.wait_for_timeout(5000)
                self.page.screenshot(path=str(TMP_DIR / "step5_stats_page.png"))
            
            print("[GC] Attempting CSV export...")
            export_btn = self.page.locator('button:has-text("Export"), a:has-text("Export")').first
            if export_btn.is_visible():
                with self.page.expect_download() as download_info:
                    export_btn.click()
                download = download_info.value
                csv_path = TMP_DIR / "gc_stats_export.csv"
                TMP_DIR.mkdir(parents=True, exist_ok=True)
                download.save_as(str(csv_path))
                print(f"[GC] CSV saved to {csv_path}")
                return self.parse_csv(csv_path)
        except Exception as e:
            print(f"[GC] Error during scraping: {e}")
        return None

    def parse_csv(self, csv_path):
        print(f"[GC] Parsing CSV: {csv_path}")
        players = []
        with open(csv_path, "r", encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                p_name = row.get("Player", "") or row.get("Name", "")
                if not p_name or p_name == "Player": continue
                p_num = row.get("#", "0")
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
        
        team = {"team_name": self.team_name, "roster": players, "last_updated": datetime.now().isoformat()}
        SHARKS_DIR.mkdir(parents=True, exist_ok=True)
        with open(SHARKS_DIR / "team.json", "w") as f:
            json.dump(team, f, indent=2)
        print(f"[GC] Saved {len(players)} players.")
        return team

    def close(self):
        if self.browser:
            self.browser.close()

def run():
    scraper = GameChangerScraper()
    with sync_playwright() as pw:
        try:
            scraper.login(pw)
            scraper.scrape_team_stats()
        finally:
            scraper.close()

if __name__ == "__main__":
    run()
