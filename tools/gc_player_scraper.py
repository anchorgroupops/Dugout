"""
gc_player_scraper.py — Per-player game-by-game stat scraper for The Sharks.

For each player on the roster (UUIDs from team.json or discovered from team stats page),
navigates to /players/{player_uuid} and extracts the game-by-game breakdown table.

Saves to data/sharks/players/{player_uuid}.json.

REQUIRES: pip install playwright && playwright install chromium
REQUIRES: GC_EMAIL, GC_PASSWORD, GC_TEAM_ID, GC_SEASON_SLUG in .env
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
PLAYERS_DIR = TEAM_DIR / "players"
LOG_DIR = ROOT_DIR / "logs"

GC_BASE = "https://web.gc.com"
GC_TEAM_ID = os.getenv("GC_TEAM_ID", "NuGgx6WvP7TO")
GC_SEASON_SLUG = os.getenv("GC_SEASON_SLUG", "2026-spring-sharks")


def _log(msg: str) -> None:
    print(f"[GCPlayer] {msg}", flush=True)


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _safe_val(val: str) -> Any:
    """Convert a cell value string to int/float/str as appropriate."""
    if val is None:
        return None
    val = val.strip()
    if val in ("", "-", "—", "N/A"):
        return None
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


class GCPlayerScraper:
    """Scrape per-player game-by-game stats from the GC player profile pages."""

    def __init__(
        self,
        team_id: str | None = None,
        season_slug: str | None = None,
        headless: bool = True,
    ):
        self.team_id = team_id or GC_TEAM_ID
        self.season_slug = season_slug or GC_SEASON_SLUG
        self.headless = headless
        PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        self._browser = None
        self._context = None
        self._page = None

    def login(self, playwright) -> Any:
        """Delegate login to GCFullScraper to avoid duplicating the logic."""
        from gc_full_scraper import GCFullScraper
        helper = GCFullScraper(
            team_id=self.team_id,
            season_slug=self.season_slug,
            headless=self.headless,
        )
        page = helper.login(playwright)
        self._browser = helper._browser
        self._context = helper._context
        self._page = page
        return page

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Roster / UUID discovery
    # ------------------------------------------------------------------
    def load_player_uuids(self) -> list[dict]:
        """
        Load player UUIDs from team.json (if present) and supplement with
        discovery from the team stats page.  Returns list of {uuid, name, number}.
        """
        players: dict[str, dict] = {}  # uuid -> {uuid, name, number}

        # 1. team.json
        team_file = TEAM_DIR / "team.json"
        if team_file.exists():
            try:
                with open(team_file) as f:
                    team_data = json.load(f)
                for p in team_data.get("roster", []):
                    uuid = _safe_str(p.get("player_uuid") or p.get("gc_player_id") or "")
                    if uuid:
                        name = _safe_str(
                            p.get("name") or f"{p.get('first','')} {p.get('last','')}".strip()
                        )
                        players[uuid] = {"uuid": uuid, "name": name, "number": _safe_str(p.get("number", ""))}
            except Exception as e:
                _log(f"[WARN] Could not read team.json: {e}")

        # 2. Player UUID discovery from team stats page (intercept API)
        if self._page:
            try:
                discovered = self._discover_uuids_from_stats_page()
                for p in discovered:
                    uuid = p.get("uuid", "")
                    if uuid and uuid not in players:
                        players[uuid] = p
            except Exception as e:
                _log(f"[WARN] UUID discovery from stats page failed: {e}")

        result = list(players.values())
        _log(f"Loaded {len(result)} player UUIDs")
        return result

    def _discover_uuids_from_stats_page(self) -> list[dict]:
        """Intercept API calls from the team stats page to collect player UUIDs."""
        stats_url = f"{GC_BASE}/teams/{self.team_id}/{self.season_slug}/stats"
        page = self._page
        discovered: list[dict] = []
        uuids_seen: set[str] = set()

        def handle_response(response) -> None:
            try:
                url = response.url
                if "api.team-manager.gc.com" not in url or response.status != 200:
                    return
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                body = response.json()
                # Look for player lists in API responses
                items = []
                if isinstance(body, list):
                    items = body
                elif isinstance(body, dict):
                    for key in ("players", "roster", "data", "items", "batting", "stats"):
                        if isinstance(body.get(key), list):
                            items = body[key]
                            break
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    uuid = _safe_str(
                        item.get("player_uuid") or item.get("uuid") or item.get("player_id") or ""
                    )
                    if uuid and uuid not in uuids_seen:
                        uuids_seen.add(uuid)
                        name = _safe_str(
                            item.get("player_name")
                            or item.get("name")
                            or f"{item.get('first','')}{item.get('last','')}".strip()
                        )
                        discovered.append(
                            {
                                "uuid": uuid,
                                "name": name,
                                "number": _safe_str(item.get("jersey_number") or item.get("number") or ""),
                            }
                        )
            except Exception:
                pass

        page.on("response", handle_response)
        try:
            page.goto(stats_url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)
        except Exception as e:
            _log(f"[WARN] Stats page navigation for UUID discovery: {e}")

        _log(f"Discovered {len(discovered)} UUIDs from stats page API intercept")
        return discovered

    # ------------------------------------------------------------------
    # Per-player scraping
    # ------------------------------------------------------------------
    def scrape_player(self, player_uuid: str, name: str = "", number: str = "") -> dict | None:
        """
        Navigate to the player profile page and extract game-by-game stats.
        Returns the player JSON dict or None on failure.
        """
        player_url = f"{GC_BASE}/teams/{self.team_id}/{self.season_slug}/players/{player_uuid}"
        _log(f"Scraping player {player_uuid} ({name or 'unknown'})")

        page = self._page
        try:
            page.goto(player_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
        except Exception as e:
            _log(f"  [WARN] Page load failed for {player_uuid}: {e}")
            return None

        # Try to extract game-by-game table — GC usually shows it on the player profile
        games_data = self._extract_game_by_game_table()

        # Also try to get season summary from page
        season_batting = self._extract_season_summary("batting")
        season_pitching = self._extract_season_summary("pitching")

        player_doc = {
            "player_uuid": player_uuid,
            "name": name,
            "number": number,
            "games": games_data,
            "season_batting": season_batting,
            "season_pitching": season_pitching,
            "captured_at": datetime.now(ET).isoformat(),
        }

        out_file = PLAYERS_DIR / f"{player_uuid}.json"
        try:
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(player_doc, f, indent=2, ensure_ascii=False)
            _log(f"  Saved: {out_file.name} ({len(games_data)} games)")
        except Exception as e:
            _log(f"  [ERROR] Could not save {out_file}: {e}")

        return player_doc

    def _extract_game_by_game_table(self) -> list[dict]:
        """Extract the game-by-game breakdown table from the current player profile page."""
        page = self._page
        try:
            js = """
            (() => {
                const tables = document.querySelectorAll('table, [role="table"]');
                if (!tables.length) return JSON.stringify([]);
                // Use first table (usually the game log)
                const table = tables[0];
                const thEls = table.querySelectorAll('thead th, [role="columnheader"]');
                const headers = Array.from(thEls).map(th => th.textContent.trim());
                const rows = [];
                table.querySelectorAll('tbody tr, [role="row"]').forEach(tr => {
                    const cells = tr.querySelectorAll('td, [role="cell"], [role="gridcell"]');
                    if (!cells.length) return;
                    const row = {};
                    cells.forEach((cell, i) => {
                        row[headers[i] || 'col' + i] = cell.textContent.trim();
                    });
                    if (Object.values(row).some(v => v && v.length > 0)) rows.push(row);
                });
                return JSON.stringify({headers, rows});
            })()
            """
            raw = page.evaluate(js)
            parsed = json.loads(raw) if raw else {}
        except Exception as e:
            _log(f"  [WARN] JS table extraction failed: {e}")
            return []

        headers = parsed.get("headers", [])
        raw_rows = parsed.get("rows", [])

        if not raw_rows:
            return []

        games: list[dict] = []
        for row in raw_rows:
            # Try to identify date and opponent from first few columns
            date_val = _safe_str(row.get("Date") or row.get("date") or row.get(headers[0] if headers else "") or "")
            opp_val = _safe_str(row.get("Opponent") or row.get("opponent") or row.get(headers[1] if len(headers) > 1 else "") or "")

            # Build stat dict from all columns
            batting: dict = {}
            pitching: dict = {}

            # Map known batting columns
            from gc_scraper import BATTING_STD_MAP, PITCHING_STD_MAP
            for gc_col, key in BATTING_STD_MAP.items():
                if gc_col in row:
                    batting[key] = _safe_val(row[gc_col])
            for gc_col, key in PITCHING_STD_MAP.items():
                if gc_col in row:
                    pitching[key] = _safe_val(row[gc_col])

            game_entry: dict = {
                "date": date_val,
                "opponent": opp_val,
            }
            if batting:
                game_entry["batting"] = batting
            if pitching:
                game_entry["pitching"] = pitching

            # Include raw row as fallback if no mapped cols found
            if not batting and not pitching:
                game_entry["raw"] = {k: _safe_val(v) for k, v in row.items()}

            games.append(game_entry)

        return games

    def _extract_season_summary(self, stat_type: str) -> dict:
        """Try to extract season-aggregate stats from the player profile sidebar."""
        page = self._page
        try:
            # GC player pages often have a summary card above the game log
            js = f"""
            (() => {{
                const els = document.querySelectorAll('[class*="stat"], [class*="Stat"], [data-stat]');
                const result = {{}};
                els.forEach(el => {{
                    const label = (el.getAttribute('data-stat') || el.getAttribute('aria-label') || '').toLowerCase();
                    const val = el.textContent.trim();
                    if (label && val) result[label] = val;
                }});
                return JSON.stringify(result);
            }})()
            """
            raw = page.evaluate(js)
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------
    def run_all_players(self, force: bool = False) -> dict:
        """Scrape all players. Returns summary dict."""
        players = self.load_player_uuids()

        summary = {
            "started_at": datetime.now(ET).isoformat(),
            "players_found": len(players),
            "players_scraped": 0,
            "players_skipped": 0,
            "players_failed": 0,
            "errors": [],
        }

        for p in players:
            uuid = p.get("uuid", "")
            if not uuid:
                continue

            out_file = PLAYERS_DIR / f"{uuid}.json"
            if not force and out_file.exists():
                _log(f"Skipping {uuid} (already scraped)")
                summary["players_skipped"] += 1
                continue

            try:
                result = self.scrape_player(uuid, p.get("name", ""), p.get("number", ""))
                if result:
                    summary["players_scraped"] += 1
                else:
                    summary["players_failed"] += 1
            except Exception as e:
                summary["players_failed"] += 1
                summary["errors"].append(f"{uuid}: {e}")
                _log(f"[ERROR] Player {uuid}: {e}")

        summary["completed_at"] = datetime.now(ET).isoformat()
        _log(
            f"Player scrape complete: {summary['players_scraped']} scraped, "
            f"{summary['players_skipped']} skipped, {summary['players_failed']} failed"
        )
        return summary


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="GC Player Scraper — per-player game logs")
    parser.add_argument("--force", action="store_true", help="Re-scrape already saved players")
    parser.add_argument("--headed", action="store_true", help="Run with visible browser")
    parser.add_argument("--player-uuid", help="Scrape a single specific player UUID")
    args = parser.parse_args()

    if sync_playwright is None:
        print("[GCPlayer] ERROR: playwright not installed.")
        sys.exit(1)

    headless = not args.headed
    scraper = GCPlayerScraper(headless=headless)

    with sync_playwright() as pw:
        scraper.login(pw)

        if args.player_uuid:
            result = scraper.scrape_player(args.player_uuid)
            if result:
                print(f"[GCPlayer] Saved player {args.player_uuid}: {len(result.get('games', []))} games")
            else:
                print(f"[GCPlayer] No data for {args.player_uuid}")
        else:
            summary = scraper.run_all_players(force=args.force)
            print(json.dumps(summary, indent=2))

        scraper.close()


if __name__ == "__main__":
    main()
