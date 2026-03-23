import time
import json
import os
import logging
import traceback
import requests
import ipaddress
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

ET = ZoneInfo("America/New_York")
from pathlib import Path
from gc_scraper import GameChangerScraper
from gc_schedule import ScheduleScraper
from stats_normalizer import (
    CANONICAL_BATTING_FIELDS,
    CANONICAL_BATTING_ADV_FIELDS,
    CANONICAL_CATCHING_FIELDS,
    CANONICAL_FIELDING_FIELDS,
    CANONICAL_INNINGS_FIELDS,
    CANONICAL_PITCHING_FIELDS,
    CANONICAL_PITCHING_ADV_FIELDS,
    count_populated_fields,
    normalize_batting_advanced_row,
    normalize_batting_row,
    normalize_catching_row,
    normalize_fielding_row,
    normalize_innings_played_row,
    normalize_pitching_advanced_row,
    normalize_pitching_row,
    safe_float as _safe_float,
    safe_int as _safe_int,
)

# ---------------------------------------------------------
# CONSTANTS & CONFIGURATION
# ---------------------------------------------------------
POLL_INTERVAL_IDLE = 3600 * 12   # 12 hours
POLL_INTERVAL_PREGAME = 600      # 10 minutes
POLL_INTERVAL_LIVE = 90          # 1.5 minutes (90 seconds)
GAME_DURATION_HOURS = 2.5        # Assumed max length of a softball game
PREGAME_WINDOW_HOURS = 1.0       # Time before game to enter PREGAME state
POST_GAME_DEDUP_MINUTES = 30     # Idempotency guard for post-game trigger

N8N_WEBHOOK_URL = "https://n8n.joelycannoli.com/webhook/gc-alert"

DATA_DIR = Path(__file__).parent.parent / "data"
SHARKS_DIR = DATA_DIR / "sharks"
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CORS_ORIGINS = [
    "https://sharks.joelycannoli.com",
    "http://localhost:3000",
    "http://localhost:5173",
]
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", ",".join(DEFAULT_CORS_ORIGINS)).split(",")
    if origin.strip() and origin.strip() != "*"
]
if not CORS_ORIGINS:
    CORS_ORIGINS = DEFAULT_CORS_ORIGINS

DEFAULT_WRITE_ORIGINS = list(DEFAULT_CORS_ORIGINS)
WRITE_ORIGINS = [
    origin.strip()
    for origin in os.getenv("WRITE_ORIGINS", ",".join(DEFAULT_WRITE_ORIGINS)).split(",")
    if origin.strip() and origin.strip() != "*"
]
if not WRITE_ORIGINS:
    WRITE_ORIGINS = DEFAULT_WRITE_ORIGINS


def _origin_hostname(origin: str) -> str:
    try:
        parsed = urlparse(origin)
        return (parsed.hostname or "").strip().lower()
    except Exception:
        return ""

DEFAULT_ALLOWED_HOSTS = [
    "sharks.joelycannoli.com",
    "localhost",
    "127.0.0.1",
    "sharks_api",
    "sharks_dashboard",
]
_derived_allowed_hosts = set()
for _origin in CORS_ORIGINS + WRITE_ORIGINS:
    _host = _origin_hostname(_origin)
    if _host:
        _derived_allowed_hosts.add(_host)
ALLOWED_HOSTS = {
    h.strip().lower()
    for h in os.getenv(
        "ALLOWED_HOSTS",
        ",".join(sorted(set(DEFAULT_ALLOWED_HOSTS).union(_derived_allowed_hosts))),
    ).split(",")
    if h.strip()
}
MAX_JSON_BODY_BYTES = int(os.getenv("MAX_JSON_BODY_BYTES", "131072"))
MUTATE_RATE_WINDOW_SEC = int(os.getenv("MUTATE_RATE_WINDOW_SEC", "60"))
MUTATE_RATE_MAX = int(os.getenv("MUTATE_RATE_MAX", "12"))
_MUTATE_RATE_BUCKETS: dict[str, list[float]] = {}
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

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


def _canonical_team_name(name: str, slug: str = "") -> str:
    raw = (name or "").strip()
    slug_l = (slug or "").strip().lower()
    if slug_l == "sharks" or raw.lower() in ("sharks", "the sharks"):
        return "The Sharks"
    if raw:
        return raw
    if slug_l:
        return slug_l.replace("_", " ").title()
    return "Unknown"


def _parse_record_parts(record: str) -> tuple[int, int, int]:
    import re
    m = re.match(r"^\s*(\d+)\s*-\s*(\d+)(?:\s*-\s*(\d+))?\s*$", str(record or "0-0"))
    if not m:
        return 0, 0, 0
    w = int(m.group(1))
    l = int(m.group(2))
    t = int(m.group(3) or 0)
    return w, l, t


def _request_origin() -> str:
    origin = (request.headers.get("Origin") or "").strip()
    if origin:
        return origin
    referer = (request.headers.get("Referer") or "").strip()
    if referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def _client_ip() -> str:
    xff = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return xff or (request.remote_addr or "")


def _is_private_or_loopback(ip_str: str) -> bool:
    try:
        ip_obj = ipaddress.ip_address(ip_str)
        return ip_obj.is_private or ip_obj.is_loopback
    except Exception:
        return False


def _guard_mutating_request():
    """Strict origin/content checks for write endpoints.
    Returns (response, status) tuple on rejection, else None."""
    if not request.is_json:
        return jsonify({"error": "json_required"}), 415

    req_origin = _request_origin()
    if req_origin:
        if req_origin not in WRITE_ORIGINS:
            logging.warning(f"[Security] Blocked mutating request from disallowed origin: {req_origin}")
            return jsonify({"error": "forbidden_origin"}), 403
        return None

    # Requests without origin/referer are only allowed from private/loopback addresses.
    ip = _client_ip()
    if not _is_private_or_loopback(ip):
        logging.warning(f"[Security] Blocked mutating request with no origin from non-private IP: {ip}")
        return jsonify({"error": "forbidden"}), 403
    return None


