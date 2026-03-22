"""
GameChanger Scraper for Softball
Browser automation via Playwright to scrape ALL stat categories from web.gc.com.

STAT CATEGORIES SCRAPED:
  • Batting: Standard, Advanced
  • Pitching: Standard, Advanced, Breakdown
  • Fielding: Standard, Catching, Innings Played

REQUIRES: pip install playwright && playwright install chromium
REQUIRES: GC_EMAIL and GC_PASSWORD in .env
"""

import argparse
import json
import os
import re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

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

# Team-specific config (env-overridable)
GC_TEAM_ID = os.getenv("GC_TEAM_ID", "NuGgx6WvP7TO")
GC_SEASON_SLUG = os.getenv("GC_SEASON_SLUG", "2026-spring-sharks")
GC_STATS_URL = f"{GC_BASE_URL}/teams/{GC_TEAM_ID}/{GC_SEASON_SLUG}/season-stats"

# ---------- Column mappings for each stat category ---------- #
# Maps raw GC column header -> clean JSON key name

BATTING_STD_MAP = {
    "GP": "gp", "PA": "pa", "AB": "ab", "AVG": "avg", "OBP": "obp",
    "OPS": "ops", "SLG": "slg", "H": "h", "1B": "singles", "2B": "doubles",
    "3B": "triples", "HR": "hr", "RBI": "rbi", "R": "r", "BB": "bb",
    "HBP": "hbp", "ROE": "roe", "FC": "fc", "CI": "ci", "SAC": "sac",
    "SF": "sf", "SO": "so", "K-L": "kl", "SB": "sb", "CS": "cs",
    "SB%": "sb_pct", "PIK": "pik",
}

BATTING_ADV_MAP = {
    "GP": "gp", "PA": "pa", "TB": "tb", "XBH": "xbh", "AB/HR": "ab_hr",
    "BA/RISP": "ba_risp", "BABIP": "babip", "PS": "ps", "PS/PA": "ps_pa",
    "QAB": "qab", "QAB%": "qab_pct", "BB/K": "bb_k", "C%": "c_pct",
    "2OUTRBI": "two_out_rbi", "HHB": "hhb", "GIDP": "gidp", "GITP": "gitp",
    "6+": "six_plus", "6+%": "six_plus_pct", "2S+3": "two_s_three",
    "2S+3%": "two_s_three_pct", "FB%": "fb_pct", "GB%": "gb_pct", "LD%": "ld_pct",
}

PITCHING_STD_MAP = {
    "GP": "gp", "GS": "gs", "W": "w", "L": "l", "SV": "sv", "SVO": "svo",
    "SV%": "sv_pct", "IP": "ip", "H": "h", "R": "r", "ER": "er", "BB": "bb",
    "SO": "so", "K-L": "kl", "ERA": "era", "WHIP": "whip", "BAA": "baa",
    "BF": "bf", "#P": "np", "PIK": "pik", "SB": "sb", "CS": "cs",
    "SB%": "sb_pct", "HBP": "hbp", "WP": "wp", "BK": "bk", "LOB": "lob",
}

PITCHING_ADV_MAP = {
    "IP": "ip", "S%": "s_pct", "P/IP": "p_ip", "P/BF": "p_bf",
    "FPS%": "fps_pct", "FPSW%": "fpsw_pct", "FPSO%": "fpso_pct",
    "FPSH%": "fpsh_pct", "<3%": "lt3_pct", "<13": "lt13",
    "LOO": "loo", "1ST2OUT": "first_2out", "123INN": "one23_inn",
    "0BBINN": "zero_bb_inn", "FIP": "fip", "K/BF": "k_bf", "K/BB": "k_bb",
    "BB/INN": "bb_inn", "BA/RISP": "ba_risp", "BABIP": "babip",
    "LD%": "ld_pct", "GB%": "gb_pct", "FB%": "fb_pct", "HHB%": "hhb_pct",
    "SM%": "sm_pct", "BBS": "bbs", "LOBBS": "lobbs", "LOBB": "lobb",
}

