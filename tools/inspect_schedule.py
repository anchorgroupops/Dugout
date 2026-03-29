import json
from pathlib import Path
from gc_scraper import GameChangerScraper

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

TMP_DIR = Path(__file__).parent.parent / ".tmp"

def inspect_schedule_api():
    scraper = GameChangerScraper()
    captured_data = []

    with sync_playwright() as pw:
        page = scraper.login(pw)
        
        # We need to go to the team page, then click Schedule.
        # But wait, without knowing the direct URL, we click.
        # Navigate to the configured team page
        
        def handle_response(response):
            if "api" in response.url and response.status == 200:
                try:
                    data = response.json()
                    captured_data.append({"url": response.url, "data": data})
                except Exception:
                    pass
        
        page.on("response", handle_response)
        
        try:
            team_link = page.locator(f'text="{scraper.team_name}"').first
            if team_link:
                team_link.click()
                page.wait_for_timeout(3000)
                
            schedule_tab = page.locator('text="Schedule"').first
            if schedule_tab:
                schedule_tab.click()
                page.wait_for_timeout(3000)
                
            # scroll to trigger lazy loading if any
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(3000)
            
        except Exception as e:
            print(f"Navigation error: {e}")
            
        print("[INSPECTOR] Pausing for 60 seconds. Please manually navigate to the Schedule tab in the visible browser if it hasn't loaded.")
        print("[INSPECTOR] Any API requests made will be captured.")
        page.wait_for_timeout(60000)
            
        scraper.close()
        
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    with open(TMP_DIR / "gc_schedule_api_capture.json", "w") as f:
        json.dump(captured_data, f, indent=2, default=str)
    print(f"Captured {len(captured_data)} API responses to .tmp/gc_schedule_api_capture.json")

if __name__ == "__main__":
    inspect_schedule_api()