def _read_json_file(path: Path, default=None, retries: int = 3, retry_delay: float = 0.08):
    """Read JSON with small retries to tolerate concurrent writer truncation windows."""
    for attempt in range(retries):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            if attempt == retries - 1:
                logging.warning(f"JSON read failed for {path}: {e}")
                return default
            time.sleep(retry_delay * (attempt + 1))
    return default

def _enrich_team_with_app_stats(team_data: dict) -> dict:
    """Apply app_stats.json stats to Sharks roster (batting, pitching, fielding).
    Keyed by jersey number. Mutates team_data in place and returns it."""
    app_stats_file = SHARKS_DIR / "app_stats.json"
    if not app_stats_file.exists():
        return team_data
    try:
        with open(app_stats_file) as f:
            app_data = json.load(f)
        app_batting = {
            str(p.get("number", "")).strip(): p
            for p in app_data.get("batting", [])
            if str(p.get("number", "")).strip()
        }
        app_pitching = {
            str(p.get("number", "")).strip(): p
            for p in app_data.get("pitching", [])
            if str(p.get("number", "")).strip()
        }
        app_fielding = {
            str(p.get("number", "")).strip(): p
            for p in app_data.get("fielding", [])
            if str(p.get("number", "")).strip()
        }

        applied_batting = 0
        applied_pitching = 0
        applied_fielding = 0
        for player in team_data.get("roster", []):
            num = str(player.get("number", "")).strip()
            if num and num in app_batting:
                app_b = app_batting[num]
                nb = normalize_batting_row(app_b)
                player["batting"] = {
                    "pa": nb["pa"],
                    "ab": nb["ab"],
                    "h": nb["h"],
                    "singles": nb["singles"],
                    "doubles": nb["doubles"],
                    "triples": nb["triples"],
                    "hr": nb["hr"],
                    "bb": nb["bb"],
                    "hbp": nb["hbp"],
                    "so": nb["so"],
                    "rbi": nb["rbi"],
                    "sb": nb["sb"],
                    "r": nb["r"],
                    "sac": nb["sac"],
                    "1b": nb["1b"],
                    "2b": nb["2b"],
                    "3b": nb["3b"],
                    "avg": nb["avg"],
                    "obp": nb["obp"],
                    "slg": nb["slg"],
                    "ops": nb["ops"],
                }
                # Preserve advanced percentages in their native % format for UI consistency.
                existing_adv = player.get("batting_advanced", {}) if isinstance(player.get("batting_advanced"), dict) else {}
                player["batting_advanced"] = {
                    **existing_adv,
                    "gp": _safe_float(app_b.get("gp", existing_adv.get("gp", 0))),
                    "pa": _safe_float(app_b.get("pa", existing_adv.get("pa", nb["pa"]))),
                    "ab": _safe_float(app_b.get("ab", existing_adv.get("ab", nb["ab"]))),
                    "qab": _safe_float(app_b.get("qab", existing_adv.get("qab", 0))),
                    "qab_pct": _safe_float(app_b.get("qab_pct", existing_adv.get("qab_pct", 0))),
                    "pa_per_bb": _safe_float(app_b.get("pa_per_bb", existing_adv.get("pa_per_bb", 0))),
                    "bb_per_k": _safe_float(app_b.get("bb_per_k", existing_adv.get("bb_per_k", 0))),
                    "c_pct": _safe_float(app_b.get("c_pct", existing_adv.get("c_pct", 0))),
                    "hhb": _safe_float(app_b.get("hhb", existing_adv.get("hhb", 0))),
                    "ld_pct": _safe_float(app_b.get("ld_pct", existing_adv.get("ld_pct", 0))),
                    "fb_pct": _safe_float(app_b.get("fb_pct", existing_adv.get("fb_pct", 0))),
                    "gb_pct": _safe_float(app_b.get("gb_pct", existing_adv.get("gb_pct", 0))),
                }
                applied_batting += 1

            if num and num in app_pitching:
                app_p = app_pitching[num]
                np = normalize_pitching_row(app_p)
                player["pitching"] = {
                    "ip": app_p.get("ip", np["ip"]),
                    "gp": _safe_float(app_p.get("gp", 0)),
                    "gs": _safe_float(app_p.get("gs", 0)),
                    "bf": _safe_float(app_p.get("bf", 0)),
                    "np": _safe_float(app_p.get("pitches", app_p.get("np", 0))),
                    "w": _safe_float(app_p.get("w", 0)),
                    "l": _safe_float(app_p.get("l", 0)),
                    "sv": _safe_float(app_p.get("sv", 0)),
                    "svo": _safe_float(app_p.get("svo", 0)),
                    "bs": _safe_float(app_p.get("bs", 0)),
                    "h": np["h"],
                    "r": _safe_float(app_p.get("r", 0)),
                    "er": np["er"],
                    "bb": np["bb"],
                    "so": np["so"],
                    "hr": _safe_float(app_p.get("hr", 0)),
                    "era": np["era"],
                    "whip": np["whip"],
                }
                existing_padv = player.get("pitching_advanced", {}) if isinstance(player.get("pitching_advanced"), dict) else {}
                norm_padv = normalize_pitching_advanced_row(app_p)
                player["pitching_advanced"] = {**existing_padv, **norm_padv}
                applied_pitching += 1

            if num and num in app_fielding:
                app_f = app_fielding[num]
                nf = normalize_fielding_row(app_f)
                player["fielding"] = {
                    "tc": _safe_float(app_f.get("tc", 0)),
                    "a": nf["a"],
                    "po": nf["po"],
                    "fpct": nf["fpct"],
                    "e": nf["e"],
                    "dp": _safe_float(app_f.get("dp", 0)),
                    "tp": _safe_float(app_f.get("tp", 0)),
                }
                applied_fielding += 1

        logging.info(
            "[Enrich] Applied app_stats: batting=%s pitching=%s fielding=%s",
            applied_batting,
            applied_pitching,
            applied_fielding,
        )
    except Exception as e:
        logging.warning(f"app_stats enrichment failed: {e}")
    return team_data