PITCHING_BRK_MAP = {
    "#P": "np",
    "FB": "fb", "FBS": "fbs", "FBS%": "fbs_pct", "FBSM%": "fbsm_pct", "FBSW%": "fbsw_pct",
    "CH": "ch", "CHS": "chs", "CHS%": "chs_pct", "CHSM%": "chsm_pct", "CHSW%": "chsw_pct",
    "CB": "cb", "CBS": "cbs", "CBS%": "cbs_pct", "CBSM%": "cbsm_pct", "CBSW%": "cbsw_pct",
    "SC": "sc", "SCS": "scs", "SCS%": "scs_pct", "SCSM%": "scsm_pct", "SCSW%": "scsw_pct",
    "RB": "rb", "RBS": "rbs", "RBS%": "rbs_pct", "RBSM%": "rbsm_pct", "RBSW%": "rbsw_pct",
    "DB": "db", "DBS": "dbs", "DBS%": "dbs_pct", "DBSM%": "dbsm_pct", "DBSW%": "dbsw_pct",
    "DC": "dc", "DCS": "dcs",
    "MPHFB": "mph_fb", "MPHCH": "mph_ch", "MPHCB": "mph_cb",
    "MPHSC": "mph_sc", "MPHRB": "mph_rb", "MPHDB": "mph_db",
}

FIELDING_STD_MAP = {
    "TC": "tc", "PO": "po", "A": "a", "E": "e", "FPCT": "fpct",
    "DP": "dp", "TP": "tp",
}

FIELDING_CATCH_MAP = {
    "INN": "inn", "SB": "sb", "CS": "cs", "CS%": "cs_pct",
    "SB-ATT": "sb_att", "PB": "pb", "PIK": "pik", "CI": "ci",
}

FIELDING_INN_MAP = {
    "IP:F": "total", "IP:P": "p", "IP:C": "c", "IP:1B": "first_base",
    "IP:2B": "second_base", "IP:3B": "third_base", "IP:SS": "ss",
    "IP:LF": "lf", "IP:CF": "cf", "IP:RF": "rf", "IP:SF": "sf",
}

# The 9 stat views, in scraping order (major_tab, sub_tab, column_map, json_key)
STAT_VIEWS = [
    ("Batting",  "Standard",      BATTING_STD_MAP,   "batting"),
    ("Batting",  "Advanced",      BATTING_ADV_MAP,   "batting_advanced"),
    ("Pitching", "Standard",      PITCHING_STD_MAP,  "pitching"),
    ("Pitching", "Advanced",      PITCHING_ADV_MAP,  "pitching_advanced"),
    ("Pitching", "Breakdown",     PITCHING_BRK_MAP,  "pitching_breakdown"),
    ("Fielding", "Standard",      FIELDING_STD_MAP,  "fielding"),
    ("Fielding", "Catching",      FIELDING_CATCH_MAP, "catching"),
    ("Fielding", "Innings Played", FIELDING_INN_MAP,  "innings_played"),
]


def _safe_val(val: str):
    """Convert a scraped cell value to int/float/string as appropriate."""
    if val is None:
        return None
    val = val.strip()
    if val in ("", "-", "—", "N/A"):
        return None
    # Try int first
    try:
        return int(val)
    except ValueError:
        pass
    # Try float
    try:
        return float(val)
    except ValueError:
        pass
    return val


