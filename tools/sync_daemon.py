import time
import json
import logging
import traceback
import requests
from datetime import datetime
from pathlib import Path
from gc_scraper import GameChangerScraper
from gc_schedule import ScheduleScraper

# ---------------------------------------------------------
# CONSTANTS & CONFIGURATION
# ---------------------------------------------------------
POLL_INTERVAL_IDLE = 3600 * 12   # 12 hours
POLL_INTERVAL_PREGAME = 600      # 10 minutes
POLL_INTERVAL_LIVE = 90          # 1.5 minutes (90 seconds)
GAME_DURATION_HOURS = 2.5        # Assumed max length of a softball game
PREGAME_WINDOW_HOURS = 1.0       # Time before game to enter PREGAME state

N8N_WEBHOOK_URL = "https://n8n.joelycannoli.com/webhook/gc-alert"

DATA_DIR = Path(__file__).parent.parent / "data"
SHARKS_DIR = DATA_DIR / "sharks"
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------
# LOGGING SETUP (Maximal Hardening)
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "sync_daemon.log"),
        logging.StreamHandler()
    ]
)

# ---------------------------------------------------------
# DAEMON LOGIC
# ---------------------------------------------------------
def send_alert(message: str, level: str = "ERROR"):
    """Sends an alert to the local n8n instance if the session drops or errors occur."""
    payload = {
        "source": "sync_daemon",
        "level": level,
        "message": message,
        "timestamp": datetime.now().isoformat()
    }
    try:
        response = requests.post(N8N_WEBHOOK_URL, json=payload, timeout=5)
        if response.status_code == 200:
            logging.info(f"Successfully sent alert to n8n: {message}")
        else:
            logging.warning(f"Failed to alert n8n. Status: {response.status_code}")
    except Exception as e:
        logging.error(f"Error reaching n8n webhook: {e}")

def get_next_game_time():
    """Parses `schedule.json` to find the nearest upcoming game. Returns datetime or None."""
    schedule_file = SHARKS_DIR / "schedule.json"
    if not schedule_file.exists():
        return None
        
    try:
        with open(schedule_file, "r") as f:
            json.load(f)
            # FUTURE HARDENING: parse structured game dates from schedule.json here.
            pass
    except Exception as e:
         logging.error(f"Error reading schedule.json: {e}")
         
    return None

def check_live_override():
    """A failsafe: if a file named 'LIVE_NOW' exists in the data dir, force LIVE mode."""
    return (DATA_DIR / "LIVE_NOW").exists()

def run_sync_cycle():
    """Executes one full sync of schedule and stats, catching ALL exceptions."""
    try:
        logging.info("--- Starting Sync Cycle ---")
        
        # 1. Scrape Schedule
        logging.info("Scraping Schedule...")
        sched_scraper = ScheduleScraper()
        sched_scraper.scrape_schedule()
        
        # 2. Scrape Stats
        logging.info("Scraping Live Stats...")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            stat_scraper = GameChangerScraper()
            stat_scraper.login(pw)
            stat_scraper.scrape_team_stats()

        # Merge multi-team stats if available
        try:
            from aggregate_team_stats import main as run_merge
            run_merge()
        except Exception as e:
            logging.warning(f"Aggregate merge skipped: {e}")
            
        logging.info("--- Sync Cycle Complete ---")
        return True
    except Exception as e:
         msg = f"Fatal Error in sync cycle: {e}\n{traceback.format_exc()}"
         logging.error(msg)
         send_alert(f"Sync Daemon encountered a critical crash: {str(e)}")
         return False

# ---------------------------------------------------------
# API SERVER (Flask)
# ---------------------------------------------------------
from flask import Flask, request, jsonify
from flask_cors import CORS
import threading

app = Flask(__name__)
CORS(app)

