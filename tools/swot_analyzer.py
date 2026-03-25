"""
SWOT Analyzer for Softball
Deterministic rules-based SWOT analysis engine for individual players and teams.
Reads player stats from data/ and generates SWOT classifications.
"""

import json
from pathlib import Path
from typing import Any

from logger import log_decision
from stats_normalizer import normalize_batting_advanced_row, normalize_batting_row

DATA_DIR = Path(__file__).parent.parent / "data"
SHARKS_DIR = DATA_DIR / "sharks"
OPPONENTS_DIR = DATA_DIR / "opponents"


# ── Thresholds ────────────────────────────────────────────────────────────
# These are calibrated for youth softball (Little League Majors, ages 10-12).
# Adjust as season data builds a better baseline.

HITTING_THRESHOLDS = {
    "ba":  {"strong": 0.350, "weak": 0.200},
    "obp": {"strong": 0.420, "weak": 0.280},
    "slg": {"strong": 0.450, "weak": 0.250},
    "ops": {"strong": 0.850, "weak": 0.530},
    "k_rate": {"strong": 0.20, "weak": 0.40},   # lower is better
    "bb_rate": {"strong": 0.12, "weak": 0.05},   # higher is better
}

PITCHING_THRESHOLDS = {
    "era":  {"strong": 3.00, "weak": 6.00},      # lower is better
    "whip": {"strong": 1.20, "weak": 1.80},       # lower is better
    "k_per_ip": {"strong": 1.0, "weak": 0.5},     # higher is better
    "bb_per_ip": {"strong": 0.40, "weak": 0.80},  # lower is better
}

FIELDING_THRESHOLDS = {
    "fielding_pct": {"strong": 0.950, "weak": 0.880},
}

BASERUNNING_THRESHOLDS = {
    "sb_success_rate": {"strong": 0.75, "weak": 0.50},
}


