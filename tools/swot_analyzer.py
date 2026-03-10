"""
SWOT Analyzer for Softball
Deterministic rules-based SWOT analysis engine for individual players and teams.
Reads player stats from data/ and generates SWOT classifications.
"""

import json
import os
from pathlib import Path
from typing import Any

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


def compute_derived_stats(player: dict) -> dict:
    """Compute derived statistics from raw counting stats."""
    hitting = player.get("stats", {}).get("hitting", {})
    pitching = player.get("stats", {}).get("pitching", {})
    fielding = player.get("stats", {}).get("fielding", {})

    ab = hitting.get("ab", 0)
    h = hitting.get("h", 0)
    bb = hitting.get("bb", 0)
    hbp = hitting.get("hbp", 0)
    k = hitting.get("k", 0)
    doubles = hitting.get("doubles", 0)
    triples = hitting.get("triples", 0)
    hr = hitting.get("hr", 0)
    sb = hitting.get("sb", 0)
    cs = hitting.get("cs", 0)

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
    ip = pitching.get("ip", 0.0)
    p_er = pitching.get("er", 0)
    p_k = pitching.get("k", 0)
    p_bb = pitching.get("bb", 0)
    p_h = pitching.get("h", 0)

    era = _safe_div(p_er * 7, ip)  # LL softball = 7 innings
    whip = _safe_div(p_bb + p_h, ip)
    k_per_ip = _safe_div(p_k, ip)
    bb_per_ip = _safe_div(p_bb, ip)

    # Fielding
    po = fielding.get("po", 0)
    a = fielding.get("a", 0)
    e = fielding.get("e", 0)
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
        strengths.append(f"Low strikeout rate (K%: {h['k_rate']})")
    elif h.get("k_rate", 0) >= HITTING_THRESHOLDS["k_rate"]["weak"]:
        weaknesses.append(f"High strikeout rate (K%: {h['k_rate']})")

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
        strengths.append(f"High strikeout rate (K/IP: {p['k_per_ip']})")
    elif p.get("k_per_ip", 99) <= PITCHING_THRESHOLDS["k_per_ip"]["weak"]:
        weaknesses.append(f"Low strikeout rate (K/IP: {p['k_per_ip']})")

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

    raw_ip = player.get("stats", {}).get("pitching", {}).get("ip", 0.0)
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

    return {
        "player_id": player.get("id", "unknown"),
        "name": player.get("name", "Unknown"),
        "number": player.get("number", 0),
        "derived_stats": derived,
        "swot": {
            "strengths": strengths or ["No standout strengths yet (need more data)"],
            "weaknesses": weaknesses or ["No major weaknesses identified"],
            "opportunities": opportunities or ["Continue developing all-around skills"],
            "threats": threats or ["No specific threats identified"],
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

    team_strengths = [f"{k} ({v} players)" for k, v in strength_types.most_common(5)]
    team_weaknesses = [f"{k} ({v} players)" for k, v in weakness_types.most_common(5)]

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


def load_team(team_dir: Path) -> dict | None:
    """Load team data from a directory."""
    team_file = team_dir / "team.json"
    if not team_file.exists():
        return None
    with open(team_file, "r") as f:
        return json.load(f)


def run_sharks_analysis() -> dict | None:
    """Run full SWOT analysis on The Sharks."""
    team = load_team(SHARKS_DIR)
    if not team:
        print(f"[SWOT] No team data found at {SHARKS_DIR / 'team.json'}")
        print("[SWOT] Run the GC scraper first to populate data.")
        return None

    # ── Availability Filter ────────────────────────────────────────────────
    availability_file = SHARKS_DIR / "availability.json"
    if availability_file.exists():
        with open(availability_file, "r") as f:
            availability = json.load(f)
        
        original_roster = team.get("roster", [])
        active_roster = []
        for p in original_roster:
            name = f"{p.get('first', '')} {p.get('last', '')}".strip()
            if availability.get(name, True): # Default to active if not in file
                active_roster.append(p)
        
        print(f"[SWOT] Filtered roster: {len(active_roster)}/{len(original_roster)} players active.")
        team["roster"] = active_roster

    result = analyze_team(team)
    output_file = SHARKS_DIR / "swot_analysis.json"
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"[SWOT] Analysis saved to {output_file}")
    return result


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