class GameChangerScraper:
    """Scrape softball statistics from GameChanger (web.gc.com)."""

    def __init__(
        self,
        team_id: str | None = None,
        season_slug: str | None = None,
        team_name: str | None = None,
        out_dir: Path | None = None,
        roster_manifest_path: Path | None = None,
        use_manifest: bool = True,
    ):
        self.email = os.getenv("GC_EMAIL", "")
        self.password = os.getenv("GC_PASSWORD", "")
        self.team_name = team_name or os.getenv("TEAM_NAME", "The Sharks")
        self.team_id = team_id or os.getenv("GC_TEAM_ID", GC_TEAM_ID)
        self.season_slug = season_slug or os.getenv("GC_SEASON_SLUG", GC_SEASON_SLUG)
        self.stats_url = f"{GC_BASE_URL}/teams/{self.team_id}/{self.season_slug}/season-stats"
        self.out_dir = out_dir or SHARKS_DIR
        self.roster_manifest_path = roster_manifest_path or (SHARKS_DIR / "roster_manifest.json")
        self.use_manifest = use_manifest
        self.browser = None
        self.page = None

    def _validate_credentials(self):
        """Ensure GC credentials are set."""
        if not self.email or not self.password:
            raise ValueError(
                "[GC] Missing credentials. Set GC_EMAIL and GC_PASSWORD in .env"
            )

    def login(self, playwright):
        """Log in to GameChanger via browser automation using persistent sessions."""
        self._validate_credentials()

        auth_file = DATA_DIR / "auth.json"

        self.browser = playwright.chromium.launch(headless=True)
        
        # Load existing session if available
        if auth_file.exists():
            print(f"[GC] Loading existing session from {auth_file}")
            context = self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                storage_state=str(auth_file)
            )
        else:
            print("[GC] No existing session found. Creating new context.")
            context = self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            
        self.page = context.new_page()

        print(f"[GC] Navigating to {GC_BASE_URL}...")
        self.page.goto(GC_BASE_URL, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(3000)
        
        # Check if we are already logged in
        if "login" not in self.page.url:
            print(f"[GC] Session valid. Currently at: {self.page.url}")
            return self.page

        print(f"[GC] Session invalid or missing. Navigating to login page...")
        self.page.goto(GC_LOGIN_URL, wait_until="networkidle", timeout=60000)

        # Fill login form
        print("[GC] Entering credentials...")
        self.page.fill('input[name="email"], input[type="email"]', self.email)
        self.page.fill('input[name="password"], input[type="password"]', self.password)
        self.page.click('button[type="submit"]')

        print("[GC] Waiting for login to complete...")
        self.page.wait_for_load_state("networkidle", timeout=60000)
        
        # Handle 2FA/CAPTCHA
        if "login" in self.page.url or "challenge" in self.page.content().lower():
             print("[WARNING] Stuck on login/challenge page! Manual intervention may be required.")
             self.page.wait_for_timeout(60000)
             
        print(f"[GC] Logged in. Current URL: {self.page.url}")
        
        # Save session state
        print(f"[GC] Saving authenticated session state to {auth_file}...")
        context.storage_state(path=str(auth_file))

        return self.page

    # ------------------------------------------------------------------ #
    #  Core: Extract a single stat table from the current view
    # ------------------------------------------------------------------ #
    def _extract_table(self) -> list[dict]:
        """
        Extract the stats table currently visible on the GC page.
        Returns a list of dicts: [{"player": "...", "#": "...", "COL1": val, ...}, ...]
        """
        js_extract = """
        (() => {
            // GC renders tables with role="table" or standard <table> elements.
            // Attempt multiple selectors.
            const tables = document.querySelectorAll('table, [role="table"]');
            if (!tables.length) return JSON.stringify([]);
            
            // Use the first (main) stats table
            const table = tables[0];
            
            // Get headers from <th> or [role="columnheader"]
            let headers = [];
            const thEls = table.querySelectorAll('thead th, [role="columnheader"]');
            if (thEls.length) {
                headers = Array.from(thEls).map(th => th.textContent.trim());
            }
            
            // Get rows from <tbody> <tr> or [role="row"]
            const rows = [];
            const trEls = table.querySelectorAll('tbody tr, [role="row"]');
            trEls.forEach(tr => {
                const cells = tr.querySelectorAll('td, [role="cell"], [role="gridcell"]');
                if (cells.length === 0) return;
                const row = {};
                cells.forEach((cell, i) => {
                    const key = (headers[i] || `col${i}`);
                    row[key] = cell.textContent.trim();
                });
                // Only include rows that look like player data (have some text)
                if (Object.values(row).some(v => v && v.length > 0)) {
                    rows.push(row);
                }
            });
            return JSON.stringify(rows);
        })()
        """
        raw = self.page.evaluate(js_extract)
        try:
            return json.loads(raw) if raw else []
        except json.JSONDecodeError:
            print(f"[GC] Warning: Could not parse table JSON")
            return []

    def _click_tab(self, tab_text: str) -> bool:
        """Click a tab/button by its visible text. Returns True if found."""
        try:
            # GC uses styled tabs — try multiple selector strategies
            selectors = [
                f'button:has-text("{tab_text}")',
                f'[role="tab"]:has-text("{tab_text}")',
                f'a:has-text("{tab_text}")',
                f'div[role="tablist"] >> text="{tab_text}"',
            ]
            for sel in selectors:
                loc = self.page.locator(sel).first
                if loc.count() > 0:
                    loc.click()
                    self.page.wait_for_timeout(1500)
                    return True
            # Fallback: broader text match
            loc = self.page.locator(f'text="{tab_text}"').first
            if loc.count() > 0:
                loc.click()
                self.page.wait_for_timeout(1500)
                return True
        except Exception as e:
            print(f"[GC] Could not click tab '{tab_text}': {e}")
        return False

    # ------------------------------------------------------------------ #
    #  Scrape W-L record from schedule page
    # ------------------------------------------------------------------ #
    def scrape_record(self) -> str:
        """Scrape the team W-L record from the schedule page. Returns e.g. '2-1'."""
        schedule_url = f"{GC_BASE_URL}/teams/{self.team_id}/{self.season_slug}/schedule"
        try:
            self.page.goto(schedule_url, wait_until="domcontentloaded", timeout=60000)
            self.page.wait_for_timeout(2000)
            # GC shows record on the schedule page — look for text like "2-1" or "W-L"
            # Try to find a record element (common patterns: "Record: 2-1", "2-1 (W-L)")
            record_text = self.page.evaluate("""
            (() => {
                // Try to find record in page text
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    if (el.children.length === 0) {
                        const t = el.textContent.trim();
                        if (/^\\d+-\\d+$/.test(t) || /Record.*\\d+-\\d+/.test(t)) {
                            return t.match(/\\d+-\\d+/)?.[0] || null;
                        }
                    }
                }
                return null;
            })()
            """)
            if record_text and re.match(r'^\d+-\d+', record_text):
                return record_text
        except Exception as e:
            print(f"[GC] Could not scrape record: {e}")
        return "0-0"

    # ------------------------------------------------------------------ #
    #  Scrape per-game box scores from the schedule page
    # ------------------------------------------------------------------ #
    def scrape_game_box_scores(self) -> list[dict]:
        """
        Scrape per-game box scores for all completed games.
        Returns a list of game dicts; also saves each to data/sharks/games/.
        """
        if not self.page:
            raise RuntimeError("[GC] Not logged in. Call login() first.")

        schedule_url = f"{GC_BASE_URL}/teams/{self.team_id}/{self.season_slug}/schedule"
        games_dir = self.out_dir / "games"
        games_dir.mkdir(parents=True, exist_ok=True)

        print(f"[GC] Navigating to schedule: {schedule_url}")
        self.page.goto(schedule_url, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(3000)

        # Find all completed game links (links that have a score visible)
        game_links = self.page.evaluate("""
        (() => {
            const links = [];
            // GC schedule links often include /games/ or /plays in the path
            document.querySelectorAll('a[href*="/schedule/"]').forEach(a => {
                const href = a.href;
                if (!links.includes(href)) links.push(href);
            });
            return links;
        })()
        """)

        print(f"[GC] Found {len(game_links)} schedule links")
        games = []

        for link in game_links[:20]:  # cap at 20 to avoid runaway
            try:
                # Navigate to the game page
                self.page.goto(link, wait_until="domcontentloaded", timeout=60000)
                self.page.wait_for_timeout(2000)

                # Click "Box Score" tab if present
                has_boxscore = self._click_tab("Box Score")
                if not has_boxscore:
                    # Try "Summary" as fallback
                    self._click_tab("Summary")

                self.page.wait_for_timeout(1500)

                # Extract game metadata from page
                meta = self.page.evaluate("""
                (() => {
                    const title = document.title || '';
                    // Look for score elements
                    const scores = Array.from(document.querySelectorAll('[class*="score"], [class*="Score"]'))
                        .map(el => el.textContent.trim()).filter(t => /^\\d+$/.test(t)).slice(0, 2);
                    // Look for date
                    const dateEl = document.querySelector('time, [datetime]');
                    const date = dateEl ? (dateEl.getAttribute('datetime') || dateEl.textContent.trim()) : '';
                    // Team names
                    const teamEls = Array.from(document.querySelectorAll('[class*="team-name"], [class*="teamName"]'))
                        .map(el => el.textContent.trim()).filter(Boolean).slice(0, 2);
                    return { title, scores, date, teams: teamEls };
                })()
                """)

                rows = self._extract_table()

                if not rows:
                    continue

                # Parse players from rows
                box_players = []
                for row in rows:
                    raw_name = (row.get("Player") or row.get("player") or row.get("") or "").strip()
                    if not raw_name or raw_name.lower() in ("team", "totals", "team totals"):
                        continue
                    player_stats = {"name": raw_name}
                    for gc_col, key in BATTING_STD_MAP.items():
                        if gc_col in row:
                            player_stats[key] = _safe_val(row[gc_col])
                    box_players.append(player_stats)

                if not box_players:
                    continue

                # Derive a filename from the URL
                url_slug = re.sub(r"[^a-z0-9]+", "_", link.lower().rstrip("/").split("/")[-1])
                game_data = {
                    "source_url": link,
                    "meta": meta,
                    "batting": box_players,
                    "scraped_at": datetime.now(ET).isoformat(),
                }

                out_file = games_dir / f"{url_slug}.json"
                with open(out_file, "w") as f:
                    json.dump(game_data, f, indent=2)
                print(f"[GC] ✓ Saved box score: {out_file.name} ({len(box_players)} players)")
                games.append(game_data)

                self.page.wait_for_timeout(2000)

            except Exception as e:
                print(f"[GC] ⚠ Error scraping game {link}: {e}")
                continue

        print(f"[GC] ✅ Box scores complete: {len(games)} games scraped")
        return games

    # ------------------------------------------------------------------ #
    #  Main: Scrape all 9 stat views
    # ------------------------------------------------------------------ #
    def scrape_all_stats(self) -> dict | None:
        """
        Scrape ALL stat categories from the GC Season Stats page.
        Merges data across all views into a unified per-player structure.
        Returns the full team dict ready for team.json.
        """
        if not self.page:
            raise RuntimeError("[GC] Not logged in. Call login() first.")

        print(f"[GC] Navigating to stats page: {self.stats_url}")
        self.page.goto(self.stats_url, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(3000)

        # Dismiss any popups (follow team dialog etc.)
        try:
            maybe_later = self.page.locator('button:has-text("Maybe later")').first
            if maybe_later.count() > 0:
                maybe_later.click()
                self.page.wait_for_timeout(1000)
        except Exception:
            pass

        # Player accumulator: keyed by canonical name
        players = {}  # name -> {stat_category: {key: val}}
        team_totals = {}  # stat_category -> {key: val}

        last_major = None

        for major_tab, sub_tab, col_map, json_key in STAT_VIEWS:
            print(f"[GC] Scraping: {major_tab} → {sub_tab}...")

            # Click major tab only if we're switching categories
            if major_tab != last_major:
                if not self._click_tab(major_tab):
                    print(f"[GC]   ⚠ Could not find major tab '{major_tab}', skipping...")
                    continue
                last_major = major_tab

            # Click sub tab
            if sub_tab != "Standard":
                if not self._click_tab(sub_tab):
                    print(f"[GC]   ⚠ Could not find sub tab '{sub_tab}', skipping...")
                    continue

            # Extract the table
            rows = self._extract_table()
            if not rows:
                print(f"[GC]   ⚠ No data found for {major_tab}/{sub_tab}")
                continue

            print(f"[GC]   ✓ Got {len(rows)} rows")

            for row in rows:
                # Identify player: first column is usually "Player" or the player name
                # GC sometimes uses "Player" header, sometimes just puts the name
                raw_name = (
                    row.get("Player")
                    or row.get("player")
                    or row.get("")
                    or row.get("col0")
                    or ""
                ).strip()

                if not raw_name:
                    continue

                # Team totals row
                if raw_name.lower() in ("team", "totals", "team totals"):
                    totals = {}
                    for gc_col, key in col_map.items():
                        if gc_col in row:
                            totals[key] = _safe_val(row[gc_col])
                    team_totals[json_key] = totals
                    continue

                # Parse player name and number
                # GC format: "FirstName LastName, #NN" or "FirstName LastName #NN"
                name = raw_name
                number = ""
                # Extract number if present
                num_match = re.search(r'#(\d+)', raw_name)
                if num_match:
                    number = num_match.group(1)
                    name = raw_name[:num_match.start()].strip().rstrip(',').strip()

                # Also check the "#" column
                if not number and "#" in row:
                    number = str(row["#"]).strip()

                # Canonical key for merging
                canon = name.lower().strip()

                if canon not in players:
                    # Split name
                    name_parts = name.split(" ", 1)
                    first = name_parts[0]
                    last = name_parts[1] if len(name_parts) > 1 else ""
                    players[canon] = {
                        "first": first,
                        "last": last,
                        "number": number,
                        "core": True,  # will be filtered later by manifest
                    }

                # Update number if we didn't have it
                if number and not players[canon].get("number"):
                    players[canon]["number"] = number

                # Map columns
                stat_obj = {}
                for gc_col, key in col_map.items():
                    if gc_col in row:
                        stat_obj[key] = _safe_val(row[gc_col])

                players[canon][json_key] = stat_obj

        # ---- Post-processing ---- #
        # Scrape actual record from schedule page
        record = self.scrape_record()
        print(f"[GC] Team record: {record}")
        print(f"[GC] Raw player count: {len(players)}")

        # Load roster manifest for core/non-core tagging
        manifest = {}
        if self.use_manifest and self.roster_manifest_path.exists():
            with open(self.roster_manifest_path, "r") as mf:
                manifest = json.load(mf)

        def _norm_name(name: str) -> str:
            return re.sub(r"[^a-z]", "", name.lower())

        core_names = {_norm_name(n) for n in manifest.get("core_players", [])}
        borrowed_names = {_norm_name(n) for n in manifest.get("borrowed_players", [])}
        alias_map = {_norm_name(k): _norm_name(v) for k, v in manifest.get("aliases", {}).items()}
        core_numbers = {str(n).lstrip("0") for n in manifest.get("core_numbers", [])}

        def _is_core(pdata: dict) -> bool:
            full_name = f"{pdata['first']} {pdata['last']}".strip()
            norm = _norm_name(full_name)
            if norm in alias_map:
                norm = alias_map[norm]
            number = str(pdata.get("number", "")).lstrip("0")
            if norm in borrowed_names:
                return False
            if core_names and norm in core_names:
                return True
            if core_numbers and number in core_numbers:
                return True
            if core_names:
                return False
            return True

        # Tag core/non-core and sort (keep ALL players for lineup management)
        roster = []
        for canon, pdata in players.items():
            full_name = f"{pdata['first']} {pdata['last']}".strip()
            pdata["core"] = _is_core(pdata)
            pdata["borrowed"] = not pdata["core"]
            if pdata["borrowed"]:
                print(f"[GC] Non-core player tagged: {full_name}")
            roster.append(pdata)

        # Sort alphabetically by first name
        roster.sort(key=lambda x: x.get("first", "").lower())
        # GUARD: Do not overwrite existing data with empty results
        if not roster:
            print("[GC] ⚠ No players scraped! Skipping team.json write to preserve existing data.")
            return None

        team = {
            "team_name": self.team_name,
            "league": "PCLL Majors",
            "season": "Spring 2026",
            "gc_team_url": self.stats_url,
            "gc_team_id": self.team_id,
            "gc_season_slug": self.season_slug,
            "last_updated": datetime.now(ET).isoformat(),
            "record": record,
            "roster": roster,
            "team_totals": team_totals,
        }

        # Save
        self.out_dir.mkdir(parents=True, exist_ok=True)
        output = self.out_dir / "team.json"
        with open(output, "w") as f:
            json.dump(team, f, indent=2)
        print(f"[GC] ✅ Team data saved to {output} ({len(roster)} players, {len(STAT_VIEWS)} stat categories)")

        return team

    # Legacy method for backward compat with sync_daemon
    def scrape_team_stats(self) -> dict | None:
        """Alias to scrape_all_stats for backward compatibility."""
        return self.scrape_all_stats()

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

    parser = argparse.ArgumentParser(description="GameChanger stats scraper")
    parser.add_argument("--team-id", dest="team_id", default=None, help="GC Team ID")
    parser.add_argument("--season-slug", dest="season_slug", default=None, help="GC season slug (e.g. 2026-spring-sharks)")
    parser.add_argument("--team-name", dest="team_name", default=None, help="Team display name")
    parser.add_argument("--out-dir", dest="out_dir", default=None, help="Output directory for team.json")
    parser.add_argument("--no-manifest", dest="no_manifest", action="store_true", help="Disable roster manifest core tagging")
    parser.add_argument("--box-scores", dest="box_scores", action="store_true", help="Also scrape per-game box scores")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else None
    scraper = GameChangerScraper(
        team_id=args.team_id,
        season_slug=args.season_slug,
        team_name=args.team_name,
        out_dir=out_dir,
        use_manifest=not args.no_manifest,
    )

    with sync_playwright() as pw:
        try:
            scraper.login(pw)
            team = scraper.scrape_all_stats()
            if team:
                print(f"[GC] Successfully scraped {len(team.get('roster', []))} players")
            if args.box_scores:
                print("[GC] Scraping per-game box scores...")
                scraper.scrape_game_box_scores()
        except Exception as e:
            print(f"[GC] Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            scraper.close()


if __name__ == "__main__":
    run()