def _aggregate_opponent_stats_from_games(opponent_slug: str) -> list:
    """Aggregate opponent_batting stats from scorebook game JSON files for a given opponent.
    Returns flattened batting_stats[] rows (ab/h/bb...) for direct use in matchup aggregator."""
    games_dir = SHARKS_DIR / "games"
    if not games_dir.exists():
        return []
    player_acc: dict = {}
    slug_clean = opponent_slug.lower().replace("-", "_").replace(" ", "_")
    for game_file in sorted(games_dir.glob("*.json")):
        if game_file.name == "index.json":
            continue
        try:
            with open(game_file) as f:
                game = json.load(f)
            game_opp = game.get("opponent", "").lower().replace(" ", "_").replace("-", "_")
            # Flexible slug match in either direction
            if slug_clean not in game_opp and game_opp not in slug_clean:
                continue
            logging.info(f"[OpponentStats] Matched game file {game_file.name} for slug '{opponent_slug}'")
            for p in game.get("opponent_batting", []):
                num = str(p.get("number", "")).strip()
                name = p.get("name", "").strip()
                key = num if num else name
                if not key:
                    continue
                b = normalize_batting_row(p)
                if key not in player_acc:
                    player_acc[key] = {"name": name, "number": num, **{k: 0 for k in CANONICAL_BATTING_FIELDS}, "sac": 0}
                acc = player_acc[key]
                for stat in CANONICAL_BATTING_FIELDS:
                    acc[stat] = acc.get(stat, 0) + b.get(stat, 0)
                acc["sac"] = acc.get("sac", 0) + b.get("sac", 0)
        except Exception as e:
            logging.warning(f"Opponent game-stat aggregation error ({game_file.name}): {e}")

    # Compute derived rates and compatibility aliases so swot_analyzer can consume directly.
    for pdata in player_acc.values():
        ab = pdata.get("ab", 0)
        h = pdata.get("h", 0)
        bb = pdata.get("bb", 0)
        hbp = pdata.get("hbp", 0)
        one_b = pdata.get("1b", 0)
        two_b = pdata.get("2b", 0)
        three_b = pdata.get("3b", 0)
        hr = pdata.get("hr", 0)
        pa = pdata.get("pa", 0) or (ab + bb + hbp + pdata.get("sac", 0))
        tb = one_b + 2 * two_b + 3 * three_b + 4 * hr
        pdata["pa"] = pa
        pdata["avg"] = round(h / ab, 3) if ab > 0 else 0.0
        pdata["obp"] = round((h + bb + hbp) / pa, 3) if pa > 0 else 0.0
        pdata["slg"] = round(tb / ab, 3) if ab > 0 else 0.0
        pdata["ops"] = round(pdata["obp"] + pdata["slg"], 3)
        pdata["singles"] = one_b
        pdata["doubles"] = two_b
        pdata["triples"] = three_b

    result = list(player_acc.values())
    if result:
        logging.info(f"[OpponentStats] Aggregated {len(result)} players for '{opponent_slug}'")
    return result


