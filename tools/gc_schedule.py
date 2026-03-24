import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from gc_scraper import GameChangerScraper

ET = ZoneInfo("America/New_York")

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except ImportError:
    sync_playwright = None

DATA_DIR = Path(__file__).parent.parent / "data"
SHARKS_DIR = DATA_DIR / "sharks"
TMP_DIR = Path(__file__).parent.parent / ".tmp"

class ScheduleScraper(GameChangerScraper):
    def scrape_schedule(self):
        """Scrapes past games, scrimmages, and future schedule from the DOM."""
        schedule_data = {
            "last_updated": datetime.now(ET).isoformat(),
            "games": []
        }
        
        page = None
        with sync_playwright() as pw:
            try:
                # Login uses the robust session persistence defined in gc_scraper.py
                page = self.login(pw)
                
                print("[GC_SCHEDULE] Navigating to The Sharks team page...")
                team_link = page.locator(f'text="{self.team_name}"').first
                if team_link:
                    team_link.click()
                    page.wait_for_timeout(3000)
                else:
                    print(f"[ERROR] Could not find team link for {self.team_name}. Check session or team name.")
                    return schedule_data
                
                print("[GC_SCHEDULE] Opening Schedule tab...")
                schedule_tab = page.locator('text="Schedule"').first
                if schedule_tab:
                    schedule_tab.click()
                    page.wait_for_timeout(5000) # give it time to load the list
                else:
                    print(f"[ERROR] Could not find Schedule tab.")
                    return schedule_data
                
                print("[GC_SCHEDULE] Extracting games...")
                schedule_container = page.locator('main').first
                text_content = schedule_container.inner_text() if schedule_container else ""
                
                schedule_data["raw_content"] = text_content
                
                print("[GC_SCHEDULE] Schedule data extracted. Saving to data/sharks/schedule.json")
                
            except PlaywrightTimeoutError as e:
                print(f"[ERROR] Timeout during schedule scrape: {e}")
                if page: self._take_error_snapshot(page, "schedule_timeout")
            except Exception as e:
                print(f"[ERROR] Unexpected error during schedule scrape: {e}")
                if page: self._take_error_snapshot(page, "schedule_error")
            finally:
                if self.browser:
                    self.browser.close()
                    
        SHARKS_DIR.mkdir(parents=True, exist_ok=True)
        with open(SHARKS_DIR / "schedule.json", "w") as f:
            json.dump(schedule_data, f, indent=2)
            
        return schedule_data

    def _take_error_snapshot(self, page, name_prefix):
        """Helper to capture state on failure for debugging."""
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
        try:
            filename = TMP_DIR / f"{name_prefix}_{timestamp}.png"
            page.screenshot(path=str(filename))
            print(f"[DEBUG] Saved error screenshot to {filename}")
        except Exception as snap_err:
            print(f"[DEBUG] Failed to take screenshot: {snap_err}")

if __name__ == "__main__":
    scraper = ScheduleScraper()
    scraper.scrape_schedule()
