"""
Scrape all teams defined in data/pcll_teams.json and save them to data/opponents/
"""
import json
import logging
from pathlib import Path
from gc_scraper import GameChangerScraper

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def run():
    teams_file = Path(__file__).parent.parent / "data" / "pcll_teams.json"
    if not teams_file.exists():
        logging.error(f"Cannot find {teams_file}")
        return

    with open(teams_file, "r") as f:
        teams = json.load(f)

    if sync_playwright is None:
        logging.error("Playwright not installed.")
        return

    with sync_playwright() as pw:
        # Re-use browser context manually if preferred, but GameChangerScraper takes care of login caching.
        for team in teams:
            team_id = team.get("gc_team_id")
            slug = team.get("gc_season_slug")
            name = team.get("team_name")
            
            if not team_id:
                continue

            # Create an out_dir per team based on ID or slug
            out_dir = Path(__file__).parent.parent / "data" / "opponents" / (slug or team_id)
            out_dir.mkdir(parents=True, exist_ok=True)

            logging.info(f"Scraping opposing team: {name} ({team_id})")
            scraper = GameChangerScraper(
                team_id=team_id,
                season_slug=slug,
                team_name=name,
                out_dir=out_dir,
                use_manifest=False  # No core tags for opponents
            )
            try:
                scraper.login(pw)
                scraper.scrape_all_stats()
            except Exception as e:
                logging.error(f"Failed to scrape {name}: {e}")
            finally:
                scraper.close()

if __name__ == "__main__":
    run()
