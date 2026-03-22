"""
PCLL Organization Scraper
Scrapes the Palm Coast Little League organization page on GameChanger:
  https://web.gc.com/organizations/7ZUyPJwky5DG/

Extracts:
  - Full league schedule (all teams, games, scores)
  - Standings
  - Team IDs -> populates data/pcll_teams.json
  - Optionally follows each opponent team page to scrape their stats

Usage:
  python scrape_pcll_org.py                  # standings + schedule + team IDs
  python scrape_pcll_org.py --teams          # also scrape stats for all opponents
  python scrape_pcll_org.py --team ravens    # scrape one specific opponent by slug
"""
import argparse
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
except ImportError:
    sync_playwright = None

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

ET = ZoneInfo("America/New_York")
ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data"
OPPONENTS_DIR = DATA_DIR / "opponents"
PCLL_TEAMS_FILE = DATA_DIR / "pcll_teams.json"

GC_BASE = "https://web.gc.com"
PCLL_ORG_ID = "7ZUyPJwky5DG"
PCLL_ORG_BASE = f"{GC_BASE}/organizations/{PCLL_ORG_ID}"

GC_EMAIL = os.getenv("GC_EMAIL", "")
GC_PASSWORD = os.getenv("GC_PASSWORD", "")


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def _slug(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '_', s).strip('_')
    # Known canonical slugs
    if 'riptide' in s: return 'riptide_rebels'
    if 'pepper' in s:  return 'peppers'
    if 'raven' in s:   return 'ravens'
    if 'nwvll' in s or 'stihler' in s or '5 star' in s or '5_star' in s: return 'nwvll'
    if 'shark' in s:   return 'sharks'
    return s[:40]