def _collect_pipeline_health() -> dict:
    """Build pipeline health coverage metrics across app/web/game feeds."""
    app_stats_file = SHARKS_DIR / "app_stats.json"
    team_merged_file = SHARKS_DIR / "team_merged.json"
    games_dir = SHARKS_DIR / "games"
    opponents_dir = DATA_DIR / "opponents"

    app_data = {}
    if app_stats_file.exists():
        try:
            with open(app_stats_file) as f:
                app_data = json.load(f)
        except Exception as e:
            logging.warning(f"[Health] Could not read app_stats.json: {e}")

    team_data = {}
    if team_merged_file.exists():
        try:
            with open(team_merged_file) as f:
                team_data = json.load(f)
        except Exception as e:
            logging.warning(f"[Health] Could not read team_merged.json: {e}")

    app_batting = app_data.get("batting", [])
    app_pitching = app_data.get("pitching", [])
    app_fielding = app_data.get("fielding", [])
    team_roster = team_data.get("roster", [])

    games = []
    sharks_rows = []
    opponent_rows = []
    if games_dir.exists():
        for game_file in sorted(games_dir.glob("*.json")):
            if game_file.name == "index.json":
                continue
            try:
                with open(game_file) as f:
                    game = json.load(f)
                games.append(game_file.name)
                sharks_rows.extend(game.get("sharks_batting", []))
                opponent_rows.extend(game.get("opponent_batting", []))
            except Exception as e:
                logging.warning(f"[Health] Could not read game file {game_file.name}: {e}")

    opponent_team_files = 0
    opponent_batting = []
    opponent_pitching = []
    opponent_fielding = []
    if opponents_dir.exists():
        for team_dir in opponents_dir.iterdir():
            if not team_dir.is_dir():
                continue
            team_file = team_dir / "team.json"
            if not team_file.exists():
                continue
            try:
                with open(team_file) as f:
                    td = json.load(f)
                opponent_team_files += 1
                opponent_batting.extend(td.get("batting_stats", []))
                opponent_pitching.extend(td.get("pitching_stats", []))
                opponent_fielding.extend(td.get("fielding_stats", []))
            except Exception as e:
                logging.warning(f"[Health] Could not read opponent team file {team_file}: {e}")

    team_batting_adv_rows = [p.get("batting_advanced", {}) for p in team_roster]
    team_pitching_adv_rows = [p.get("pitching_advanced", {}) for p in team_roster]
    team_catching_rows = [p.get("catching", {}) for p in team_roster]
    team_innings_rows = [p.get("innings_played", {}) for p in team_roster]

    return {
        "generated_at": datetime.now(ET).isoformat(),
        "schema": {
            "batting": CANONICAL_BATTING_FIELDS,
            "batting_advanced": CANONICAL_BATTING_ADV_FIELDS,
            "pitching": CANONICAL_PITCHING_FIELDS,
            "pitching_advanced": CANONICAL_PITCHING_ADV_FIELDS,
            "fielding": CANONICAL_FIELDING_FIELDS,
            "catching": CANONICAL_CATCHING_FIELDS,
            "innings_played": CANONICAL_INNINGS_FIELDS,
        },
        "feeds": {
            "app_stats": {
                "batting_rows": len(app_batting),
                "pitching_rows": len(app_pitching),
                "fielding_rows": len(app_fielding),
                "batting_populated_counts": count_populated_fields(app_batting, CANONICAL_BATTING_FIELDS, normalize_batting_row),
                "batting_advanced_populated_counts": count_populated_fields(app_batting, CANONICAL_BATTING_ADV_FIELDS, normalize_batting_advanced_row),
                "pitching_populated_counts": count_populated_fields(app_pitching, CANONICAL_PITCHING_FIELDS, normalize_pitching_row),
                "pitching_advanced_populated_counts": count_populated_fields(app_pitching, CANONICAL_PITCHING_ADV_FIELDS, normalize_pitching_advanced_row),
                "fielding_populated_counts": count_populated_fields(app_fielding, CANONICAL_FIELDING_FIELDS, normalize_fielding_row),
            },
            "team_merged": {
                "roster_rows": len(team_roster),
                "batting_populated_counts": count_populated_fields([p.get("batting", {}) for p in team_roster], CANONICAL_BATTING_FIELDS, normalize_batting_row),
                "batting_advanced_populated_counts": count_populated_fields(team_batting_adv_rows, CANONICAL_BATTING_ADV_FIELDS, normalize_batting_advanced_row),
                "pitching_populated_counts": count_populated_fields([p.get("pitching", {}) for p in team_roster], CANONICAL_PITCHING_FIELDS, normalize_pitching_row),
                "pitching_advanced_populated_counts": count_populated_fields(team_pitching_adv_rows, CANONICAL_PITCHING_ADV_FIELDS, normalize_pitching_advanced_row),
                "fielding_populated_counts": count_populated_fields([p.get("fielding", {}) for p in team_roster], CANONICAL_FIELDING_FIELDS, normalize_fielding_row),
                "catching_populated_counts": count_populated_fields(team_catching_rows, CANONICAL_CATCHING_FIELDS, normalize_catching_row),
                "innings_played_populated_counts": count_populated_fields(team_innings_rows, CANONICAL_INNINGS_FIELDS, normalize_innings_played_row),
            },
            "games": {
                "game_files": len(games),
                "game_ids": games,
                "sharks_batting_rows": len(sharks_rows),
                "opponent_batting_rows": len(opponent_rows),
                "sharks_batting_populated_counts": count_populated_fields(sharks_rows, CANONICAL_BATTING_FIELDS, normalize_batting_row),
                "opponent_batting_populated_counts": count_populated_fields(opponent_rows, CANONICAL_BATTING_FIELDS, normalize_batting_row),
            },
            "opponents": {
                "team_files": opponent_team_files,
                "batting_rows": len(opponent_batting),
                "pitching_rows": len(opponent_pitching),
                "fielding_rows": len(opponent_fielding),
                "batting_populated_counts": count_populated_fields(opponent_batting, CANONICAL_BATTING_FIELDS, normalize_batting_row),
                "pitching_populated_counts": count_populated_fields(opponent_pitching, CANONICAL_PITCHING_FIELDS, normalize_pitching_row),
                "fielding_populated_counts": count_populated_fields(opponent_fielding, CANONICAL_FIELDING_FIELDS, normalize_fielding_row),
            },
        },
        "required_field_coverage": {
            "batting": count_populated_fields(
                app_batting + [p.get("batting", {}) for p in team_roster] + sharks_rows + opponent_rows + opponent_batting,
                CANONICAL_BATTING_FIELDS,
                normalize_batting_row,
            ),
            "pitching": count_populated_fields(
                app_pitching + [p.get("pitching", {}) for p in team_roster] + opponent_pitching,
                CANONICAL_PITCHING_FIELDS,
                normalize_pitching_row,
            ),
            "fielding": count_populated_fields(
                app_fielding + [p.get("fielding", {}) for p in team_roster] + opponent_fielding,
                CANONICAL_FIELDING_FIELDS,
                normalize_fielding_row,
            ),
        },
    }


def _write_pipeline_health_artifact():
    out = _collect_pipeline_health()
    out_file = SHARKS_DIR / "pipeline_health.json"
    with open(out_file, "w") as f:
        json.dump(out, f, indent=2)
    app_rows = out["feeds"]["app_stats"]["batting_rows"]
    team_rows = out["feeds"]["team_merged"]["roster_rows"]
    game_rows = out["feeds"]["games"]["opponent_batting_rows"]
    opp_rows = out["feeds"]["opponents"]["batting_rows"]
    logging.info(
        "[Health] pipeline_health.json updated (app batting rows=%s, team roster=%s, opponent game rows=%s, opponent team batting rows=%s)",
        app_rows,
        team_rows,
        game_rows,
        opp_rows,
    )
    return out


def get_next_game_time():
    """Parse schedule_manual.json to find the nearest upcoming game. Returns datetime or None."""
    schedule_file = SHARKS_DIR / "schedule_manual.json"
    if not schedule_file.exists():
        return None
    try:
        with open(schedule_file) as f:
            sched = json.load(f)
        now = datetime.now(ET)
        for game in sched.get("upcoming", []):
            if not game.get("is_game"):
                continue
            date_str = game.get("date", "")
            time_str = game.get("time", "12:00 PM")
            if not date_str:
                continue
            try:
                naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %I:%M %p")
            except ValueError:
                try:
                    naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                except ValueError:
                    continue
            game_dt = naive_dt.replace(tzinfo=ET)
            # Include games that could still be in progress
            if game_dt > now - timedelta(hours=GAME_DURATION_HOURS):
                return game_dt
    except Exception as e:
        logging.error(f"get_next_game_time error: {e}")
    return None

def check_live_override():
    """A failsafe: if a file named 'LIVE_NOW' exists in the data dir, force LIVE mode."""
    return (DATA_DIR / "LIVE_NOW").exists()

