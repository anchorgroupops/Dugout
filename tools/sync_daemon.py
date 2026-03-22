import time
import json
import logging
import traceback
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
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
        "timestamp": datetime.now(ET).isoformat()
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


# ---------------------------------------------------------
# SUB AUTO-DEACTIVATION HELPERS
# ---------------------------------------------------------
def _load_roster_manifest():
    """Load core player names from roster_manifest.json."""
    mf = SHARKS_DIR / "roster_manifest.json"
    if not mf.exists():
        return []
    with open(mf) as f:
        data = json.load(f)
    return [n.strip().lower() for n in data.get("core_players", [])]


def _load_sub_tracker():
    """Load sub activation tracker (timestamps)."""
    tracker_file = SHARKS_DIR / "sub_tracker.json"
    if not tracker_file.exists():
        return {}
    with open(tracker_file) as f:
        return json.load(f)


def _save_sub_tracker(tracker):
    SHARKS_DIR.mkdir(parents=True, exist_ok=True)
    with open(SHARKS_DIR / "sub_tracker.json", "w") as f:
        json.dump(tracker, f, indent=2)


def _is_core_player(name):
    core = _load_roster_manifest()
    return name.strip().lower() in core


def auto_deactivate_subs():
    """After a game day, deactivate all non-core players and record in sub_tracker."""
    games_dir = SHARKS_DIR / "games"
    index_file = games_dir / "index.json"
    availability_file = SHARKS_DIR / "availability.json"

    if not index_file.exists() or not availability_file.exists():
        return

    with open(index_file) as f:
        games = json.load(f)
    with open(availability_file) as f:
        avail = json.load(f)

    # Check if any game was yesterday
    yesterday = (datetime.now(ET) - timedelta(days=1)).strftime("%Y-%m-%d")
    game_yesterday = any(g.get("date") == yesterday for g in games)

    if not game_yesterday:
        return

    tracker = _load_sub_tracker()
    changed = False

    for name, status in list(avail.items()):
        if _is_core_player(name):
            continue
        if status is True or (isinstance(status, dict) and status.get("available")):
            # Deactivate this sub
            avail[name] = False
            tracker[name] = {
                "last_active": datetime.now(ET).isoformat(),
                "auto_deactivated": True,
                "deactivated_after_game": yesterday
            }
            logging.info(f"Auto-deactivated sub: {name} (game on {yesterday})")
            changed = True

    if changed:
        with open(availability_file, "w") as f:
            json.dump(avail, f, indent=2)
        _save_sub_tracker(tracker)

@app.route('/api/recent-subs', methods=['GET'])
def handle_recent_subs():
    """Return recently auto-deactivated subs (within last 14 days)."""
    tracker = _load_sub_tracker()
    cutoff = (datetime.now(ET) - timedelta(days=14)).isoformat()
    recent = []
    for name, info in tracker.items():
        if isinstance(info, dict) and info.get("last_active", "") >= cutoff:
            recent.append({"name": name, **info})
    recent.sort(key=lambda x: x.get("last_active", ""), reverse=True)
    return jsonify(recent)


@app.route('/api/availability', methods=['GET', 'POST'])
def handle_availability():
    availability_file = SHARKS_DIR / "availability.json"

    if request.method == 'POST':
        data = request.json

        # Track sub activations in sub_tracker
        old_avail = {}
        if availability_file.exists():
            with open(availability_file) as f:
                old_avail = json.load(f)

        tracker = _load_sub_tracker()
        tracker_changed = False
        for name, new_status in data.items():
            if _is_core_player(name):
                continue
            old_status = old_avail.get(name, False)
            # Sub was just turned ON
            if new_status is True and old_status is not True:
                tracker[name] = {
                    "last_active": datetime.now(ET).isoformat(),
                    "auto_deactivated": False
                }
                tracker_changed = True
        if tracker_changed:
            _save_sub_tracker(tracker)

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
            return jsonify({f"{p.get('first', '')} {p.get('last', '')}".strip(): p.get("core", True) for p in team_data.get("roster", [])})
    
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

