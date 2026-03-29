"""
gc_csv_auto.py — Automated CSV export downloader for GameChanger stats.

Logs into GC, navigates to the stats page, clicks the CSV export button,
waits for the download, saves it, and then automatically runs gc_csv_ingest.py.

REQUIRES: pip install playwright && playwright install chromium
REQUIRES: GC_EMAIL, GC_PASSWORD, GC_TEAM_ID, GC_SEASON_SLUG in .env
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None  # type: ignore

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = ROOT_DIR / "data"
TEAM_DIR = DATA_DIR / os.getenv("TEAM_SLUG", "sharks")
LOG_DIR = ROOT_DIR / "logs"

GC_BASE = "https://web.gc.com"
GC_TEAM_ID = os.getenv("GC_TEAM_ID", "NuGgx6WvP7TO")
GC_SEASON_SLUG = os.getenv("GC_SEASON_SLUG", "2026-spring-sharks")


def _log(msg: str) -> None:
    print(f"[GCCsvAuto] {msg}", flush=True)


def download_season_csv(page: Any, output_dir: Path) -> Path | None:
    """
    Navigate to the stats page and click the CSV export/download button.
    Waits for the browser download and saves to output_dir.
    Returns the saved Path or None on failure.
    """
    stats_url = f"{GC_BASE}/teams/{GC_TEAM_ID}/{GC_SEASON_SLUG}/stats"
    _log(f"Navigating to stats page: {stats_url}")

    try:
        page.goto(stats_url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)
    except Exception as e:
        _log(f"[WARN] Stats page load: {e}")
        try:
            page.goto(stats_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
        except Exception as e2:
            _log(f"[ERROR] Cannot load stats page: {e2}")
            return None

    # Dismiss popups
    try:
        maybe_later = page.locator('button:has-text("Maybe later")').first
        if maybe_later.count() > 0:
            maybe_later.click()
            page.wait_for_timeout(500)
    except Exception:
        pass

    # Locate the export/download button using multiple strategies
    export_btn = None
    strategies = [
        lambda: page.get_by_role("button", name=re.compile(r"export|download|csv", re.I)).first,
        lambda: page.locator("[data-testid*='export'], [aria-label*='export'], [title*='export']").first,
        lambda: page.locator("[data-testid*='download'], [aria-label*='download'], [title*='download']").first,
        lambda: page.locator("button, a").filter(has_text=re.compile(r"export|download|csv", re.I)).first,
        lambda: page.locator("[class*='export'], [class*='Export'], [class*='download'], [class*='Download']").first,
    ]

    for strategy_fn in strategies:
        try:
            loc = strategy_fn()
            if loc.count() > 0 and loc.is_visible():
                export_btn = loc
                _log(f"Found export button via strategy")
                break
        except Exception:
            continue

    if export_btn is None:
        _log("[ERROR] Could not find CSV export button. Taking diagnostic screenshot.")
        try:
            diag_dir = LOG_DIR / "diagnostics"
            diag_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
            page.screenshot(path=str(diag_dir / f"gccsvauto_no_btn_{ts}.png"), full_page=True)
        except Exception:
            pass
        return None

    # Trigger download
    dest = output_dir / f"season_stats_auto_{datetime.now(ET).strftime('%Y%m%d')}.csv"
    try:
        with page.expect_download(timeout=30000) as dl_info:
            export_btn.click()
        download = dl_info.value
        download.save_as(str(dest))
        _log(f"CSV downloaded to: {dest.name}")
        return dest
    except Exception as e:
        _log(f"[ERROR] Download failed: {e}")
        # Check if a dropdown appeared — sometimes GC shows a submenu
        try:
            csv_option = page.locator("li, [role='menuitem'], [role='option']").filter(
                has_text=re.compile("csv", re.I)
            ).first
            if csv_option.count() > 0 and csv_option.is_visible():
                _log("Found CSV option in submenu, clicking...")
                with page.expect_download(timeout=30000) as dl_info2:
                    csv_option.click()
                download = dl_info2.value
                download.save_as(str(dest))
                _log(f"CSV downloaded via submenu to: {dest.name}")
                return dest
        except Exception as e2:
            _log(f"[ERROR] Submenu CSV download also failed: {e2}")
        return None


def run_csv_ingest(csv_path: Path) -> bool:
    """Run gc_csv_ingest.py on the downloaded CSV file."""
    ingest_script = Path(__file__).parent / "gc_csv_ingest.py"
    if not ingest_script.exists():
        _log(f"[WARN] gc_csv_ingest.py not found at {ingest_script}, skipping ingest")
        return False

    _log(f"Running gc_csv_ingest.py on {csv_path.name}...")
    try:
        result = subprocess.run(
            [sys.executable, str(ingest_script), str(csv_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            _log("CSV ingest completed successfully.")
            if result.stdout:
                for line in result.stdout.strip().splitlines()[-10:]:
                    _log(f"  [ingest] {line}")
            return True
        else:
            _log(f"[ERROR] CSV ingest failed (exit {result.returncode}):")
            if result.stderr:
                for line in result.stderr.strip().splitlines()[-10:]:
                    _log(f"  [ingest] {line}")
            return False
    except subprocess.TimeoutExpired:
        _log("[ERROR] CSV ingest timed out after 120s")
        return False
    except Exception as e:
        _log(f"[ERROR] CSV ingest subprocess error: {e}")
        return False


def run_auto_csv(
    headless: bool = True,
    skip_ingest: bool = False,
    output_dir: Path | None = None,
) -> dict:
    """
    Full automated CSV download and ingest flow.
    Returns a summary dict.
    """
    if sync_playwright is None:
        return {"error": "playwright not installed", "success": False}

    out_dir = output_dir or TEAM_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: dict = {
        "started_at": datetime.now(ET).isoformat(),
        "csv_downloaded": False,
        "csv_path": None,
        "ingest_run": False,
        "ingest_success": False,
        "success": False,
        "errors": [],
    }

    with sync_playwright() as pw:
        # Use GCFullScraper's login helper
        from gc_full_scraper import GCFullScraper
        helper = GCFullScraper(headless=headless)
        try:
            page = helper.login(pw)
        except Exception as e:
            summary["errors"].append(f"Login failed: {e}")
            _log(f"[ERROR] Login failed: {e}")
            return summary

        csv_path = download_season_csv(page, out_dir)

        if csv_path and csv_path.exists():
            summary["csv_downloaded"] = True
            summary["csv_path"] = str(csv_path)
            _log(f"CSV saved: {csv_path}")

            if not skip_ingest:
                ok = run_csv_ingest(csv_path)
                summary["ingest_run"] = True
                summary["ingest_success"] = ok
            summary["success"] = True
        else:
            summary["errors"].append("CSV download returned no file")
            _log("[ERROR] CSV download failed")

        helper.close()

    summary["completed_at"] = datetime.now(ET).isoformat()
    return summary


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="GC CSV Auto — download season stats CSV from GC")
    parser.add_argument("--headed", action="store_true", help="Run with visible browser")
    parser.add_argument("--skip-ingest", action="store_true", help="Download CSV but don't run ingest")
    parser.add_argument("--output-dir", help="Directory to save the CSV (default: data/sharks/)")
    args = parser.parse_args()

    if sync_playwright is None:
        print("[GCCsvAuto] ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else None
    result = run_auto_csv(
        headless=not args.headed,
        skip_ingest=args.skip_ingest,
        output_dir=output_dir,
    )
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