def run_sync_cycle():
    """Executes one full sync of schedule and stats, catching ALL exceptions."""
    try:
        logging.info("--- Starting Sync Cycle ---")

        # 0. Refresh opponent discovery from public org/team feeds.
        try:
            from opponent_discovery import discover_and_persist_opponents
            discovery = discover_and_persist_opponents(
                data_dir=DATA_DIR,
                sharks_team_id=os.getenv("GC_TEAM_ID", "NuGgx6WvP7TO"),
            )
            missing = len((discovery or {}).get("missing_schedule_opponents", []))
            logging.info(f"[Sync] Opponent discovery refreshed (missing schedule opponents={missing}).")
        except Exception as e:
            logging.warning(f"[Sync] Opponent discovery skipped: {e}")
        
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

        # Write team_enriched.json (team_merged + app_stats) for downstream tools
        try:
            team_file = SHARKS_DIR / ("team_merged.json" if (SHARKS_DIR / "team_merged.json").exists() else "team.json")
            with open(team_file) as f:
                team_data = json.load(f)
            _enrich_team_with_app_stats(team_data)
            enriched_file = SHARKS_DIR / "team_enriched.json"
            with open(enriched_file, "w") as f:
                json.dump(team_data, f)
            logging.info("[Sync] team_enriched.json written.")
        except Exception as e:
            logging.warning(f"team_enriched.json write skipped: {e}")

        # Re-run SWOT and lineup optimizer with enriched data
        try:
            from swot_analyzer import run_sharks_analysis
            run_sharks_analysis()
            logging.info("[Sync] SWOT analysis refreshed.")
        except Exception as e:
            logging.warning(f"SWOT re-run skipped: {e}")
        try:
            from lineup_optimizer import run as run_lineup
            run_lineup()
            logging.info("[Sync] Lineup optimizer refreshed.")
        except Exception as e:
            logging.warning(f"Lineup re-run skipped: {e}")

        # Refresh pipeline coverage metrics artifact
        try:
            _write_pipeline_health_artifact()
        except Exception as e:
            logging.warning(f"[Health] pipeline artifact write skipped: {e}")

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
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge, HTTPException

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_JSON_BODY_BYTES
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = False
CORS(app, origins=CORS_ORIGINS)
_MUTATE_RATE_LOCK = threading.Lock()

_API_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "X-Permitted-Cross-Domain-Policies": "none",
}


def _normalized_request_host() -> str:
    host = (request.headers.get("X-Forwarded-Host") or request.host or "").split(",")[0].strip().lower()
    if not host:
        return ""
    if host.startswith("["):
        # IPv6 host format: [::1]:5000
        closing = host.find("]")
        return host[1:closing] if closing > 0 else host
    return host.split(":")[0].strip()


def _is_mutating_api_request() -> bool:
    return request.path.startswith("/api/") and request.method.upper() in MUTATING_METHODS


def _guard_mutating_rate_limit():
    """In-app write throttle as defense-in-depth if edge limits are bypassed.
    Returns (response, status) tuple when blocked, else None."""
    if not _is_mutating_api_request():
        return None

    now_ts = time.time()
    key = f"{_client_ip()}:{request.path}"
    window_floor = now_ts - MUTATE_RATE_WINDOW_SEC

    with _MUTATE_RATE_LOCK:
        bucket = _MUTATE_RATE_BUCKETS.get(key, [])
        bucket = [ts for ts in bucket if ts >= window_floor]
        if len(bucket) >= MUTATE_RATE_MAX:
            retry_after = max(1, int(MUTATE_RATE_WINDOW_SEC - (now_ts - bucket[0])))
            resp = jsonify({
                "error": "rate_limited",
                "scope": "mutating",
                "window_seconds": MUTATE_RATE_WINDOW_SEC,
                "max_requests": MUTATE_RATE_MAX,
            })
            resp.headers["Retry-After"] = str(retry_after)
            return resp, 429
        bucket.append(now_ts)
        _MUTATE_RATE_BUCKETS[key] = bucket

        # Opportunistic cleanup of stale keys.
        if len(_MUTATE_RATE_BUCKETS) > 2000:
            stale_before = now_ts - (MUTATE_RATE_WINDOW_SEC * 2)
            stale_keys = [k for k, v in _MUTATE_RATE_BUCKETS.items() if not v or v[-1] < stale_before]
            for stale_key in stale_keys[:500]:
                _MUTATE_RATE_BUCKETS.pop(stale_key, None)
    return None


@app.before_request
def _security_before_request():
    host = _normalized_request_host()
    if host and ALLOWED_HOSTS and host not in ALLOWED_HOSTS:
        logging.warning(f"[Security] Blocked request with disallowed host header: {host}")
        return jsonify({"error": "invalid_host"}), 400

    content_length = request.content_length
    if content_length is not None and content_length > MAX_JSON_BODY_BYTES:
        return jsonify({"error": "payload_too_large", "max_bytes": MAX_JSON_BODY_BYTES}), 413

    if _is_mutating_api_request():
        return _guard_mutating_rate_limit()
    return None


@app.after_request
def _security_after_request(response):
    for key, value in _API_SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    if request.path.startswith("/api/"):
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        response.headers.setdefault("Cache-Control", "no-store")
    response.headers.pop("Server", None)
    return response


@app.errorhandler(RequestEntityTooLarge)
def _handle_too_large(_exc):
    return jsonify({"error": "payload_too_large", "max_bytes": MAX_JSON_BODY_BYTES}), 413


@app.errorhandler(BadRequest)
def _handle_bad_request(_exc):
    return jsonify({"error": "bad_request"}), 400


