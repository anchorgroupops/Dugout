"""Dump AG Grid col-ids and sample row from GC game stats page."""
import json, os
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
AUTH = ROOT / "data" / "auth.json"
GC_TEAM = os.getenv("GC_TEAM_ID", "NuGgx6WvP7TO")
GC_SEASON = os.getenv("GC_SEASON_SLUG", "2026-spring-sharks")
GAME = "7931431c-a877-4839-9c6c-c512a138db25"
URL = f"https://web.gc.com/teams/{GC_TEAM}/{GC_SEASON}/schedule/{GAME}/game-stats"

with sync_playwright() as pw:
    br = pw.chromium.launch(headless=True)
    ctx = br.new_context(storage_state=str(AUTH))
    p = ctx.new_page()
    p.goto(URL, wait_until="networkidle", timeout=30000)
    p.wait_for_timeout(3000)

    result = p.evaluate("""
    (() => {
        const grid = document.querySelector('[role="treegrid"]');
        if (!grid) return {headers:[], sample_row:{}};
        const headers = [];
        grid.querySelectorAll('[role="columnheader"]').forEach(h => {
            headers.push({col_id: h.getAttribute("col-id"), label: h.textContent.trim()});
        });
        const sample = {};
        const rows = grid.querySelectorAll('[role="row"][aria-rowindex]');
        rows.forEach(row => {
            const idx = parseInt(row.getAttribute('aria-rowindex'));
            if (idx === 2) {
                row.querySelectorAll('[role="gridcell"]').forEach(c => {
                    const cid = c.getAttribute("col-id");
                    sample[cid] = c.textContent.trim();
                });
            }
        });
        return {headers, sample_row: sample};
    })()
    """)
    out = json.dumps(result, ensure_ascii=True, indent=2)
    print(out)
    br.close()
