"""
Ingest GameChanger CSV season-stats export into the Dugout data pipeline.

Reads the comprehensive 200-column GC CSV export and produces:
  1. data/<team_slug>/team.json   — full roster with all stat categories
  2. data/<team_slug>/app_stats.json — backward-compat batting/pitching/fielding arrays
  3. data/<team_slug>/season_stats.csv — copy of the source CSV

Usage:
    python tools/gc_csv_ingest.py --csv-path "Scorebooks/Other docs/Sharks Spring 2026 Stats (4).csv"
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stats_normalizer import safe_float, safe_int

ET = ZoneInfo("America/New_York")
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
TEAM_DIR = DATA_DIR / os.getenv("TEAM_SLUG", "sharks")

# ---------------------------------------------------------------------------
# CSV column indices (from GC export, 0-indexed, row 1 = column names)
# ---------------------------------------------------------------------------

# Identity
COL_NUMBER = 0
COL_LAST = 1
COL_FIRST = 2

# Batting standard (cols 3-28)
BAT = {
    "gp": 3, "pa": 4, "ab": 5, "avg": 6, "obp": 7, "ops": 8, "slg": 9,
    "h": 10, "1b": 11, "2b": 12, "3b": 13, "hr": 14, "rbi": 15, "r": 16,
    "bb": 17, "so": 18, "kl": 19, "hbp": 20, "sac": 21, "sf": 22,
    "roe": 23, "fc": 24, "sb": 25, "sb_pct": 26, "cs": 27, "pik": 28,
}

# Batting advanced (cols 29-53)
BAT_ADV = {
    "qab": 29, "qab_pct": 30, "pa_per_bb": 31, "bb_per_k": 32, "c_pct": 33,
    "hhb": 34, "ld_pct": 35, "fb_pct": 36, "gb_pct": 37,
    "babip": 38, "ba_risp": 39, "bat_lob": 40, "two_out_rbi": 41,
    "xbh": 42, "tb": 43, "ps": 44, "ps_pa": 45,
    "two_s_three": 46, "two_s_three_pct": 47,
    "six_plus": 48, "six_plus_pct": 49,
    "ab_hr": 50, "gidp": 51, "gitp": 52, "ci": 53,
}

# Pitching standard (cols 54-80)
PITCH = {
    "ip": 54, "gp": 55, "gs": 56, "bf": 57, "np": 58,
    "w": 59, "l": 60, "sv": 61, "svo": 62, "bs": 63, "sv_pct": 64,
    "h": 65, "r": 66, "er": 67, "bb": 68, "so": 69, "kl": 70, "hbp": 71,
    "era": 72, "whip": 73, "lob": 74, "bk": 75, "pik": 76,
    "cs": 77, "sb": 78, "sb_pct": 79, "wp": 80,
}

# Pitching advanced (cols 81-117)
PITCH_ADV = {
    "baa": 81,
    "mph_fb": 82, "mph_ct": 83, "mph_cb": 84, "mph_sl": 85, "mph_ch": 86, "mph_os": 87,
    "p_ip": 88, "p_bf": 89,
    "lt3_pct": 90, "loo": 91, "first_2out": 92, "one23_inn": 93, "lt13": 94,
    "fip": 95, "s_pct": 96, "fps_pct": 97,
    "fpso_pct": 98, "fpsw_pct": 99, "fpsh_pct": 100,
    "bb_inn": 101, "zero_bb_inn": 102, "bbs": 103, "lobb": 104, "lobbs": 105, "sm_pct": 106,
    "k_bf": 107, "k_bb": 108,
    "weak_pct": 109, "hhb_pct": 110, "go_ao": 111, "p_hr": 112,
    "ld_pct": 113, "fb_pct": 114, "gb_pct": 115,
    "babip": 116, "ba_risp": 117,
}

# Pitching breakdown by pitch type (cols 118-173)
PITCH_BRK = {
    "fb": 118, "fbs": 119, "fbs_pct": 120, "fbsw_pct": 121, "fbsm_pct": 122,
    "ch": 123, "chs": 124, "chs_pct": 125, "chsw_pct": 126, "chsm_pct": 127,
    "rb": 128, "rbs": 129, "rbs_pct": 130, "rbsw_pct": 131, "rbsm_pct": 132, "mph_rb": 133,
    "db": 134, "dbs": 135, "dbs_pct": 136, "dbsw_pct": 137, "dbsm_pct": 138, "mph_db": 139,
    "sc": 140, "scs": 141, "scs_pct": 142, "scsw_pct": 143, "scsm_pct": 144, "mph_sc": 145,
    "cb": 146, "cbs": 147, "cbs_pct": 148, "cbsw_pct": 149, "cbsm_pct": 150,
    "dc": 151, "dcs": 152, "dcs_pct": 153, "dcsw_pct": 154, "dcsm_pct": 155, "mph_dc": 156,
    "kb": 157, "kbs": 158, "kbs_pct": 159, "kbsw_pct": 160, "kbsm_pct": 161, "mph_kb": 162,
    "kc": 163, "kcs": 164, "kcs_pct": 165, "kcsw_pct": 166, "kcsm_pct": 167, "mph_kc": 168,
    "os": 169, "oss": 170, "oss_pct": 171, "ossw_pct": 172, "ossm_pct": 173,
}

# Fielding (cols 174-180)
FIELD = {
    "tc": 174, "a": 175, "po": 176, "fpct": 177,
    "e": 178, "dp": 179, "tp": 180,
}

# Catching (cols 181-188)
CATCH = {
    "inn": 181, "pb": 182, "sb": 183, "sb_att": 184,
    "cs": 185, "cs_pct": 186, "pik": 187, "ci": 188,
}

# Innings played by position (cols 189-199)
INNINGS = {
    "p": 189, "c": 190, "first_base": 191, "second_base": 192,
    "third_base": 193, "ss": 194, "lf": 195, "cf": 196,
    "rf": 197, "sf": 198, "total": 199,
}


def _val(row: list[str], idx: int) -> str:
    """Safe accessor for CSV row by column index."""
    if idx < len(row):
        v = row[idx].strip()
        return v if v not in ("", "-", "—", "N/A") else ""
    return ""


def _load_core_players() -> set[str]:
    manifest = TEAM_DIR / "roster_manifest.json"
    if not manifest.exists():
        return set()
    with open(manifest) as f:
        data = json.load(f)
    return {name.strip().lower() for name in data.get("core_players", [])}


def _is_core(first: str, last: str, core_set: set[str]) -> bool:
    full = f"{first} {last}".strip().lower()
    return full in core_set


def _parse_row_section(row: list[str], col_map: dict[str, int]) -> dict:
    """Extract a dict from a CSV row using a column mapping."""
    return {key: _val(row, idx) for key, idx in col_map.items()}


def _has_data(section: dict) -> bool:
    """Check if any value in the section is non-empty."""
    return any(v != "" for v in section.values())


def parse_player_row(row: list[str], core_set: set[str]) -> dict | None:
    """Parse a single CSV row into a full player dict."""
    number = _val(row, COL_NUMBER)
    last = _val(row, COL_LAST)
    first = _val(row, COL_FIRST)

    # Skip totals/glossary/empty rows
    if number == "Totals" or number == "Glossary":
        return None
    if not number and not first and not last:
        return None

    # --- Batting ---
    bat_raw = _parse_row_section(row, BAT)
    batting = {
        "gp": safe_int(bat_raw["gp"]),
        "pa": safe_int(bat_raw["pa"]),
        "ab": safe_int(bat_raw["ab"]),
        "avg": safe_float(bat_raw["avg"]),
        "obp": safe_float(bat_raw["obp"]),
        "ops": safe_float(bat_raw["ops"]),
        "slg": safe_float(bat_raw["slg"]),
        "h": safe_int(bat_raw["h"]),
        "singles": safe_int(bat_raw["1b"]),
        "doubles": safe_int(bat_raw["2b"]),
        "triples": safe_int(bat_raw["3b"]),
        "hr": safe_int(bat_raw["hr"]),
        "rbi": safe_int(bat_raw["rbi"]),
        "r": safe_int(bat_raw["r"]),
        "bb": safe_int(bat_raw["bb"]),
        "so": safe_int(bat_raw["so"]),
        "kl": safe_int(bat_raw["kl"]),
        "hbp": safe_int(bat_raw["hbp"]),
        "sac": safe_int(bat_raw["sac"]),
        "sf": safe_int(bat_raw["sf"]),
        "roe": safe_int(bat_raw["roe"]),
        "fc": safe_int(bat_raw["fc"]),
        "sb": safe_int(bat_raw["sb"]),
        "sb_pct": safe_float(bat_raw["sb_pct"]) if bat_raw["sb_pct"] else None,
        "cs": safe_int(bat_raw["cs"]),
        "pik": safe_int(bat_raw["pik"]),
        "ci": safe_int(bat_raw.get("ci")) if bat_raw.get("ci") else None,
    }

    # --- Batting Advanced ---
    ba_raw = _parse_row_section(row, BAT_ADV)
    batting_advanced = {
        "gp": batting["gp"],
        "pa": batting["pa"],
        "ab": batting["ab"],
        "qab": safe_int(ba_raw["qab"]),
        "qab_pct": safe_float(ba_raw["qab_pct"]),
        "pa_per_bb": safe_float(ba_raw["pa_per_bb"]),
        "bb_per_k": safe_float(ba_raw["bb_per_k"]),
        "bb_k": safe_float(ba_raw["bb_per_k"]),  # alias
        "c_pct": safe_float(ba_raw["c_pct"]),
        "hhb": safe_int(ba_raw["hhb"]),
        "ld_pct": safe_float(ba_raw["ld_pct"]),
        "fb_pct": safe_float(ba_raw["fb_pct"]),
        "gb_pct": safe_float(ba_raw["gb_pct"]),
        "babip": safe_float(ba_raw["babip"]),
        "ba_risp": safe_float(ba_raw["ba_risp"]),
        "lob": safe_int(ba_raw.get("bat_lob", "")),
        "two_out_rbi": safe_int(ba_raw["two_out_rbi"]),
        "xbh": safe_int(ba_raw["xbh"]),
        "tb": safe_int(ba_raw["tb"]),
        "ps": safe_int(ba_raw["ps"]),
        "ps_pa": safe_float(ba_raw["ps_pa"]),
        "two_s_three": safe_int(ba_raw["two_s_three"]),
        "two_s_three_pct": safe_float(ba_raw["two_s_three_pct"]),
        "six_plus": safe_int(ba_raw["six_plus"]),
        "six_plus_pct": safe_float(ba_raw["six_plus_pct"]),
        "ab_hr": ba_raw["ab_hr"] if ba_raw["ab_hr"] else None,
        "gidp": safe_int(ba_raw["gidp"]),
        "gitp": safe_int(ba_raw["gitp"]),
    }

    # --- Pitching ---
    pitch_raw = _parse_row_section(row, PITCH)
    ip_str = _val(row, PITCH["ip"])
    has_pitching = ip_str != "" and ip_str != "0.0"

    if has_pitching:
        pitching = {
            "ip": ip_str,
            "gp": safe_int(pitch_raw["gp"]),
            "gs": safe_int(pitch_raw["gs"]),
            "bf": safe_int(pitch_raw["bf"]),
            "np": safe_int(pitch_raw["np"]),
            "w": safe_int(pitch_raw["w"]),
            "l": safe_int(pitch_raw["l"]),
            "sv": safe_int(pitch_raw["sv"]),
            "svo": safe_int(pitch_raw["svo"]),
            "bs": safe_int(pitch_raw["bs"]),
            "h": safe_int(pitch_raw["h"]),
            "r": safe_int(pitch_raw["r"]),
            "er": safe_int(pitch_raw["er"]),
            "bb": safe_int(pitch_raw["bb"]),
            "so": safe_int(pitch_raw["so"]),
            "kl": safe_int(pitch_raw["kl"]),
            "hbp": safe_int(pitch_raw["hbp"]),
            "era": safe_float(pitch_raw["era"]),
            "whip": safe_float(pitch_raw["whip"]),
            "lob": safe_int(pitch_raw["lob"]),
            "bk": safe_int(pitch_raw["bk"]),
            "pik": safe_int(pitch_raw["pik"]),
            "cs": safe_int(pitch_raw["cs"]),
            "sb": safe_int(pitch_raw["sb"]),
            "wp": safe_int(pitch_raw["wp"]),
            "baa": safe_float(_val(row, PITCH_ADV["baa"])),
        }

        pa_raw = _parse_row_section(row, PITCH_ADV)
        pitching_advanced = {
            "bf": safe_int(pitch_raw["bf"]),
            "np": safe_int(pitch_raw["np"]),
            "baa": safe_float(pa_raw["baa"]),
            "mph_fb": pa_raw.get("mph_fb", "") or None,
            "mph_ch": pa_raw.get("mph_ch", "") or None,
            "mph_cb": pa_raw.get("mph_cb", "") or None,
            "p_ip": safe_float(pa_raw["p_ip"]),
            "p_bf": safe_float(pa_raw["p_bf"]),
            "lt3_pct": safe_float(pa_raw.get("lt3_pct", "")),
            "fip": safe_float(pa_raw["fip"]),
            "s_pct": safe_float(pa_raw["s_pct"]),
            "fps_pct": safe_float(pa_raw["fps_pct"]),
            "fpso_pct": safe_float(pa_raw.get("fpso_pct", "")),
            "fpsw_pct": safe_float(pa_raw.get("fpsw_pct", "")),
            "fpsh_pct": safe_float(pa_raw.get("fpsh_pct", "")),
            "bb_inn": safe_float(pa_raw["bb_inn"]),
            "zero_bb_inn": safe_float(pa_raw.get("zero_bb_inn", "")),
            "sm_pct": safe_float(pa_raw.get("sm_pct", "")),
            "k_bf": safe_float(pa_raw["k_bf"]),
            "k_bb": safe_float(pa_raw["k_bb"]),
            "weak_pct": safe_float(pa_raw.get("weak_pct", "")),
            "hhb_pct": safe_float(pa_raw["hhb_pct"]),
            "go_ao": safe_float(pa_raw["go_ao"]),
            "p_hr": safe_int(pa_raw.get("p_hr", "")),
            "ld_pct": safe_float(pa_raw["ld_pct"]),
            "fb_pct": safe_float(pa_raw["fb_pct"]),
            "gb_pct": safe_float(pa_raw["gb_pct"]),
            "babip": safe_float(pa_raw["babip"]),
            "ba_risp": safe_float(pa_raw["ba_risp"]),
        }

        # --- Pitching Breakdown (by pitch type) ---
        brk_raw = _parse_row_section(row, PITCH_BRK)
        pitching_breakdown = {}
        if _has_data(brk_raw):
            pitching_breakdown = {k: (safe_float(v) if v else None) for k, v in brk_raw.items()}
    else:
        pitching = None
        pitching_advanced = None
        pitching_breakdown = None

    # --- Fielding ---
    fld_raw = _parse_row_section(row, FIELD)
    fielding = {
        "tc": safe_int(fld_raw["tc"]),
        "po": safe_int(fld_raw["po"]),
        "a": safe_int(fld_raw["a"]),
        "fpct": safe_float(fld_raw["fpct"]) if fld_raw["fpct"] else None,
        "e": safe_int(fld_raw["e"]),
        "dp": safe_int(fld_raw["dp"]),
        "tp": safe_int(fld_raw["tp"]),
    }

    # --- Catching ---
    cat_raw = _parse_row_section(row, CATCH)
    has_catching = _val(row, CATCH["inn"]) not in ("", "0.0")
    if has_catching:
        catching = {
            "inn": _val(row, CATCH["inn"]),
            "pb": safe_int(cat_raw["pb"]),
            "sb": safe_int(cat_raw["sb"]),
            "cs": safe_int(cat_raw["cs"]),
            "cs_pct": safe_float(cat_raw["cs_pct"]) if cat_raw["cs_pct"] else None,
            "pik": safe_int(cat_raw["pik"]),
            "ci": safe_int(cat_raw["ci"]),
        }
    else:
        catching = None

    # --- Innings Played ---
    innings_played = {
        "total": _val(row, INNINGS["total"]) or "0.0",
        "p": _val(row, INNINGS["p"]) or "0.0",
        "c": _val(row, INNINGS["c"]) or "0.0",
        "first_base": _val(row, INNINGS["first_base"]) or "0.0",
        "second_base": _val(row, INNINGS["second_base"]) or "0.0",
        "third_base": _val(row, INNINGS["third_base"]) or "0.0",
        "ss": _val(row, INNINGS["ss"]) or "0.0",
        "lf": _val(row, INNINGS["lf"]) or "0.0",
        "cf": _val(row, INNINGS["cf"]) or "0.0",
        "rf": _val(row, INNINGS["rf"]) or "0.0",
        "sf": _val(row, INNINGS["sf"]) or "0.0",
    }

    core = _is_core(first, last, core_set)

    return {
        "first": first,
        "last": last,
        "number": number,
        "core": core,
        "borrowed": not core,
        "batting": batting,
        "batting_advanced": batting_advanced,
        "pitching": pitching,
        "pitching_advanced": pitching_advanced,
        "pitching_breakdown": pitching_breakdown if pitching else None,
        "fielding": fielding,
        "catching": catching,
        "innings_played": innings_played,
        "games_played": batting["gp"],
    }


def _merge_players(existing: dict, new: dict) -> dict:
    """Merge two player dicts with the same jersey number (sum counting stats, keep richer data)."""
    merged = {**existing}
    merged["games_played"] = existing.get("games_played", 0) + new.get("games_played", 0)

    # Use the entry with a last name if the other doesn't have one
    if not merged.get("last") and new.get("last"):
        merged["last"] = new["last"]

    # For batting, sum counting stats
    eb = existing.get("batting", {})
    nb = new.get("batting", {})
    count_keys = ["gp", "pa", "ab", "h", "singles", "doubles", "triples", "hr",
                  "rbi", "r", "bb", "so", "kl", "hbp", "sac", "sf", "roe", "fc", "sb", "cs", "pik"]
    merged_bat = {}
    for k in count_keys:
        merged_bat[k] = safe_int(eb.get(k)) + safe_int(nb.get(k))

    # Recalculate rate stats
    ab = merged_bat["ab"]
    h = merged_bat["h"]
    bb = merged_bat["bb"]
    hbp = merged_bat["hbp"]
    pa = merged_bat["pa"]
    tb = merged_bat["singles"] + 2 * merged_bat["doubles"] + 3 * merged_bat["triples"] + 4 * merged_bat["hr"]
    merged_bat["avg"] = round(h / ab, 3) if ab > 0 else 0.0
    merged_bat["obp"] = round((h + bb + hbp) / pa, 3) if pa > 0 else 0.0
    merged_bat["slg"] = round(tb / ab, 3) if ab > 0 else 0.0
    merged_bat["ops"] = round(merged_bat["obp"] + merged_bat["slg"], 3)
    merged_bat["sb_pct"] = existing["batting"].get("sb_pct")
    merged_bat["ci"] = existing["batting"].get("ci")
    merged["batting"] = merged_bat

    # For other sections, keep whichever is non-null / richer
    for section in ["batting_advanced", "pitching", "pitching_advanced", "fielding", "catching", "innings_played"]:
        e_sec = existing.get(section)
        n_sec = new.get(section)
        if n_sec and not e_sec:
            merged[section] = n_sec
        # else keep existing

    return merged


def parse_gc_csv(csv_path: Path) -> list[dict]:
    """Parse GC CSV export into a list of player dicts."""
    core_set = _load_core_players()
    players_by_number: dict[str, dict] = {}
    players_no_number: list[dict] = []

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    # Row 0 = section labels, Row 1 = column names, Rows 2+ = data
    for row in rows[2:]:
        player = parse_player_row(row, core_set)
        if player is None:
            continue

        num = player["number"]
        if num:
            if num in players_by_number:
                # Merge duplicate jersey numbers (e.g., two #11 entries)
                players_by_number[num] = _merge_players(players_by_number[num], player)
            else:
                players_by_number[num] = player
        else:
            players_no_number.append(player)

    return list(players_by_number.values()) + players_no_number


def build_team_json(roster: list[dict], csv_path: Path) -> dict:
    """Build team.json-compatible structure from parsed roster."""
    # Preserve existing team metadata if available
    team_file = TEAM_DIR / "team.json"
    meta = {}
    if team_file.exists():
        with open(team_file) as f:
            existing = json.load(f)
        meta = {
            "team_name": existing.get("team_name", "The Sharks"),
            "league": existing.get("league", "PCLL Majors"),
            "season": existing.get("season", "Spring 2026"),
            "gc_team_url": existing.get("gc_team_url", ""),
            "gc_team_id": existing.get("gc_team_id", ""),
        }
    else:
        meta = {
            "team_name": "The Sharks",
            "league": "PCLL Majors",
            "season": "Spring 2026",
        }

    meta["last_updated"] = datetime.now(ET).isoformat()
    meta["source"] = f"gc_csv_export:{csv_path.name}"

    # Calculate record from known_game_results.json (authoritative source)
    max_gp = max((p.get("games_played", 0) for p in roster), default=0)
    known_results_file = Path(__file__).parent.parent / "config" / "known_game_results.json"
    wins, losses = 0, 0
    try:
        if known_results_file.exists():
            with open(known_results_file) as f:
                kr = json.load(f)
            for r in kr.get("results", []):
                if r.get("result") == "W":
                    wins += 1
                elif r.get("result") == "L":
                    losses += 1
    except Exception:
        pass
    if wins + losses > 0:
        meta["record"] = f"{wins}-{losses} ({max_gp} GP)"
    else:
        meta["record"] = f"0-0 ({max_gp} GP)"

    meta["roster"] = roster
    return meta


def build_app_stats_json(roster: list[dict]) -> dict:
    """Build app_stats.json-compatible structure from parsed roster."""
    batting = []
    pitching = []
    fielding = []

    for p in roster:
        first = p.get("first", "")
        last = p.get("last", "")
        number = p.get("number", "")
        # app_stats uses abbreviated names: "E Hourahan"
        initial = first[0] if first else ""
        name = f"{initial} {last}".strip() if last else first

        b = p.get("batting", {})
        batting.append({
            "name": name,
            "number": number,
            "gp": str(b.get("gp", 0)),
            "pa": str(b.get("pa", 0)),
            "ab": str(b.get("ab", 0)),
            "avg": safe_float(b.get("avg", 0)),
            "obp": safe_float(b.get("obp", 0)),
            "ops": safe_float(b.get("ops", 0)),
            "slg": safe_float(b.get("slg", 0)),
            "h": str(b.get("h", 0)),
            "1b": str(b.get("singles", 0)),
            "2b": str(b.get("doubles", 0)),
            "3b": str(b.get("triples", 0)),
            "hr": str(b.get("hr", 0)),
            "rbi": str(b.get("rbi", 0)),
            "bb": str(b.get("bb", 0)),
            "hbp": str(b.get("hbp", 0)),
            "so": str(b.get("so", 0)),
            "sb": str(b.get("sb", 0)),
            "cs": str(b.get("cs", 0)),
            # Advanced fields that _enrich_team_with_app_stats reads
            "qab": str((p.get("batting_advanced") or {}).get("qab", 0)),
            "qab_pct": str((p.get("batting_advanced") or {}).get("qab_pct", 0)),
            "pa_per_bb": str((p.get("batting_advanced") or {}).get("pa_per_bb", 0)),
            "bb_per_k": str((p.get("batting_advanced") or {}).get("bb_per_k", 0)),
            "c_pct": str((p.get("batting_advanced") or {}).get("c_pct", 0)),
            "hhb": str((p.get("batting_advanced") or {}).get("hhb", 0)),
            "ld_pct": str((p.get("batting_advanced") or {}).get("ld_pct", 0)),
        })

        pit = p.get("pitching")
        if pit:
            pitching.append({
                "name": name,
                "number": number,
                "ip": str(pit.get("ip", "0.0")),
                "gp": str(pit.get("gp", 0)),
                "gs": str(pit.get("gs", 0)),
                "bf": str(pit.get("bf", 0)),
                "np": str(pit.get("np", 0)),
                "pitches": str(pit.get("np", 0)),
                "w": str(pit.get("w", 0)),
                "l": str(pit.get("l", 0)),
                "sv": str(pit.get("sv", 0)),
                "svo": str(pit.get("svo", 0)),
                "h": str(pit.get("h", 0)),
                "r": str(pit.get("r", 0)),
                "er": str(pit.get("er", 0)),
                "bb": str(pit.get("bb", 0)),
                "so": str(pit.get("so", 0)),
                "hbp": str(pit.get("hbp", 0)),
                "era": str(pit.get("era", 0)),
                "whip": str(pit.get("whip", 0)),
                "wp": str(pit.get("wp", 0)),
                "bk": str(pit.get("bk", 0)),
                "lob": str(pit.get("lob", 0)),
                "sb": str(pit.get("sb", 0)),
                "cs": str(pit.get("cs", 0)),
                "baa": str(pit.get("baa", 0)),
                # Advanced fields
                "k_bf": str((p.get("pitching_advanced") or {}).get("k_bf", 0)),
                "k_bb": str((p.get("pitching_advanced") or {}).get("k_bb", 0)),
                "bb_inn": str((p.get("pitching_advanced") or {}).get("bb_inn", 0)),
                "fip": str((p.get("pitching_advanced") or {}).get("fip", 0)),
                "babip": str((p.get("pitching_advanced") or {}).get("babip", 0)),
            })

        fld = p.get("fielding")
        if fld:
            fielding.append({
                "name": name,
                "number": number,
                "tc": str(fld.get("tc", 0)),
                "po": str(fld.get("po", 0)),
                "a": str(fld.get("a", 0)),
                "fpct": str(fld.get("fpct", 0)) if fld.get("fpct") is not None else "",
                "e": str(fld.get("e", 0)),
                "dp": str(fld.get("dp", 0)),
                "tp": str(fld.get("tp", 0)),
            })

    return {
        "last_updated": datetime.now(ET).isoformat(),
        "source": "gc_csv_export",
        "batting": batting,
        "pitching": pitching,
        "fielding": fielding,
    }


def main():
    parser = argparse.ArgumentParser(description="Ingest GC CSV season-stats export")
    parser.add_argument(
        "--csv-path",
        type=str,
        help="Path to the GC CSV export file (relative to project root or absolute)",
    )
    args = parser.parse_args()

    # Resolve CSV path
    if args.csv_path:
        csv_path = Path(args.csv_path)
        if not csv_path.is_absolute():
            csv_path = ROOT_DIR / csv_path
    else:
        # Auto-discover from Scorebooks/Other docs
        search_dir = ROOT_DIR / "Scorebooks" / "Other docs"
        candidates = sorted(search_dir.glob("Sharks Spring 2026 Stats*.csv"))
        if not candidates:
            print("ERROR: No CSV found. Use --csv-path to specify.")
            return
        csv_path = candidates[-1]

    if not csv_path.exists():
        print(f"ERROR: CSV not found: {csv_path}")
        return

    print(f"Ingesting: {csv_path.name}")

    # Parse
    roster = parse_gc_csv(csv_path)
    print(f"Parsed {len(roster)} players")

    # Build outputs
    team_json = build_team_json(roster, csv_path)
    app_stats = build_app_stats_json(roster)

    # Write team.json
    team_out = TEAM_DIR / "team.json"
    with open(team_out, "w") as f:
        json.dump(team_json, f, indent=2)
    print(f"Wrote {team_out}")

    # Write app_stats.json
    app_out = TEAM_DIR / "app_stats.json"
    with open(app_out, "w") as f:
        json.dump(app_stats, f, indent=2)
    print(f"Wrote {app_out}")

    # Copy CSV to season_stats.csv
    season_out = TEAM_DIR / "season_stats.csv"
    shutil.copy2(csv_path, season_out)
    print(f"Copied CSV -> {season_out}")

    # Summary
    core_count = sum(1 for p in roster if p.get("core"))
    borrowed_count = sum(1 for p in roster if not p.get("core"))
    pitchers = sum(1 for p in roster if p.get("pitching"))
    max_gp = max((p.get("games_played", 0) for p in roster), default=0)
    print(f"\nSummary: {core_count} core, {borrowed_count} borrowed, {pitchers} pitchers, {max_gp} GP max")

    for p in roster:
        gp = p.get("games_played", 0)
        tag = "*" if p.get("core") else " "
        pit = "P" if p.get("pitching") else " "
        cat = "C" if p.get("catching") else " "
        print(f"  {tag} #{p['number']:>3s} {p['first']:>12s} {p['last']:<15s} GP={gp}  {pit}{cat}")


if __name__ == "__main__":
    main()