@app.errorhandler(Exception)
def _handle_unexpected_error(exc):
    if isinstance(exc, HTTPException):
        return exc
    logging.exception("[API] Unhandled exception: %s", exc)
    return jsonify({"error": "internal_error"}), 500


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
    schedule_file = SHARKS_DIR / "schedule_manual.json"
    availability_file = SHARKS_DIR / "availability.json"

    if not schedule_file.exists() or not availability_file.exists():
        return

    with open(schedule_file) as f:
        sched = json.load(f)
    with open(availability_file) as f:
        avail = json.load(f)

    # Find the most recent past game
    past_games = sched.get("past", [])
    if not past_games:
        return
        
    # Sort past games by date descending to get the literal last game
    past_games.sort(key=lambda x: x.get("date", ""), reverse=True)
    last_game = past_games[0]
    last_game_date_str = last_game.get("date", "")[:10]  # yyyy-mm-dd
    
    if not last_game_date_str:
        return
        
    # If the last game's date is strictly before today (in ET), we are post-game day.
    today_str = datetime.now(ET).strftime("%Y-%m-%d")
    is_post_game_day = last_game_date_str < today_str

    if not is_post_game_day:
        return

    tracker = _load_sub_tracker()
    changed = False

    for name, status in list(avail.items()):
        if _is_core_player(name):
            continue
        # If the sub is currently active
        if status is True or (isinstance(status, dict) and status.get("available")):
            # Check if we ALREADY auto-deactivated them for this specific game to avoid spamming
            already_deactivated = isinstance(tracker.get(name), dict) and tracker[name].get("deactivated_after_game") == last_game_date_str
            if not already_deactivated:
                # Deactivate this sub
                avail[name] = False
                tracker[name] = {
                    "last_active": datetime.now(ET).isoformat(),
                    "auto_deactivated": True,
                    "deactivated_after_game": last_game_date_str
                }
                logging.info(f"Auto-deactivated sub: {name} (last game was on {last_game_date_str})")
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
        blocked = _guard_mutating_request()
        if blocked:
            return blocked
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({"error": "invalid_json_object"}), 400

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

def _build_games_feed(include_detail: bool = False) -> list[dict]:
    """Return parsed scorebook games enriched with W/L from schedule.
    Optionally includes per-player batting detail from game JSON files."""
    import re as _re
    games_dir = SHARKS_DIR / "games"
    index_path = games_dir / "index.json"
    schedule_file = SHARKS_DIR / "schedule_manual.json"

    pdf_games = []
    if index_path.exists():
        pdf_games = _read_json_file(index_path, default=[]) or []

    # Load schedule W/L results
    sched_results = []
    if schedule_file.exists():
        sched_data = _read_json_file(schedule_file, default={}) or {}
        for g in sched_data.get("past", []):
            if g.get("result"):
                sched_results.append(g)

    def _slug(name: str) -> str:
        return _re.sub(r'[^a-z0-9]', '', (name or '').lower())

    # Enrich PDF games with schedule result by fuzzy opponent match
    for game in pdf_games:
        opp_slug = _slug(game.get("opponent", ""))
        for sg in sched_results:
            sg_opp = _clean_opponent_name(sg.get("opponent", ""))
            if _slug(sg_opp) and (_slug(sg_opp) in opp_slug or opp_slug in _slug(sg_opp)):
                game["result"] = sg.get("result", "")
                game["score"] = sg.get("score", "")
                break

    # Optional detail: attach full player batting data
    if include_detail:
        for entry in pdf_games:
            game_file = games_dir / f"{entry['game_id']}.json"
            if game_file.exists():
                full = _read_json_file(game_file, default={}) or {}
                entry["sharks_batting"] = full.get("sharks_batting", [])

    # Also surface schedule games with results that have no PDF (schedule-only)
    pdf_opps = {_slug(g.get("opponent", "")) for g in pdf_games}
    for sg in sched_results:
        sg_opp = _clean_opponent_name(sg.get("opponent", ""))
        sg_slug = _slug(sg_opp)
        if not any(sg_slug and (sg_slug in po or po in sg_slug) for po in pdf_opps if po):
            pdf_games.append({
                "game_id": f"sched_{sg.get('date','')[:10]}_{sg_slug[:20]}",
                "date": sg.get("date", ""),
                "opponent": sg_opp,
                "sharks_side": sg.get("home_away", ""),
                "result": sg.get("result", ""),
                "score": sg.get("score", ""),
                "sharks_totals": None,
            })

    pdf_games.sort(key=lambda x: x.get("date", ""), reverse=True)
    return pdf_games


@app.route('/api/games', methods=['GET'])
def handle_games():
    """Return parsed scorebook games enriched with W/L from schedule."""
    include_detail = request.args.get("detail") == "1"
    pdf_games = _build_games_feed(include_detail=include_detail)
    return jsonify(pdf_games)

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