@app.route('/api/availability', methods=['GET', 'POST'])
def handle_availability():
    availability_file = SHARKS_DIR / "availability.json"
    
    if request.method == 'POST':
        data = request.json
        with open(availability_file, "w") as f:
            json.dump(data, f, indent=2)
        
        logging.info("Availability updated via API. Re-running analytics tools...")
        try:
            from lineup_optimizer import run as run_lineup
            from swot_analyzer import run_sharks_analysis
            run_lineup()
            run_sharks_analysis()
        except Exception as e:
            logging.error(f"Error re-running tools after update: {e}")
            
        return jsonify({"status": "success"})
    
    # GET logic
    if not availability_file.exists():
        team_file = SHARKS_DIR / "team.json"
        if not team_file.exists():
            return jsonify({})
        with open(team_file, "r") as f:
            team_data = json.load(f)
            return jsonify({f"{p.get('first', '')} {p.get('last', '')}".strip(): True for p in team_data.get("roster", [])})
    
    with open(availability_file, "r") as f:
        return jsonify(json.load(f))

@app.route('/api/games', methods=['GET'])
def handle_games():
    """Return list of parsed scorebook games (index + optional detail)."""
    games_dir = SHARKS_DIR / "games"
    index_path = games_dir / "index.json"
    if not index_path.exists():
        return jsonify([])
    with open(index_path) as f:
        index = json.load(f)
    # If ?detail=1, attach full player batting data
    if request.args.get("detail") == "1":
        for entry in index:
            game_file = games_dir / f"{entry['game_id']}.json"
            if game_file.exists():
                with open(game_file) as gf:
                    full = json.load(gf)
                entry["sharks_batting"] = full.get("sharks_batting", [])
    return jsonify(index)


@app.route('/api/games/<game_id>', methods=['GET'])
def handle_game_detail(game_id):
    """Return full detail for a single game."""
    game_file = SHARKS_DIR / "games" / f"{game_id}.json"
    if not game_file.exists():
        return jsonify({"error": "Not found"}), 404
    with open(game_file) as f:
        return jsonify(json.load(f))


@app.route('/api/borrowed-player', methods=['POST'])
def handle_borrowed_player():
    """Add a borrowed player to roster_manifest.json, optionally trigger stat scrape."""
    data = request.json or {}
    first = (data.get("first") or "").strip()
    last = (data.get("last") or "").strip()
    number = str(data.get("number") or "").strip()
    gc_team_id = (data.get("gc_team_id") or "").strip()

    if not first:
        return jsonify({"error": "first name required"}), 400

    manifest_file = SHARKS_DIR / "roster_manifest.json"
    manifest = {}
    if manifest_file.exists():
        with open(manifest_file) as f:
            manifest = json.load(f)
    if "borrowed_players" not in manifest:
        manifest["borrowed_players"] = []

    # Avoid duplicates
    existing = [p for p in manifest["borrowed_players"]
                if p.get("first", "").lower() == first.lower()
                and p.get("last", "").lower() == last.lower()]
    if not existing:
        entry = {"first": first, "last": last, "number": number, "gc_team_id": gc_team_id}
        manifest["borrowed_players"].append(entry)
        with open(manifest_file, "w") as f:
            json.dump(manifest, f, indent=2)
        logging.info(f"Added borrowed player: {first} {last} #{number}")

    # Optionally scrape stats from their home team
    if gc_team_id:
        try:
            threading.Thread(
                target=_scrape_borrowed_player_stats,
                args=(gc_team_id,),
                daemon=True
            ).start()
        except Exception as e:
            logging.warning(f"Could not start borrowed player scrape: {e}")

    return jsonify({"status": "added", "player": f"{first} {last}"})