@app.route('/api/league-players', methods=['GET'])
def handle_league_players():
    """Return an aggregated list of all players from scraped PCLL teams."""
    opponents_dir = DATA_DIR / "opponents"
    league_players = []
    
    if opponents_dir.exists():
        for team_dir in opponents_dir.iterdir():
            if team_dir.is_dir():
                team_file = team_dir / "team.json"
                if team_file.exists():
                    try:
                        with open(team_file, "r") as f:
                            team_data = json.load(f)
                            team_name = team_data.get("team_name", team_dir.name)
                            gc_team_id = team_data.get("gc_team_id", "")
                            
                            for p in team_data.get("roster", []):
                                league_players.append({
                                    "first": p.get("first", ""),
                                    "last": p.get("last", ""),
                                    "number": p.get("number", ""),
                                    "team_name": team_name,
                                    "gc_team_id": gc_team_id
                                })
                    except Exception as e:
                        logging.error(f"Error reading {team_file}: {e}")
    
    # Sort alphabetically by name
    league_players.sort(key=lambda p: (p["first"].lower(), p["last"].lower()))
    return jsonify(league_players)


@app.route('/api/games/<game_id>', methods=['GET'])
def handle_game_detail(game_id):
    """Return full detail for a single game."""
    game_file = SHARKS_DIR / "games" / f"{game_id}.json"
    if not game_file.exists():
        return jsonify({"error": "Not found"}), 404
    with open(game_file) as f:
        return jsonify(json.load(f))


@app.route('/api/opponents', methods=['GET'])
def handle_opponents():
    """List all scraped opponent teams."""
    opponents_dir = DATA_DIR / "opponents"
    teams = []
    if opponents_dir.exists():
        for team_dir in opponents_dir.iterdir():
            if team_dir.is_dir():
                team_file = team_dir / "team.json"
                if team_file.exists():
                    try:
                        with open(team_file) as f:
                            td = json.load(f)
                        teams.append({
                            "slug": team_dir.name,
                            "team_name": td.get("team_name", team_dir.name),
                            "record": td.get("record", {}),
                            "roster_size": len(td.get("roster", [])),
                        })
                    except Exception as e:
                        logging.error(f"Error reading opponent {team_dir.name}: {e}")
    teams.sort(key=lambda t: t["team_name"].lower())
    return jsonify(teams)


@app.route('/api/matchup/<opponent_slug>', methods=['GET'])
def handle_matchup(opponent_slug):
    """Run matchup analysis: Sharks vs a specific opponent."""
    from swot_analyzer import analyze_matchup, load_team
    our_team = load_team(SHARKS_DIR, prefer_merged=True)
    if not our_team:
        return jsonify({"error": "Sharks team data not found"}), 404
    opp_dir = DATA_DIR / "opponents" / opponent_slug
    opp_team = load_team(opp_dir)
    if not opp_team:
        return jsonify({"error": f"Opponent '{opponent_slug}' not found"}), 404
    result = analyze_matchup(our_team, opp_team)
    return jsonify(result)


def _aggregate_stats_from_games():
    """Aggregate batting stats per player across all parsed game files. Returns dict keyed by jersey number."""
    games_dir = SHARKS_DIR / "games"
    if not games_dir.exists():
        return {}

    player_stats = {}

    for game_file in sorted(games_dir.glob("*.json")):
        if game_file.name == "index.json":
            continue
        try:
            with open(game_file) as f:
                game = json.load(f)
            for player in game.get("sharks_batting", []):
                num = str(player.get("number", "")).strip()
                b = player.get("batting", {})
                if not b or not num:
                    continue

                if num not in player_stats:
                    player_stats[num] = {
                        "number": num,
                        "name": player.get("name", ""),
                        "batting": {"pa": 0, "ab": 0, "h": 0, "singles": 0, "doubles": 0,
                                    "triples": 0, "hr": 0, "bb": 0, "hbp": 0, "so": 0,
                                    "sac": 0, "r": 0, "rbi": 0, "sb": 0},
                        "games_played": 0
                    }

                acc = player_stats[num]["batting"]
                for stat in ["pa", "ab", "h", "singles", "doubles", "triples", "hr",
                             "bb", "hbp", "so", "sac", "r", "rbi", "sb"]:
                    acc[stat] = acc.get(stat, 0) + b.get(stat, 0)
                player_stats[num]["games_played"] += 1
        except Exception as e:
            logging.warning(f"Error aggregating game {game_file.name}: {e}")

    # Compute derived stats
    for ps in player_stats.values():
        b = ps["batting"]
        ab = b.get("ab", 0)
        h = b.get("h", 0)
        bb = b.get("bb", 0)
        hbp = b.get("hbp", 0)
        sac = b.get("sac", 0)
        singles = b.get("singles", 0)
        doubles = b.get("doubles", 0)
        triples = b.get("triples", 0)
        hr = b.get("hr", 0)

        b["avg"] = round(h / ab, 3) if ab > 0 else 0.0
        ob_den = ab + bb + hbp + sac
        b["obp"] = round((h + bb + hbp) / ob_den, 3) if ob_den > 0 else 0.0
        tb = singles + 2 * doubles + 3 * triples + 4 * hr
        b["slg"] = round(tb / ab, 3) if ab > 0 else 0.0
        b["ops"] = round(b["obp"] + b["slg"], 3)

    return player_stats


