from __future__ import annotations
import time
import json
import os
import re
import logging
import traceback
import requests
import ipaddress
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

ET = ZoneInfo("America/New_York")
from pathlib import Path
from gc_scraper import GameChangerScraper, is_auth_on_cooldown
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
    build_player_metric_profile,
    player_identity_key,
    validate_team_outlier_stats,
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
TEAM_DIR = DATA_DIR / os.getenv("TEAM_SLUG", "sharks")
LOG_DIR = Path(__file__).parent.parent / "logs"
CONFIG_DIR = Path(__file__).parent.parent / "config"
LOG_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_FALLBACK_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
_SECRET_CACHE: dict[str, str] | None = None
_SYNC_STATUS: dict = {"stage": "idle", "last_completed": "", "progress": 0}

# Ordered sync stages with progress percentages and display labels
_SYNC_STAGES = [
    ("starting",           5,  "Starting"),
    ("scraping_schedule", 15,  "Schedule"),
    ("scraping_stats",    35,  "Stats"),
    ("enriching",         60,  "Enriching"),
    ("analyzing",         80,  "Analyzing"),
    ("finalizing",        95,  "Finalizing"),
]

def _set_sync_stage(stage: str):
    """Update sync status with stage name and computed progress percentage."""
    _SYNC_STATUS["stage"] = stage
    for s_name, s_pct, _ in _SYNC_STAGES:
        if s_name == stage:
            _SYNC_STATUS["progress"] = s_pct
            return
    if stage == "idle":
        _SYNC_STATUS["progress"] = 0