@app.route('/api/standings', methods=['GET'])
def handle_standings():
    """Return PCLL league standings."""
    league_name = "PCLL Spring '26 Majors Softball"
    standings: list[dict] = []

    standings_file = DATA_DIR / "pcll_standings.json"
    if standings_file.exists():
        try:
            payload = _read_json_file(standings_file, default={}) or {}
            league_name = payload.get("league") or league_name
            for row in payload.get("standings", []):
                slug = str(row.get("slug", "")).strip().lower()
                record = str(row.get("record", "")).strip()
                w = row.get("w")
                l = row.get("l")
                t = row.get("t", 0)
                if w is None or l is None:
                    rw, rl, rt = _parse_record_parts(record)
                    w = rw
                    l = rl
                    t = rt
                try:
                    w = int(w)
                    l = int(l)
                    t = int(t)
                except Exception:
                    w, l, t = _parse_record_parts(record)
                gp = w + l + t
                pct = round(w / gp, 3) if gp > 0 else 0.0
                standings.append({
                    "slug": slug or "unknown",
                    "team_name": _canonical_team_name(row.get("team_name", slug), slug),
                    "record": f"{w}-{l}" if t == 0 else f"{w}-{l}-{t}",
                    "w": w,
                    "l": l,
                    "t": t,
                    "pct": pct,
                })
        except Exception as e:
            logging.warning(f"Could not parse standings file: {e}")

    # Fallback: build from opponent team.json records when standings file is absent or empty.
    if not standings:
        opponents_dir = DATA_DIR / "opponents"
        if opponents_dir.exists():
            for team_dir in opponents_dir.iterdir():
                if team_dir.is_dir():
                    team_file = team_dir / "team.json"
                    if team_file.exists():
                        try:
                            with open(team_file) as f:
                                td = json.load(f)
                            record = td.get("record", "0-0")
                            w, l, t = _parse_record_parts(record)
                            gp = w + l + t
                            standings.append({
                                "slug": team_dir.name,
                                "team_name": _canonical_team_name(td.get("team_name", team_dir.name), team_dir.name),
                                "record": f"{w}-{l}" if t == 0 else f"{w}-{l}-{t}",
                                "w": w,
                                "l": l,
                                "t": t,
                                "pct": round(w / gp, 3) if gp > 0 else 0.0,
                            })
                        except Exception:
                            pass

    # Force Sharks row to match Games tab source of truth (same parsed + enriched games feed).
    sharks_w = sharks_l = sharks_t = 0
    for g in _build_games_feed(include_detail=False):
        result = str(g.get("result", "")).strip().upper()
        if result == "W":
            sharks_w += 1
        elif result == "L":
            sharks_l += 1
        elif result == "T":
            sharks_t += 1
    sharks_gp = sharks_w + sharks_l + sharks_t
    sharks_pct = round(sharks_w / sharks_gp, 3) if sharks_gp > 0 else 0.0
    sharks_row = {
        "slug": "sharks",
        "team_name": "The Sharks",
        "record": f"{sharks_w}-{sharks_l}" if sharks_t == 0 else f"{sharks_w}-{sharks_l}-{sharks_t}",
        "w": sharks_w,
        "l": sharks_l,
        "t": sharks_t,
        "pct": sharks_pct,
    }
    standings = [s for s in standings if str(s.get("slug", "")).lower() != "sharks"]
    standings.append(sharks_row)

    standings.sort(key=lambda x: (-x["w"], x["l"]))
    return jsonify({"league": league_name, "standings": standings})


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
                            "team_name": _canonical_team_name(td.get("team_name", team_dir.name), team_dir.name),
                            "record": td.get("record", {}),
                            "gc_team_id": td.get("gc_team_id", ""),
                            "gc_season_slug": td.get("gc_season_slug", ""),
                            "roster_size": len(td.get("roster", [])),
                            "batting_rows": len(td.get("batting_stats", [])),
                            "pitching_rows": len(td.get("pitching_stats", [])),
                            "public_game_metrics": td.get("public_game_metrics", {}),
                        })
                    except Exception as e:
                        logging.error(f"Error reading opponent {team_dir.name}: {e}")
    teams.sort(key=lambda t: t["team_name"].lower())
    return jsonify(teams)


@app.route('/api/opponents/<slug>', methods=['GET'])
def handle_opponent_detail(slug):
    """Return full data for a single opponent team."""
    team_file = DATA_DIR / "opponents" / slug / "team.json"
    if not team_file.exists():
        return jsonify({"error": "Not found"}), 404
    with open(team_file) as f:
        team = json.load(f)
    team["team_name"] = _canonical_team_name(team.get("team_name", slug), slug)
    return jsonify(team)


@app.route('/api/matchup/<opponent_slug>', methods=['GET'])
def handle_matchup(opponent_slug):
    """Run matchup analysis: Sharks vs a specific opponent."""
    from swot_analyzer import analyze_matchup, load_team
    our_team = load_team(SHARKS_DIR, prefer_merged=True)
    if not our_team:
        return jsonify({"error": "Sharks team data not found"}), 404

    # Enrich Sharks roster with app_stats so matchup uses current season stats
    _enrich_team_with_app_stats(our_team)
    our_team["team_name"] = _canonical_team_name(our_team.get("team_name", "The Sharks"), "sharks")

    opp_dir = DATA_DIR / "opponents" / opponent_slug
    opp_team = load_team(opp_dir)
    if not opp_team:
        # Try loading directly from team.json
        team_file = DATA_DIR / "opponents" / opponent_slug / "team.json"
        if team_file.exists():
            with open(team_file) as f:
                opp_team = json.load(f)
        else:
            return jsonify({"error": f"Opponent '{opponent_slug}' not found"}), 404
    opp_team["team_name"] = _canonical_team_name(opp_team.get("team_name", opponent_slug), opponent_slug)

    # Determine what data source matchup analysis can use for the opponent.
    # Precedence: opponent team feed -> parsed game history -> none.
    data_source = "none"
    team_json_pa = 0
    if opp_team.get("batting_stats"):
        for row in opp_team.get("batting_stats", []):
            team_json_pa += normalize_batting_row(row).get("pa", 0)
    elif opp_team.get("roster"):
        for row in opp_team.get("roster", []):
            team_json_pa += normalize_batting_row(row).get("pa", 0)

    if team_json_pa >= 5:
        data_source = "opponent_team_json"
    else:
        # Fallback to scorebook history for teams we've already faced.
        opp_game_stats = _aggregate_opponent_stats_from_games(opponent_slug)
        if opp_game_stats:
            opp_team["batting_stats"] = opp_game_stats
            data_source = "opponent_game_history"
        elif isinstance(opp_team.get("public_game_metrics"), dict) and opp_team.get("public_game_metrics", {}).get("completed_games", 0) > 0:
            data_source = "opponent_public_games"

    result = analyze_matchup(our_team, opp_team)
    result["data_source"] = data_source
    if isinstance(opp_team.get("public_game_metrics"), dict):
        result["opponent_public_metrics"] = opp_team.get("public_game_metrics", {})
    if result.get("empty"):
        if data_source == "none":
            result["reason"] = "no_opponent_history"
        elif data_source == "opponent_public_games":
            result["reason"] = "no_player_level_history"
            m = opp_team.get("public_game_metrics", {})
            completed = int(m.get("completed_games", 0) or 0)
            rs = m.get("runs_scored_per_game", 0)
            ra = m.get("runs_allowed_per_game", 0)
            hits = m.get("hits_scored_per_game", 0)
            errs = m.get("errors_committed_per_game", 0)
            fir = m.get("first_inning_runs_avg", 0)
            big = m.get("big_inning_rate", 0)
            result["recommendation"] = (
                f"{result.get('recommendation', 'Limited player-level data.')}"
                f" Opponent season profile: {completed} completed games, {rs} RS/G, {ra} RA/G,"
                f" {hits} hits/G, {errs} errors/G, {fir} first-inning runs/G, {round(float(big)*100, 1)}% big-inning rate."
            ).strip()
        elif not result.get("reason"):
            result["reason"] = "insufficient_data"

    # Attach opponent roster for display
    result["their_roster"] = [
        {"name": p.get("name", f"{p.get('first','')} {p.get('last','')}".strip()),
         "number": p.get("number", "")}
        for p in opp_team.get("roster", [])
    ]
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
                b = normalize_batting_row(player)
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

    team = _read_json_file(team_file, default=None)
    if not isinstance(team, dict):
        return jsonify({"error": "team_data_unavailable"}), 503

    # Enrich roster with current app_stats.json (always most up-to-date)
    _enrich_team_with_app_stats(team)
    team["team_name"] = _canonical_team_name(team.get("team_name", "The Sharks"), "sharks")

    # Fall back to PDF-aggregated stats for players still missing data
    pdf_stats = {}
    for player in team.get("roster", []):
        if player.get("batting", {}).get("pa", 0) == 0:
            if not pdf_stats:
                pdf_stats = _aggregate_stats_from_games()
            num = str(player.get("number", "")).strip()
            if num and num in pdf_stats:
                player["batting"] = pdf_stats[num]["batting"]
                player["games_played"] = pdf_stats[num]["games_played"]

    return jsonify(team)