@app.route('/api/team', methods=['GET'])
def handle_team():
    """Return team data, enriching roster stats from app_stats.json or PDF game files."""
    team_file = SHARKS_DIR / "team_merged.json"
    if not team_file.exists():
        team_file = SHARKS_DIR / "team.json"
    if not team_file.exists():
        return jsonify({"error": "No team data found"}), 404

    with open(team_file) as f:
        team = json.load(f)

    # Prefer app-scraped stats (richer, from BlueStacks GC app)
    app_stats_file = SHARKS_DIR / "app_stats.json"
    app_batting = {}
    if app_stats_file.exists():
        try:
            with open(app_stats_file) as f:
                app_data = json.load(f)
            for p in app_data.get("batting", []):
                num = str(p.get("number", "")).strip()
                if num:
                    app_batting[num] = p
        except Exception as e:
            logging.warning(f"Could not load app_stats.json: {e}")

    # Fall back to PDF-aggregated stats
    pdf_stats = _aggregate_stats_from_games() if not app_batting else {}

    for player in team.get("roster", []):
        num = str(player.get("number", "")).strip()
        existing = player.get("batting", {})
        if existing.get("pa", 0) > 0:
            continue  # GC-scraped stats already present
        if num and num in app_batting:
            ap = app_batting[num]
            player["batting"] = {
                "gp": _safe_int(ap.get("gp")),
                "pa": _safe_int(ap.get("pa")),
                "ab": _safe_int(ap.get("ab")),
                "avg": _safe_float(ap.get("avg")),
                "obp": _safe_float(ap.get("obp")),
                "ops": _safe_float(ap.get("ops")),
                "slg": _safe_float(ap.get("slg")),
                "h": _safe_int(ap.get("h")),
                "hr": _safe_int(ap.get("hr")),
                "rbi": _safe_int(ap.get("rbi")),
                "bb": _safe_int(ap.get("bb")),
                "so": _safe_int(ap.get("so")),
                "sb": _safe_int(ap.get("sb")),
            }
            player["games_played"] = _safe_int(ap.get("gp"))
        elif num and num in pdf_stats:
            player["batting"] = pdf_stats[num]["batting"]
            player["games_played"] = pdf_stats[num]["games_played"]

    return jsonify(team)


def _safe_int(v):
    try:
        return int(str(v).replace(",",""))
    except (TypeError, ValueError):
        return 0


def _safe_float(v):
    try:
        return float(str(v).replace(",",""))
    except (TypeError, ValueError):
        return 0.0


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


def _clean_opponent_name(name: str) -> str:
    """Strip GC schedule prefixes (@ / vs. / vs ) from opponent display names."""
    name = name.strip()
    for prefix in ("@ ", "vs. ", "vs "):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name.strip()


@app.route('/api/schedule', methods=['GET'])
def handle_schedule():
    """Return upcoming and past games from schedule_manual.json."""
    schedule_file = SHARKS_DIR / "schedule_manual.json"
    if not schedule_file.exists():
        return jsonify({"upcoming": [], "past": []})
    with open(schedule_file) as f:
        data = json.load(f)
    # Clean opponent names for display
    for section in ("upcoming", "past"):
        for game in data.get(section, []):
            raw = game.get("opponent", "")
            game["opponent_raw"] = raw
            game["opponent"] = _clean_opponent_name(raw)
    return jsonify(data)


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

    # Auto-deactivate subs from yesterday's game
    try:
        auto_deactivate_subs()
    except Exception as e:
        logging.warning(f"Sub auto-deactivation skipped: {e}")

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
