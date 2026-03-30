"""
League-Wide GameChanger Scraper
Orchestrates gc_scraper.py across ALL teams in a league for complete opponent stats.

Usage:
    python league_scraper.py                      # Scrape all known PCLL teams
    python league_scraper.py --team-ids ID1,ID2   # Specific teams only
    python league_scraper.py --discover            # Auto-discover teams from schedule
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Import the main scraper
sys.path.insert(0, str(Path(__file__).parent))
from gc_scraper import GameChangerScraper, sync_playwright, GC_BASE_URL

DATA_DIR = Path(__file__).parent.parent / "data"
OPPONENTS_DIR = DATA_DIR / "opponents"
SHARKS_DIR = DATA_DIR / "sharks"

# Known PCLL Majors teams — update with actual GC team IDs as discovered
# Format: { "slug": { "team_id": "...", "season_slug": "...", "name": "..." } }
KNOWN_TEAMS_FILE = DATA_DIR / "pcll_teams.json"


def load_known_teams() -> dict:
    """Load known PCLL team configurations."""
    if KNOWN_TEAMS_FILE.exists():
        try:
            with open(KNOWN_TEAMS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[LEAGUE] [WARN] Could not load {KNOWN_TEAMS_FILE}: {e}")
    return {}


def save_known_teams(teams: dict):
    """Persist discovered teams for future runs."""
    KNOWN_TEAMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(KNOWN_TEAMS_FILE, "w") as f:
        json.dump(teams, f, indent=2)
    print(f"[LEAGUE] Saved {len(teams)} teams to {KNOWN_TEAMS_FILE.name}")


def discover_teams_from_schedule(scraper: GameChangerScraper) -> list[dict]:
    """
    Navigate the Sharks' schedule page and extract opponent team IDs
    from game links. GC game URLs contain both team IDs.
    """
    if not scraper.page:
        raise RuntimeError("[LEAGUE] Scraper not logged in.")

    schedule_url = f"{GC_BASE_URL}/teams/{scraper.team_id}/{scraper.season_slug}/schedule"
    print(f"[LEAGUE] Discovering teams from schedule: {schedule_url}")
    scraper.page.goto(schedule_url, wait_until="domcontentloaded", timeout=60000)
    scraper.page.wait_for_timeout(3000)

    # Extract all team links from the schedule page
    discovered = scraper.page.evaluate("""
    (() => {
        const teams = new Map();
        // Look for opponent links — GC schedule shows opponent team name as a link
        const links = document.querySelectorAll('a[href*="/teams/"]');
        links.forEach(a => {
            const href = a.href || '';
            const match = href.match(/\\/teams\\/([A-Za-z0-9_-]+)\\/([A-Za-z0-9_-]+)/);
            if (match) {
                const teamId = match[1];
                const seasonSlug = match[2];
                const name = a.textContent.trim();
                if (name && !teams.has(teamId)) {
                    teams.set(teamId, {
                        team_id: teamId,
                        season_slug: seasonSlug,
                        name: name,
                        discovered_from: 'schedule'
                    });
                }
            }
        });
        return Array.from(teams.values());
    })()
    """)

    print(f"[LEAGUE] Discovered {len(discovered)} teams from schedule links")
    return discovered


def scrape_team(scraper: GameChangerScraper, team_config: dict) -> dict | None:
    """
    Scrape a single opponent team's stats using the existing scraper infrastructure.
    Reuses the logged-in browser session.
    """
    team_id = team_config["team_id"]
    season_slug = team_config["season_slug"]
    team_name = team_config.get("name", team_id)

    # Skip our own team
    if team_id == scraper.team_id:
        print(f"[LEAGUE] Skipping own team: {team_name}")
        return None

    # Create opponent output directory
    slug = team_name.lower().replace(" ", "_").replace("'", "")
    out_dir = OPPONENTS_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[LEAGUE] === Scraping: {team_name} (ID: {team_id}) ===")

    # Temporarily override the scraper's target
    original_team_id = scraper.team_id
    original_season = scraper.season_slug
    original_stats_url = scraper.stats_url
    original_out_dir = scraper.out_dir
    original_team_name = scraper.team_name

    try:
        scraper.team_id = team_id
        scraper.season_slug = season_slug
        scraper.stats_url = f"{GC_BASE_URL}/teams/{team_id}/{season_slug}/season-stats"
        scraper.out_dir = out_dir
        scraper.team_name = team_name

        # Disable manifest-based core tagging for opponents (all players are relevant)
        scraper.use_manifest = False

        team_data = scraper.scrape_all_stats()

        if team_data:
            print(f"[LEAGUE] [OK] {team_name}: {len(team_data.get('roster', []))} players scraped")

            # Also try to scrape box scores for the opponent
            try:
                box_scores = scraper.scrape_game_box_scores()
                if box_scores:
                    print(f"[LEAGUE] [OK] {team_name}: {len(box_scores)} box scores scraped")
            except Exception as e:
                print(f"[LEAGUE] [WARN] Box score scraping failed for {team_name}: {e}")
        else:
            print(f"[LEAGUE] [WARN] No data returned for {team_name}")

        return team_data

    except Exception as e:
        print(f"[LEAGUE] [ERROR] Failed to scrape {team_name}: {e}")
        return None

    finally:
        # Restore original scraper state
        scraper.team_id = original_team_id
        scraper.season_slug = original_season
        scraper.stats_url = original_stats_url
        scraper.out_dir = original_out_dir
        scraper.team_name = original_team_name
        scraper.use_manifest = True


def scrape_league(
    team_ids: list[str] | None = None,
    discover: bool = False,
    delay_between_teams: int = 5,
):
    """
    Main entry point: scrape stats for all teams in the league.

    Args:
        team_ids: Specific team IDs to scrape (None = all known)
        discover: If True, discover teams from schedule first
        delay_between_teams: Seconds to wait between teams (rate limiting)
    """
    if sync_playwright is None:
        print("[LEAGUE] ERROR: Playwright not installed.")
        sys.exit(1)

    known_teams = load_known_teams()
    results = {"scraped": [], "failed": [], "skipped": []}

    with sync_playwright() as pw:
        # Create scraper and login once
        scraper = GameChangerScraper()
        try:
            scraper.login(pw)
            print("[LEAGUE] Authenticated successfully.")

            # Step 1: Discover teams if requested
            if discover:
                discovered = discover_teams_from_schedule(scraper)
                for t in discovered:
                    tid = t["team_id"]
                    if tid not in known_teams:
                        known_teams[tid] = t
                        print(f"[LEAGUE] New team discovered: {t['name']} ({tid})")
                save_known_teams(known_teams)

            # Step 2: Determine which teams to scrape
            if team_ids:
                targets = {tid: known_teams.get(tid, {"team_id": tid, "season_slug": "unknown", "name": tid})
                           for tid in team_ids}
            else:
                targets = known_teams

            if not targets:
                print("[LEAGUE] No teams to scrape. Run with --discover first or provide --team-ids")
                return results

            print(f"\n[LEAGUE] Scraping {len(targets)} teams...")

            # Step 3: Scrape each team, reusing the same browser session
            for i, (tid, config) in enumerate(targets.items()):
                team_data = scrape_team(scraper, config)

                if team_data:
                    results["scraped"].append(config.get("name", tid))
                else:
                    results["failed"].append(config.get("name", tid))

                # Rate limiting between teams
                if i < len(targets) - 1:
                    print(f"[LEAGUE] Waiting {delay_between_teams}s before next team...")
                    time.sleep(delay_between_teams)

            # Step 4: Scrape our own team too (refresh)
            print("\n[LEAGUE] Refreshing Sharks stats...")
            scraper.team_id = os.getenv("GC_TEAM_ID", "NuGgx6WvP7TO")
            scraper.season_slug = os.getenv("GC_SEASON_SLUG", "2026-spring-sharks")
            scraper.stats_url = f"{GC_BASE_URL}/teams/{scraper.team_id}/{scraper.season_slug}/season-stats"
            scraper.out_dir = SHARKS_DIR
            scraper.team_name = os.getenv("TEAM_NAME", "The Sharks")
            scraper.use_manifest = True
            sharks_data = scraper.scrape_all_stats()
            if sharks_data:
                results["scraped"].append("Sharks")

        except Exception as e:
            print(f"[LEAGUE] Fatal error: {e}")
            import traceback
            traceback.print_exc()

        finally:
            scraper.close()

    # Summary
    print("\n" + "=" * 60)
    print("[LEAGUE] SCRAPING COMPLETE")
    print(f"  Scraped: {len(results['scraped'])} teams")
    print(f"  Failed:  {len(results['failed'])} teams")
    if results["failed"]:
        print(f"  Failed teams: {', '.join(results['failed'])}")
    print(f"  Timestamp: {datetime.now(ET).isoformat()}")
    print("=" * 60)

    # Save run summary
    summary_file = DATA_DIR / "league_scrape_summary.json"
    with open(summary_file, "w") as f:
        json.dump({
            **results,
            "timestamp": datetime.now(ET).isoformat(),
            "total_known_teams": len(known_teams),
        }, f, indent=2)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="League-wide GameChanger scraper")
    parser.add_argument(
        "--team-ids", dest="team_ids", default=None,
        help="Comma-separated GC team IDs to scrape"
    )
    parser.add_argument(
        "--discover", action="store_true",
        help="Auto-discover opponent teams from schedule page"
    )
    parser.add_argument(
        "--delay", type=int, default=5,
        help="Seconds between team scrapes (default: 5)"
    )
    args = parser.parse_args()

    ids = args.team_ids.split(",") if args.team_ids else None
    scrape_league(team_ids=ids, discover=args.discover, delay_between_teams=args.delay)