@app.route('/api/borrowed-player', methods=['POST'])
def handle_borrowed_player():
    """Add a borrowed player to roster_manifest.json, optionally trigger stat scrape."""
    blocked = _guard_mutating_request()
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "invalid_json_object"}), 400
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
    data = _read_json_file(schedule_file, default={"upcoming": [], "past": []}) or {"upcoming": [], "past": []}
    # Clean opponent names for display
    for section in ("upcoming", "past"):
        for game in data.get(section, []):
            raw = game.get("opponent", "")
            game["opponent_raw"] = raw
            game["opponent"] = _clean_opponent_name(raw)
    return jsonify(data)


@app.route('/api/opponent-discovery', methods=['GET'])
def handle_opponent_discovery():
    """Return latest opponent ID discovery artifact."""
    artifact_file = SHARKS_DIR / "opponent_discovery.json"
    if not artifact_file.exists():
        return jsonify({"generated_at": None, "teams": [], "missing_schedule_opponents": []})
    data = _read_json_file(artifact_file, default={}) or {}
    return jsonify(data)


@app.route('/api/regenerate-lineups', methods=['POST'])
def handle_regenerate_lineups():
    """Regenerate lineups (and optionally SWOT) on demand."""
    try:
        blocked = _guard_mutating_request()
        if blocked:
            return blocked
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({"error": "invalid_json_object"}), 400
        from lineup_optimizer import run as run_lineup
        run_lineup()
        lineups_file = SHARKS_DIR / "lineups.json"
        lineups = {}
        if lineups_file.exists():
            with open(lineups_file) as f:
                lineups = json.load(f)
        # Optionally regenerate SWOT too
        if data.get("swot"):
            from swot_analyzer import run_sharks_analysis
            run_sharks_analysis()
        return jsonify({"status": "ok", "lineups": lineups})
    except Exception as e:
        logging.error(f"Regenerate lineups error: {e}")
        return jsonify({"error": str(e)}), 500


def _trigger_post_game_analysis():
    """Run immediately after a game ends: re-scrape, enrich, update SWOT + lineups."""
    logging.info("[Post-Game] Starting post-game analysis pipeline...")
    success = False
    try:
        from parse_scorebook_pdf import run as parse_pdfs
        parse_pdfs()
        logging.info("[Post-Game] Scorebook parse complete.")
    except Exception as e:
        logging.error(f"[Post-Game] scorebook parse failed: {e}")
    try:
        success = run_sync_cycle()
    except Exception as e:
        logging.error(f"[Post-Game] sync cycle failed: {e}")
    if success:
        send_alert("Post-game analysis complete — scorebooks, SWOT, and lineups refreshed.", level="INFO")
        logging.info("[Post-Game] Analysis pipeline complete.")
    else:
        send_alert("Post-game analysis encountered errors. Check sync_daemon logs.", level="ERROR")


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

    run_api_server = os.getenv("RUN_API_SERVER", "1").lower() in ("1", "true", "yes")
    if run_api_server:
        api_thread = threading.Thread(target=run_api, daemon=True)
        api_thread.start()
    else:
        logging.info("RUN_API_SERVER=0 -> Flask dev API thread disabled (expect Gunicorn service).")
    
    consecutive_errors = 0
    _last_state = "IDLE"
    _last_post_game_trigger_at = None

    while True:
        try:
            # Determine Polling State
            is_live_forced = check_live_override()
            next_game = get_next_game_time()
            now = datetime.now(ET)

            state = "IDLE"
            sleep_duration = POLL_INTERVAL_IDLE

            if is_live_forced:
                state = "LIVE (Manual Override)"
                sleep_duration = POLL_INTERVAL_LIVE
            elif next_game:
                time_until_game = (next_game - now).total_seconds()

                if time_until_game < -(GAME_DURATION_HOURS * 3600):
                    state = "IDLE"
                    sleep_duration = POLL_INTERVAL_IDLE
                elif time_until_game <= 0:
                    state = "LIVE"
                    sleep_duration = POLL_INTERVAL_LIVE
                elif time_until_game <= (PREGAME_WINDOW_HOURS * 3600):
                    state = "PREGAME"
                    sleep_duration = POLL_INTERVAL_PREGAME

            # Post-game hook: fire when transitioning out of LIVE state
            if _last_state in ("LIVE", "LIVE (Manual Override)") and state == "IDLE":
                if _last_post_game_trigger_at and (now - _last_post_game_trigger_at) < timedelta(minutes=POST_GAME_DEDUP_MINUTES):
                    logging.info("[Post-Game] Duplicate LIVE->IDLE transition ignored by idempotency guard.")
                else:
                    logging.info("[Post-Game] Game ended — triggering immediate re-analysis.")
                    _trigger_post_game_analysis()
                    _last_post_game_trigger_at = now

            _last_state = state
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