def _scrape_borrowed_player_stats(gc_team_id: str):
    """Background task: scrape a borrowed player's home team stats."""
    try:
        from playwright.sync_api import sync_playwright
        from gc_scraper import GameChangerScraper
        from aggregate_team_stats import main as run_merge
        with sync_playwright() as pw:
            scraper = GameChangerScraper(team_id=gc_team_id)
            scraper.login(pw)
            scraper.scrape_all_stats()
            scraper.close()
        run_merge()
        from lineup_optimizer import run as run_lineup
        from swot_analyzer import run_sharks_analysis
        run_lineup()
        run_sharks_analysis()
        logging.info(f"Borrowed player stats scraped for team {gc_team_id}")
    except Exception as e:
        logging.error(f"Error scraping borrowed player stats: {e}")


@app.route('/api/regenerate-lineups', methods=['POST'])
def handle_regenerate_lineups():
    """Regenerate lineups (and optionally SWOT) on demand."""
    try:
        from lineup_optimizer import run as run_lineup
        run_lineup()
        lineups_file = SHARKS_DIR / "lineups.json"
        lineups = {}
        if lineups_file.exists():
            with open(lineups_file) as f:
                lineups = json.load(f)
        # Optionally regenerate SWOT too
        if request.json and request.json.get("swot"):
            from swot_analyzer import run_sharks_analysis
            run_sharks_analysis()
        return jsonify({"status": "ok", "lineups": lineups})
    except Exception as e:
        logging.error(f"Regenerate lineups error: {e}")
        return jsonify({"error": str(e)}), 500


def run_api():
    logging.info("Starting API server on port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# ---------------------------------------------------------
# DAEMON LOGIC
# ---------------------------------------------------------
# ... (rest of the file stays same, but main starts the thread)
def main():
    logging.info("======================================")
    logging.info(" SHARKS REAL-TIME SYNC DAEMON STARTED ")
    logging.info("======================================")
    
    # Parse any scorebook PDFs on startup
    try:
        from parse_scorebook_pdf import run as parse_pdfs
        parse_pdfs()
    except Exception as e:
        logging.warning(f"Scorebook PDF parse skipped: {e}")

    # Start API server in a separate thread
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    
    consecutive_errors = 0
    
    while True:
        try:
            # Determine Polling State
            is_live_forced = check_live_override()
            next_game = get_next_game_time()
            now = datetime.now()
            
            state = "IDLE"
            sleep_duration = POLL_INTERVAL_IDLE
            
            if is_live_forced:
                state = "LIVE (Manual Override)"
                sleep_duration = POLL_INTERVAL_LIVE
            elif next_game:
                # Calculate diff
                time_until_game = (next_game - now).total_seconds()
                
                if time_until_game < -(GAME_DURATION_HOURS * 3600):
                     # Game is way in the past
                     state = "IDLE"
                     sleep_duration = POLL_INTERVAL_IDLE
                elif time_until_game <= 0:
                     # Game is actively playing
                     state = "LIVE"
                     sleep_duration = POLL_INTERVAL_LIVE
                elif time_until_game <= (PREGAME_WINDOW_HOURS * 3600):
                     # Game is starting within an hour
                     state = "PREGAME"
                     sleep_duration = POLL_INTERVAL_PREGAME

            logging.info(f"Current State: {state}. Next cycle in {sleep_duration} seconds.")
            
            success = run_sync_cycle()
            
            if success:
                consecutive_errors = 0
            else:
                consecutive_errors += 1
                if consecutive_errors > 3:
                     # Exponential backoff on chronic failures to avoid slamming GC servers and getting banned
                     sleep_duration = min(sleep_duration * (2 ** (consecutive_errors - 3)), 3600)
                     logging.warning(f"Multiple consecutive errors. Backing off for {sleep_duration} seconds.")
                     send_alert("Sync Daemon is experiencing chronic failures and has entered backoff mode.")
            
            time.sleep(sleep_duration)

        except KeyboardInterrupt:
            logging.info("Daemon stopped by user.")
            break
        except Exception as e:
            logging.critical(f"UNHANDLED EXCEPTION IN DAEMON LOOP: {e}")
            time.sleep(300) # Failsafe sleep before retry

if __name__ == "__main__":
    main()