DEFAULT_CORS_ORIGINS = [
    "https://dugout.joelycannoli.com",
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


def _candidate_secrets_csv_paths() -> list[Path]:
    raw_paths = [
        os.getenv("SECRETS_CSV", "").strip(),
        os.getenv("APIS_CSV_PATH", "").strip(),
        r"H:\APIs.csv",
        r"H:\APIs - Sheet1 (6).csv",
        str(Path(__file__).parent.parent / "APIs.csv"),
        str(Path(__file__).parent / "APIs - Sheet1 (6).csv"),
        str(Path(__file__).parent.parent / "Scorebooks" / "APIs - Sheet1 (6).csv"),
    ]
    out: list[Path] = []
    seen: set[str] = set()
    for p in raw_paths:
        if not p:
            continue
        norm = str(Path(p))
        if norm in seen:
            continue
        seen.add(norm)
        out.append(Path(p))
    return out


def _load_secret_cache() -> dict[str, str]:
    global _SECRET_CACHE
    if isinstance(_SECRET_CACHE, dict):
        return _SECRET_CACHE

    _SECRET_CACHE = {}
    try:
        from runtime_ops import extract_secrets_from_csv  # lazy import; no CLI side effects
    except Exception:
        return _SECRET_CACHE

    for path in _candidate_secrets_csv_paths():
        try:
            if not path.exists():
                continue
            found = extract_secrets_from_csv(path)
            if isinstance(found, dict):
                _SECRET_CACHE = {k: str(v).strip() for k, v in found.items() if str(v).strip()}
                if _SECRET_CACHE:
                    return _SECRET_CACHE
        except Exception:
            continue
    return _SECRET_CACHE


def _resolve_secret(name: str, default: str = "") -> str:
    env_val = os.getenv(name, "").strip()
    if env_val:
        return env_val
    cache = _load_secret_cache()
    return str(cache.get(name, default)).strip()


def _origin_hostname(origin: str) -> str:
    try:
        parsed = urlparse(origin)
        return (parsed.hostname or "").strip().lower()
    except Exception:
        return ""

DEFAULT_ALLOWED_HOSTS = [
    "dugout.joelycannoli.com",
    "localhost",
    "127.0.0.1",
    "dugout_api",
    "dugout_dashboard",
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
    _team_name = os.getenv("TEAM_NAME", "The Sharks")
    if slug_l == "sharks" or raw.lower() in ("sharks", "the sharks"):
        return _team_name
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
    app_stats_file = TEAM_DIR / "app_stats.json"
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


def _supplement_enriched_from_base(team_data: dict):
    """Supplement enriched team data with fields from base team.json that enrichment didn't cover.

    After _enrich_team_with_app_stats replaces batting and maps 12 batting_advanced fields,
    some fields from the original CSV (babip, ba_risp, ps, tb, xbh, etc.) can be lost.
    This reads the base team.json and fills in any missing values.
    """
    base_file = TEAM_DIR / "team.json"
    if not base_file.exists():
        return
    try:
        with open(base_file) as f:
            base_team = json.load(f)
    except Exception:
        return

    base_by_num = {}
    for bp in base_team.get("roster", []):
        num = str(bp.get("number", "")).strip()
        if num:
            base_by_num[num] = bp

    ADV_SUPPLEMENT = ["babip", "ps", "ps_pa", "tb", "xbh", "two_out_rbi", "ba_risp",
                      "lob", "two_s_three", "two_s_three_pct", "six_plus", "six_plus_pct",
                      "gidp", "gitp"]
    SECTION_SUPPLEMENT = ["catching", "innings_played", "pitching_advanced", "pitching_breakdown"]

    for player in team_data.get("roster", []):
        num = str(player.get("number", "")).strip()
        bp = base_by_num.get(num)
        if not bp:
            continue
        # Fill missing top-level stat sections
        for key in SECTION_SUPPLEMENT:
            if not player.get(key) and bp.get(key):
                player[key] = bp[key]
        # Fill missing batting_advanced fields
        if isinstance(player.get("batting_advanced"), dict) and isinstance(bp.get("batting_advanced"), dict):
            adv = player["batting_advanced"]
            base_adv = bp["batting_advanced"]
            for k in ADV_SUPPLEMENT:
                if adv.get(k) is None and base_adv.get(k) is not None:
                    adv[k] = base_adv[k]
        # Fill missing pitching fields
        if isinstance(player.get("pitching"), dict) and isinstance(bp.get("pitching"), dict):
            p_block = player["pitching"]
            base_p = bp["pitching"]
            for k in ["gp", "gs", "sv", "svo", "bs", "bf", "np", "r", "kl", "hbp", "wp", "pik", "bk", "cs", "sb", "lob", "baa"]:
                if p_block.get(k) is None and base_p.get(k) is not None:
                    p_block[k] = base_p[k]
        elif not player.get("pitching") and bp.get("pitching"):
            player["pitching"] = bp["pitching"]


def _aggregate_opponent_stats_from_games(opponent_slug: str) -> list:
    """Aggregate opponent_batting stats from scorebook game JSON files for a given opponent.
    Returns flattened batting_stats[] rows (ab/h/bb...) for direct use in matchup aggregator."""
    games_dir = TEAM_DIR / "games"
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


def _merge_batting_with_scorebook(current_batting: dict, scorebook_batting: dict) -> tuple[dict, bool]:
    """Merge two batting rows, preserving the richer counting stats.
    Rule: use max() per counting field so partial app/web rows cannot zero-out scorebook signal."""
    cur = normalize_batting_row(current_batting or {})
    sb = normalize_batting_row(scorebook_batting or {})

    count_fields = ["pa", "ab", "h", "1b", "2b", "3b", "hr", "bb", "hbp", "so", "rbi", "sb", "r", "sac"]
    merged = {field: max(int(cur.get(field, 0)), int(sb.get(field, 0))) for field in count_fields}

    # Keep singles internally consistent with H/2B/3B/HR.
    merged["1b"] = max(merged["1b"], merged["h"] - merged["2b"] - merged["3b"] - merged["hr"], 0)
    min_pa = merged["ab"] + merged["bb"] + merged["hbp"] + merged["sac"]
    merged["pa"] = max(merged["pa"], min_pa)

    ab = merged["ab"]
    h = merged["h"]
    bb = merged["bb"]
    hbp = merged["hbp"]
    pa = merged["pa"]
    tb = merged["1b"] + 2 * merged["2b"] + 3 * merged["3b"] + 4 * merged["hr"]

    merged["avg"] = round(h / ab, 3) if ab > 0 else 0.0
    merged["obp"] = round((h + bb + hbp) / pa, 3) if pa > 0 else 0.0
    merged["slg"] = round(tb / ab, 3) if ab > 0 else 0.0
    merged["ops"] = round(merged["obp"] + merged["slg"], 3)

    # Compatibility aliases
    merged["singles"] = merged["1b"]
    merged["doubles"] = merged["2b"]
    merged["triples"] = merged["3b"]

    changed = any(int(cur.get(field, 0)) != int(merged.get(field, 0)) for field in count_fields)
    changed = changed or any(round(float(cur.get(k, 0.0)), 3) != round(float(merged.get(k, 0.0)), 3) for k in ("avg", "obp", "slg", "ops"))
    return merged, changed


def _merge_team_with_scorebook_stats(team_data: dict) -> tuple[dict, dict]:
    """Merge aggregated scorebook batting into team roster after app/web enrichment."""
    game_stats = _aggregate_stats_from_games()
    if not game_stats:
        return team_data, {"players_matched": 0, "players_updated": 0, "source_players": 0}

    matched = 0
    updated = 0
    for player in team_data.get("roster", []):
        num = str(player.get("number", "")).strip()
        if not num or num not in game_stats:
            continue
        matched += 1
        scorebook_batting = game_stats[num].get("batting", {})
        merged_batting, changed = _merge_batting_with_scorebook(player.get("batting", {}), scorebook_batting)
        if changed:
            updated += 1
        player["batting"] = merged_batting
        player["games_played"] = max(
            int(_safe_int(player.get("games_played", 0))),
            int(_safe_int(game_stats[num].get("games_played", 0))),
        )

    meta = {"players_matched": matched, "players_updated": updated, "source_players": len(game_stats)}
    logging.info(
        "[Reconcile] scorebook merge complete: matched=%s updated=%s source_players=%s",
        matched,
        updated,
        len(game_stats),
    )
    return team_data, meta


def _collect_pipeline_health() -> dict:
    """Build pipeline health coverage metrics across app/web/game feeds."""
    app_stats_file = TEAM_DIR / "app_stats.json"
    team_merged_file = TEAM_DIR / "team_merged.json"
    games_dir = TEAM_DIR / "games"
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
    out_file = TEAM_DIR / "pipeline_health.json"
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


def _record_stats_db_snapshot(team_data: dict, source: str = "sync_cycle", notes: str = ""):
    """Persist a time-series snapshot to the running SQLite stats database."""
    try:
        from stats_db import record_team_snapshot

        snapshot_id = record_team_snapshot(team_data, source=source, notes=notes)
        logging.info("[DB] Recorded stats snapshot id=%s source=%s", snapshot_id, source)
        return snapshot_id
    except Exception as e:
        logging.warning(f"[DB] Snapshot write skipped: {e}")
        return None


def _load_recent_metric_profiles(limit: int = 30) -> dict[str, list[dict[str, float]]]:
    """
    Load recent historical player metric profiles from stats_history.db.
    Returns: {player_identity_key: [metric_profile, ...]}
    """
    try:
        from stats_db import DB_PATH
    except Exception:
        return {}

    db_path = Path(DB_PATH)
    if not db_path.exists():
        return {}

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT ?", (int(limit),))
        snapshot_ids = [int(r[0]) for r in cur.fetchall() if r and r[0] is not None]
        if not snapshot_ids:
            return {}

        placeholders = ",".join("?" for _ in snapshot_ids)
        query = f"""
            SELECT
                p.number, p.first_name, p.last_name, p.display_name,
                bs.pa, bs.bb, bs.so, bs.avg, bs.obp, bs.slg, bs.ops,
                ps.ip, ps.bb, ps.so, ps.era, ps.whip,
                fs.fpct, fs.e
            FROM batting_snapshots bs
            JOIN players p ON p.player_key = bs.player_key
            JOIN pitching_snapshots ps ON ps.player_key = bs.player_key AND ps.snapshot_id = bs.snapshot_id
            JOIN fielding_snapshots fs ON fs.player_key = bs.player_key AND fs.snapshot_id = bs.snapshot_id
            WHERE bs.snapshot_id IN ({placeholders})
        """
        cur.execute(query, snapshot_ids)

        history: dict[str, list[dict[str, float]]] = {}
        for row in cur.fetchall():
            faux_player = {
                "number": row[0],
                "first": row[1] or "",
                "last": row[2] or "",
                "name": row[3] or "",
                "batting": {
                    "pa": row[4] or 0,
                    "bb": row[5] or 0,
                    "so": row[6] or 0,
                    "avg": row[7] or 0.0,
                    "obp": row[8] or 0.0,
                    "slg": row[9] or 0.0,
                    "ops": row[10] or 0.0,
                },
                "pitching": {
                    "ip": row[11] or 0.0,
                    "bb": row[12] or 0,
                    "so": row[13] or 0,
                    "era": row[14] or 0.0,
                    "whip": row[15] or 0.0,
                },
                "fielding": {
                    "fpct": row[16] or 0.0,
                    "e": row[17] or 0,
                },
            }
            key = player_identity_key(faux_player)
            history.setdefault(key, []).append(build_player_metric_profile(faux_player))
        return history
    except Exception as e:
        logging.warning(f"[Validate] Historical profile load failed: {e}")
        return {}
    finally:
        conn.close()


def _detect_threshold_anomalies(team_data: dict) -> list[dict]:
    """Flag players with concerning stat thresholds (no history needed)."""
    alerts = []
    roster = team_data.get("roster", [])
    for player in roster:
        batting = normalize_batting_row(player)
        pa = batting.get("pa", 0)
        if pa < 5:
            continue
        name = f"{player.get('first', '')} {player.get('last', '')}".strip() or player.get("name", "Unknown")
        number = player.get("number", "?")
        ab = batting.get("ab", 0)
        h = batting.get("h", 0)
        so = batting.get("so", 0)
        ba = h / ab if ab > 0 else 0
        k_rate = so / pa if pa > 0 else 0
        player_alerts = []
        if ba < 0.100 and pa >= 8:
            player_alerts.append(f"Very low BA ({ba:.3f}) over {pa} PA")
        if k_rate > 0.50 and pa >= 8:
            player_alerts.append(f"High K-rate ({k_rate:.1%}) over {pa} PA")
        if player_alerts:
            alerts.append({"player": name, "number": number, "alerts": player_alerts})
    return alerts


def _validate_and_write_stat_anomalies(team_data: dict) -> list[dict]:
    """
    Flag outlier stats (>3 SD by default) before writing team_enriched.json.
    Also applies threshold-based detection for teams without enough history.
    """
    z_threshold = float(os.getenv("STATS_OUTLIER_Z_THRESHOLD", "3.0"))
    min_samples = int(os.getenv("STATS_OUTLIER_MIN_SAMPLES", "5"))
    history_limit = int(os.getenv("STATS_OUTLIER_HISTORY_LIMIT", "30"))

    history = _load_recent_metric_profiles(limit=history_limit)
    findings = validate_team_outlier_stats(
        team_data=team_data,
        historical_profiles_by_player=history,
        z_threshold=z_threshold,
        min_history_samples=min_samples,
    )

    threshold_alerts = _detect_threshold_anomalies(team_data)

    out = {
        "generated_at": datetime.now(ET).isoformat(),
        "z_threshold": z_threshold,
        "min_history_samples": min_samples,
        "history_snapshot_limit": history_limit,
        "anomaly_count": len(findings),
        "anomalies": findings,
        "threshold_alerts": threshold_alerts,
        "threshold_alert_count": len(threshold_alerts),
    }
    out_file = TEAM_DIR / "stats_anomalies.json"
    with open(out_file, "w") as f:
        json.dump(out, f, indent=2)

    if findings:
        for player_finding in findings:
            player = player_finding.get("player", {})
            for metric in player_finding.get("outliers", []):
                logging.warning(
                    "[Validate] Outlier flagged for %s (%s): %s current=%s mean=%s std=%s z=%s",
                    player.get("name", "Unknown"),
                    player.get("number", "?"),
                    metric.get("metric"),
                    metric.get("current"),
                    metric.get("mean"),
                    metric.get("stddev"),
                    metric.get("z_score"),
                )
    else:
        logging.info("[Validate] No outlier stats detected before team save.")

    return findings


def get_next_game_time():
    """Parse schedule_manual.json to find the nearest upcoming game. Returns datetime or None."""
    schedule_file = TEAM_DIR / "schedule_manual.json"
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
        _set_sync_stage("starting")

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
        
        # Check auth cooldown — if GC login recently failed (2FA required),
        # skip all authenticated scrapers to avoid flooding fly386@gmail.com with codes.
        _auth_available = not is_auth_on_cooldown()
        if not _auth_available:
            logging.warning("[Sync] Auth on cooldown — skipping all authenticated GC scrapers this cycle.")

        # 1. Scrape Schedule (requires auth)
        _set_sync_stage("scraping_schedule")
        if _auth_available:
            logging.info("Scraping Schedule...")
            sched_scraper = ScheduleScraper()
            sched_scraper.scrape_schedule()
        else:
            logging.info("[Sync] Schedule scrape skipped (auth cooldown).")

        # 1b. Secondary game ingest path (mobile-web box scores -> data/sharks/games/*.json).
        # Keeps scorebook-derived reconciliation alive even when GC app selectors drift.
        try:
            from gc_web_mobile_scraper import sync_recent_games as sync_web_mobile_games

            web_ingest = sync_web_mobile_games(
                team_id=os.getenv("GC_TEAM_ID", "NuGgx6WvP7TO"),
                season_slug=os.getenv("GC_SEASON_SLUG", "2026-spring-sharks"),
                sharks_team_name=os.getenv("TEAM_NAME", "Sharks"),
                max_games=int(os.getenv("GC_WEB_BOX_MAX_GAMES", "8")),
            )
            logging.info(
                "[Sync] Web box score ingest: target=%s saved=%s skipped=%s failed=%s",
                web_ingest.get("target_games", 0),
                web_ingest.get("saved", 0),
                web_ingest.get("skipped_existing", 0),
                web_ingest.get("failed", 0),
            )
        except Exception as e:
            logging.warning(f"[Sync] Web box score ingest skipped: {e}")
        
        # 2. Scrape Stats (requires auth)
        _set_sync_stage("scraping_stats")
        if _auth_available:
            logging.info("Scraping Live Stats...")
            try:
                from playwright.sync_api import sync_playwright

                with sync_playwright() as pw:
                    stat_scraper = GameChangerScraper()
                    stat_scraper.login(pw)
                    stat_scraper.scrape_team_stats()
            except Exception as e:
                logging.warning(f"[Sync] Live stat scrape failed; continuing with fallback data: {e}")
        else:
            logging.info("[Sync] Live stat scrape skipped (auth cooldown).")

        # Merge multi-team stats if available
        try:
            from aggregate_team_stats import main as run_merge
            run_merge()
        except Exception as e:
            logging.warning(f"Aggregate merge skipped: {e}")

        enriched_team_data = None

        _set_sync_stage("enriching")
        # Write team_enriched.json (team_merged + app_stats + scorebook reconciliation)
        try:
            team_file = TEAM_DIR / ("team_merged.json" if (TEAM_DIR / "team_merged.json").exists() else "team.json")
            with open(team_file) as f:
                team_data = json.load(f)
            _enrich_team_with_app_stats(team_data)
            _, reconcile_meta = _merge_team_with_scorebook_stats(team_data)
            # Supplement batting_advanced with fields from base team.json that enrichment didn't cover
            _supplement_enriched_from_base(team_data)
            anomaly_findings = _validate_and_write_stat_anomalies(team_data)
            enriched_team_data = team_data
            enriched_file = TEAM_DIR / "team_enriched.json"
            with open(enriched_file, "w") as f:
                json.dump(team_data, f, indent=2)
            logging.info(
                "[Sync] team_enriched.json written (scorebook matched=%s updated=%s, anomalies=%s).",
                reconcile_meta.get("players_matched", 0),
                reconcile_meta.get("players_updated", 0),
                len(anomaly_findings),
            )
        except Exception as e:
            logging.warning(f"team_enriched.json write skipped: {e}")

        _set_sync_stage("analyzing")
        # Re-run SWOT and lineup optimizer with enriched data
        try:
            from swot_analyzer import run_team_analysis
            run_team_analysis()
            logging.info("[Sync] SWOT analysis refreshed.")
        except Exception as e:
            logging.warning(f"SWOT re-run skipped: {e}")
        try:
            from lineup_optimizer import run as run_lineup
            run_lineup()
            logging.info("[Sync] Lineup optimizer refreshed.")
        except Exception as e:
            logging.warning(f"Lineup re-run skipped: {e}")

        # Practice plan scheduling:
        #  - initial generation waits until 1h after last completed game/practice
        #  - refresh runs 1h before next practice only if new source data is detected
        try:
            from practice_gen import run_scheduled as run_practice_planner

            practice_result = run_practice_planner(force=False)
            logging.info(
                "[Sync] Practice planner: status=%s reason=%s",
                practice_result.get("status"),
                practice_result.get("reason"),
            )
        except Exception as e:
            logging.warning(f"[Sync] Practice planner skipped: {e}")

        # Full-depth GC scrape: all stat tabs, both teams, every game (requires auth).
        if _auth_available:
            try:
                from gc_full_scraper import GCFullScraper
                full_scraper = GCFullScraper()
                full_result = full_scraper.run_full_sync()
                logging.info(
                    "[Sync] gc_full_scraper: scraped=%s skipped=%s failed=%s team_stats=%s",
                    full_result.get("games_scraped", 0),
                    full_result.get("games_skipped", 0),
                    full_result.get("games_failed", 0),
                    full_result.get("team_stats_scraped", False),
                )
            except Exception as e:
                logging.warning(f"[Sync] gc_full_scraper skipped: {e}")

            # Automated CSV download + ingest (requires auth).
            try:
                from gc_csv_auto import run_auto_csv
                csv_result = run_auto_csv(headless=True, skip_ingest=False)
                logging.info(
                    "[Sync] gc_csv_auto: downloaded=%s ingest_ok=%s path=%s",
                    csv_result.get("csv_downloaded"),
                    csv_result.get("ingest_success"),
                    csv_result.get("csv_path"),
                )
            except Exception as e:
                logging.warning(f"[Sync] gc_csv_auto skipped: {e}")
        else:
            logging.info("[Sync] gc_full_scraper + gc_csv_auto skipped (auth cooldown).")

        _set_sync_stage("finalizing")

        # NotebookLM payload rebuild with all new data.
        try:
            from notebooklm_sync import prepare_notebooklm_payload
            prepare_notebooklm_payload()
            logging.info("[Sync] NotebookLM payload refreshed.")
        except Exception as e:
            logging.warning(f"[Sync] notebooklm_sync skipped: {e}")

        # Refresh pipeline coverage metrics artifact
        try:
            _write_pipeline_health_artifact()
        except Exception as e:
            logging.warning(f"[Health] pipeline artifact write skipped: {e}")

        # Persist running historical snapshot DB.
        if isinstance(enriched_team_data, dict):
            _record_stats_db_snapshot(enriched_team_data, source="sync_cycle")

        _set_sync_stage("idle")
        _SYNC_STATUS["last_completed"] = datetime.now(ET).isoformat()
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
from flask import Flask, Response, jsonify, request
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

PRACTICE_NEED_DRILLS = {
    "plate_discipline": [
        {"name": "Two-Strike Battle Rounds", "duration_min": 15, "goal": "Reduce chase + strikeout rate under pressure."},
        {"name": "Zone Recognition Front Toss", "duration_min": 12, "goal": "Improve swing decisions and walk quality."},
    ],
    "contact_on_base": [
        {"name": "Short-Bat Contact Circuit", "duration_min": 15, "goal": "Increase barrel control and line-drive contact."},
        {"name": "QAB Challenge (team)", "duration_min": 12, "goal": "Raise quality-at-bat rate and OBP."},
    ],
    "slugging_power": [
        {"name": "Gap-to-Gap Tee Progression", "duration_min": 15, "goal": "Build extra-base contact mechanics."},
        {"name": "Launch-Point Soft Toss", "duration_min": 12, "goal": "Improve damage on hittable pitches."},
    ],
    "defense_reliability": [
        {"name": "Rapid Fire Ground Ball Transfer", "duration_min": 15, "goal": "Reduce clean-handling and throw errors."},
        {"name": "Communication Fly Ball Grid", "duration_min": 12, "goal": "Improve first-step reads and calls."},
    ],
    "pitch_command": [
        {"name": "3-Spot Command Ladder", "duration_min": 15, "goal": "Lower BB/IP and improve first-pitch strike quality."},
        {"name": "Pressure Count Bullpen", "duration_min": 12, "goal": "Execute in hitter counts and two-strike counts."},
    ],
    "baserunning_iq": [
        {"name": "Jump + Read Leads", "duration_min": 12, "goal": "Improve first-step timing and steal decisions."},
        {"name": "First-to-Third Decisions", "duration_min": 12, "goal": "Better round-and-read choices at game speed."},
    ],
}


_SLUG_RE = re.compile(r'^[A-Za-z0-9_-]{1,80}$')


def _validate_path_slug(value: str, label: str = "slug"):
    """Return None if valid, else a (response, status) error tuple."""
    if not value or not _SLUG_RE.match(value):
        logging.warning(f"[Security] Rejected invalid {label}: {value!r}")
        return jsonify({"error": "invalid_parameter"}), 400
    return None


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
    mf = TEAM_DIR / "roster_manifest.json"
    if not mf.exists():
        return []
    with open(mf) as f:
        data = json.load(f)
    return [n.strip().lower() for n in data.get("core_players", [])]


def _load_sub_tracker():
    """Load sub activation tracker (timestamps)."""
    tracker_file = TEAM_DIR / "sub_tracker.json"
    if not tracker_file.exists():
        return {}
    with open(tracker_file) as f:
        return json.load(f)


def _save_sub_tracker(tracker):
    TEAM_DIR.mkdir(parents=True, exist_ok=True)
    with open(TEAM_DIR / "sub_tracker.json", "w") as f:
        json.dump(tracker, f, indent=2)


def _is_core_player(name):
    core = _load_roster_manifest()
    return name.strip().lower() in core


def auto_deactivate_subs():
    """After a game day, deactivate all non-core players and record in sub_tracker."""
    schedule_file = TEAM_DIR / "schedule_manual.json"
    availability_file = TEAM_DIR / "availability.json"

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
    availability_file = TEAM_DIR / "availability.json"

    if request.method == 'POST':
        blocked = _guard_mutating_request()
        if blocked:
            return blocked
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({"error": "invalid_json_object"}), 400
        if len(data) > 60:
            return jsonify({"error": "payload_too_large"}), 400
        for k, v in data.items():
            if not isinstance(k, str) or len(k) > 80:
                return jsonify({"error": "invalid_player_name"}), 400
            if not isinstance(v, bool):
                return jsonify({"error": "values_must_be_boolean"}), 400

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
            from swot_analyzer import run_team_analysis
            run_lineup()
            run_team_analysis()
        except Exception as e:
            logging.error(f"Error re-running tools after update: {e}")
            
        return jsonify({"status": "success"})
    
    # GET logic
    if not availability_file.exists():
        team_file = TEAM_DIR / "team.json"
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
    games_dir = TEAM_DIR / "games"
    index_path = games_dir / "index.json"
    schedule_file = TEAM_DIR / "schedule_manual.json"

    pdf_games = []
    if index_path.exists():
        pdf_games = _read_json_file(index_path, default=[]) or []

    # Load schedule W/L results — also include upcoming games with past dates (self-healing)
    today_str = datetime.now(ET).strftime("%Y-%m-%d")
    sched_results = []
    if schedule_file.exists():
        sched_data = _read_json_file(schedule_file, default={}) or {}
        for g in sched_data.get("past", []):
            if g.get("result"):
                sched_results.append(g)
        # Also include upcoming games that have since passed, even without result
        # so they show up in the feed (result derived from GC data later)
        for g in sched_data.get("upcoming", []):
            g_date = (g.get("date") or "")[:10]
            if g_date and g_date <= today_str and not any(
                sr.get("date", "")[:10] == g_date and
                _re.sub(r'[^a-z0-9]', '', (sr.get("opponent") or "").lower()) in
                _re.sub(r'[^a-z0-9]', '', (g.get("opponent") or "").lower())
                for sr in sched_results
            ):
                sched_results.append(g)

    def _slug(name: str) -> str:
        return _re.sub(r'[^a-z0-9]', '', (name or '').lower())

    # Enrich PDF games with schedule result by fuzzy opponent match
    for game in pdf_games:
        opp_slug = _slug(game.get("opponent", ""))
        for sg in sched_results:
            sg_opp = _clean_opponent_name(sg.get("opponent", ""))
            if _slug(sg_opp) and (_slug(sg_opp) in opp_slug or opp_slug in _slug(sg_opp)):
                if sg.get("result"):
                    game["result"] = sg.get("result", "")
                if sg.get("score"):
                    game["score"] = sg.get("score", "")
                break

    # Load known game results override (tracked in git; authoritative for confirmed games)
    known_results_file = CONFIG_DIR / "known_game_results.json"
    if known_results_file.exists():
        try:
            known_data = _read_json_file(known_results_file, default={}) or {}
            for kr in known_data.get("results", []):
                kr_date = (kr.get("date") or "")[:10]
                if not kr_date or not kr.get("result"):
                    continue
                for game in pdf_games:
                    g_date = (game.get("date") or "")[:10]
                    if g_date == kr_date and not game.get("result"):
                        game["result"] = kr["result"]
                        game["score"] = kr.get("score", "")
                        logging.debug(f"[Feed] Applied known result {kr_date} {kr['result']} to {game.get('game_id')}")
                        break
        except Exception as _ke:
            logging.debug(f"_build_games_feed known_results read error: {_ke}")

    # Self-heal: backfill result/score for PDF games from GC UUID game files by date match
    if games_dir.exists():
        for game in pdf_games:
            if game.get("result") and game.get("score"):
                continue  # already enriched
            g_date = (game.get("date") or "")[:10]
            if not g_date:
                continue
            for gf in games_dir.glob("game_*.json"):
                try:
                    gdata = _read_json_file(gf, default={}) or {}
                    if (gdata.get("date") or "")[:10] != g_date:
                        continue
                    # Verify it's a real GC game file (has sharks block or score)
                    sc = gdata.get("score", {})
                    sh = sc.get("sharks") if isinstance(sc, dict) else None
                    op = sc.get("opponent") if isinstance(sc, dict) else None
                    if sh is None or op is None:
                        continue
                    gc_result = "W" if sh > op else ("L" if sh < op else "T")
                    gc_score_str = gdata.get("score_str") or f"{sh}-{op}"
                    if not game.get("result"):
                        game["result"] = gdata.get("result") or gc_result
                    if not game.get("score"):
                        game["score"] = gc_score_str
                    break
                except Exception:
                    continue

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

    # --- Also surface new-format games from gc_full_scraper_v2 not in index.json ---
    indexed_ids = {g.get("game_id") for g in pdf_games}
    if games_dir.exists():
        for gf in sorted(games_dir.glob("*.json")):
            if gf.name == "index.json":
                continue
            try:
                gdata = _read_json_file(gf, default={}) or {}
                if gdata.get("source") != "gc_full_scraper_v2":
                    continue
                gid = gdata.get("game_id") or gf.stem
                if gid in indexed_ids:
                    continue
                # Skip GC-scraped games with no actual stat data (future/unplayed games)
                sharks_block = gdata.get("sharks") or {}
                has_any_stats = any(
                    isinstance(v, list) and len(v) > 0
                    for v in sharks_block.values()
                )
                if not has_any_stats:
                    continue
                # Build a summary entry compatible with the dashboard GameCard
                sc = gdata.get("score", {})
                sh = sc.get("sharks") if isinstance(sc, dict) else None
                op = sc.get("opponent") if isinstance(sc, dict) else None
                score_str = f"{sh}-{op}" if sh is not None and op is not None else ""
                # Derive result from score
                result = ""
                if sh is not None and op is not None:
                    result = "W" if sh > op else ("L" if sh < op else "T")
                sharks_batting = sharks_block.get("batting") or []
                totals: dict = {}
                if sharks_batting:
                    def _s(lst, k):
                        try:
                            return sum(int(r.get(k) or 0) for r in lst)
                        except Exception:
                            return 0
                    totals = {
                        "pa": _s(sharks_batting, "pa"),
                        "ab": _s(sharks_batting, "ab"),
                        "h":  _s(sharks_batting, "h"),
                        "doubles": _s(sharks_batting, "doubles"),
                        "triples": _s(sharks_batting, "triples"),
                        "hr":  _s(sharks_batting, "hr"),
                        "rbi": _s(sharks_batting, "rbi"),
                        "r":   _s(sharks_batting, "r"),
                        "bb":  _s(sharks_batting, "bb"),
                        "hbp": _s(sharks_batting, "hbp"),
                        "so":  _s(sharks_batting, "so"),
                        "sb":  _s(sharks_batting, "sb"),
                    }
                pdf_games.append({
                    "game_id":     gid,
                    "date":        gdata.get("date", ""),
                    "opponent":    gdata.get("opponent", ""),
                    "sharks_side": gdata.get("sharks_side", ""),
                    "result":      gdata.get("result", "") or result,
                    "score":       gdata.get("score_str", score_str),
                    "sharks_totals": totals or None,
                    "source":      "gc_full_scraper_v2",
                })
                indexed_ids.add(gid)
            except Exception as _e:
                logging.debug(f"_build_games_feed new-format read error {gf.name}: {_e}")

    # De-duplicate: prefer GC-scraped games over PDF games for the same date
    gc_dates = {g["date"] for g in pdf_games if g.get("source") == "gc_full_scraper_v2" and g.get("date")}
    pdf_games = [g for g in pdf_games if not (
        g.get("source") != "gc_full_scraper_v2" and g.get("date") in gc_dates
    )]

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
    """Return full detail for a single game.
    Normalises both legacy (sharks_batting) and new (sharks.batting) formats
    so the dashboard always receives the shape it expects."""
    err = _validate_path_slug(game_id, "game_id")
    if err:
        return err
    game_file = TEAM_DIR / "games" / f"{game_id}.json"
    if not game_file.exists():
        return jsonify({"error": "Not found"}), 404
    try:
        with open(game_file, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logging.error(f"[GameDetail] Failed to read {game_id}: {e}")
        return jsonify({"error": "game_data_unavailable"}), 503

    # Self-heal: if primary file lacks full stats (PDF format), supplement from GC UUID file by date
    if "sharks" not in data and data.get("date"):
        g_date = str(data["date"])[:10]
        gc_dir = TEAM_DIR / "games"
        for gf in gc_dir.glob("game_*.json"):
            try:
                gdata = _read_json_file(gf, default={}) or {}
                if str(gdata.get("date") or "")[:10] == g_date and "sharks" in gdata:
                    data["sharks"] = gdata["sharks"]
                    # Also copy score/result if missing
                    if not data.get("result") and gdata.get("result"):
                        data["result"] = gdata["result"]
                    if not data.get("score") and gdata.get("score"):
                        data["score"] = gdata["score"]
                    if not data.get("score_str") and gdata.get("score_str"):
                        data["score_str"] = gdata["score_str"]
                    logging.debug(f"[GameDetail] Supplemented {game_id} with GC stats from {gf.name}")
                    break
            except Exception:
                continue

    def _strip_team_totals_row(rows: list) -> list:
        """Remove the AG Grid pinned-bottom team totals row from a batting/adv list.
        The totals row has aria-rowindex=2 (now filtered by scraper i > 2) but may
        survive in older scraped files.  Heuristic: the first row whose PA equals or
        exceeds the sum of all subsequent rows' PA is a totals row, not a player."""
        if not rows or len(rows) < 2:
            return rows
        try:
            first_pa = int(rows[0].get("pa") or 0)
            rest_pa  = sum(int(r.get("pa") or 0) for r in rows[1:])
            # totals row PA == team total == sum of player PAs (allow ±1 rounding)
            if first_pa > 0 and rest_pa > 0 and abs(first_pa - rest_pa) <= 1:
                return rows[1:]
        except Exception:
            pass
        return rows

    # --- Backward-compat bridge: new format → legacy fields ---
    # New format: data["sharks"] = {batting: [...], pitching: [...], ...}
    # Legacy format: data["sharks_batting"] = [...]
    if "sharks" in data and isinstance(data["sharks"], dict):
        sharks_block = data["sharks"]
        if "sharks_batting" not in data:
            data["sharks_batting"] = _strip_team_totals_row(sharks_block.get("batting") or [])
        if "sharks_pitching" not in data:
            data["sharks_pitching"] = sharks_block.get("pitching") or []
        if "sharks_fielding" not in data:
            data["sharks_fielding"] = sharks_block.get("fielding") or []
        # Enrich: expose all stat categories under explicit top-level keys
        for key in ("batting_advanced", "pitching_advanced", "pitching_breakdown",
                    "catching", "innings_played"):
            if key not in data and key in sharks_block:
                raw = sharks_block[key]
                # Strip totals row from batting_advanced too
                if key == "batting_advanced":
                    raw = _strip_team_totals_row(raw or [])
                data[f"sharks_{key}"] = raw

    # --- Opponent stats bridge ---
    if "opponent_stats" in data and isinstance(data["opponent_stats"], dict):
        opp_block = data["opponent_stats"]
        if "opponent_batting" not in data:
            data["opponent_batting"] = opp_block.get("batting") or []
        if "opponent_pitching" not in data:
            data["opponent_pitching"] = opp_block.get("pitching") or []

    # --- Score bridge: {sharks: 11, opponent: 10} → "11-10" string ---
    if isinstance(data.get("score"), dict) and "score_str" not in data:
        sc = data["score"]
        sh = sc.get("sharks")
        op = sc.get("opponent")
        if sh is not None and op is not None:
            data["score_str"] = f"{sh}-{op}"

    return jsonify(data)


@app.route('/api/scoreboard', methods=['GET'])
def handle_scoreboard():
    """Return live/recent scoreboard data from the GC public API.

    Checks for in-progress or today's game, returns score, inning, and
    game status so the frontend can render a real-time scoreboard.
    Falls back to schedule_manual.json for context when no API data."""
    team_id = os.getenv("GC_TEAM_ID", "NuGgx6WvP7TO")
    gc_api_base = "https://api.team-manager.gc.com"

    now = datetime.now(ET)
    today_str = now.strftime("%Y-%m-%d")

    # 1. Fetch games list from GC public API
    games = []
    try:
        resp = requests.get(
            f"{gc_api_base}/public/teams/{team_id}/games",
            timeout=10,
        )
        if resp.ok:
            games = resp.json() if isinstance(resp.json(), list) else []
    except Exception as e:
        logging.warning(f"[Scoreboard] GC API fetch failed: {e}")

    # 2. Find in-progress game first, then today's game
    live_game = None
    today_game = None
    for g in games:
        status = str(g.get("game_status", "")).lower()
        start_ts = str(g.get("start_ts", ""))
        game_date = ""
        try:
            game_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00")).astimezone(ET)
            game_date = game_dt.date().isoformat()
        except Exception:
            pass

        if status in ("in_progress", "active", "live"):
            live_game = g
            break
        if game_date == today_str and not today_game:
            today_game = g

    target_game = live_game or today_game

    # 3. Build response
    if not target_game:
        # Fallback: use schedule to show next game info
        sched_file = TEAM_DIR / "schedule_manual.json"
        if sched_file.exists():
            try:
                sched = _read_json_file(sched_file, default={}) or {}
                for sg in sched.get("upcoming", []):
                    if sg.get("is_game") and (sg.get("date") or "") >= today_str:
                        opponent = _clean_opponent_name(sg.get("opponent", ""))
                        return jsonify({
                            "status": "upcoming",
                            "opponent": opponent,
                            "date": sg.get("date"),
                            "time": sg.get("time"),
                            "home_away": sg.get("home_away"),
                            "message": "No game in progress",
                        })
            except Exception:
                pass
        return jsonify({"status": "no_game", "message": "No game scheduled today"})

    # Parse the target game
    gc_game_id = str(target_game.get("id", ""))
    status = str(target_game.get("game_status", "")).lower()
    score_obj = target_game.get("score") or {}
    opp_info = target_game.get("opponent_team") or {}
    opp_name = (opp_info.get("name") or "Opponent").strip()
    home_away = str(target_game.get("home_away", "")).lower()
    start_ts = str(target_game.get("start_ts", ""))

    # Determine score mapping: GC API uses "team" and "opponent_team"
    team_score = _safe_int(str(score_obj.get("team", 0)))
    opp_score = _safe_int(str(score_obj.get("opponent_team", 0)))

    # If we're the away team, the "team" score is us; if home, same
    # GC API always returns "team" as the team you queried for
    sharks_score = team_score
    opponent_score = opp_score

    # Inning/period info from the game data
    inning = target_game.get("current_inning") or target_game.get("inning")
    inning_half = target_game.get("inning_half") or target_game.get("half")
    linescore = target_game.get("linescore") or target_game.get("line_score")

    # Determine display status
    if status in ("in_progress", "active", "live"):
        display_status = "live"
    elif status == "completed":
        display_status = "final"
    elif status in ("scheduled", "pregame", ""):
        # Empty status = GC knows about the game but it hasn't started
        display_status = "pregame"
    else:
        display_status = "pregame"

    # Derive date and time from start_ts
    game_date_str = today_str
    game_time_str = ""
    try:
        game_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00")).astimezone(ET)
        game_date_str = game_dt.date().isoformat()
        game_time_str = game_dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        pass

    result = {
        "status": display_status,
        "gc_game_id": gc_game_id,
        "opponent": opp_name,
        "home_away": home_away,
        "sharks_score": sharks_score,
        "opponent_score": opponent_score,
        "inning": inning,
        "inning_half": inning_half,
        "linescore": linescore,
        "start_ts": start_ts,
        "date": game_date_str,
        "time": game_time_str,
        "game_status_raw": status,
        "fetched_at": now.isoformat(),
    }

    # 4. Try to get richer box-score data from local game files
    try:
        game_date = ""
        try:
            game_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00")).astimezone(ET)
            game_date = game_dt.date().isoformat()
        except Exception:
            game_date = today_str
        games_dir = TEAM_DIR / "games"
        if games_dir.exists():
            for gf in games_dir.glob("*.json"):
                if gf.name == "index.json":
                    continue
                try:
                    gdata = _read_json_file(gf, default={}) or {}
                    if (gdata.get("gc_game_id") == gc_game_id or
                        (gdata.get("date") or "")[:10] == game_date):
                        result["sharks_batting"] = gdata.get("sharks_batting") or []
                        result["opponent_batting"] = gdata.get("opponent_batting") or []
                        local_score = gdata.get("score")
                        if isinstance(local_score, dict):
                            if local_score.get("sharks") is not None:
                                result["sharks_score"] = _safe_int(str(local_score["sharks"]))
                            if local_score.get("opponent") is not None:
                                result["opponent_score"] = _safe_int(str(local_score["opponent"]))
                        break
                except Exception:
                    continue
    except Exception as e:
        logging.debug(f"[Scoreboard] Local game enrichment failed: {e}")

    # 5. Schedule context (time, home/away from our schedule)
    sched_file = TEAM_DIR / "schedule_manual.json"
    if sched_file.exists():
        try:
            sched = _read_json_file(sched_file, default={}) or {}
            for sg in sched.get("upcoming", []):
                if (sg.get("date") or "")[:10] == today_str:
                    result["time"] = sg.get("time", "") or result.get("time", "")
                    if not result.get("home_away"):
                        result["home_away"] = sg.get("home_away", "")
                    result["opponent"] = _clean_opponent_name(sg.get("opponent", result["opponent"]))
                    break
        except Exception:
            pass

    return jsonify(result)


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
    err = _validate_path_slug(slug, "opponent_slug")
    if err:
        return err
    team_file = DATA_DIR / "opponents" / slug / "team.json"
    if not team_file.exists():
        return jsonify({"error": "Not found"}), 404
    try:
        with open(team_file) as f:
            team = json.load(f)
    except Exception as e:
        logging.error(f"[OpponentDetail] Failed to read {slug}: {e}")
        return jsonify({"error": "opponent_data_unavailable"}), 503
    team["team_name"] = _canonical_team_name(team.get("team_name", slug), slug)
    return jsonify(team)


@app.route('/api/next-game', methods=['GET'])
def handle_next_game():
    """Return the next upcoming game with opponent slug and matchup URL."""
    sched_file = TEAM_DIR / "schedule_manual.json"
    if not sched_file.exists():
        return jsonify({"error": "Schedule unavailable"}), 503
    try:
        with open(sched_file) as f:
            schedule = json.load(f)
    except Exception:
        return jsonify({"error": "Schedule unavailable"}), 503
    if not isinstance(schedule, dict):
        return jsonify({"error": "Schedule unavailable"}), 503
    now = datetime.now(ET)
    disc_file = TEAM_DIR / "opponent_discovery.json"
    teams_list = []
    if disc_file.exists():
        try:
            with open(disc_file) as f:
                discovery = json.load(f)
            teams_list = discovery.get("teams", []) if isinstance(discovery, dict) else []
        except Exception:
            pass

    for game in schedule.get("upcoming", []):
        if not isinstance(game, dict) or game.get("is_game") is False:
            continue
        date_str = (game.get("date") or "").strip()
        time_str = (game.get("time") or "").strip()
        if not date_str:
            continue
        try:
            from practice_gen import _parse_event_datetime, _clean_opponent_name
            start = _parse_event_datetime(date_str, time_str, default_time="12:00 PM")
        except Exception:
            start = None
        if start and start > now:
            raw_opponent = (game.get("opponent") or "").strip()
            try:
                opponent = _clean_opponent_name(raw_opponent)
            except Exception:
                opponent = raw_opponent
            # Resolve slug
            slug = None
            for t in teams_list:
                tn = (t.get("team_name") or "").lower()
                if tn and (tn in opponent.lower() or opponent.lower() in tn):
                    slug = t.get("slug")
                    break
            if not slug:
                opp_dir = DATA_DIR / "opponents"
                if opp_dir.exists():
                    name_lower = opponent.lower().replace(" ", "_").replace("-", "_")
                    for d in opp_dir.iterdir():
                        if d.is_dir() and d.name in name_lower:
                            slug = d.name
                            break
            return jsonify({
                "opponent": opponent,
                "slug": slug,
                "date": date_str,
                "time": time_str,
                "home_away": game.get("home_away", ""),
            })
    return jsonify({"opponent": None, "slug": None, "date": None, "message": "No upcoming games"})


@app.route('/api/matchup/<opponent_slug>', methods=['GET'])
def handle_matchup(opponent_slug):
    """Run matchup analysis: Sharks vs a specific opponent."""
    err = _validate_path_slug(opponent_slug, "opponent_slug")
    if err:
        return err
    from swot_analyzer import analyze_matchup, load_team
    our_team = load_team(TEAM_DIR, prefer_merged=True)
    if not our_team:
        return jsonify({"error": "Sharks team data not found"}), 404

    # Enrich and reconcile Sharks roster so matchup uses complete season stats.
    _enrich_team_with_app_stats(our_team)
    _merge_team_with_scorebook_stats(our_team)
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
            # Also inject batting into roster entries so _team_aggregates roster-first
            # path can pick up stats (it checks roster[].batting before batting_stats[]).
            roster = opp_team.get("roster", [])
            if roster:
                game_by_num = {str(g.get("number", "")).strip(): g for g in opp_game_stats if g.get("number")}
                game_by_name = {g.get("name", "").strip().lower(): g for g in opp_game_stats if g.get("name")}
                for rp in roster:
                    rnum = str(rp.get("number", "")).strip()
                    rname = (rp.get("name") or "").strip().lower()
                    match = game_by_num.get(rnum) or game_by_name.get(rname)
                    if match:
                        game_bat = {k: v for k, v in match.items() if k not in ("name", "number")}
                        existing = rp.get("batting")
                        if not existing:
                            rp["batting"] = game_bat
                        else:
                            # Merge: use max() per counting stat so partial data doesn't zero-out game history
                            for k, v in game_bat.items():
                                cur = existing.get(k, 0)
                                if isinstance(v, (int, float)) and isinstance(cur, (int, float)):
                                    existing[k] = max(cur, v)
                                elif k not in existing or not cur:
                                    existing[k] = v
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

    # Attach opponent roster for display, sorted alphabetically by first name
    their_roster = [
        {"name": p.get("name", f"{p.get('first','')} {p.get('last','')}".strip()),
         "number": p.get("number", "")}
        for p in opp_team.get("roster", [])
    ]
    their_roster.sort(key=lambda p: (p.get("name") or "").strip().lower())
    result["their_roster"] = their_roster
    return jsonify(result)


def _aggregate_stats_from_games():
    """Aggregate batting stats per player across all parsed game files. Returns dict keyed by jersey number."""
    games_dir = TEAM_DIR / "games"
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


@app.route('/api/2fa-pending', methods=['GET'])
def handle_2fa_pending():
    """Check if the scraper is waiting for a 2FA code."""
    pending_file = DATA_DIR / ".2fa_pending"
    if pending_file.exists():
        try:
            requested_at = pending_file.read_text().strip()
        except Exception:
            requested_at = ""
        return jsonify({"pending": True, "requested_at": requested_at})
    return jsonify({"pending": False})


@app.route('/api/2fa-submit', methods=['POST'])
def handle_2fa_submit():
    """Submit a 2FA code for the scraper to use on next login attempt.

    Body: {"code": "123456"}
    The code is written to a file that the scraper checks during OTP handling.
    Also clears the auth cooldown so the scraper retries immediately.
    """
    data = request.get_json(silent=True) or {}
    code = str(data.get("code", "")).strip()
    if not code or not code.isdigit() or len(code) != 6:
        return jsonify({"error": "Invalid code. Must be a 6-digit number."}), 400

    # Write code for the scraper to pick up
    code_file = DATA_DIR / ".2fa_code"
    code_file.write_text(code)

    # Clear pending status
    pending_file = DATA_DIR / ".2fa_pending"
    pending_file.unlink(missing_ok=True)

    # Clear auth cooldown so the scraper retries on next cycle
    cooldown_file = DATA_DIR / ".auth_cooldown"
    cooldown_file.unlink(missing_ok=True)

    return jsonify({"ok": True, "message": "2FA code submitted. Scraper will use it on next login attempt."})


@app.route('/api/sync/status', methods=['GET'])
def handle_sync_status():
    """Return current sync daemon stage, progress, and milestone info."""
    milestones = [{"id": s, "pct": p, "label": l} for s, p, l in _SYNC_STAGES]
    return jsonify({**_SYNC_STATUS, "milestones": milestones})


_DEPLOY_STATUS: dict = {"status": "idle", "last_triggered": "", "last_completed": "", "error": ""}


@app.route('/api/deploy', methods=['POST'])
def handle_deploy_webhook():
    """Webhook endpoint for GitHub Actions to trigger a pull + rebuild.

    Secured with a bearer token set via DEPLOY_WEBHOOK_TOKEN env var.
    If no token is configured, the endpoint is disabled for safety.
    """
    expected_token = os.getenv("DEPLOY_WEBHOOK_TOKEN", "").strip()
    if not expected_token:
        return jsonify({"error": "Deploy webhook not configured (DEPLOY_WEBHOOK_TOKEN not set)"}), 503

    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {expected_token}":
        return jsonify({"error": "Unauthorized"}), 401

    if _DEPLOY_STATUS["status"] == "deploying":
        return jsonify({"status": "already_deploying", "since": _DEPLOY_STATUS["last_triggered"]}), 409

    def _run_deploy():
        _DEPLOY_STATUS["status"] = "deploying"
        _DEPLOY_STATUS["last_triggered"] = datetime.now(ET).isoformat()
        _DEPLOY_STATUS["error"] = ""
        try:
            import subprocess
            script = Path(__file__).parent.parent / "scripts" / "deploy.sh"
            result = subprocess.run(
                ["bash", str(script)],
                capture_output=True, text=True, timeout=600,
                cwd=str(Path(__file__).parent.parent),
            )
            if result.returncode != 0:
                _DEPLOY_STATUS["error"] = result.stderr[-500:] if result.stderr else "Unknown error"
                logging.error(f"[Deploy] Failed: {result.stderr}")
            else:
                logging.info(f"[Deploy] Success: {result.stdout[-200:]}")
            _DEPLOY_STATUS["last_completed"] = datetime.now(ET).isoformat()
        except Exception as e:
            _DEPLOY_STATUS["error"] = str(e)
            logging.error(f"[Deploy] Exception: {e}")
        finally:
            _DEPLOY_STATUS["status"] = "idle"

    deploy_thread = threading.Thread(target=_run_deploy, daemon=True)
    deploy_thread.start()
    return jsonify({"status": "triggered", "message": "Deploy started in background"}), 202


@app.route('/api/deploy/status', methods=['GET'])
def handle_deploy_status():
    """Check the current deploy status."""
    return jsonify(_DEPLOY_STATUS)


@app.route('/api/health', methods=['GET'])
def handle_health():
    """Return pipeline health with staleness detection for each data source.

    Sources are split into *required* (produced by the sync daemon pipeline)
    and *optional* (produced by external tools like gc_app_auto).  Only
    required sources contribute to the ``stale_sources`` warning list shown
    in the dashboard banner.  Optional sources are still reported in the
    per-source detail so operators can inspect them, but missing/stale
    optional files no longer trigger a user-facing warning.
    """
    STALE_THRESHOLD_HOURS = 48
    now = datetime.now(ET)
    # Required: files the sync daemon pipeline directly creates/updates
    required_sources = {
        "team_enriched": TEAM_DIR / "team_enriched.json",
        "swot_analysis": TEAM_DIR / "swot_analysis.json",
        "lineups": TEAM_DIR / "lineups.json",
        "pipeline_health": TEAM_DIR / "pipeline_health.json",
    }
    # Optional: external feed files (gc_app_auto produces these; the daemon
    # consumes them but does not generate them)
    optional_sources = {
        "app_stats": TEAM_DIR / "app_stats.json",
        "schedule": TEAM_DIR / "schedule_manual.json",
    }
    result = {"checked_at": now.isoformat(), "stale_sources": [], "sources": {}}
    for name, path in {**required_sources, **optional_sources}.items():
        is_required = name in required_sources
        if not path.exists():
            result["sources"][name] = {"exists": False, "stale": True, "required": is_required}
            if is_required:
                result["stale_sources"].append(name)
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=ET)
        age_hours = (now - mtime).total_seconds() / 3600
        stale = age_hours > STALE_THRESHOLD_HOURS
        result["sources"][name] = {
            "exists": True,
            "last_updated": mtime.isoformat(),
            "age_hours": round(age_hours, 1),
            "stale": stale,
            "required": is_required,
        }
        if stale and is_required:
            result["stale_sources"].append(name)
    return jsonify(result)


@app.route('/api/h2h/<opponent_slug>', methods=['GET'])
def handle_h2h(opponent_slug):
    """Return head-to-head game history and W-L summary against an opponent."""
    err = _validate_path_slug(opponent_slug, "opponent_slug")
    if err:
        return err
    try:
        from stats_db import get_h2h_summary
        summary = get_h2h_summary(opponent_slug)
        return jsonify(summary)
    except Exception as e:
        logging.warning(f"[H2H] query failed for '{opponent_slug}': {e}")
        return jsonify({"error": "H2H data unavailable", "games": [], "games_played": 0}), 503


@app.route('/api/team', methods=['GET'])
def handle_team():
    """Return team data, enriched from app_stats and reconciled with scorebook totals."""
    team_file = TEAM_DIR / "team_enriched.json"
    if not team_file.exists():
        team_file = TEAM_DIR / "team_merged.json"
    if not team_file.exists():
        team_file = TEAM_DIR / "team.json"
    if not team_file.exists():
        return jsonify({"error": "No team data found"}), 404

    team = _read_json_file(team_file, default=None)
    if not isinstance(team, dict):
        return jsonify({"error": "team_data_unavailable"}), 503

    # Enrich roster with current app_stats.json (always most up-to-date)
    _enrich_team_with_app_stats(team)
    _merge_team_with_scorebook_stats(team)
    team["team_name"] = _canonical_team_name(team.get("team_name", "The Sharks"), "sharks")

    # Supplement with richer stats from team.json (CSV-ingested) when fields are missing
    # team.json has: catching, innings_played, pitching_advanced, pitching_breakdown, babip, etc.
    base_team_file = TEAM_DIR / "team.json"
    if base_team_file.exists() and base_team_file != team_file:
        base_team = _read_json_file(base_team_file, default={}) or {}
        base_by_name = {}
        for bp in base_team.get("roster", []):
            first = (bp.get("first") or "").strip().lower()
            last = (bp.get("last") or "").strip().lower()
            num = str(bp.get("number") or "").strip()
            if first:
                base_by_name[f"{first} {last}".strip()] = bp
            if num:
                base_by_name[f"#{num}"] = bp
        SUPPLEMENT_KEYS = ["catching", "innings_played", "pitching_advanced", "pitching_breakdown"]
        ADV_SUPPLEMENT = ["babip", "ps", "ps_pa", "tb", "xbh", "two_out_rbi", "ba_risp",
                          "qab_pct", "lob", "two_s_three", "six_plus", "gidp", "gitp"]
        PITCHING_SUPPLEMENT = ["gp", "gs", "sv", "svo", "bs", "bf", "np", "r", "kl",
                               "hbp", "wp", "pik", "bk", "cs", "sb", "lob", "baa"]
        for player in team.get("roster", []):
            first = (player.get("first") or "").strip().lower()
            last = (player.get("last") or "").strip().lower()
            num = str(player.get("number") or "").strip()
            bp = base_by_name.get(f"{first} {last}".strip()) or base_by_name.get(f"#{num}")
            if not bp:
                continue
            # Add missing top-level stat blocks
            for key in SUPPLEMENT_KEYS:
                if not player.get(key) and bp.get(key):
                    player[key] = bp[key]
            # Supplement batting_advanced with extra fields from CSV
            if isinstance(player.get("batting_advanced"), dict) and isinstance(bp.get("batting_advanced"), dict):
                adv = player["batting_advanced"]
                base_adv = bp["batting_advanced"]
                for k in ADV_SUPPLEMENT:
                    if adv.get(k) is None and base_adv.get(k) is not None:
                        adv[k] = base_adv[k]
            # Supplement pitching block with extra fields from team.json (baa, gp, bf, np, etc.)
            if isinstance(player.get("pitching"), dict) and isinstance(bp.get("pitching"), dict):
                p_block = player["pitching"]
                base_p = bp["pitching"]
                for k in PITCHING_SUPPLEMENT:
                    if p_block.get(k) is None and base_p.get(k) is not None:
                        p_block[k] = base_p[k]
            elif not player.get("pitching") and bp.get("pitching"):
                player["pitching"] = bp["pitching"]

    # Update record from known_game_results.json (authoritative source)
    try:
        known_results = _read_json_file(CONFIG_DIR / "known_game_results.json", default={}) or {}
        results_list = known_results.get("results") or []
        wins = sum(1 for r in results_list if isinstance(r, dict) and r.get("result") == "W")
        losses = sum(1 for r in results_list if isinstance(r, dict) and r.get("result") == "L")
        if wins + losses > 0:
            # Preserve GP from existing record if present
            gp_match = ""
            old_record = team.get("record", "")
            if "GP" in old_record:
                import re as _re
                m = _re.search(r'\((\d+ GP)\)', old_record)
                gp_match = f" ({m.group(1)})" if m else ""
            team["record"] = f"{wins}-{losses}{gp_match}"
    except Exception:
        pass

    # Sort roster alphabetically by first name for consistent display
    if isinstance(team.get("roster"), list):
        team["roster"] = sorted(
            team["roster"],
            key=lambda p: (p.get("first") or p.get("name", "")).strip().lower()
        )

    # Always set last_updated from team file mtime so frontend timestamp refreshes after sync
    try:
        team["last_updated"] = datetime.fromtimestamp(
            team_file.stat().st_mtime, tz=ET
        ).isoformat()
    except Exception:
        pass

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
    if len(first) > 64 or len(last) > 64:
        return jsonify({"error": "name_too_long"}), 400
    if len(number) > 4:
        return jsonify({"error": "invalid_number"}), 400
    if gc_team_id and (len(gc_team_id) > 40 or not re.match(r'^[A-Za-z0-9_-]+$', gc_team_id)):
        return jsonify({"error": "invalid_gc_team_id"}), 400

    manifest_file = TEAM_DIR / "roster_manifest.json"
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
        from swot_analyzer import run_team_analysis
        run_lineup()
        run_team_analysis()
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


def _all_roster_names(team: dict) -> list[str]:
    names = []
    for p in team.get("roster", []):
        name = (p.get("name") or f"{p.get('first','')} {p.get('last','')}").strip()
        if name:
            names.append(name)
    return names


def _core_roster_names(team: dict) -> list[str]:
    names = []
    for p in team.get("roster", []):
        if p.get("core") is False:
            continue
        name = (p.get("name") or f"{p.get('first','')} {p.get('last','')}").strip()
        if name:
            names.append(name)
    # Sort alphabetically by first name for consistent display
    names.sort(key=lambda n: n.strip().lower())
    return names


def _load_practice_rsvp_defaults(team: dict) -> tuple[list[str], str, dict]:
    """Find default selected practice players.
    Priority: practice_rsvp.json -> availability.json -> full roster."""
    roster_names = _core_roster_names(team)
    roster_set = {n.lower(): n for n in roster_names}
    practice_meta = {"date": None, "title": None}

    rsvp_file = TEAM_DIR / "practice_rsvp.json"
    if rsvp_file.exists():
        data = _read_json_file(rsvp_file, default={}) or {}
        candidates = []
        if isinstance(data.get("next"), dict):
            nxt = data.get("next", {})
            practice_meta["date"] = nxt.get("date")
            practice_meta["title"] = nxt.get("title")
            candidates = nxt.get("attending", []) or []
            if not candidates and isinstance(nxt.get("rsvps"), dict):
                candidates = [n for n, v in nxt.get("rsvps", {}).items() if bool(v)]
        elif isinstance(data.get("practices"), list) and data.get("practices"):
            upcoming = sorted(
                [p for p in data.get("practices", []) if isinstance(p, dict)],
                key=lambda x: str(x.get("date", "")),
            )
            now = datetime.now(ET).strftime("%Y-%m-%d")
            pick = next((p for p in upcoming if str(p.get("date", "")) >= now), upcoming[-1] if upcoming else {})
            practice_meta["date"] = pick.get("date")
            practice_meta["title"] = pick.get("title")
            candidates = pick.get("attending", []) or []
            if not candidates and isinstance(pick.get("rsvps"), dict):
                candidates = [n for n, v in pick.get("rsvps", {}).items() if bool(v)]

        selected = []
        for raw in candidates:
            key = str(raw).strip().lower()
            if key in roster_set:
                selected.append(roster_set[key])
        if selected:
            return sorted(set(selected)), "practice_rsvp", practice_meta

    availability_file = TEAM_DIR / "availability.json"
    availability = _read_json_file(availability_file, default={}) or {}
    if isinstance(availability, dict) and availability:
        selected = []
        for name, state in availability.items():
            if bool(state):
                key = str(name).strip().lower()
                if key in roster_set:
                    selected.append(roster_set[key])
        if selected:
            return sorted(set(selected)), "availability", practice_meta

    return sorted(roster_names), "roster_default", practice_meta


def _calc_player_practice_profile(player: dict) -> dict:
    batting = normalize_batting_row(player.get("batting", player))
    pitching = normalize_pitching_row(player.get("pitching", player))
    fielding = normalize_fielding_row(player.get("fielding", player))
    ab = batting.get("ab", 0)
    pa = batting.get("pa", 0)
    h = batting.get("h", 0)
    bb = batting.get("bb", 0)
    hbp = batting.get("hbp", 0)
    so = batting.get("so", 0)
    sb = batting.get("sb", 0)
    r = batting.get("r", 0)
    obp = batting.get("obp", 0.0)
    slg = batting.get("slg", 0.0)
    k_rate = (so / pa) if pa > 0 else 0.0
    bb_rate = (bb / pa) if pa > 0 else 0.0
    contact_rate = (h / ab) if ab > 0 else 0.0
    ip = pitching.get("ip", 0.0)
    bb_per_ip = (pitching.get("bb", 0) / ip) if ip > 0 else 0.0
    err = fielding.get("e", 0)
    fpct = fielding.get("fpct", 0.0)
    return {
        "pa": pa, "ab": ab, "h": h, "bb": bb, "hbp": hbp, "so": so, "sb": sb, "r": r,
        "obp": obp, "slg": slg, "k_rate": k_rate, "bb_rate": bb_rate, "contact_rate": contact_rate,
        "ip": ip, "bb_per_ip": bb_per_ip, "errors": err, "fpct": fpct,
    }


def _build_practice_needs(team: dict, selected_names: list[str]) -> list[dict]:
    selected_set = {n.lower() for n in selected_names}
    players = []
    for p in team.get("roster", []):
        name = (p.get("name") or f"{p.get('first','')} {p.get('last','')}").strip()
        if not name:
            continue
        if selected_set and name.lower() not in selected_set:
            continue
        prof = _calc_player_practice_profile(p)
        players.append({"name": name, "number": p.get("number", ""), "profile": prof})

    if not players:
        return []

    def _top(items):
        return [f"#{p['number']} {p['name']}".strip() for p in items[:5]]

    needs = []
    plate = sorted([p for p in players if p["profile"]["pa"] >= 4 and p["profile"]["k_rate"] >= 0.33], key=lambda x: x["profile"]["k_rate"], reverse=True)
    if plate:
        score = round(sum((p["profile"]["k_rate"] - 0.33) * 100 for p in plate), 1)
        needs.append({"key": "plate_discipline", "title": "Plate Discipline & Two-Strike Plan", "score": score, "focus_players": _top(plate), "why": "Strikeout pressure is limiting run creation.", "drills": PRACTICE_NEED_DRILLS["plate_discipline"]})

    contact = sorted([p for p in players if p["profile"]["pa"] >= 4 and p["profile"]["obp"] < 0.34], key=lambda x: x["profile"]["obp"])
    if contact:
        score = round(sum((0.34 - p["profile"]["obp"]) * 100 for p in contact), 1)
        needs.append({"key": "contact_on_base", "title": "On-Base Contact Quality", "score": score, "focus_players": _top(contact), "why": "Low OBP group needs more quality at-bats.", "drills": PRACTICE_NEED_DRILLS["contact_on_base"]})

    power = sorted([p for p in players if p["profile"]["pa"] >= 4 and p["profile"]["slg"] < 0.30], key=lambda x: x["profile"]["slg"])
    if power:
        score = round(sum((0.30 - p["profile"]["slg"]) * 100 for p in power), 1)
        needs.append({"key": "slugging_power", "title": "Gap Power Development", "score": score, "focus_players": _top(power), "why": "Need more extra-base impact from hittable pitches.", "drills": PRACTICE_NEED_DRILLS["slugging_power"]})

    defense = sorted([p for p in players if p["profile"]["errors"] > 0 or (p["profile"]["fpct"] > 0 and p["profile"]["fpct"] < 0.90)], key=lambda x: (x["profile"]["errors"], 1 - x["profile"]["fpct"]), reverse=True)
    if defense:
        score = round(sum((p["profile"]["errors"] * 8) + (max(0.0, 0.90 - p["profile"]["fpct"]) * 100) for p in defense), 1)
        needs.append({"key": "defense_reliability", "title": "Defensive Reliability", "score": score, "focus_players": _top(defense), "why": "Errors and conversion consistency are costing outs.", "drills": PRACTICE_NEED_DRILLS["defense_reliability"]})

    pitchers = sorted([p for p in players if p["profile"]["ip"] >= 0.7 and p["profile"]["bb_per_ip"] >= 1.0], key=lambda x: x["profile"]["bb_per_ip"], reverse=True)
    if pitchers:
        score = round(sum((p["profile"]["bb_per_ip"] - 1.0) * 25 for p in pitchers), 1)
        needs.append({"key": "pitch_command", "title": "Pitch Command", "score": score, "focus_players": _top(pitchers), "why": "Walk rate is elevating pitch count and traffic.", "drills": PRACTICE_NEED_DRILLS["pitch_command"]})

    baserun = sorted([p for p in players if p["profile"]["pa"] >= 4 and p["profile"]["sb"] == 0 and p["profile"]["obp"] >= 0.33], key=lambda x: x["profile"]["obp"], reverse=True)
    if baserun:
        score = round(sum((p["profile"]["obp"] - 0.33) * 60 for p in baserun), 1)
        needs.append({"key": "baserunning_iq", "title": "Baserunning Decision Speed", "score": score, "focus_players": _top(baserun), "why": "On-base runners can convert more pressure with better reads.", "drills": PRACTICE_NEED_DRILLS["baserunning_iq"]})

    needs.sort(key=lambda x: x["score"], reverse=True)
    for idx, item in enumerate(needs, start=1):
        item["priority"] = idx
    return needs


def _load_voice_context() -> dict:
    team_file = TEAM_DIR / "team_enriched.json"
    if not team_file.exists():
        team_file = TEAM_DIR / ("team_merged.json" if (TEAM_DIR / "team_merged.json").exists() else "team.json")

    team = _read_json_file(team_file, default={}) or {}
    if isinstance(team, dict):
        _enrich_team_with_app_stats(team)
        _merge_team_with_scorebook_stats(team)
        team["team_name"] = _canonical_team_name(team.get("team_name", "The Sharks"), "sharks")

    swot = _read_json_file(TEAM_DIR / "swot_analysis.json", default={}) or {}
    lineups = _read_json_file(TEAM_DIR / "lineups.json", default={}) or {}
    schedule = _read_json_file(TEAM_DIR / "schedule_manual.json", default={"upcoming": [], "past": []}) or {"upcoming": [], "past": []}

    # Build deduplicated games list using the authoritative feed (uses known_game_results.json)
    games = _build_games_feed()

    return {"team": team, "swot": swot, "lineups": lineups, "schedule": schedule, "games": games}


def _tts_stat(v) -> str:
    """Convert a decimal stat like 0.778 to a spoken form like 'seven seventy-eight'."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    # Format to 3 decimal places, strip leading zero: 0.778 -> ".778" -> "778"
    s = f"{f:.3f}"  # e.g. "0.778"
    if s.startswith("0."):
        digits = s[2:]  # "778"
    elif s.startswith("-0."):
        digits = s[3:]
    else:
        return str(round(f, 3))
    # Speak as two parts: first digit and last two, e.g. "7 seventy-eight" -> "seven seventy-eight"
    if len(digits) == 3:
        hundreds = int(digits[0])
        tens_ones = int(digits[1:])
        hundreds_words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
        return f"{hundreds_words[hundreds]} {tens_ones:02d}" if tens_ones > 0 else hundreds_words[hundreds]
    return digits


# Phonetic pronunciation map for names the TTS engine mispronounces.
# Key: substring to find (case-insensitive), Value: phonetic replacement.
_PHONETIC_MAP = {
    "VanDeusen": "Van Doo-sen",
    "Hourahan": "Hour-a-han",
    "Moros": "Morr-ohs",
    "Gomez": "Go-mez",
    "Santiago": "Sahn-tee-ah-go",
    "McKinney": "Mick-Kinney",
    "Sephina": "Seh-fee-nah",
    "Maylani": "May-lah-nee",
    "Mikayla": "Mih-Kay-lah",
    "Juliette": "Julie-ett",
    "Deliliah": "Duh-LYE-luh",
    "Ember": "Em-ber",
    "Lexi": "LEX-ee",
    "Ruby": "ROO-bee",
    "NWVLL": "North West Volusia Little League",
    "PCLL": "Palm Coast Little League",
    "Stihlers": "Steelers",
    "Riptide": "Rip-tide",
}


def _apply_phonetics(text: str) -> str:
    """Replace known mispronounced names/words with phonetic spellings for TTS."""
    result = text
    for word, phonetic in _PHONETIC_MAP.items():
        # Case-insensitive replacement preserving original position
        import re
        result = re.sub(re.escape(word), phonetic, result, flags=re.IGNORECASE)
    return result


def _build_voice_overview_text(ctx: dict) -> str:
    team = ctx.get("team", {}) if isinstance(ctx, dict) else {}
    swot = ctx.get("swot", {}) if isinstance(ctx, dict) else {}
    lineups = ctx.get("lineups", {}) if isinstance(ctx, dict) else {}
    schedule = ctx.get("schedule", {}) if isinstance(ctx, dict) else {}

    # Compute record from games data — deduplicate by date to avoid double-counting
    games_list = ctx.get("games", [])
    if isinstance(games_list, list):
        seen_dates = set()
        wins = 0
        losses = 0
        for g in games_list:
            if not isinstance(g, dict) or not g.get("result"):
                continue
            g_date = (g.get("date") or "")[:10]
            if g_date in seen_dates:
                continue
            seen_dates.add(g_date)
            if g["result"] == "W":
                wins += 1
            elif g["result"] == "L":
                losses += 1
        record = f"{wins} and {losses}" if (wins + losses) > 0 else "oh and oh"
    else:
        record = "oh and oh"

    roster = [p for p in team.get("roster", []) if isinstance(p, dict) and p.get("core", True) is not False]

    def _player_name(p: dict) -> str:
        return str(p.get("name") or f"{p.get('first', '')} {p.get('last', '')}").strip() or "Unknown"

    top_hitters = sorted(
        roster,
        key=lambda p: (
            float(normalize_batting_row(p).get("obp", 0.0)),
            float(normalize_batting_row(p).get("ops", 0.0)),
            str(p.get("last", "")),
        ),
        reverse=True,
    )[:3]
    hitter_text = ", ".join(
        f"{_player_name(p)}, on-base percentage {_tts_stat(normalize_batting_row(p).get('obp', 0.0))}"
        for p in top_hitters
    ) or "no clear hitting leaders yet"

    strengths = ((swot.get("team_swot") or {}).get("strengths") or [])
    weaknesses = ((swot.get("team_swot") or {}).get("weaknesses") or [])
    strengths_text = strengths[0] if strengths else "team strengths still stabilizing"
    weaknesses_text = weaknesses[0] if weaknesses else "no major weakness trend yet"

    balanced = (lineups.get("balanced") or {}).get("lineup") or []
    top_order = ", ".join(
        f"{_player_name(p)}, jersey number {p.get('number', '?')}"
        for p in balanced[:3]
    ) or "lineup not generated"

    today = datetime.now(ET).strftime("%Y-%m-%d")
    next_game = sorted(
        [g for g in (schedule.get("upcoming") or []) if str(g.get("date", "")) >= today],
        key=lambda x: str(x.get("date", "")),
    )
    next_game_text = "No games on the horizon right now."
    if next_game:
        game = next_game[0]
        opp = _clean_opponent_name(str(game.get("opponent", "Opponent")))
        ha = "at home" if game.get("home_away") == "home" else "on the road"
        game_date = game.get('date', '')
        try:
            dt = datetime.strptime(game_date, '%Y-%m-%d')
            date_spoken = dt.strftime('%A, %B ') + str(dt.day)
        except Exception:
            date_spoken = game_date or 'a date to be determined'
        next_game_text = f"Next up, the Sharks take on the {opp} {ha} on {date_spoken}! Let's go!"

    raw = (
        f"Hey Sharks fans! Here's your latest Sharks update! "
        f"The squad is {record} this season! "
        f"Leading the charge at the plate: {hitter_text}! "
        f"The team's biggest strength right now? {strengths_text}. "
        f"Area to focus on: {weaknesses_text}. "
        f"The projected top of the batting order is {top_order}. "
        f"{next_game_text}"
    )
    return _apply_phonetics(raw)


def _synthesize_voice_update(text: str) -> bytes:
    api_key = _resolve_secret("ELEVENLABS_API_KEY")
    voice_id = (
        _resolve_secret("ELEVENLABS_VOICE_ID")
        or os.getenv("ELEVENLABS_DEFAULT_VOICE_ID", "").strip()
        or DEFAULT_FALLBACK_VOICE_ID
    )
    model_id = os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")

    if not api_key:
        raise RuntimeError("Voice updates require an ElevenLabs API key. Add ELEVENLABS_API_KEY to .env")
    if not voice_id:
        raise RuntimeError("Missing ELEVENLABS_VOICE_ID.")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.15,
            "similarity_boost": 0.85,
            "style": 0.65,
            "use_speaker_boost": True,
        },
    }
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key,
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs returned {resp.status_code}: {resp.text[:300]}")
    return resp.content


@app.route('/api/voice-update', methods=['GET'])
def handle_voice_update():
    """
    Generate and return a short spoken team status update as MP3.
    Falls back to the most recently cached MP3 if live synthesis fails.
    """
    mp3_file = TEAM_DIR / "voice_overview_latest.mp3"
    meta_file = TEAM_DIR / "voice_overview_latest.json"

    try:
        ctx = _load_voice_context()
        text = _build_voice_overview_text(ctx)
        audio = _synthesize_voice_update(text)

        now_iso = datetime.now(ET).isoformat()
        with open(mp3_file, "wb") as f:
            f.write(audio)
        with open(meta_file, "w") as f:
            json.dump({"generated_at": now_iso, "script": text}, f, indent=2)

        response = Response(audio, mimetype="audio/mpeg")
        response.headers["Content-Disposition"] = 'inline; filename="voice_overview_latest.mp3"'
        response.headers["X-Voice-Generated-At"] = now_iso
        return response
    except Exception as e:
        logging.error(f"[Voice] Live synthesis failed: {e}")
        # Fallback: serve cached MP3 if available
        if mp3_file.exists() and mp3_file.stat().st_size > 0:
            logging.info("[Voice] Serving cached voice_overview_latest.mp3")
            with open(mp3_file, "rb") as f:
                cached_audio = f.read()
            generated_at = ""
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text())
                    generated_at = meta.get("generated_at", "")
                except Exception:
                    pass
            response = Response(cached_audio, mimetype="audio/mpeg")
            response.headers["Content-Disposition"] = 'inline; filename="voice_overview_latest.mp3"'
            response.headers["X-Voice-Generated-At"] = generated_at
            response.headers["X-Voice-Cached"] = "true"
            return response
        return jsonify({"error": "voice_update_failed", "detail": str(e)}), 503


@app.route('/api/schedule', methods=['GET'])
def handle_schedule():
    """Return upcoming and past games from schedule_manual.json.

    Dynamically reconciles placement: any 'upcoming' game whose date has
    already passed is promoted to 'past', and its result/score are filled
    in from config/known_game_results.json if available.  This means the
    Pi never needs a manual edit when schedule_manual.json lags reality.
    """
    schedule_file = TEAM_DIR / "schedule_manual.json"
    if not schedule_file.exists():
        return jsonify({"upcoming": [], "past": []})
    data = _read_json_file(schedule_file, default={"upcoming": [], "past": []}) or {"upcoming": [], "past": []}

    # Load authoritative known results (tracked in git)
    known_by_date: dict = {}
    known_results_file = CONFIG_DIR / "known_game_results.json"
    if known_results_file.exists():
        try:
            kd = _read_json_file(known_results_file, default={}) or {}
            for kr in kd.get("results", []):
                kr_date = (kr.get("date") or "")[:10]
                if kr_date:
                    known_by_date[kr_date] = kr
        except Exception:
            pass

    today_str = datetime.now(ET).strftime("%Y-%m-%d")

    # Promote stale 'upcoming' entries to 'past'
    still_upcoming: list = []
    promoted: list = []
    for game in data.get("upcoming", []):
        game_date = (game.get("date") or "")[:10]
        if game_date and game_date < today_str:
            # Apply known result if available
            kr = known_by_date.get(game_date)
            if kr:
                game.setdefault("result", kr.get("result", ""))
                game.setdefault("score", kr.get("score", ""))
            promoted.append(game)
        else:
            still_upcoming.append(game)

    # Merge promoted games at the front of past (newest first)
    merged_past = promoted + list(data.get("past", []))

    # Apply known results to all past games (fill blanks)
    for game in merged_past:
        game_date = (game.get("date") or "")[:10]
        kr = known_by_date.get(game_date)
        if kr:
            if not game.get("result"):
                game["result"] = kr.get("result", "")
            if not game.get("score"):
                game["score"] = kr.get("score", "")

    # Clean opponent names for display
    for game in still_upcoming + merged_past:
        raw = game.get("opponent", "")
        game["opponent_raw"] = raw
        game["opponent"] = _clean_opponent_name(raw)

    return jsonify({"upcoming": still_upcoming, "past": merged_past})


@app.route('/api/opponent-discovery', methods=['GET'])
def handle_opponent_discovery():
    """Return latest opponent ID discovery artifact."""
    artifact_file = TEAM_DIR / "opponent_discovery.json"
    if not artifact_file.exists():
        return jsonify({"generated_at": None, "teams": [], "missing_schedule_opponents": []})
    data = _read_json_file(artifact_file, default={}) or {}
    return jsonify(data)


@app.route('/api/practice-insights', methods=['GET', 'POST'])
def handle_practice_insights():
    """Build tailored practice priorities from current team stats."""
    try:
        team_file = TEAM_DIR / "team_enriched.json"
        if not team_file.exists():
            team_file = TEAM_DIR / ("team_merged.json" if (TEAM_DIR / "team_merged.json").exists() else "team.json")
        team = _read_json_file(team_file, default={}) or {}
        if not isinstance(team, dict):
            team = {}

        try:
            _enrich_team_with_app_stats(team)
        except Exception as e:
            logging.warning(f"[PracticeInsights] app_stats enrichment skipped: {e}")
        try:
            _merge_team_with_scorebook_stats(team)
        except Exception as e:
            logging.warning(f"[PracticeInsights] scorebook merge skipped: {e}")
        team["team_name"] = _canonical_team_name(team.get("team_name", "The Sharks"), "sharks")

        # Ensure roster exists as a list even if missing/malformed
        if not isinstance(team.get("roster"), list):
            team["roster"] = []

        default_players, default_source, practice_meta = _load_practice_rsvp_defaults(team)
        core_names = _core_roster_names(team)
        core_set = {n.lower() for n in core_names}

        selected_names = []
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            if not isinstance(body, dict):
                body = {}
            players_raw = body.get("players") or []
            if not isinstance(players_raw, list):
                players_raw = []
            selected_names = [str(n).strip() for n in players_raw if str(n).strip()]
        else:
            csv = (request.args.get("players") or "").strip()
            if csv:
                selected_names = [p.strip() for p in csv.split(",") if p.strip()]

        if not selected_names:
            selected_names = default_players if isinstance(default_players, list) else []
        selected_names = [n for n in selected_names if n.lower() in core_set]
        if not selected_names:
            selected_names = core_names if isinstance(core_names, list) else []

        try:
            needs = _build_practice_needs(team, selected_names)
        except Exception as e:
            logging.warning(f"[PracticeInsights] _build_practice_needs failed: {e}")
            needs = []
        if not needs:
            needs = [{
                "key": "general_fundamentals",
                "title": "General Fundamentals",
                "priority": 1,
                "score": 1.0,
                "focus_players": selected_names[:5],
                "why": "Not enough player sample for stat-targeted specialization yet.",
                "drills": [
                    {"name": "Throw-Catch-Footwork Circuit", "duration_min": 15, "goal": "Improve transfer speed and receiving mechanics."},
                    {"name": "Contact + Baserun Combo", "duration_min": 15, "goal": "Build consistent bat-to-ball and first-step aggression."},
                ],
            }]

        recommended_plan = []
        for need in needs[:3]:
            if not isinstance(need, dict):
                continue
            for drill in (need.get("drills") or [])[:2]:
                if not isinstance(drill, dict):
                    continue
                recommended_plan.append({
                    "need": need.get("title", ""),
                    "drill": drill.get("name", ""),
                    "duration_min": drill.get("duration_min", 10),
                    "goal": drill.get("goal", ""),
                    "focus_players": need.get("focus_players", []),
                })

        return jsonify({
            "generated_at": datetime.now(ET).isoformat(),
            "team_name": team.get("team_name", "The Sharks"),
            "default_player_source": default_source,
            "practice_meta": practice_meta if isinstance(practice_meta, dict) else {"date": None, "title": None},
            "selected_players": selected_names,
            "available_players": core_names,
            "needs": needs,
            "recommended_plan": recommended_plan,
        })
    except Exception as e:
        logging.error(f"[PracticeInsights] Unhandled error: {e}")
        return jsonify({
            "error": "practice_insights_failed",
            "detail": str(e),
            "generated_at": datetime.now(ET).isoformat(),
            "team_name": "The Sharks",
            "default_player_source": "error",
            "practice_meta": {"date": None, "title": None},
            "selected_players": [],
            "available_players": [],
            "needs": [{
                "key": "general_fundamentals",
                "title": "General Fundamentals",
                "priority": 1,
                "score": 1.0,
                "focus_players": [],
                "why": "Practice data temporarily unavailable — run general fundamentals.",
                "drills": [
                    {"name": "Throw-Catch-Footwork Circuit", "duration_min": 15, "goal": "Improve transfer speed and receiving mechanics."},
                    {"name": "Contact + Baserun Combo", "duration_min": 15, "goal": "Build consistent bat-to-ball and first-step aggression."},
                ],
            }],
            "recommended_plan": [],
        })


@app.route('/api/stats-db/status', methods=['GET'])
def handle_stats_db_status():
    """Return snapshot DB status for operational visibility."""
    try:
        from stats_db import get_db_status

        return jsonify(get_db_status())
    except Exception as e:
        logging.error(f"[DB] status read failed: {e}")
        return jsonify({"error": "stats_db_unavailable"}), 503


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
        lineups_file = TEAM_DIR / "lineups.json"
        lineups = {}
        if lineups_file.exists():
            with open(lineups_file) as f:
                lineups = json.load(f)
        # Sanitize: separate strategy dicts from metadata strings so callers
        # can safely iterate values calling .get() without crashing.
        if isinstance(lineups, dict):
            sanitized = {}
            meta = {}
            for k, v in lineups.items():
                if isinstance(v, dict):
                    sanitized[k] = v
                else:
                    meta[k] = v
            lineups = {**sanitized, "_meta": meta}
        # Optionally regenerate SWOT too
        if data.get("swot"):
            from swot_analyzer import run_team_analysis
            run_team_analysis()
        return jsonify({"status": "ok", "lineups": lineups})
    except Exception as e:
        logging.error(f"Regenerate lineups error: {e}")
        return jsonify({"error": str(e)}), 500


def _record_h2h_from_games():
    """Scan game JSON files and insert h2h records for any new games."""
    games_dir = TEAM_DIR / "games"
    if not games_dir.exists():
        return
    try:
        from stats_db import insert_h2h_game
    except Exception:
        return
    schedule = {}
    sched_file = TEAM_DIR / "schedule_manual.json"
    if sched_file.exists():
        try:
            with open(sched_file) as f:
                schedule = json.load(f)
        except Exception:
            pass
    # Build a lookup of results from schedule
    sched_results = {}
    for section in ("past", "upcoming"):
        for row in (schedule.get(section) or []):
            if not isinstance(row, dict):
                continue
            result = (row.get("result") or "").strip()
            score = (row.get("score") or "").strip()
            if result and score:
                date = (row.get("date") or "").strip()
                if date:
                    sched_results[date] = {"result": result, "score": score}

    for gf in sorted(games_dir.glob("*.json")):
        if gf.name == "index.json":
            continue
        try:
            with open(gf) as f:
                game = json.load(f)
            game_id = gf.stem
            date = game.get("date", game_id[:10])
            sharks_score = game.get("sharks_score", game.get("runs_for", 0))
            opp_score = game.get("opponent_score", game.get("runs_against", 0))
            opp_slug = game.get("opponent_slug", "")
            if not opp_slug:
                opp_name = game.get("opponent", "").lower().replace(" ", "_").replace("-", "_")
                opp_slug = opp_name
            result = game.get("result", "")
            if not result:
                sr = sched_results.get(date, {})
                result = sr.get("result", "")
            if not result:
                if sharks_score > opp_score:
                    result = "W"
                elif opp_score > sharks_score:
                    result = "L"
                else:
                    result = "T"
            insert_h2h_game(game_id, opp_slug, date, int(sharks_score), int(opp_score), result)
        except Exception as e:
            logging.debug(f"[H2H] skipped {gf.name}: {e}")


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
    # Record h2h results from game files
    try:
        _record_h2h_from_games()
        logging.info("[Post-Game] H2H records updated.")
    except Exception as e:
        logging.warning(f"[Post-Game] H2H recording skipped: {e}")
    if success:
        send_alert("Post-game analysis complete — scorebooks, SWOT, and lineups refreshed.", level="INFO")
        logging.info("[Post-Game] Analysis pipeline complete.")
    else:
        send_alert("Post-game analysis encountered errors. Check sync_daemon logs.", level="ERROR")


def run_api():
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"Starting API server on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ---------------------------------------------------------
# DAEMON LOGIC
# ---------------------------------------------------------
# ... (rest of the file stays same, but main starts the thread)
def main():
    # Signal to scrapers that we're running non-interactively
    os.environ["SYNC_DAEMON_MODE"] = "1"

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

    # Bootstrap a DB snapshot from current enriched/team data on startup.
    try:
        bootstrap_file = TEAM_DIR / "team_enriched.json"
        if not bootstrap_file.exists():
            bootstrap_file = TEAM_DIR / ("team_merged.json" if (TEAM_DIR / "team_merged.json").exists() else "team.json")
        if bootstrap_file.exists():
            with open(bootstrap_file) as f:
                bootstrap_team = json.load(f)
            _enrich_team_with_app_stats(bootstrap_team)
            _merge_team_with_scorebook_stats(bootstrap_team)
            _record_stats_db_snapshot(bootstrap_team, source="startup_bootstrap")
    except Exception as e:
        logging.warning(f"[DB] startup bootstrap snapshot skipped: {e}")

    # Bootstrap h2h records from existing game files
    try:
        _record_h2h_from_games()
        logging.info("[Startup] H2H game records bootstrapped.")
    except Exception as e:
        logging.warning(f"[Startup] H2H bootstrap skipped: {e}")

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
