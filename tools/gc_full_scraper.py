"""
gc_full_scraper.py — Comprehensive GameChanger stats scraper for The Sharks.

Strategy: Navigate the GC React SPA, click through all stat tabs (Batting/Pitching/Fielding
with Standard/Advanced/Breakdown/Catching/Innings sub-tabs), and extract every stats table
for both teams on each game-stats page.

Also scrapes the season-level team stats page and saves to data/sharks/team_web.json.

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
    from playwright.sync_api import sync_playwright, Page
except ImportError:
    sync_playwright = None  # type: ignore
    Page = None  # type: ignore

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = ROOT_DIR / "data"
SHARKS_DIR = DATA_DIR / "sharks"
LOG_DIR = ROOT_DIR / "logs"

GC_BASE = "https://web.gc.com"
GC_API_BASE = "https://api.team-manager.gc.com"

GC_TEAM_ID = os.getenv("GC_TEAM_ID", "NuGgx6WvP7TO")
GC_SEASON_SLUG = os.getenv("GC_SEASON_SLUG", "2026-spring-sharks")
GC_EMAIL = os.getenv("GC_EMAIL", "")
GC_PASSWORD = os.getenv("GC_PASSWORD", "")
GC_HEADLESS = os.getenv("GC_HEADLESS", "true").lower() != "false"

# Re-use column maps from gc_scraper to stay DRY
from gc_scraper import (
    BATTING_STD_MAP,
    BATTING_ADV_MAP,
    PITCHING_STD_MAP,
    PITCHING_ADV_MAP,
    PITCHING_BRK_MAP,
    FIELDING_STD_MAP,
    FIELDING_CATCH_MAP,
    FIELDING_INN_MAP,
    STAT_VIEWS,
    _safe_val,
)

SOURCE_TAG = "gc_full_scraper_v2"

# Tab order: (major_tab_name, sub_tab_name, col_map, json_key)
GAME_STAT_VIEWS = [
    ("Batting",  "Standard",       BATTING_STD_MAP,    "batting"),
    ("Batting",  "Advanced",       BATTING_ADV_MAP,    "batting_advanced"),
    ("Pitching", "Standard",       PITCHING_STD_MAP,   "pitching"),
    ("Pitching", "Advanced",       PITCHING_ADV_MAP,   "pitching_advanced"),
    ("Pitching", "Breakdown",      PITCHING_BRK_MAP,   "pitching_breakdown"),
    ("Fielding", "Standard",       FIELDING_STD_MAP,   "fielding"),
    ("Fielding", "Catching",       FIELDING_CATCH_MAP, "catching"),
    ("Fielding", "Innings Played", FIELDING_INN_MAP,   "innings_played"),
]


def _log(msg: str) -> None:
    print(f"[GCFull] {msg}", flush=True)


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _opponent_slug(name: str) -> str:
    """Convert an opponent name to a safe filename slug."""
    s = re.sub(r"[^a-z0-9]+", "_", name.lower().strip())
    return s.strip("_")


class GCFullScraper:
    """Full-depth GameChanger scraper — all stat tabs, both teams, every game."""

    def __init__(
        self,
        team_id: str | None = None,
        season_slug: str | None = None,
        email: str | None = None,
        password: str | None = None,
        out_dir: Path | None = None,
        headless: bool | None = None,
    ):
        self.team_id = team_id or GC_TEAM_ID
        self.season_slug = season_slug or GC_SEASON_SLUG
        self.email = email or GC_EMAIL
        self.password = password or GC_PASSWORD
        self.out_dir = out_dir or SHARKS_DIR
        self.headless = headless if headless is not None else GC_HEADLESS

        self.games_dir = self.out_dir / "games"
        self.games_dir.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        self._browser = None
        self._context = None
        self._page = None

    # ------------------------------------------------------------------
    # Authentication helpers (mirrors gc_scraper.GameChangerScraper.login)
    # ------------------------------------------------------------------
    def login(self, playwright) -> "Page":
        """Login to GC and return the active page. Reuses saved auth state when possible."""
        if not self.email or not self.password:
            raise ValueError("[GCFull] Missing credentials. Set GC_EMAIL and GC_PASSWORD in .env")

        auth_file = DATA_DIR / "auth.json"
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        self._browser = playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        if auth_file.exists():
            _log(f"Loading session from {auth_file.name}")
            self._context = self._browser.new_context(
                storage_state=str(auth_file),
                user_agent=user_agent,
            )
        else:
            _log("Creating fresh browser context (no saved auth)")
            self._context = self._browser.new_context(user_agent=user_agent)

        self._page = (
            self._context.pages[0] if self._context.pages else self._context.new_page()
        )

        self._page.goto(GC_BASE, wait_until="domcontentloaded", timeout=60000)
        state = self._auth_state()
        _log(f"Initial auth state: {state}")

        if state in ("LOGIN_REQUIRED", "UNKNOWN"):
            self._do_login_flow()

        # Give GC's SPA up to 10s to finish navigating away from the login page
        for _ in range(10):
            final = self._auth_state()
            if final == "AUTHENTICATED":
                break
            self._page.wait_for_timeout(1000)

        final = self._auth_state()
        _log(f"Post-login URL: {self._page.url}")
        _log(f"Post-login state: {final}")
        if final != "AUTHENTICATED":
            self._capture_diag("login_failed")
            raise RuntimeError(
                f"[GCFull] Authentication failed. State: {final}\n"
                f"  URL: {self._page.url}\n"
                "  If GC required a 2FA code, re-run with GC_2FA_CODE=<code> env var.\n"
                "  Each run triggers a new code email — use only the LATEST code."
            )

        # Save auth for reuse
        self._context.storage_state(path=str(auth_file))
        _log("Session saved.")
        return self._page

    def _auth_state(self) -> str:
        url = self._page.url.lower()
        if "login" in url or "signin" in url:
            return "LOGIN_REQUIRED"
        if self._page.locator('input[type="email"]').count() > 0:
            return "LOGIN_REQUIRED"
        # GC redirects to /home or /teams/ after successful login
        if ("/teams" in url or "stats" in url or "schedule" in url
                or "dashboard" in url or "/home" in url or url.rstrip("/") == "https://web.gc.com"):
            return "AUTHENTICATED"
        return "UNKNOWN"

    def _do_login_flow(self) -> None:
        _log("Entering credentials...")
        try:
            email_field = self._page.locator('input[type="email"], input[name="email"]').first
            email_field.wait_for(state="visible", timeout=15000)
            email_field.fill(self.email)

            continue_btn = self._page.get_by_role(
                "button", name=re.compile("Continue|Sign in", re.I)
            ).first
            if continue_btn.count() > 0:
                continue_btn.click()
            else:
                email_field.press("Enter")

            # GC uses a 2FA flow: email step → page with Code + Password fields
            # Wait up to 15s for either the code field or password field to appear
            self._page.wait_for_timeout(2000)
            code_field = self._page.locator(
                'input[name="code"], input[placeholder*="ode"], input[aria-label*="ode"]'
            ).first
            has_code_field = code_field.count() > 0
            if not has_code_field:
                # Re-check after a moment in case the page is still loading
                self._page.wait_for_timeout(3000)
                has_code_field = code_field.count() > 0

            if has_code_field:
                _log("[2FA] GC sent a verification code to your email.")
                _log("[2FA] Check fly386@gmail.com for a code from GameChanger.")
                # Give the user time to receive the email, then prompt
                # If running non-interactively, read from GC_2FA_CODE env var
                otp = os.getenv("GC_2FA_CODE", "").strip()
                if not otp:
                    _log("[2FA] Enter the code (or set GC_2FA_CODE env var): ", )
                    try:
                        otp = input("[2FA] Code: ").strip()
                    except EOFError:
                        raise RuntimeError("[GCFull] 2FA required but no code provided. "
                                           "Re-run with GC_2FA_CODE=<code> env var.")
                if otp:
                    code_field.fill(otp)
                    _log(f"[2FA] Code entered: {otp}")

            pwd_field = self._page.locator('input[type="password"], input[name="password"]').first
            pwd_field.wait_for(state="visible", timeout=15000)
            pwd_field.fill(self.password)

            sign_btn = self._page.get_by_role(
                "button", name=re.compile("Sign in|Continue|Log in", re.I)
            ).first
            if sign_btn.count() > 0:
                sign_btn.click()
            else:
                pwd_field.press("Enter")

            # Wait for navigation AWAY from the login page (up to 20s)
            try:
                self._page.wait_for_url(
                    re.compile(r"web\.gc\.com/(?!login)"),
                    timeout=20000,
                )
            except Exception:
                # If wait_for_url times out, fall back to networkidle
                self._page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as exc:
            _log(f"[ERROR] Login flow error: {exc}")
            self._capture_diag("login_error")
            raise

    def _capture_diag(self, label: str) -> None:
        try:
            ts = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
            diag_dir = LOG_DIR / "diagnostics"
            diag_dir.mkdir(parents=True, exist_ok=True)
            self._page.screenshot(path=str(diag_dir / f"gcfull_{label}_{ts}.png"), full_page=True)
        except Exception:
            pass

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Tab navigation
    # ------------------------------------------------------------------
    def _click_tab(self, major: str, sub: str | None = None) -> bool:
        """Click a major tab and optionally a sub-tab. Returns True if both succeed."""
        page = self._page
        try:
            # Click major tab
            major_loc = page.get_by_role("tab", name=major, exact=False).first
            if major_loc.count() == 0:
                major_loc = page.locator(
                    "button, a, [role='tab'], [role='button']"
                ).filter(has_text=re.compile(major, re.I)).first
            if major_loc.count() == 0:
                _log(f"[WARN] Major tab not found: '{major}'")
                return False
            if major_loc.is_visible():
                major_loc.click()
                page.wait_for_timeout(800)
        except Exception as e:
            _log(f"[WARN] Error clicking major tab '{major}': {e}")
            return False

        if sub is None:
            return True

        try:
            sub_loc = page.get_by_role("tab", name=sub, exact=False).first
            if sub_loc.count() == 0:
                sub_loc = page.locator(
                    "button, a, [role='tab'], [role='button']"
                ).filter(has_text=re.compile(sub, re.I)).first
            if sub_loc.count() == 0:
                _log(f"[WARN] Sub-tab not found: '{sub}'")
                return False
            if sub_loc.is_visible():
                sub_loc.click()
                page.wait_for_timeout(800)
        except Exception as e:
            _log(f"[WARN] Error clicking sub-tab '{sub}': {e}")
            return False

        return True

    # ------------------------------------------------------------------
    # Table parsing
    # ------------------------------------------------------------------
    def _parse_stats_table(self, col_map: dict) -> list[dict]:
        """
        Extract stats from GC's AG Grid component.

        GC renders stats in ag-grid (not HTML <table>). The grid has:
          - [role="treegrid"]  — grid root
          - [role="columnheader"] — headers (col-id attribute is the canonical column key)
          - pinned-left rowgroup — player name cells (ag-pinned-left-cols-container)
          - center rowgroup — stat value cells (ag-center-cols-container)
          Rows are correlated by aria-rowindex.

        Falls back to standard <table> extraction if AG Grid is not found.
        """
        page = self._page
        try:
            js = r"""
            (() => {
                // --- Strategy 1: AG Grid (GC's primary stats renderer) ---
                const grid = document.querySelector('[role="treegrid"]');
                if (grid) {
                    // Collect column headers: col-id → display text
                    const colHeaders = {};
                    const headerOrder = [];
                    grid.querySelectorAll('[role="columnheader"]').forEach(h => {
                        const colId = h.getAttribute('col-id') || h.textContent.trim();
                        const label = h.textContent.trim();
                        colHeaders[colId] = label;
                        headerOrder.push(colId);
                    });

                    // Collect ALL cells keyed by {rowIndex: {colId: value}}
                    const byRow = {};
                    grid.querySelectorAll('[role="gridcell"]').forEach(cell => {
                        const row = cell.closest('[role="row"]');
                        if (!row) return;
                        const rowIdx = row.getAttribute('aria-rowindex');
                        if (!rowIdx) return;
                        const colId = cell.getAttribute('col-id') || '';
                        const val = cell.textContent.trim();
                        if (!byRow[rowIdx]) byRow[rowIdx] = {};
                        if (colId) byRow[rowIdx][colId] = val;
                    });

                    // Also collect pinned left cells (player name column)
                    grid.querySelectorAll('.ag-pinned-left-cols-container [role="gridcell"]').forEach(cell => {
                        const row = cell.closest('[role="row"]');
                        if (!row) return;
                        const rowIdx = row.getAttribute('aria-rowindex');
                        if (!rowIdx) return;
                        const colId = cell.getAttribute('col-id') || 'player';
                        const val = cell.textContent.trim();
                        if (!byRow[rowIdx]) byRow[rowIdx] = {};
                        byRow[rowIdx][colId] = val;
                    });

                    // Collect pinned left header to find the player col-id
                    let playerColId = 'player';
                    const leftHeader = grid.querySelector('.ag-pinned-left-header [role="columnheader"]');
                    if (leftHeader) playerColId = leftHeader.getAttribute('col-id') || 'player';

                    // Convert to list, skip header row (rowindex=1) AND pinned totals row (rowindex=2)
                    const rows = Object.keys(byRow)
                        .map(Number)
                        .sort((a,b) => a-b)
                        .filter(i => i > 2)
                        .map(i => byRow[String(i)]);

                    if (rows.length > 0) {
                        return JSON.stringify({source: 'ag-grid', rows, playerColId, headers: colHeaders});
                    }
                }

                // --- Strategy 2: Standard HTML table fallback ---
                const tables = document.querySelectorAll('table');
                if (tables.length) {
                    const table = tables[0];
                    const thEls = table.querySelectorAll('thead th');
                    const headers = Array.from(thEls).map(th => th.textContent.trim());
                    const rows = [];
                    table.querySelectorAll('tbody tr').forEach(tr => {
                        const cells = tr.querySelectorAll('td');
                        if (!cells.length) return;
                        const row = {};
                        cells.forEach((cell, i) => {
                            row[headers[i] || 'col' + i] = cell.textContent.trim();
                        });
                        if (Object.values(row).some(v => v)) rows.push(row);
                    });
                    return JSON.stringify({source: 'table', rows, playerColId: headers[0] || 'col0', headers: {}});
                }

                return JSON.stringify({source: 'none', rows: [], playerColId: 'player', headers: {}});
            })()
            """
            raw = page.evaluate(js)
            result = json.loads(raw) if raw else {}
        except Exception as e:
            _log(f"[WARN] JS table extract failed: {e}")
            return []

        raw_rows = result.get("rows", [])
        player_col = result.get("playerColId", "player")
        col_headers = result.get("headers", {})  # colId → display label

        # Build a reverse map: display label → colId (for col_map matching)
        label_to_id: dict[str, str] = {v: k for k, v in col_headers.items()}

        players = []
        for row in raw_rows:
            # Identify player name
            raw_name = (
                row.get(player_col) or row.get("Player") or row.get("player") or
                row.get("") or row.get("col0") or ""
            ).strip()
            if not raw_name or raw_name.lower() in ("team", "totals", "team totals", "total", ""):
                continue

            # Parse name & jersey number
            name = raw_name
            number = ""
            num_match = re.search(r"#(\s*\d+)", raw_name)
            if num_match:
                number = num_match.group(1).strip()
                name = raw_name[: num_match.start()].strip().rstrip(",").strip()

            player_dict: dict[str, Any] = {"name": name, "number": number}

            # Map stats: try col_map keys against both col-id and display label
            for gc_col_label, stat_key in col_map.items():
                # Try direct col-id match first (e.g. "PA", "AB")
                val = row.get(gc_col_label)
                if val is None:
                    # Try the label→id lookup
                    col_id = label_to_id.get(gc_col_label)
                    if col_id:
                        val = row.get(col_id)
                if val is not None:
                    player_dict[stat_key] = _safe_val(val)

            players.append(player_dict)

        return players

    # ------------------------------------------------------------------
    # Schedule discovery
    # ------------------------------------------------------------------
    def discover_schedule(self) -> list[dict]:
        """
        Navigate to the schedule page and extract game metadata.
        Returns list of dicts: {gc_game_id, date, opponent, sharks_side, result, score}.
        Intercepts API responses AND falls back to DOM link parsing.
        """
        schedule_url = f"{GC_BASE}/teams/{self.team_id}/{self.season_slug}/schedule"
        _log(f"Discovering schedule at {schedule_url}")

        intercepted_games: list[dict] = []
        api_responses: list[dict] = []

        def handle_response(response) -> None:
            try:
                url = response.url
                if GC_API_BASE not in url:
                    return
                if response.status != 200:
                    return
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                body = response.json()
                api_responses.append({"url": url, "body": body})
            except Exception:
                pass

        self._page.on("response", handle_response)

        try:
            self._page.goto(schedule_url, wait_until="networkidle", timeout=60000)
            self._page.wait_for_timeout(3000)
        except Exception as e:
            _log(f"[WARN] Schedule page load issue: {e}")
            try:
                self._page.goto(schedule_url, wait_until="domcontentloaded", timeout=60000)
                self._page.wait_for_timeout(4000)
            except Exception:
                pass

        # Try to extract schedule from intercepted API calls
        for resp in api_responses:
            body = resp["body"]
            games_raw = None
            if isinstance(body, list):
                games_raw = body
            elif isinstance(body, dict):
                for key in ("games", "schedule", "data", "items", "results"):
                    if isinstance(body.get(key), list):
                        games_raw = body[key]
                        break

            if not games_raw:
                continue

            for g in games_raw:
                if not isinstance(g, dict):
                    continue
                gc_game_id = _safe_str(g.get("id") or g.get("game_id") or g.get("gc_id") or "")
                if not gc_game_id:
                    continue
                date_raw = _safe_str(
                    g.get("date") or g.get("start_date") or g.get("scheduled_at") or ""
                )
                date = date_raw[:10] if date_raw else ""
                opponent = _safe_str(
                    g.get("opponent_team_name")
                    or g.get("away_team_name")
                    or g.get("home_team_name")
                    or g.get("opponent")
                    or ""
                )
                sharks_score = g.get("sharks_score") or g.get("home_score") or g.get("score_us")
                opp_score = g.get("opp_score") or g.get("away_score") or g.get("score_them")
                intercepted_games.append(
                    {
                        "gc_game_id": gc_game_id,
                        "date": date,
                        "opponent": opponent,
                        "sharks_side": _safe_str(g.get("sharks_side") or g.get("side") or ""),
                        "result": _safe_str(g.get("result") or g.get("outcome") or ""),
                        "score": {
                            "sharks": int(sharks_score) if sharks_score is not None else None,
                            "opponent": int(opp_score) if opp_score is not None else None,
                        },
                        "_source": "api_intercept",
                    }
                )

        if intercepted_games:
            _log(f"API intercept: found {len(intercepted_games)} games")

        # DOM fallback: extract /schedule/{gc_game_id} links
        dom_games: list[dict] = []
        try:
            game_links = self._page.evaluate(
                """
                (() => {
                    const links = new Set();
                    document.querySelectorAll('a[href*="/schedule/"]').forEach(a => {
                        const href = a.href;
                        // Only want game-specific links (not just /schedule)
                        const m = href.match(/\\/schedule\\/([a-zA-Z0-9_-]+)/);
                        if (m && m[1]) links.add(href);
                    });
                    return Array.from(links);
                })()
                """
            )
            for link in game_links or []:
                m = re.search(r"/schedule/([a-zA-Z0-9_-]+)", link)
                gc_game_id = m.group(1) if m else ""
                if not gc_game_id:
                    continue
                # Check if we already have this from API intercept
                existing_ids = {g["gc_game_id"] for g in intercepted_games}
                if gc_game_id in existing_ids:
                    continue
                dom_games.append(
                    {
                        "gc_game_id": gc_game_id,
                        "date": "",
                        "opponent": "",
                        "sharks_side": "",
                        "result": "",
                        "score": {"sharks": None, "opponent": None},
                        "_source": "dom_link",
                        "_url": link,
                    }
                )
        except Exception as e:
            _log(f"[WARN] DOM link extraction error: {e}")

        all_games = intercepted_games + dom_games

        # Remove duplicate gc_game_ids (keep first)
        seen_ids: set[str] = set()
        deduped: list[dict] = []
        for g in all_games:
            gid = g["gc_game_id"]
            if gid and gid not in seen_ids:
                seen_ids.add(gid)
                deduped.append(g)

        _log(f"Schedule discovery complete: {len(deduped)} unique games")
        return deduped

    # ------------------------------------------------------------------
    # Per-game scraping
    # ------------------------------------------------------------------
    def scrape_game(self, game: dict) -> dict | None:
        """
        Navigate to game-stats page and scrape all stat tabs for both teams.
        Returns a full game JSON dict or None on total failure.
        """
        gc_game_id = game.get("gc_game_id", "")
        if not gc_game_id:
            _log("[WARN] No gc_game_id in game dict, skipping")
            return None

        game_stats_url = (
            f"{GC_BASE}/teams/{self.team_id}/{self.season_slug}/schedule/{gc_game_id}/game-stats"
        )
        _log(f"Scraping game {gc_game_id} ({game.get('date','')} vs {game.get('opponent','')})")

        page = self._page

        # Intercept API to pick up richer metadata
        api_meta: dict = {}

        def handle_api(response) -> None:
            try:
                url = response.url
                if GC_API_BASE not in url or response.status != 200:
                    return
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                body = response.json()
                if isinstance(body, dict):
                    api_meta.update(body)
            except Exception:
                pass

        page.on("response", handle_api)

        try:
            page.goto(game_stats_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
        except Exception as e:
            _log(f"[WARN] Game page load failed: {e}")
            try:
                page.goto(game_stats_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
            except Exception as e2:
                _log(f"[ERROR] Cannot load game {gc_game_id}: {e2}")
                return None

        # Build output structure
        date_str = game.get("date", "")
        opponent_name = game.get("opponent", "") or _safe_str(api_meta.get("opponent_team_name", ""))
        sharks_side = game.get("sharks_side", "")
        score = game.get("score", {"sharks": None, "opponent": None})
        result = game.get("result", "")

        game_doc: dict = {
            "game_id": f"{date_str}_{_opponent_slug(opponent_name) or gc_game_id}",
            "gc_game_id": gc_game_id,
            "date": date_str,
            "opponent": opponent_name,
            "sharks_side": sharks_side,
            "result": result,
            "score": score,
            "source": SOURCE_TAG,
            "captured_at": datetime.now(ET).isoformat(),
            "sharks": {},
            "opponent_stats": {},
        }

        # Scrape for Sharks first, then toggle to opponent
        for team_key in ("sharks", "opponent_stats"):
            _log(f"  Scraping stats for: {team_key}")

            # If opponent tab, try to find a team toggle
            if team_key == "opponent_stats":
                toggled = self._toggle_to_opponent(opponent_name)
                if not toggled:
                    _log("  [WARN] Could not toggle to opponent team view, skipping opponent stats")
                    continue
                page.wait_for_timeout(1000)

            team_stats: dict = {}
            last_major: str | None = None

            for major_tab, sub_tab, col_map, json_key in GAME_STAT_VIEWS:
                try:
                    # Only click major tab when switching categories
                    if major_tab != last_major:
                        if not self._click_tab(major_tab, None):
                            _log(f"  [WARN] Major tab '{major_tab}' not found, skipping {json_key}")
                            last_major = None
                            continue
                        last_major = major_tab
                        page.wait_for_timeout(500)

                    # Click sub-tab (Standard is usually default, still click it)
                    if not self._click_tab(major_tab, sub_tab):
                        _log(f"  [WARN] Sub-tab '{sub_tab}' not found for {json_key}")
                        continue

                    page.wait_for_timeout(600)
                    rows = self._parse_stats_table(col_map)

                    if rows:
                        team_stats[json_key] = rows
                        _log(f"  {major_tab}/{sub_tab}: {len(rows)} players")
                    else:
                        _log(f"  [WARN] No rows for {major_tab}/{sub_tab}")

                except Exception as e:
                    _log(f"  [WARN] Error scraping {major_tab}/{sub_tab}: {e}")
                    continue

            game_doc[team_key] = team_stats

        # Save file
        file_name = f"{date_str}_{_opponent_slug(opponent_name) or gc_game_id}.json"
        if not date_str:
            file_name = f"game_{gc_game_id}.json"
        out_file = self.games_dir / file_name

        try:
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(game_doc, f, indent=2, ensure_ascii=False)
            _log(f"  Saved: {out_file.name}")
        except Exception as e:
            _log(f"  [ERROR] Could not save {out_file}: {e}")

        return game_doc

    def _toggle_to_opponent(self, opponent_name: str) -> bool:
        """Attempt to switch the game-stats view to the opponent team."""
        page = self._page
        try:
            # GC typically shows a team selector dropdown or tabs with team names
            # Try clicking a button/tab that matches opponent name fragment
            opp_words = [w for w in opponent_name.split() if len(w) > 2]
            for word in opp_words:
                loc = page.locator("button, [role='tab'], [role='button']").filter(
                    has_text=re.compile(word, re.I)
                ).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click()
                    page.wait_for_timeout(600)
                    return True

            # Generic fallback: look for "Away" or "Visiting" team selector
            for label in ("Away", "Visiting", "Guest", "Opponent"):
                loc = page.get_by_role("tab", name=label, exact=False).first
                if loc.count() == 0:
                    loc = page.get_by_role("button", name=label, exact=False).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click()
                    page.wait_for_timeout(600)
                    return True
        except Exception as e:
            _log(f"  [WARN] Toggle to opponent failed: {e}")
        return False

    # ------------------------------------------------------------------
    # Season team stats scraping
    # ------------------------------------------------------------------
    def scrape_team_season_stats(self) -> dict:
        """
        Scrape all 8 stat views from the team stats page.
        Saves to data/sharks/team_web.json and returns the dict.
        """
        stats_url = f"{GC_BASE}/teams/{self.team_id}/{self.season_slug}/stats"
        _log(f"Scraping team season stats from {stats_url}")

        page = self._page
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
                return {}

        # Dismiss "follow team" or other popups
        try:
            maybe_later = page.locator('button:has-text("Maybe later")').first
            if maybe_later.count() > 0:
                maybe_later.click()
                page.wait_for_timeout(500)
        except Exception:
            pass

        team_stats: dict = {"captured_at": datetime.now(ET).isoformat(), "source": SOURCE_TAG}
        last_major: str | None = None

        for major_tab, sub_tab, col_map, json_key in GAME_STAT_VIEWS:
            try:
                if major_tab != last_major:
                    if not self._click_tab(major_tab, None):
                        _log(f"  [WARN] Major tab '{major_tab}' not found")
                        last_major = None
                        continue
                    last_major = major_tab
                    page.wait_for_timeout(500)

                if not self._click_tab(major_tab, sub_tab):
                    _log(f"  [WARN] Sub-tab '{sub_tab}' not found")
                    continue

                page.wait_for_timeout(600)
                rows = self._parse_stats_table(col_map)

                if rows:
                    team_stats[json_key] = rows
                    _log(f"  Team stats {major_tab}/{sub_tab}: {len(rows)} players")
                else:
                    _log(f"  [WARN] No rows for {major_tab}/{sub_tab}")

            except Exception as e:
                _log(f"  [WARN] Error scraping team {major_tab}/{sub_tab}: {e}")
                continue

        out_file = self.out_dir / "team_web.json"
        try:
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(team_stats, f, indent=2, ensure_ascii=False)
            _log(f"Saved team season stats to {out_file.name}")
        except Exception as e:
            _log(f"[ERROR] Could not save team_web.json: {e}")

        return team_stats

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def run_full_sync(self, force: bool = False) -> dict:
        """
        Full sync: login, discover schedule, scrape each game, scrape team stats.
        Returns summary dict.

        force=True re-scrapes games that already have source == SOURCE_TAG.
        """
        if sync_playwright is None:
            raise ImportError("playwright is not installed. Run: pip install playwright && playwright install chromium")

        summary: dict = {
            "started_at": datetime.now(ET).isoformat(),
            "games_found": 0,
            "games_scraped": 0,
            "games_skipped": 0,
            "games_failed": 0,
            "team_stats_scraped": False,
            "errors": [],
        }

        with sync_playwright() as pw:
            try:
                self.login(pw)
            except Exception as e:
                summary["errors"].append(f"Login failed: {e}")
                _log(f"[ERROR] Login failed: {e}")
                return summary

            # Discover schedule
            try:
                games = self.discover_schedule()
                summary["games_found"] = len(games)
            except Exception as e:
                summary["errors"].append(f"Schedule discovery failed: {e}")
                _log(f"[ERROR] Schedule discovery failed: {e}")
                games = []

            # Scrape each game
            for game in games:
                gc_id = game.get("gc_game_id", "")
                date_str = game.get("date", "")
                opp_name = game.get("opponent", "")
                file_name = f"{date_str}_{_opponent_slug(opp_name) or gc_id}.json"
                if not date_str:
                    file_name = f"game_{gc_id}.json"
                out_file = self.games_dir / file_name

                # Idempotency: skip if already fully scraped (unless force)
                if not force and out_file.exists():
                    try:
                        with open(out_file) as fh:
                            existing = json.load(fh)
                        if existing.get("source") == SOURCE_TAG:
                            _log(f"Skipping {file_name} (already scraped)")
                            summary["games_skipped"] += 1
                            continue
                    except Exception:
                        pass

                try:
                    result = self.scrape_game(game)
                    if result:
                        summary["games_scraped"] += 1
                    else:
                        summary["games_failed"] += 1
                except Exception as e:
                    summary["games_failed"] += 1
                    summary["errors"].append(f"Game {gc_id}: {e}")
                    _log(f"[ERROR] Game {gc_id}: {e}")

            # Scrape season-level team stats
            try:
                team_stats = self.scrape_team_season_stats()
                summary["team_stats_scraped"] = bool(team_stats)
            except Exception as e:
                summary["errors"].append(f"Team stats: {e}")
                _log(f"[ERROR] Team stats scrape failed: {e}")

            self.close()

        summary["completed_at"] = datetime.now(ET).isoformat()
        _log(
            f"Full sync complete: {summary['games_scraped']} scraped, "
            f"{summary['games_skipped']} skipped, {summary['games_failed']} failed"
        )
        return summary


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="GC Full Scraper — all stat tabs, both teams")
    parser.add_argument("--force", action="store_true", help="Re-scrape games already saved")
    parser.add_argument("--headed", action="store_true", help="Run with visible browser (debug)")
    parser.add_argument("--schedule-only", action="store_true", help="Only discover schedule, no game scraping")
    parser.add_argument("--team-stats-only", action="store_true", help="Only scrape team season stats")
    parser.add_argument("--game-id", help="Scrape a single specific game by gc_game_id")
    args = parser.parse_args()

    headless = not args.headed

    scraper = GCFullScraper(headless=headless)

    if sync_playwright is None:
        print("[GCFull] ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    if not args.schedule_only and not args.team_stats_only and not args.game_id:
        # run_full_sync manages its own sync_playwright context
        summary = scraper.run_full_sync(force=args.force)
        print(json.dumps(summary, indent=2))
    else:
        with sync_playwright() as pw:
            scraper.login(pw)

            if args.schedule_only:
                games = scraper.discover_schedule()
                print(json.dumps(games, indent=2))

            elif args.team_stats_only:
                stats = scraper.scrape_team_season_stats()
                print(f"[GCFull] Team stats keys: {list(stats.keys())}")

            elif args.game_id:
                game_doc = scraper.scrape_game({"gc_game_id": args.game_id})
                if game_doc:
                    print(f"[GCFull] Saved: {game_doc.get('game_id')}")
                else:
                    print("[GCFull] Scrape returned no data")

            scraper.close()


if __name__ == "__main__":
    main()
