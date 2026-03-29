"""
Aggregate multiple team.json files into a single merged roster.
Intended for combining team + borrowed players' home-team stats.
"""
import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
TEAM_DIR = DATA_DIR / os.getenv("TEAM_SLUG", "sharks")
TEAMS_DIR = DATA_DIR / "teams"
MANIFEST_FILE = TEAM_DIR / "teams_manifest.json"
OUTPUT_FILE = TEAM_DIR / "team_merged.json"

BAT_COUNT_KEYS = {
    "gp", "pa", "ab", "h", "singles", "doubles", "triples", "hr",
    "rbi", "r", "bb", "hbp", "so", "sb", "cs", "roe", "fc", "sac", "sf", "kl", "pik"
}

PITCH_COUNT_KEYS = {
    "gp", "gs", "w", "l", "sv", "svo", "h", "r", "er", "bb", "so", "kl",
    "bf", "np", "pik", "sb", "cs", "hbp", "wp", "bk", "lob"
}

FIELD_COUNT_KEYS = {"tc", "po", "a", "e", "dp", "tp"}
CATCH_COUNT_KEYS = {"sb", "cs", "pb", "pik", "ci"}

RATE_KEY_MARKERS = ("_pct", "pct", "avg", "obp", "slg", "ops", "era", "whip", "baa", "bb_k", "k_bb")

def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())

def _parse_number(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if s in ("", "-", "—", "N/A"):
            return None
        if s.endswith("%"):
            s = s[:-1]
        if s.startswith("."):
            s = "0" + s
        try:
            return float(s)
        except ValueError:
            return None
    return None

def _innings_to_outs(val) -> int | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    if "." in s:
        try:
            whole, frac = s.split(".", 1)
            return int(whole) * 3 + int(frac)
        except Exception:
            return None
    try:
        return int(float(s) * 3)
    except Exception:
        return None

def _outs_to_innings(outs: int) -> str:
    whole = outs // 3
    rem = outs % 3
    return f"{whole}.{rem}"

def _merge_numeric(dst: dict, src: dict, keys: set[str]):
    for k in keys:
        v = _parse_number(src.get(k))
        if v is None:
            continue
        dst[k] = dst.get(k, 0) + v

def _merge_innings(dst_outs: dict, src: dict, keys: set[str]):
    for k in keys:
        outs = _innings_to_outs(src.get(k))
        if outs is None:
            continue
        dst_outs[k] = dst_outs.get(k, 0) + outs

def _is_rate_key(key: str) -> bool:
    if key.endswith("_pct") or key.endswith("pct"):
        return True
    return any(marker in key for marker in RATE_KEY_MARKERS)

def _merge_generic(dst: dict, src: dict):
    for k, v in (src or {}).items():
        if _is_rate_key(k):
            continue
        num = _parse_number(v)
        if num is None:
            continue
        dst[k] = dst.get(k, 0) + num

def _recompute_batting(b: dict) -> dict:
    ab = b.get("ab", 0) or 0
    h = b.get("h", 0) or 0
    bb = b.get("bb", 0) or 0
    hbp = b.get("hbp", 0) or 0
    doubles = b.get("doubles", 0) or 0
    triples = b.get("triples", 0) or 0
    hr = b.get("hr", 0) or 0
    sb = b.get("sb", 0) or 0
    cs = b.get("cs", 0) or 0
    pa = b.get("pa") if b.get("pa") is not None else (ab + bb + hbp)

    singles = h - doubles - triples - hr
    total_bases = singles + (2 * doubles) + (3 * triples) + (4 * hr)
    ba = h / ab if ab > 0 else 0
    obp = (h + bb + hbp) / pa if pa > 0 else 0
    slg = total_bases / ab if ab > 0 else 0
    ops = obp + slg
    sb_pct = sb / (sb + cs) if (sb + cs) > 0 else None

    b["pa"] = pa
    b["avg"] = round(ba, 3)
    b["obp"] = round(obp, 3)
    b["slg"] = round(slg, 3)
    b["ops"] = round(ops, 3)
    if sb_pct is not None:
        b["sb_pct"] = round(sb_pct * 100, 2)
    return b

def _recompute_pitching(p: dict, ip_outs: int | None) -> dict:
    if ip_outs is None:
        return p
    ip = ip_outs / 3.0
    er = p.get("er", 0) or 0
    bb = p.get("bb", 0) or 0
    h = p.get("h", 0) or 0
    era = (er * 7) / ip if ip > 0 else None
    whip = (bb + h) / ip if ip > 0 else None
    p["ip"] = _outs_to_innings(ip_outs)
    if era is not None:
        p["era"] = round(era, 2)
    if whip is not None:
        p["whip"] = round(whip, 2)
    return p

def _recompute_fielding(f: dict) -> dict:
    po = f.get("po", 0) or 0
    a = f.get("a", 0) or 0
    e = f.get("e", 0) or 0
    denom = po + a + e
    if denom > 0:
        f["fpct"] = round((po + a) / denom, 3)
    return f

def _recompute_catching(c: dict, inn_outs: int | None) -> dict:
    if inn_outs is not None:
        c["inn"] = _outs_to_innings(inn_outs)
    sb = c.get("sb", 0) or 0
    cs = c.get("cs", 0) or 0
    if sb + cs > 0:
        c["cs_pct"] = round((cs / (sb + cs)) * 100, 2)
    return c

def _load_manifest():
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "primary_team": {
            "id": "NuGgx6WvP7TO",
            "season_slug": "2026-spring-sharks",
            "name": os.getenv("TEAM_NAME", "The Sharks"),
            "data_path": str(TEAM_DIR / "team.json"),
        },
        "extra_teams": []
    }

