import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Add parent dir to path so we can import tools
sys.path.append(str(Path(__file__).parent.parent))

from tools.gc_scraper import GameChangerScraper

def test_login():
    """Smoke test for GC Scraper authentication and diagnostics."""
    load_dotenv()
    
    print("--- 🧪 GC Scraper Smoke Test ---")
    
    scraper = GameChangerScraper()
    
    with sync_playwright() as p:
        try:
            # Run login flow
            scraper.login(p)
            print("✅ Login successful!")
            
            # Try to click a tab to verify selector resilience
            print("Testing tab click (Batting)...")
            success = scraper._click_tab("Batting")
            if success:
                print("✅ Tab click successful!")
            else:
                print("❌ Tab click failed.")
            
            # CHAOS TEST: Try to click a tab with WRONG role
            print("\n--- 🌪️ Chaos Test: Clicking 'Pitching' with wrong role ---")
            # We bypass the normal _click_tab to test the healer directly
            healed_btn = scraper._heal_locator("Pitching", role="checkbox") # Wrong role!
            if healed_btn:
                print("✅ HEALED: Found 'Pitching' even with wrong role 'checkbox'!")
                healed_btn.click()
            else:
                print("❌ HEALED: Could not find 'Pitching' with wrong role.")

            print("\n--- 🌪️ Chaos Test: Clicking with fuzzy text ---")
            healed_btn = scraper._heal_locator("Field", role="tab") # Partial text "Fielding"
            if healed_btn:
                print("✅ HEALED: Found 'Fielding' using fuzzy text 'Field'!")
            else:
                print("❌ HEALED: Could not find 'Fielding' via 'Field'.")
                
            # Wait a moment to visually confirm if needed (run with HEADLESS=false)
            # import time; time.sleep(5)
            
        except Exception as e:
            print(f"❌ Test failed: {e}")
            # The scraper should have captured diagnostics automatically in logs/diagnostics/
        finally:
            scraper.close()
            print("--- Test Complete ---")

if __name__ == "__main__":
    test_login()