def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safe division avoiding ZeroDivisionError."""
    return numerator / denominator if denominator > 0 else default

def _parse_number(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if s in ("", "-", "—", "N/A"):
            return default
        if s.endswith("%"):
            s = s[:-1]
        if s.startswith("."):
            s = "0" + s
        try:
            return float(s)
        except ValueError:
            return default
    return default

def _innings_to_float(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        s = str(val)
    else:
        s = str(val).strip()
    if not s:
        return 0.0
    if "." in s:
        try:
            whole, frac = s.split(".", 1)
            outs = int(whole) * 3 + int(frac)
            return outs / 3.0
        except Exception:
            return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0

def _get_stat(player: dict, category: dict, key: str, fallback: str | None = None) -> float:
    if key in category:
        return _parse_number(category.get(key))
    if fallback and fallback in category:
        return _parse_number(category.get(fallback))
    if key in player:
        return _parse_number(player.get(key))
    if fallback and fallback in player:
        return _parse_number(player.get(fallback))
    return 0.0


def compute_derived_stats(player: dict) -> dict:
    """Compute derived statistics from raw counting stats."""
    hitting = player.get("stats", {}).get("hitting", {}) or player.get("batting", {}) or {}
    pitching = player.get("stats", {}).get("pitching", {}) or player.get("pitching", {}) or {}
    fielding = player.get("stats", {}).get("fielding", {}) or player.get("fielding", {}) or {}

    ab = _get_stat(player, hitting, "ab")
    h = _get_stat(player, hitting, "h")
    bb = _get_stat(player, hitting, "bb")
    hbp = _get_stat(player, hitting, "hbp")
    k = _get_stat(player, hitting, "k", fallback="so")
    doubles = _get_stat(player, hitting, "doubles", fallback="2b")
    triples = _get_stat(player, hitting, "triples", fallback="3b")
    hr = _get_stat(player, hitting, "hr")
    sb = _get_stat(player, hitting, "sb")
    cs = _get_stat(player, hitting, "cs")

    pa = ab + bb + hbp
    singles = h - doubles - triples - hr
    total_bases = singles + (2 * doubles) + (3 * triples) + (4 * hr)

    # Hitting
    ba = _safe_div(h, ab)
    obp = _safe_div(h + bb + hbp, pa)
    slg = _safe_div(total_bases, ab)
    ops = obp + slg
    k_rate = _safe_div(k, pa)
    bb_rate = _safe_div(bb, pa)

    # Pitching
    ip = _innings_to_float(pitching.get("ip", 0.0))
    p_er = _get_stat(player, pitching, "er")
    p_k = _get_stat(player, pitching, "k", fallback="so")
    p_bb = _get_stat(player, pitching, "bb")
    p_h = _get_stat(player, pitching, "h")

    era = _safe_div(p_er * 7, ip)  # LL softball = 7 innings
    whip = _safe_div(p_bb + p_h, ip)
    k_per_ip = _safe_div(p_k, ip)
    bb_per_ip = _safe_div(p_bb, ip)

    # Fielding
    po = _get_stat(player, fielding, "po")
    a = _get_stat(player, fielding, "a")
    e = _get_stat(player, fielding, "e")
    fielding_pct = _safe_div(po + a, po + a + e)

    # Baserunning
    sb_success_rate = _safe_div(sb, sb + cs)

    return {
        "hitting": {
            "ba": round(ba, 3), "obp": round(obp, 3), "slg": round(slg, 3),
            "ops": round(ops, 3), "k_rate": round(k_rate, 3),
            "bb_rate": round(bb_rate, 3), "pa": pa, "total_bases": total_bases,
        },
        "pitching": {
            "era": round(era, 2), "whip": round(whip, 2),
            "k_per_ip": round(k_per_ip, 2), "bb_per_ip": round(bb_per_ip, 2),
        },
        "fielding": {
            "fielding_pct": round(fielding_pct, 3),
        },
        "baserunning": {
            "sb_success_rate": round(sb_success_rate, 3),
        },
    }


def classify_hitting(derived: dict) -> tuple[list[str], list[str]]:
    """Classify hitting stats into strengths and weaknesses."""
    h = derived["hitting"]
    strengths, weaknesses = [], []

    labels = {
        "ba": ("High batting average", "Low batting average"),
        "obp": ("Gets on base frequently", "Struggles to reach base"),
        "slg": ("Strong extra-base power", "Limited power"),
        "ops": ("Elite overall hitting", "Below-average production"),
    }
    for stat, (s_label, w_label) in labels.items():
        val = h.get(stat, 0)
        if val >= HITTING_THRESHOLDS[stat]["strong"]:
            strengths.append(f"{s_label} ({stat.upper()}: {val})")
        elif val <= HITTING_THRESHOLDS[stat]["weak"]:
            weaknesses.append(f"{w_label} ({stat.upper()}: {val})")

    # Inverse stats
    if h.get("k_rate", 1) <= HITTING_THRESHOLDS["k_rate"]["strong"]:
        strengths.append(f"Low strikeout rate as batter (K%: {h['k_rate']})")
    elif h.get("k_rate", 0) >= HITTING_THRESHOLDS["k_rate"]["weak"]:
        weaknesses.append(f"High strikeout rate as batter (K%: {h['k_rate']})")

    if h.get("bb_rate", 0) >= HITTING_THRESHOLDS["bb_rate"]["strong"]:
        strengths.append(f"Good plate discipline (BB%: {h['bb_rate']})")
    elif h.get("bb_rate", 1) <= HITTING_THRESHOLDS["bb_rate"]["weak"]:
        weaknesses.append(f"Rarely walks (BB%: {h['bb_rate']})")

    return strengths, weaknesses


def classify_pitching(derived: dict, raw_ip: float = 0.0) -> tuple[list[str], list[str]]:
    """Classify pitching stats into strengths and weaknesses."""
    p = derived["pitching"]
    strengths, weaknesses = [], []

    # Only classify pitching for players with meaningful innings
    if raw_ip < 1.0:
        return strengths, weaknesses

    # ERA (lower is better)
    if p.get("era", 99) <= PITCHING_THRESHOLDS["era"]["strong"]:
        strengths.append(f"Dominant ERA ({p['era']})")
    elif p.get("era", 0) >= PITCHING_THRESHOLDS["era"]["weak"]:
        weaknesses.append(f"High ERA ({p['era']})")

    # WHIP (lower is better)
    if p.get("whip", 99) <= PITCHING_THRESHOLDS["whip"]["strong"]:
        strengths.append(f"Excellent WHIP ({p['whip']})")
    elif p.get("whip", 0) >= PITCHING_THRESHOLDS["whip"]["weak"]:
        weaknesses.append(f"High WHIP ({p['whip']})")

    # K/IP (higher is better)
    if p.get("k_per_ip", 0) >= PITCHING_THRESHOLDS["k_per_ip"]["strong"]:
        strengths.append(f"High strikeout rate as pitcher (K/IP: {p['k_per_ip']})")
    elif p.get("k_per_ip", 99) <= PITCHING_THRESHOLDS["k_per_ip"]["weak"]:
        weaknesses.append(f"Low strikeout rate as pitcher (K/IP: {p['k_per_ip']})")

    # BB/IP (lower is better)
    if p.get("bb_per_ip", 99) <= PITCHING_THRESHOLDS["bb_per_ip"]["strong"]:
        strengths.append(f"Good control (BB/IP: {p['bb_per_ip']})")
    elif p.get("bb_per_ip", 0) >= PITCHING_THRESHOLDS["bb_per_ip"]["weak"]:
        weaknesses.append(f"Control issues (BB/IP: {p['bb_per_ip']})")

    return strengths, weaknesses


def classify_fielding(derived: dict) -> tuple[list[str], list[str]]:
    """Classify fielding stats into strengths and weaknesses."""
    f = derived["fielding"]
    strengths, weaknesses = [], []

    fp = f.get("fielding_pct", 0)
    if fp >= FIELDING_THRESHOLDS["fielding_pct"]["strong"]:
        strengths.append(f"Reliable fielder (F%: {fp})")
    elif fp <= FIELDING_THRESHOLDS["fielding_pct"]["weak"]:
        weaknesses.append(f"Error-prone fielding (F%: {fp})")

    return strengths, weaknesses


def classify_baserunning(derived: dict) -> tuple[list[str], list[str]]:
    """Classify baserunning stats into strengths and weaknesses."""
    b = derived["baserunning"]
    strengths, weaknesses = [], []

    sb_rate = b.get("sb_success_rate", 0)
    if sb_rate >= BASERUNNING_THRESHOLDS["sb_success_rate"]["strong"]:
        strengths.append(f"Effective base stealer (SB%: {sb_rate})")
    elif sb_rate <= BASERUNNING_THRESHOLDS["sb_success_rate"]["weak"]:
        weaknesses.append(f"Inefficient on the bases (SB%: {sb_rate})")

    return strengths, weaknesses


def analyze_player(player: dict) -> dict:
    """Run full SWOT analysis on a single player."""
    derived = compute_derived_stats(player)

    strengths, weaknesses = [], []
    opportunities, threats = [], []

    # Classify each area
    h_s, h_w = classify_hitting(derived)
    strengths.extend(h_s)
    weaknesses.extend(h_w)

    # Advanced hitting profile (QAB/contact quality) from web/app feeds.
    adv = normalize_batting_advanced_row(player)
    pa = derived["hitting"].get("pa", 0)
    if pa >= 6:
        if adv.get("qab_pct", 0) >= 0.55:
            strengths.append(f"High quality at-bat profile (QAB%: {round(adv['qab_pct'], 3)})")
        elif adv.get("qab_pct", 0) <= 0.30:
            weaknesses.append(f"Low quality at-bat profile (QAB%: {round(adv['qab_pct'], 3)})")

        if adv.get("c_pct", 0) >= 0.70:
            strengths.append(f"Consistent contact quality (C%: {round(adv['c_pct'], 3)})")
        elif adv.get("c_pct", 0) > 0 and adv.get("c_pct", 0) <= 0.45:
            weaknesses.append(f"Inconsistent contact quality (C%: {round(adv['c_pct'], 3)})")

        if adv.get("bb_per_k", 0) > 0 and adv.get("bb_per_k", 0) <= 0.25:
            weaknesses.append(f"Plate-discipline risk (BB/K: {round(adv['bb_per_k'], 3)})")

    raw_ip = _innings_to_float(player.get("stats", {}).get("pitching", {}).get("ip", player.get("pitching", {}).get("ip", 0.0)))
    p_s, p_w = classify_pitching(derived, raw_ip=raw_ip)
    strengths.extend(p_s)
    weaknesses.extend(p_w)

    f_s, f_w = classify_fielding(derived)
    strengths.extend(f_s)
    weaknesses.extend(f_w)

    b_s, b_w = classify_baserunning(derived)
    strengths.extend(b_s)
    weaknesses.extend(b_w)

    # Opportunities: areas trending up or with development potential
    if derived["hitting"]["pa"] < 15:
        opportunities.append("Limited plate appearances — sample size too small; potential upside")
    if weaknesses:
        opportunities.append(f"{len(weaknesses)} areas identified for targeted training improvement")

    # Threats: external risks
    if derived["hitting"].get("k_rate", 0) > 0.35:
        threats.append("Vulnerable to strikeout-heavy pitchers")
    if derived["fielding"].get("fielding_pct", 1) < 0.900:
        threats.append("Errors could be exploited by aggressive baserunning opponents")

    name = player.get("name")
    if not name:
        name = f"{player.get('first', '')} {player.get('last', '')}".strip() or "Unknown"

    return {
        "player_id": player.get("id", "unknown"),
        "name": name,
        "number": player.get("number", 0),
        "derived_stats": derived,
        "swot": {
            "strengths": strengths[:3] or ["No standout strengths yet (need more data)"],
            "weaknesses": weaknesses[:3] or ["No major weaknesses identified"],
            "opportunities": opportunities[:3] or ["Continue developing all-around skills"],
            "threats": threats[:3] or ["No specific threats identified"],
        },
    }


def analyze_team(team_data: dict) -> dict:
    """Run SWOT analysis on the entire team roster."""
    roster = team_data.get("roster", [])
    player_analyses = [analyze_player(p) for p in roster]

    # Aggregate team-level SWOT
    all_strengths, all_weaknesses = [], []
    for pa in player_analyses:
        all_strengths.extend(pa["swot"]["strengths"])
        all_weaknesses.extend(pa["swot"]["weaknesses"])

    # Count frequency of strength/weakness types
    from collections import Counter
    strength_types = Counter(s.split("(")[0].strip() for s in all_strengths)
    weakness_types = Counter(w.split("(")[0].strip() for w in all_weaknesses)

    team_strengths = [f"{k} ({v} players)" for k, v in strength_types.most_common(3)]
    team_weaknesses = [f"{k} ({v} players)" for k, v in weakness_types.most_common(3)]

    team_swot = {
        "strengths": team_strengths or ["Insufficient data for team strengths"],
        "weaknesses": team_weaknesses or ["Insufficient data for team weaknesses"],
        "opportunities": [
            f"{len([p for p in player_analyses if len(p['swot']['weaknesses']) > 2])} players with multiple areas for growth",
            "Targeted practice plans can address common weaknesses",
        ],
        "threats": [
            f"{len([p for p in player_analyses if any('strikeout' in t.lower() for t in p['swot']['threats'])])} players vulnerable to strikeout pitchers",
        ],
    }

    return {
        "team_name": team_data.get("team_name", "Unknown"),
        "player_analyses": player_analyses,
        "team_swot": team_swot,
    }


def _swot_rationale_from_team(result: dict) -> str:
    players = result.get("player_analyses", [])
    if not players:
        return "No player analyses available; rationale not generated."

    def _name(p: dict) -> str:
        return str(p.get("name", "Unknown")).strip() or "Unknown"

    ops_leaders = sorted(
        players,
        key=lambda p: (
            float(((p.get("derived_stats") or {}).get("hitting") or {}).get("ops", 0.0)),
            _name(p),
        ),
        reverse=True,
    )[:3]
    k_risks = sorted(
        players,
        key=lambda p: (
            float(((p.get("derived_stats") or {}).get("hitting") or {}).get("k_rate", 0.0)),
            _name(p),
        ),
        reverse=True,
    )[:3]
    fielding_risks = sorted(
        players,
        key=lambda p: (
            float(((p.get("derived_stats") or {}).get("fielding") or {}).get("fielding_pct", 1.0)),
            _name(p),
        ),
    )[:2]

    ops_text = ", ".join(
        f"{_name(p)} OPS {((p.get('derived_stats') or {}).get('hitting') or {}).get('ops', 0.0)}"
        for p in ops_leaders
    )
    k_text = ", ".join(
        f"{_name(p)} K% {((p.get('derived_stats') or {}).get('hitting') or {}).get('k_rate', 0.0)}"
        for p in k_risks
    )
    f_text = ", ".join(
        f"{_name(p)} FPCT {((p.get('derived_stats') or {}).get('fielding') or {}).get('fielding_pct', 1.0)}"
        for p in fielding_risks
    )
    return f"Top offensive signals: {ops_text}. Strikeout pressure drivers: {k_text}. Defensive risk markers: {f_text}."


def load_team(team_dir: Path, prefer_merged: bool = False) -> dict | None:
    """Load team data from a directory.
    Priority (Sharks): team_enriched.json > team_merged.json > team.json
    """
    # Always prefer the enriched file (app_stats applied) when it exists
    enriched = team_dir / "team_enriched.json"
    if enriched.exists():
        with open(enriched, "r") as f:
            return json.load(f)
    team_file = team_dir / ("team_merged.json" if prefer_merged else "team.json")
    if prefer_merged and not team_file.exists():
        team_file = team_dir / "team.json"
    if not team_file.exists():
        return None
    with open(team_file, "r") as f:
        return json.load(f)


def run_sharks_analysis() -> dict | None:
    """Run full SWOT analysis on The Sharks."""
    team = load_team(SHARKS_DIR, prefer_merged=True)
    if not team:
        print(f"[SWOT] No team data found at {SHARKS_DIR / 'team.json'}")
        print("[SWOT] Run the GC scraper first to populate data.")
        return None

    # SWOT should remain a full-season intelligence view, not only current availability.
    # Keep roster complete so player stats don't disappear when someone is marked unavailable.
    print(f"[SWOT] Using full roster: {len(team.get('roster', []))} players.")

    result = analyze_team(team)
    output_file = SHARKS_DIR / "swot_analysis.json"
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"[SWOT] Analysis saved to {output_file}")

    try:
        rationale = _swot_rationale_from_team(result)
        log_decision(
            category="swot_analysis",
            input_data={
                "team_name": result.get("team_name", "Unknown"),
                "players_analyzed": len(result.get("player_analyses", [])),
            },
            output_data={"team_swot": result.get("team_swot", {})},
            rationale=rationale,
        )
    except Exception as e:
        print(f"[SWOT] Audit log skipped: {e}")

    return result


def _team_aggregates(team_data: dict) -> dict:
    """Compute team-level aggregate stats for matchup comparison.
    Handles three data formats:
      1. Sharks team_merged.json: roster[].batting with numeric values
      2. GC app opponent: roster[].batting with string values + top-level batting_stats[]
      3. PDF-derived: roster[].batting with numeric values, no top-level stats
    """
    roster = team_data.get("roster", [])
    totals = team_data.get("team_totals", {})
    bt = totals.get("batting", totals) if totals else {}

    # Try team_totals first, otherwise aggregate from roster
    ab = _parse_number(bt.get("ab", 0))
    h = _parse_number(bt.get("h", 0))
    bb = _parse_number(bt.get("bb", 0))
    hbp = _parse_number(bt.get("hbp", 0))
    so = _parse_number(bt.get("so", bt.get("k", 0)))
    hr = _parse_number(bt.get("hr", 0))
    doubles = _parse_number(bt.get("doubles", bt.get("2b", 0)))
    triples = _parse_number(bt.get("triples", bt.get("3b", 0)))
    sb = _parse_number(bt.get("sb", 0))
    r = _parse_number(bt.get("r", 0))
    rbi = _parse_number(bt.get("rbi", 0))

    if ab == 0 and roster:
        for p in roster:
            batting = p.get("batting", {})
            ab += _parse_number(batting.get("ab", 0))
            h += _parse_number(batting.get("h", 0))
            bb += _parse_number(batting.get("bb", 0))
            hbp += _parse_number(batting.get("hbp", 0))
            so += _parse_number(batting.get("so", batting.get("k", 0)))
            hr += _parse_number(batting.get("hr", 0))
            doubles += _parse_number(batting.get("doubles", batting.get("2b", 0)))
            triples += _parse_number(batting.get("triples", batting.get("3b", 0)))
            sb += _parse_number(batting.get("sb", 0))
            r += _parse_number(batting.get("r", 0))
            rbi += _parse_number(batting.get("rbi", 0))

    # Fallback: try top-level batting_stats[] (GC app / web format or flattened game history)
    if ab == 0:
        for p in team_data.get("batting_stats", []):
            b = normalize_batting_row(p)
            ab += _parse_number(b.get("ab", 0))
            h += _parse_number(b.get("h", 0))
            bb += _parse_number(b.get("bb", 0))
            hbp += _parse_number(b.get("hbp", 0))
            so += _parse_number(b.get("so", 0))
            hr += _parse_number(b.get("hr", 0))
            doubles += _parse_number(b.get("2b", b.get("doubles", 0)))
            triples += _parse_number(b.get("3b", b.get("triples", 0)))
            sb += _parse_number(b.get("sb", 0))
            r += _parse_number(b.get("r", 0))
            rbi += _parse_number(b.get("rbi", 0))

    pa = ab + bb + hbp
    singles = max(0, h - doubles - triples - hr)
    tb = singles + 2*doubles + 3*triples + 4*hr

    # Advanced batting aggregates (QAB/contact profile) for matchup edge signals.
    adv_pa = 0.0
    adv_qab = 0.0
    adv_hhb = 0.0
    adv_bb = 0.0
    adv_so = 0.0
    weighted_c = 0.0
    weighted_ld = 0.0
    weighted_fb = 0.0
    weighted_gb = 0.0

    def _acc_adv(row: dict, pa_hint: float = 0.0):
        nonlocal adv_pa, adv_qab, adv_hhb, adv_bb, adv_so
        nonlocal weighted_c, weighted_ld, weighted_fb, weighted_gb
        adv = normalize_batting_advanced_row(row or {})
        row_pa = _parse_number(adv.get("pa", 0))
        if row_pa <= 0 and pa_hint > 0:
            row_pa = pa_hint
        wt = row_pa if row_pa > 0 else 1.0
        adv_pa += row_pa
        adv_qab += _parse_number(adv.get("qab", 0))
        adv_hhb += _parse_number(adv.get("hhb", 0))
        adv_bb += _parse_number(adv.get("bb", 0))
        adv_so += _parse_number(adv.get("so", 0))
        weighted_c += _parse_number(adv.get("c_pct", 0)) * wt
        weighted_ld += _parse_number(adv.get("ld_pct", 0)) * wt
        weighted_fb += _parse_number(adv.get("fb_pct", 0)) * wt
        weighted_gb += _parse_number(adv.get("gb_pct", 0)) * wt

    for p in roster:
        batting = p.get("batting", {})
        pa_hint = _parse_number(batting.get("pa", 0))
        if pa_hint <= 0:
            pa_hint = _parse_number(batting.get("ab", 0)) + _parse_number(batting.get("bb", 0)) + _parse_number(batting.get("hbp", 0))
        _acc_adv(p, pa_hint=pa_hint)

    # Fallback if roster has no advanced signal: use top-level batting_stats rows.
    if adv_qab == 0 and weighted_c == 0 and weighted_ld == 0 and weighted_fb == 0 and adv_hhb == 0:
        for p in team_data.get("batting_stats", []):
            b = normalize_batting_row(p)
            _acc_adv(p, pa_hint=_parse_number(b.get("pa", 0)))

    # Pitching aggregates — check per-player pitching, then top-level pitching_stats[]
    total_ip = 0.0
    total_er = 0.0
    total_p_bb = 0.0
    total_p_h = 0.0
    total_p_so = 0.0

    pitching_sources = [p.get("pitching", {}) for p in roster if p.get("pitching")]
    if not pitching_sources:
        pitching_sources = team_data.get("pitching_stats", [])

    for pitching in pitching_sources:
        ip = _innings_to_float(pitching.get("ip", 0))
        total_ip += ip
        total_er += _parse_number(pitching.get("er", 0))
        total_p_bb += _parse_number(pitching.get("bb", 0))
        total_p_h += _parse_number(pitching.get("h", 0))
        total_p_so += _parse_number(pitching.get("so", pitching.get("k", 0)))

    # Fielding — check per-player, then top-level fielding_stats[]
    total_po = 0.0
    total_a = 0.0
    total_e = 0.0

    fielding_sources = [p.get("fielding", {}) for p in roster if p.get("fielding")]
    if not fielding_sources:
        fielding_sources = team_data.get("fielding_stats", [])

    for fielding in fielding_sources:
        total_po += _parse_number(fielding.get("po", 0))
        total_a += _parse_number(fielding.get("a", 0))
        total_e += _parse_number(fielding.get("e", 0))

    q_pct = _safe_div(adv_qab, adv_pa) if adv_pa > 0 else None
    c_pct = _safe_div(weighted_c, adv_pa) if adv_pa > 0 else None
    ld_pct = _safe_div(weighted_ld, adv_pa) if adv_pa > 0 else None
    fb_pct = _safe_div(weighted_fb, adv_pa) if adv_pa > 0 else None
    gb_pct = _safe_div(weighted_gb, adv_pa) if adv_pa > 0 else None
    bb_per_k = _safe_div(adv_bb, adv_so) if adv_so > 0 else None

    return {
        "batting": {
            "avg": round(_safe_div(h, ab), 3),
            "obp": round(_safe_div(h + bb + hbp, pa), 3),
            "slg": round(_safe_div(tb, ab), 3),
            "ops": round(_safe_div(h + bb + hbp, pa) + _safe_div(tb, ab), 3),
            "k_rate": round(_safe_div(so, pa), 3),
            "bb_rate": round(_safe_div(bb, pa), 3),
            "hr": int(hr), "sb": int(sb), "r": int(r), "rbi": int(rbi),
            "ab": int(ab), "h": int(h), "pa": int(pa),
        },
        "batting_advanced": {
            "qab": int(adv_qab),
            "qab_pct": round(q_pct, 3) if q_pct is not None else None,
            "c_pct": round(c_pct, 3) if c_pct is not None else None,
            "ld_pct": round(ld_pct, 3) if ld_pct is not None else None,
            "fb_pct": round(fb_pct, 3) if fb_pct is not None else None,
            "gb_pct": round(gb_pct, 3) if gb_pct is not None else None,
            "hhb": int(adv_hhb),
            "bb_per_k": round(bb_per_k, 3) if bb_per_k is not None else None,
        },
        "pitching": {
            "era": round(_safe_div(total_er * 7, total_ip), 2) if total_ip > 0 else None,
            "whip": round(_safe_div(total_p_bb + total_p_h, total_ip), 2) if total_ip > 0 else None,
            "k_per_ip": round(_safe_div(total_p_so, total_ip), 2) if total_ip > 0 else None,
            "bb_per_ip": round(_safe_div(total_p_bb, total_ip), 2) if total_ip > 0 else None,
            "ip": round(total_ip, 1),
        },
        "fielding": {
            "fpct": round(_safe_div(total_po + total_a, total_po + total_a + total_e), 3) if (total_po + total_a + total_e) > 0 else None,
            "errors": int(total_e),
        },
        "roster_size": len(roster),
    }


def _n(v):
    """Coerce None to 0 for safe numeric comparison."""
    return 0 if v is None else v


def analyze_matchup(our_team: dict, opponent_team: dict) -> dict:
    """Compare two teams and generate matchup insights."""
    us = _team_aggregates(our_team)
    them = _team_aggregates(opponent_team)

    # Do not generate statistical analysis if the opponent lacks history
    if them.get("batting", {}).get("pa", 0) < 5 and them.get("pitching", {}).get("ip", 0) < 2.0:
        return {
            "our_team": our_team.get("team_name", "Sharks"),
            "opponent": opponent_team.get("team_name", "Opponent"),
            "empty": True,
            "reason": "insufficient_data",
            "our_stats": us,
            "their_stats": them,
            "our_advantages": [],
            "their_advantages": [],
            "key_matchups": [],
            "recommendation": "Not enough historical data available for this opponent to calculate a stat-based matchup.",
        }

    our_advantages = []
    their_advantages = []
    key_matchups = []

    # Batting comparison
    if _n(us["batting"]["avg"]) > _n(them["batting"]["avg"]) + 0.030:
        our_advantages.append(f"Higher team batting average ({us['batting']['avg']} vs {them['batting']['avg']})")
    elif _n(them["batting"]["avg"]) > _n(us["batting"]["avg"]) + 0.030:
        their_advantages.append(f"Higher team batting average ({them['batting']['avg']} vs {us['batting']['avg']})")

    if _n(us["batting"]["obp"]) > _n(them["batting"]["obp"]) + 0.030:
        our_advantages.append(f"Better on-base percentage ({us['batting']['obp']} vs {them['batting']['obp']})")
    elif _n(them["batting"]["obp"]) > _n(us["batting"]["obp"]) + 0.030:
        their_advantages.append(f"Better on-base percentage ({them['batting']['obp']} vs {us['batting']['obp']})")

    if _n(us["batting"]["ops"]) > _n(them["batting"]["ops"]) + 0.050:
        our_advantages.append(f"Stronger overall hitting (OPS: {us['batting']['ops']} vs {them['batting']['ops']})")
    elif _n(them["batting"]["ops"]) > _n(us["batting"]["ops"]) + 0.050:
        their_advantages.append(f"Stronger overall hitting (OPS: {them['batting']['ops']} vs {us['batting']['ops']})")

    # K rate comparison (lower is better for batting team)
    if _n(us["batting"]["k_rate"]) < _n(them["batting"]["k_rate"]) - 0.05:
        our_advantages.append(f"Better contact rate (K%: {us['batting']['k_rate']} vs {them['batting']['k_rate']})")
    elif _n(them["batting"]["k_rate"]) < _n(us["batting"]["k_rate"]) - 0.05:
        their_advantages.append(f"Better contact rate (K%: {them['batting']['k_rate']} vs {us['batting']['k_rate']})")

    # Advanced batting quality signals
    if _n(us["batting_advanced"]["qab_pct"]) > _n(them["batting_advanced"]["qab_pct"]) + 0.08:
        our_advantages.append(
            f"Higher quality-at-bat rate (QAB%: {us['batting_advanced']['qab_pct']} vs {them['batting_advanced']['qab_pct']})"
        )
    elif _n(them["batting_advanced"]["qab_pct"]) > _n(us["batting_advanced"]["qab_pct"]) + 0.08:
        their_advantages.append(
            f"Higher quality-at-bat rate (QAB%: {them['batting_advanced']['qab_pct']} vs {us['batting_advanced']['qab_pct']})"
        )

    if _n(us["batting_advanced"]["c_pct"]) > _n(them["batting_advanced"]["c_pct"]) + 0.07:
        our_advantages.append(
            f"Better contact quality (C%: {us['batting_advanced']['c_pct']} vs {them['batting_advanced']['c_pct']})"
        )
    elif _n(them["batting_advanced"]["c_pct"]) > _n(us["batting_advanced"]["c_pct"]) + 0.07:
        their_advantages.append(
            f"Better contact quality (C%: {them['batting_advanced']['c_pct']} vs {us['batting_advanced']['c_pct']})"
        )

    # Pitching comparison — only if both teams have meaningful innings
    if _n(us["pitching"]["ip"]) >= 3 and _n(them["pitching"]["ip"]) >= 3:
        if _n(us["pitching"]["era"]) < _n(them["pitching"]["era"]) - 1.0:
            our_advantages.append(f"Superior pitching (ERA: {us['pitching']['era']} vs {them['pitching']['era']})")
        elif _n(them["pitching"]["era"]) < _n(us["pitching"]["era"]) - 1.0:
            their_advantages.append(f"Superior pitching (ERA: {them['pitching']['era']} vs {us['pitching']['era']})")

        if _n(us["pitching"]["whip"]) < _n(them["pitching"]["whip"]) - 0.2:
            our_advantages.append(f"Better pitch control (WHIP: {us['pitching']['whip']} vs {them['pitching']['whip']})")
        elif _n(them["pitching"]["whip"]) < _n(us["pitching"]["whip"]) - 0.2:
            their_advantages.append(f"Better pitch control (WHIP: {them['pitching']['whip']} vs {us['pitching']['whip']})")

    # Fielding — skip comparison if either side has no fielding data
    if us["fielding"]["fpct"] is not None and them["fielding"]["fpct"] is not None:
        if _n(us["fielding"]["fpct"]) > _n(them["fielding"]["fpct"]) + 0.02:
            our_advantages.append(f"Cleaner defense (FPCT: {us['fielding']['fpct']} vs {them['fielding']['fpct']})")
        elif _n(them["fielding"]["fpct"]) > _n(us["fielding"]["fpct"]) + 0.02:
            their_advantages.append(f"Cleaner defense (FPCT: {them['fielding']['fpct']} vs {us['fielding']['fpct']})")

    # Cross-matchups: our batting vs their pitching and vice versa
    if _n(us["batting"]["ops"]) > 0.700 and _n(them["pitching"]["era"]) > 5.0:
        key_matchups.append("Our offense should exploit their pitching struggles")
    if _n(them["batting"]["ops"]) > 0.700 and _n(us["pitching"]["era"]) > 5.0:
        key_matchups.append("Their offense could exploit our pitching - keep pitch count low")
    if _n(us["batting"]["k_rate"]) > 0.35 and _n(them["pitching"]["k_per_ip"]) > 0.8:
        key_matchups.append("Warning: our high K-rate meets their strikeout pitcher - focus on contact approach")
    if _n(them["batting"]["k_rate"]) > 0.35 and _n(us["pitching"]["k_per_ip"]) > 0.8:
        key_matchups.append("Opportunity: their team strikes out a lot and our pitchers can rack up Ks")
    if _n(us["batting"]["sb"]) > _n(them["batting"]["sb"]) + 3:
        key_matchups.append("Speed advantage - aggressive baserunning recommended")
    if _n(them["batting_advanced"]["ld_pct"]) > 0.30 and _n(us["fielding"]["fpct"]) < 0.900:
        key_matchups.append("They profile as a line-drive offense; tighten infield readiness and first-step defense.")
    if _n(us["batting_advanced"]["bb_per_k"]) > _n(them["batting_advanced"]["bb_per_k"]) + 0.25:
        key_matchups.append("Plate-discipline edge favors us; work deep counts and force pitch volume.")

    # Recommendation
    recs = []
    if their_advantages and not our_advantages:
        recs.append("Tough matchup. Focus on disciplined at-bats and minimizing errors.")
    elif our_advantages and not their_advantages:
        recs.append("Favorable matchup. Play aggressive and apply pressure early.")
    elif len(our_advantages) > len(their_advantages):
        recs.append("Slight edge for us. Execute fundamentals and capitalize on matchup advantages.")
    elif len(their_advantages) > len(our_advantages):
        recs.append("They have an edge on paper. Need strong defense and clutch hitting to win.")
    else:
        recs.append("Evenly matched. The team that makes fewer mistakes will win.")

    return {
        "our_team": our_team.get("team_name", "Sharks"),
        "opponent": opponent_team.get("team_name", "Opponent"),
        "empty": False,
        "reason": None,
        "our_stats": us,
        "their_stats": them,
        "our_advantages": our_advantages or ["No clear statistical advantages (need more data)"],
        "their_advantages": their_advantages or ["No clear statistical advantages (need more data)"],
        "key_matchups": key_matchups or ["Not enough data for cross-matchup analysis"],
        "recommendation": recs[0],
    }


def run_opponent_analysis(opponent_name: str) -> dict | None:
    """Run SWOT analysis on a specific opponent."""
    opp_dir = OPPONENTS_DIR / opponent_name.lower().replace(" ", "_")
    team = load_team(opp_dir)
    if not team:
        print(f"[SWOT] No opponent data found at {opp_dir / 'team.json'}")
        return None
    result = analyze_team(team)
    output_file = opp_dir / "swot_analysis.json"
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"[SWOT] Opponent analysis saved to {output_file}")

    try:
        rationale = _swot_rationale_from_team(result)
        log_decision(
            category="swot_analysis_opponent",
            input_data={
                "team_name": result.get("team_name", opponent_name),
                "players_analyzed": len(result.get("player_analyses", [])),
            },
            output_data={"team_swot": result.get("team_swot", {})},
            rationale=rationale,
        )
    except Exception as e:
        print(f"[SWOT] Opponent audit log skipped: {e}")

    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--opponent":
        if len(sys.argv) < 3:
            print("Usage: python swot_analyzer.py --opponent <team_name>")
            sys.exit(1)
        run_opponent_analysis(sys.argv[2])
    else:
        result = run_sharks_analysis()
        if result:
            print(f"\n=== TEAM SWOT: {result['team_name']} ===")
            for cat, items in result["team_swot"].items():
                print(f"\n{cat.upper()}:")
                for item in items:
                    print(f"  • {item}")
