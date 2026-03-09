import time
import json
import logging
import traceback
import requests
from datetime import datetime, timedelta
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
            data = json.load(f)
            # A robust daemon attempts to parse standard formats or relies on fallback logic
            # Since HTML DOM parsing is unstructured, we look for structured dates if we had them.
            # For now, without structured dates in `schedule.json`, we fall back to manual IDLE polling 
            # unless a manual live override file is created.
            
            # FUTURE HARDENING: parse `data.get("games", [])` properly here.
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
            
        logging.info("--- Sync Cycle Complete ---")
        return True
    except Exception as e:
         msg = f"Fatal Error in sync cycle: {e}\n{traceback.format_exc()}"
         logging.error(msg)
         send_alert(f"Sync Daemon encountered a critical crash: {str(e)}")
         return False

def main():
    logging.info("======================================")
    logging.info(" SHARKS REAL-TIME SYNC DAEMON STARTED ")
    logging.info("======================================")
    
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
