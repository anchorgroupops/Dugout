"""
diag_game.py - Quick diagnostic: navigate to a game stats page and dump
the actual column headers found in any table, plus a screenshot.
"""
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = ROOT_DIR / "data"
AUTH_FILE = DATA_DIR / "auth.json"
GC_BASE = "https://web.gc.com"
GC_TEAM_ID = os.getenv("GC_TEAM_ID", "NuGgx6WvP7TO")
GC_SEASON_SLUG = os.getenv("GC_SEASON_SLUG", "2026-spring-sharks")

# The game ID to diagnose — try one that returned "SHRK/TBD"
GAME_ID = sys.argv[1] if len(sys.argv) > 1 else "7931431c-a877-4839-9c6c-c512a138db25"

def main():
    url = f"{GC_BASE}/teams/{GC_TEAM_ID}/{GC_SEASON_SLUG}/schedule/{GAME_ID}/game-stats"
    print(f"Navigating to: {url}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            storage_state=str(AUTH_FILE),
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        # Screenshot
        diag_dir = ROOT_DIR / "logs" / "diagnostics"
        diag_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(diag_dir / f"diag_game_{GAME_ID[:8]}.png"), full_page=True)
        print(f"Screenshot saved.")

        # Dump all tables headers
        table_info = page.evaluate("""
        (() => {
            const result = [];
            const tables = document.querySelectorAll('table, [role="table"], [role="grid"]');
            tables.forEach((t, i) => {
                const headers = Array.from(t.querySelectorAll('th, [role="columnheader"]')).map(h => h.textContent.trim());
                const rowCount = t.querySelectorAll('tbody tr, [role="row"]').length;
                const firstRows = [];
                t.querySelectorAll('tbody tr, [role="row"]').forEach((tr, ri) => {
                    if (ri >= 3) return;
                    const cells = Array.from(tr.querySelectorAll('td, [role="cell"], [role="gridcell"]'))
                                       .map(c => c.textContent.trim().substring(0, 30));
                    firstRows.push(cells);
                });
                result.push({table_index: i, headers, rowCount, firstRows});
            });
            return result;
        })()
        """)
        print(f"\\nTables found: {len(table_info)}")
        for t in table_info:
            print(f"  Table {t['table_index']}: {t['rowCount']} rows, headers={t['headers']}")
            for r in t['firstRows']:
                print(f"    row: {r}")

        # Dump all tab/button text
        tabs = page.evaluate("""
        (() => {
            const tabs = document.querySelectorAll('[role="tab"], [role="button"], button, a');
            return Array.from(tabs).map(t => t.textContent.trim()).filter(t => t.length > 0 && t.length < 50);
        })()
        """)
        print(f"\\nTabs/buttons found: {tabs[:30]}")

        # Page title and URL
        print(f"\\nPage URL: {page.url}")
        print(f"Page title: {page.title()}")

        # Full page text (first 2000 chars)
        body_text = page.evaluate("document.body.innerText")
        print(f"\\nPage body (first 2000 chars):\\n{body_text[:2000]}")

        browser.close()

if __name__ == "__main__":
    main()
