"""Dump the raw DOM structure around the stats section to find the right selectors."""
import os, sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")
AUTH_FILE = ROOT_DIR / "data" / "auth.json"
GC_BASE = "https://web.gc.com"
TEAM_ID = os.getenv("GC_TEAM_ID", "NuGgx6WvP7TO")
SEASON = os.getenv("GC_SEASON_SLUG", "2026-spring-sharks")
GAME_ID = sys.argv[1] if len(sys.argv) > 1 else "7931431c-a877-4839-9c6c-c512a138db25"

URL = f"{GC_BASE}/teams/{TEAM_ID}/{SEASON}/schedule/{GAME_ID}/game-stats"

def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(storage_state=str(AUTH_FILE))
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        # 1. Dump inner HTML of the stats grid area (first 8000 chars)
        html = page.evaluate("""
        (() => {
            // Try to find the stats container — look for known player name
            const allEls = document.querySelectorAll('*');
            for (const el of allEls) {
                if (el.textContent.includes('Ruby VanDeusen') && el.children.length > 2) {
                    return el.outerHTML.substring(0, 8000);
                }
            }
            // Fallback: dump main content area
            const main = document.querySelector('main') || document.body;
            return main.outerHTML.substring(0, 8000);
        })()
        """)
        print("=== STATS CONTAINER HTML (first 8000 chars) ===")
        print(html)

        # 2. Find all elements that look like a stats row (has player name)
        rows_info = page.evaluate("""
        (() => {
            const results = [];
            const allEls = Array.from(document.querySelectorAll('*'));
            for (const el of allEls) {
                const txt = el.textContent.trim();
                if (txt.startsWith('Ruby VanDeusen') || txt.startsWith('Emma Williams')) {
                    results.push({
                        tag: el.tagName,
                        role: el.getAttribute('role'),
                        class: el.className,
                        text: txt.substring(0, 80),
                        parentTag: el.parentElement?.tagName,
                        parentRole: el.parentElement?.getAttribute('role'),
                        parentClass: el.parentElement?.className,
                        siblingCount: el.parentElement?.children.length
                    });
                    if (results.length >= 3) break;
                }
            }
            return results;
        })()
        """)
        print("\n=== PLAYER ROW ELEMENTS ===")
        for r in rows_info:
            print(r)

        browser.close()

if __name__ == "__main__":
    main()