def _wait_content(page, timeout=12000):
    """Wait for GC React content to hydrate."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except PwTimeout:
        pass
    time.sleep(1.5)


# ---------------------------------------------------------------------------
# LOGIN
# ---------------------------------------------------------------------------
def login(page):
    if not GC_EMAIL or not GC_PASSWORD:
        print("[PCLL] No GC credentials — scraping public pages only.")
        return False
    print("[PCLL] Logging in...")
    page.goto(f"{GC_BASE}/login", wait_until="domcontentloaded")
    _wait_content(page, 8000)
    try:
        page.fill('input[type="email"], input[name="email"]', GC_EMAIL, timeout=5000)
        page.fill('input[type="password"], input[name="password"]', GC_PASSWORD, timeout=5000)
        page.keyboard.press("Enter")
        _wait_content(page, 10000)
        print("[PCLL] Logged in.")
        return True
    except Exception as e:
        print(f"[PCLL] Login failed: {e}")
        return False


# ---------------------------------------------------------------------------
# STANDINGS
# ---------------------------------------------------------------------------
def scrape_standings(page) -> list[dict]:
    print("[PCLL] Scraping standings...")
    page.goto(f"{PCLL_ORG_BASE}/standings", wait_until="domcontentloaded")
    _wait_content(page)

    teams = []
    try:
        rows = page.query_selector_all("table tbody tr, [data-testid*='standing'] [role='row']")
        if not rows:
            # Try generic table rows
            rows = page.query_selector_all("tr")

        for row in rows:
            cells = row.query_selector_all("td, [role='cell']")
            if len(cells) < 2:
                continue
            texts = [c.inner_text().strip() for c in cells]
            # Look for team link to extract team ID
            link = row.query_selector("a[href*='/teams/']")
            team_id = ""
            season_slug = ""
            if link:
                href = link.get_attribute("href") or ""
                m = re.search(r'/teams/([^/]+)/([^/]+)', href)
                if m:
                    team_id = m.group(1)
                    season_slug = m.group(2)

            team_name = texts[0] if texts else ""
            if not team_name or team_name.lower() in ('team', 'name', ''):
                continue

            entry = {
                "team_name": team_name,
                "slug": _slug(team_name),
                "gc_team_id": team_id,
                "gc_season_slug": season_slug,
                "stats": texts[1:] if len(texts) > 1 else []
            }
            teams.append(entry)
            print(f"  {team_name:30s} id={team_id or 'unknown'}")

    except Exception as e:
        print(f"[PCLL] Standings parse error: {e}")

    # Fallback: extract team IDs from any team links on the page
    if not any(t["gc_team_id"] for t in teams):
        print("[PCLL] Trying link-based team extraction...")
        links = page.query_selector_all("a[href*='/teams/']")
        seen = set()
        for link in links:
            href = link.get_attribute("href") or ""
            m = re.search(r'/teams/([^/]+)/([^/?]+)', href)
            if m:
                team_id = m.group(1)
                season_slug = m.group(2)
                if team_id in seen:
                    continue
                seen.add(team_id)
                text = link.inner_text().strip() or href
                teams.append({
                    "team_name": text,
                    "slug": _slug(text),
                    "gc_team_id": team_id,
                    "gc_season_slug": season_slug,
                    "stats": []
                })
                print(f"  {text:30s} id={team_id}")

    return teams


# ---------------------------------------------------------------------------
# SCHEDULE
# ---------------------------------------------------------------------------
def scrape_schedule(page) -> list[dict]:
    print("[PCLL] Scraping league schedule...")
    page.goto(f"{PCLL_ORG_BASE}/schedule", wait_until="domcontentloaded")
    _wait_content(page)

    games = []
    # Scroll to load all games
    for _ in range(8):
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        time.sleep(0.6)

    try:
        # GC schedule rows typically have date, home team, away team, score
        rows = page.query_selector_all("[data-testid*='game'], [class*='game-row'], [class*='schedule-row']")
        if not rows:
            rows = page.query_selector_all("li[class*='event'], div[class*='event']")

        for row in rows:
            text = row.inner_text().strip()
            if not text:
                continue

            # Extract team links to get team IDs
            links = row.query_selector_all("a[href*='/teams/']")
            teams_in_game = []
            for link in links:
                href = link.get_attribute("href") or ""
                m = re.search(r'/teams/([^/]+)/([^/?]+)', href)
                if m:
                    teams_in_game.append({
                        "name": link.inner_text().strip(),
                        "gc_team_id": m.group(1),
                        "gc_season_slug": m.group(2),
                    })

            games.append({
                "raw_text": text[:200],
                "teams": teams_in_game,
            })

    except Exception as e:
        print(f"[PCLL] Schedule parse error: {e}")

    # Collect all unique team IDs found across schedule
    return games


# ---------------------------------------------------------------------------
# TEAM STATS
# ---------------------------------------------------------------------------
def scrape_team_stats(page, team_id: str, season_slug: str, team_name: str) -> dict | None:
    """Scrape batting stats for a specific opponent team."""
    url = f"{GC_BASE}/teams/{team_id}/{season_slug}/season-stats"
    print(f"[PCLL] Scraping team stats: {team_name} ({team_id})...")
    try:
        page.goto(url, wait_until="domcontentloaded")
        _wait_content(page)

        # Click Batting > Standard
        try:
            page.click("text=Batting", timeout=5000)
            time.sleep(1)
        except Exception:
            pass

        players = _scrape_stats_table(page, "batting")

        # Click Pitching
        pitching = []
        try:
            page.click("text=Pitching", timeout=5000)
            time.sleep(1.5)
            pitching = _scrape_stats_table(page, "pitching")
        except Exception:
            pass

        return {"team_name": team_name, "gc_team_id": team_id, "batting": players, "pitching": pitching}
    except Exception as e:
        print(f"  Error: {e}")
        return None


def _scrape_stats_table(page, stat_type: str) -> list[dict]:
    """Extract rows from a stats table on the current page."""
    players = []
    try:
        # Wait for table
        page.wait_for_selector("table, [role='table']", timeout=6000)
        headers_els = page.query_selector_all("th, [role='columnheader']")
        headers = [h.inner_text().strip() for h in headers_els if h.inner_text().strip()]

        rows = page.query_selector_all("tbody tr, [role='row']:not([role='columnheader'])")
        for row in rows:
            cells = row.query_selector_all("td, [role='cell']")
            vals = [c.inner_text().strip() for c in cells]
            if not vals or not vals[0]:
                continue
            entry = {"name": vals[0]}
            for i, h in enumerate(headers[1:], 1):
                if i < len(vals):
                    entry[h.lower()] = vals[i]
            players.append(entry)
    except Exception as e:
        print(f"  Table parse error ({stat_type}): {e}")
    return players


# ---------------------------------------------------------------------------
# SAVE
# ---------------------------------------------------------------------------
def save_teams(teams: list[dict]):
    """Write/update pcll_teams.json with discovered team IDs."""
    # Load existing
    existing = {}
    if PCLL_TEAMS_FILE.exists():
        try:
            for t in json.load(open(PCLL_TEAMS_FILE)):
                existing[t.get("slug", t.get("team_name", ""))] = t
        except Exception:
            pass

    for t in teams:
        slug = t["slug"]
        if slug and t.get("gc_team_id"):
            existing[slug] = {
                "team_name": t["team_name"],
                "slug": slug,
                "gc_team_id": t["gc_team_id"],
                "gc_season_slug": t.get("gc_season_slug", ""),
            }

    out = sorted(existing.values(), key=lambda x: x["team_name"].lower())
    PCLL_TEAMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PCLL_TEAMS_FILE, "w") as f:
        json.dump(out, f, indent=2)
    print(f"[PCLL] Saved {len(out)} teams -> {PCLL_TEAMS_FILE}")


def save_opponent(team_data: dict):
    """Save opponent stats to data/opponents/<slug>/team.json."""
    slug = _slug(team_data["team_name"])
    opp_dir = OPPONENTS_DIR / slug
    opp_dir.mkdir(parents=True, exist_ok=True)

    # Build roster from batting rows
    roster = []
    for p in team_data.get("batting", []):
        batting = {k: v for k, v in p.items() if k != "name"}
        roster.append({"name": p.get("name", ""), "number": p.get("#", ""), "batting": batting})

    out = {
        "team_name": team_data["team_name"],
        "slug": slug,
        "gc_team_id": team_data.get("gc_team_id", ""),
        "last_updated": datetime.now(ET).isoformat(),
        "source": "gc_web",
        "batting_stats": team_data.get("batting", []),
        "pitching_stats": team_data.get("pitching", []),
        "roster": roster,
    }
    path = opp_dir / "team.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"[PCLL] Saved {slug}/team.json ({len(roster)} players)")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--teams", action="store_true", help="Also scrape stats for all opponent teams")
    parser.add_argument("--team", help="Scrape one specific opponent slug (e.g. ravens)")
    args = parser.parse_args()

    if sync_playwright is None:
        print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        return

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()

        # Login
        login(page)

        # Scrape standings to get team IDs
        teams = scrape_standings(page)

        # Also scan schedule for more team IDs
        games = scrape_schedule(page)
        for game in games:
            for t in game.get("teams", []):
                if t["gc_team_id"] and not any(x["gc_team_id"] == t["gc_team_id"] for x in teams):
                    teams.append({
                        "team_name": t["name"],
                        "slug": _slug(t["name"]),
                        "gc_team_id": t["gc_team_id"],
                        "gc_season_slug": t["gc_season_slug"],
                    })

        if teams:
            save_teams(teams)
        else:
            print("[PCLL] No teams found from standings/schedule — check if login is required or page structure changed.")

        # Optionally scrape team stats
        targets = []
        if args.team:
            targets = [t for t in teams if t["slug"] == args.team or args.team in t["slug"]]
            if not targets:
                print(f"[PCLL] Team '{args.team}' not found in standings. Available: {[t['slug'] for t in teams]}")
        elif args.teams:
            targets = [t for t in teams if t["slug"] != "sharks" and t.get("gc_team_id")]

        for t in targets:
            if not t.get("gc_team_id"):
                print(f"  Skipping {t['team_name']} — no GC team ID")
                continue
            data = scrape_team_stats(page, t["gc_team_id"], t.get("gc_season_slug", ""), t["team_name"])
            if data:
                save_opponent(data)

        browser.close()

    print("[PCLL] Done.")


if __name__ == "__main__":
    main()