def _team_file_from_entry(entry: dict) -> Path:
    if entry.get("data_path"):
        p = Path(entry["data_path"])
        return p if p.is_absolute() else (ROOT_DIR / p)
    team_id = entry.get("id")
    season_slug = entry.get("season_slug")
    if team_id and season_slug:
        return TEAMS_DIR / f"{team_id}_{season_slug}" / "team.json"
    return TEAM_DIR / "team.json"

def main():
    manifest = _load_manifest()
    team_entries = []
    if manifest.get("primary_team"):
        team_entries.append(manifest["primary_team"])
    team_entries.extend(manifest.get("extra_teams", []))

    team_files = [(_team_file_from_entry(e), e) for e in team_entries]
    teams = []
    for tf, entry in team_files:
        if not tf.exists():
            print(f"[MERGE] Missing team file: {tf}")
            continue
        with open(tf, "r", encoding="utf-8") as f:
            teams.append((json.load(f), entry))

    if not teams:
        print("[MERGE] No team data found. Aborting.")
        return

    primary_entry = manifest.get("primary_team", {})
    primary_file = _team_file_from_entry(primary_entry) if primary_entry else None
    primary_core_keys = set()
    allowed_names = set()
    if primary_file and primary_file.exists():
        with open(primary_file, "r", encoding="utf-8") as f:
            primary_team = json.load(f)
        for p in primary_team.get("roster", []):
            full_name = f"{p.get('first', '')} {p.get('last', '')}".strip()
            norm = _norm_name(full_name)
            number = str(p.get("number", "")).strip()
            key = f"{norm}|{number}" if number else norm
            if p.get("core", False):
                primary_core_keys.add(key)
            if norm:
                allowed_names.add(norm)

    roster_manifest = TEAM_DIR / "roster_manifest.json"
    if roster_manifest.exists():
        with open(roster_manifest, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)
        for n in manifest_data.get("borrowed_players", []):
            allowed_names.add(_norm_name(n))

    roster_map = {}
    primary_key = None
    if primary_entry:
        primary_key = f"{primary_entry.get('id','')}|{primary_entry.get('season_slug','')}"

    for team, entry in teams:
        entry_key = f"{entry.get('id','')}|{entry.get('season_slug','')}"
        is_primary = primary_key and entry_key == primary_key
        team_name = entry.get("name") or team.get("team_name") or "Unknown"
        for p in team.get("roster", []):
            full_name = f"{p.get('first', '')} {p.get('last', '')}".strip()
            norm = _norm_name(full_name)
            number = str(p.get("number", "")).strip()
            key = f"{norm}|{number}" if number else norm

            if not is_primary and norm and norm not in allowed_names:
                continue

            if key not in roster_map:
                roster_map[key] = {
                    "first": p.get("first", ""),
                    "last": p.get("last", ""),
                    "number": p.get("number", ""),
                    "core": p.get("core", False),
                    "borrowed": p.get("borrowed", False),
                    "teams": [],
                    "batting": {},
                    "batting_advanced": {},
                    "pitching": {},
                    "pitching_advanced": {},
                    "fielding": {},
                    "catching": {},
                    "innings_played": {},
                    "_outs_pitching": 0,
                    "_outs_catching": 0,
                    "_outs_innings_played": {},
                }

            merged = roster_map[key]
            merged["teams"].append(team_name)
            merged["core"] = key in primary_core_keys
            merged["borrowed"] = not merged["core"]

            # Merge batting
            if p.get("batting"):
                _merge_numeric(merged["batting"], p["batting"], BAT_COUNT_KEYS)
            # Merge batting advanced (numeric only, skip rates)
            if p.get("batting_advanced"):
                _merge_generic(merged["batting_advanced"], p["batting_advanced"])

            # Merge pitching
            if p.get("pitching"):
                _merge_numeric(merged["pitching"], p["pitching"], PITCH_COUNT_KEYS)
                ip_outs = _innings_to_outs(p["pitching"].get("ip"))
                if ip_outs:
                    merged["_outs_pitching"] += ip_outs
            if p.get("pitching_advanced"):
                _merge_generic(merged["pitching_advanced"], p["pitching_advanced"])

            # Merge fielding
            if p.get("fielding"):
                _merge_numeric(merged["fielding"], p["fielding"], FIELD_COUNT_KEYS)

            # Merge catching
            if p.get("catching"):
                _merge_numeric(merged["catching"], p["catching"], CATCH_COUNT_KEYS)
                inn_outs = _innings_to_outs(p["catching"].get("inn"))
                if inn_outs:
                    merged["_outs_catching"] += inn_outs

            # Merge innings played (positions)
            if p.get("innings_played"):
                for k, v in p["innings_played"].items():
                    outs = _innings_to_outs(v)
                    if outs is None:
                        continue
                    merged["_outs_innings_played"][k] = merged["_outs_innings_played"].get(k, 0) + outs

    merged_roster = []
    for merged in roster_map.values():
        merged["teams"] = sorted(set(merged["teams"]))
        merged["batting"] = _recompute_batting(merged["batting"])
        merged["pitching"] = _recompute_pitching(merged["pitching"], merged["_outs_pitching"] or None)
        merged["fielding"] = _recompute_fielding(merged["fielding"])
        merged["catching"] = _recompute_catching(merged["catching"], merged["_outs_catching"] or None)
        if merged["_outs_innings_played"]:
            merged["innings_played"] = {
                k: _outs_to_innings(v) for k, v in merged["_outs_innings_played"].items()
            }
        else:
            merged["innings_played"] = {}

        # Clean temporary fields
        merged.pop("_outs_pitching", None)
        merged.pop("_outs_catching", None)
        merged.pop("_outs_innings_played", None)
        merged_roster.append(merged)

    merged_team = {
        "team_name": manifest.get("primary_team", {}).get("name", "Merged Teams"),
        "league": teams[0][0].get("league", ""),
        "season": teams[0][0].get("season", ""),
        "last_updated": datetime.now(ZoneInfo("America/New_York")).isoformat(),
        "source_teams": [e.get("name") for e in team_entries if e.get("name")],
        "roster": merged_roster,
        "team_totals": {}
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(merged_team, f, indent=2)
    print(f"[MERGE] Wrote merged roster -> {OUTPUT_FILE} ({len(merged_roster)} players)")

if __name__ == "__main__":
    main()
