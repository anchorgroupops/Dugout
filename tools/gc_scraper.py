"""
GameChanger Scraper for Softball
Browser automation via Playwright to scrape stats from web.gc.com.
Falls back to CSV parsing if direct scraping is blocked.

REQUIRES: pip install playwright && playwright install chromium
REQUIRES: GC_EMAIL and GC_PASSWORD in .env
"""

import json
import os
import csv
import io
from pathlib import Path
from datetime import datetime

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DATA_DIR = Path(__file__).parent.parent / "data"
SHARKS_DIR = DATA_DIR / "sharks"
OPPONENTS_DIR = DATA_DIR / "opponents"
TMP_DIR = Path(__file__).parent.parent / ".tmp"

GC_BASE_URL = "https://web.gc.com"
GC_LOGIN_URL = f"{GC_BASE_URL}/login"


class GameChangerScraper:
    """Scrape softball statistics from GameChanger (web.gc.com)."""

    def __init__(self):
        self.email = os.getenv("GC_EMAIL", "")
        self.password = os.getenv("GC_PASSWORD", "")
        self.team_name = os.getenv("TEAM_NAME", "The Sharks")
        self.browser = None
        self.page = None

    def _validate_credentials(self):
        """Ensure GC credentials are set."""
        if not self.email or not self.password:
            raise ValueError(
                "[GC] Missing credentials. Set GC_EMAIL and GC_PASSWORD in .env"
            )

    def login(self, playwright):
        """Log in to GameChanger via browser automation."""
        self._validate_credentials()

        self.browser = playwright.chromium.launch(headless=True)
        context = self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        self.page = context.new_page()

        print(f"[GC] Navigating to {GC_LOGIN_URL}...")
        self.page.goto(GC_LOGIN_URL, wait_until="networkidle", timeout=60000)

        # Fill login form
        print("[GC] Entering credentials...")
        self.page.fill('input[name="email"], input[type="email"]', self.email)
        self.page.fill('input[name="password"], input[type="password"]', self.password)
        self.page.click('button[type="submit"]')

        # Wait for dashboard to load
        self.page.wait_for_load_state("networkidle", timeout=60000)
        print(f"[GC] Logged in. Current URL: {self.page.url}")

        return self.page

    def scrape_team_stats(self) -> dict | None:
        """
        Scrape season statistics for the team.
        Returns structured data matching our Player/Team schema.
        """
        if not self.page:
            raise RuntimeError("[GC] Not logged in. Call login() first.")

        print(f"[GC] Looking for team: {self.team_name}...")

        # Navigate to team page
        # GC structure: After login, teams are listed on the dashboard
        # We need to click into the specific team, then go to Stats
        try:
            # Try to find team link on dashboard
            team_link = self.page.locator(f'text="{self.team_name}"').first
            if team_link:
                team_link.click()
                self.page.wait_for_load_state("networkidle", timeout=60000)
                print(f"[GC] Navigated to team page: {self.page.url}")
        except Exception as e:
            print(f"[GC] Could not find team link: {e}")
            print("[GC] Try navigating manually to your team page first.")
            return None

        # Try to find and click Stats tab
        try:
            stats_tab = self.page.locator('text="Stats"').first
            if stats_tab:
                stats_tab.click()
                self.page.wait_for_load_state("networkidle", timeout=60000)
        except Exception as e:
            print(f"[GC] Could not navigate to Stats: {e}")

        # Attempt to intercept API responses for structured data
        # GC loads stats via internal API calls — we can capture these
        stats_data = self._try_intercept_api()

        if not stats_data:
            # Fallback: try CSV export
            stats_data = self._try_csv_export()

        return stats_data

    def _try_intercept_api(self) -> dict | None:
        """
        Try to intercept internal GC API calls for structured JSON data.
        GC's frontend makes XHR requests to internal APIs that return JSON.
        """
        print("[GC] Attempting to intercept API responses...")
        captured_data = []

        def handle_response(response):
            if "api" in response.url and response.status == 200:
                try:
                    data = response.json()
                    if isinstance(data, dict) and ("stats" in str(data).lower() or "players" in str(data).lower()):
                        captured_data.append({"url": response.url, "data": data})
                except Exception:
                    pass

        self.page.on("response", handle_response)

        # Reload the stats page to trigger API calls
        self.page.reload()
        self.page.wait_for_load_state("networkidle", timeout=10000)

        if captured_data:
            print(f"[GC] Captured {len(captured_data)} API responses")
            # Save raw captured data
            TMP_DIR.mkdir(parents=True, exist_ok=True)
            with open(TMP_DIR / "gc_api_capture.json", "w") as f:
                json.dump(captured_data, f, indent=2, default=str)
            return self._parse_api_data(captured_data)

        print("[GC] No API data captured. Trying CSV export...")
        return None

    def _try_csv_export(self) -> dict | None:
        """
        Try to use GC's built-in CSV export feature.
        Staff accounts can export from web.gc.com → Team → Stats → Export.
        """
        print("[GC] Attempting CSV export...")
        try:
            export_btn = self.page.locator('text="Export"').first
            if export_btn:
                # Set up download handler
                with self.page.expect_download() as download_info:
                    export_btn.click()
                download = download_info.value
                csv_path = TMP_DIR / "gc_stats_export.csv"
                TMP_DIR.mkdir(parents=True, exist_ok=True)
                download.save_as(str(csv_path))
                print(f"[GC] CSV saved to {csv_path}")
                return self._parse_csv(csv_path)
        except Exception as e:
            print(f"[GC] CSV export failed: {e}")

        return None

    def _parse_api_data(self, captured_data: list) -> dict | None:
        """Parse captured API data into our schema format."""
        # This will need to be adapted based on actual GC API response structure
        # For now, return raw data for manual inspection
        print("[GC] API data captured. Manual parsing may be needed.")
        print("[GC] Check .tmp/gc_api_capture.json for raw data structure.")
        return {"raw_api": captured_data}

    def _parse_csv(self, csv_path: Path) -> dict | None:
        """Parse GC CSV export into our schema format."""
        print(f"[GC] Parsing CSV: {csv_path}")
        players = []

        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                player = {
                    "id": row.get("#", row.get("Number", "")),
                    "name": row.get("Player", row.get("Name", "Unknown")),
                    "number": int(row.get("#", row.get("Number", 0)) or 0),
                    "position_primary": row.get("Pos", row.get("Position", "")),
                    "positions_secondary": [],
                    "stats": {
                        "hitting": {
                            "ab": int(row.get("AB", 0) or 0),
                            "h": int(row.get("H", 0) or 0),
                            "bb": int(row.get("BB", 0) or 0),
                            "k": int(row.get("K", row.get("SO", 0)) or 0),
                            "hbp": int(row.get("HBP", 0) or 0),
                            "rbi": int(row.get("RBI", 0) or 0),
                            "runs": int(row.get("R", 0) or 0),
                            "doubles": int(row.get("2B", 0) or 0),
                            "triples": int(row.get("3B", 0) or 0),
                            "hr": int(row.get("HR", 0) or 0),
                            "sb": int(row.get("SB", 0) or 0),
                            "cs": int(row.get("CS", 0) or 0),
                        },
                        "pitching": {
                            "ip": float(row.get("IP", 0) or 0),
                            "er": int(row.get("ER", 0) or 0),
                            "k": int(row.get("PK", row.get("Pitching K", 0)) or 0),
                            "bb": int(row.get("PBB", row.get("Pitching BB", 0)) or 0),
                            "h": int(row.get("PH", row.get("Pitching H", 0)) or 0),
                            "w": int(row.get("W", 0) or 0),
                            "l": int(row.get("L", 0) or 0),
                        },
                        "fielding": {
                            "po": int(row.get("PO", 0) or 0),
                            "a": int(row.get("A", 0) or 0),
                            "e": int(row.get("E", 0) or 0),
                        },
                    },
                }
                players.append(player)

        team = {
            "team_name": self.team_name,
            "league": "PCLL",
            "division": os.getenv("DIVISION", "Majors"),
            "season": "Spring 2026",
            "is_own_team": True,
            "roster": players,
            "record": {"w": 0, "l": 0, "t": 0},
            "games": [],
            "last_updated": datetime.now().isoformat(),
        }

        # Save to data directory
        SHARKS_DIR.mkdir(parents=True, exist_ok=True)
        output = SHARKS_DIR / "team.json"
        with open(output, "w") as f:
            json.dump(team, f, indent=2)
        print(f"[GC] Team data saved to {output} ({len(players)} players)")

        return team

    def scrape_schedule(self) -> list[dict] | None:
        """Scrape game schedule from GC."""
        if not self.page:
            raise RuntimeError("[GC] Not logged in. Call login() first.")

        print("[GC] Scraping schedule...")
        try:
            schedule_tab = self.page.locator('text="Schedule"').first
            if schedule_tab:
                schedule_tab.click()
                self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            print(f"[GC] Could not navigate to Schedule: {e}")
            return None

        # TODO: Parse schedule elements from page
        # This will need adaptation based on actual GC page structure
        print("[GC] Schedule scraping requires manual structure inspection.")
        return None

    def scrape_opponent(self, opponent_url: str) -> dict | None:
        """Scrape stats from an opponent's public team page."""
        if not self.page:
            raise RuntimeError("[GC] Not logged in. Call login() first.")

        print(f"[GC] Scraping opponent from {opponent_url}...")
        self.page.goto(opponent_url, wait_until="networkidle")

        # TODO: Parse opponent stats from public page
        # Public pages have limited data compared to staff view
        print("[GC] Opponent scraping requires manual structure inspection.")
        return None

    def close(self):
        """Close the browser."""
        if self.browser:
            self.browser.close()
            print("[GC] Browser closed.")


def run():
    """Main entry point for the GC scraper."""
    if sync_playwright is None:
        print("[GC] ERROR: Playwright not installed.")
        print("[GC] Run: pip install playwright && playwright install chromium")
        return

    scraper = GameChangerScraper()

    with sync_playwright() as pw:
        try:
            scraper.login(pw)
            team = scraper.scrape_team_stats()
            if team:
                print(f"[GC] Successfully scraped {len(team.get('roster', []))} players")
            schedule = scraper.scrape_schedule()
        except Exception as e:
            print(f"[GC] Error: {e}")
        finally:
            scraper.close()


if __name__ == "__main__":
    run()
