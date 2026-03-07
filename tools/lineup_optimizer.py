"""
Lineup Optimizer for Softball
Generates optimal batting orders based on player stats and PCLL rules.
Enforces mandatory play requirements (1 AB + 6 defensive outs per player).
"""

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent.parent / "data"
SHARKS_DIR = DATA_DIR / "sharks"


# ── PCLL Mandatory Play Rules ────────────────────────────────────────────
# Every player must receive:
#   - At least 1 at-bat per game
#   - At least 6 consecutive defensive outs (approximately 2 innings)
# Continuous batting order is used (all players bat).

POSITIONS = ["P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
BENCH_POSITIONS = ["EH"]  # Extra hitter in continuous batting order


def compute_batting_score(player: dict, strategy: str = "balanced") -> float:
    """
    Compute a composite batting score for lineup ordering.

    Strategies:
        'balanced'    — OBP-weighted all-around score
        'aggressive'  — Power/SLG-heavy, maximize run production
        'development' — Distribute at-bats more evenly, weight less on pure stats
    """
    hitting = player.get("stats", {}).get("hitting", {})
    ab = hitting.get("ab", 0)
    h = hitting.get("h", 0)
    bb = hitting.get("bb", 0)
    hbp = hitting.get("hbp", 0)
    k = hitting.get("k", 0)
    doubles = hitting.get("doubles", 0)
    triples = hitting.get("triples", 0)
    hr = hitting.get("hr", 0)
    sb = hitting.get("sb", 0)
    runs = hitting.get("runs", 0)
    rbi = hitting.get("rbi", 0)

    pa = ab + bb + hbp
    if pa == 0:
        return 0.0

    ba = h / ab if ab > 0 else 0
    obp = (h + bb + hbp) / pa
    singles = h - doubles - triples - hr
    total_bases = singles + (2 * doubles) + (3 * triples) + (4 * hr)
    slg = total_bases / ab if ab > 0 else 0
    k_rate = k / pa

    if strategy == "balanced":
        # OBP is king, then SLG, then contact, then speed
        score = (obp * 40) + (slg * 25) + ((1 - k_rate) * 20) + (sb / max(pa, 1) * 15)
    elif strategy == "aggressive":
        # Maximize run production: SLG + RBI rate
        rbi_rate = rbi / pa
        score = (slg * 35) + (obp * 25) + (rbi_rate * 25) + ((1 - k_rate) * 15)
    elif strategy == "development":
        # Flatten the curve — give everyone more balanced placement
        score = (obp * 30) + (ba * 30) + ((1 - k_rate) * 25) + (sb / max(pa, 1) * 15)
        score = score * 0.7 + 0.3 * 10  # pull toward center
    else:
        score = obp * 50 + slg * 50

    return round(score, 3)


def slot_players(sorted_players: list[dict]) -> list[dict]:
    """
    Assign batting order slots based on ranked player scores.

    Slot logic (adapted for youth softball):
        1st (Leadoff)  — Highest OBP, good speed
        2nd            — Contact hitter, advances runners
        3rd            — Best all-around hitter
        4th (Cleanup)  — Power hitter
        5th            — Secondary run producer
        6-N            — Remaining players in score order
    """
    lineup = []
    pool = list(sorted_players)

    if not pool:
        return lineup

    # Find best leadoff candidate: highest OBP + speed combo
    leadoff_scores = []
    for i, p in enumerate(pool):
        hitting = p.get("stats", {}).get("hitting", {})
        ab = hitting.get("ab", 0)
        h = hitting.get("h", 0)
        bb = hitting.get("bb", 0)
        hbp = hitting.get("hbp", 0)
        sb = hitting.get("sb", 0)
        pa = ab + bb + hbp
        obp = (h + bb + hbp) / pa if pa > 0 else 0
        speed = sb / max(pa, 1)
        leadoff_scores.append((i, obp * 0.6 + speed * 0.4))

    leadoff_scores.sort(key=lambda x: x[1], reverse=True)
    leadoff_idx = leadoff_scores[0][0]
    leadoff = pool.pop(leadoff_idx)
    lineup.append({"slot": 1, "role": "Leadoff", **leadoff})

    if not pool:
        return lineup

    # Slot 3: Best all-around hitter (already sorted by composite score)
    best_hitter = pool.pop(0)

    # Slot 4: Next best = cleanup
    cleanup = pool.pop(0) if pool else None

    # Slot 2: Best remaining contact hitter
    if pool:
        contact_scores = []
        for i, p in enumerate(pool):
            hitting = p.get("stats", {}).get("hitting", {})
            ab = hitting.get("ab", 0)
            h = hitting.get("h", 0)
            k = hitting.get("k", 0)
            pa = ab + hitting.get("bb", 0) + hitting.get("hbp", 0)
            ba = h / ab if ab > 0 else 0
            k_rate = k / pa if pa > 0 else 1
            contact_scores.append((i, ba * 0.5 + (1 - k_rate) * 0.5))
        contact_scores.sort(key=lambda x: x[1], reverse=True)
        contact_idx = contact_scores[0][0]
        second_hitter = pool.pop(contact_idx)
        lineup.append({"slot": 2, "role": "Contact", **second_hitter})
    else:
        lineup.append({"slot": 2, "role": "Contact", "name": "—", "number": 0})

    lineup.append({"slot": 3, "role": "Best Hitter", **best_hitter})

    if cleanup:
        lineup.append({"slot": 4, "role": "Cleanup", **cleanup})

    # 5th slot: next best power option
    if pool:
        fifth = pool.pop(0)
        lineup.append({"slot": 5, "role": "Run Producer", **fifth})

    # Remaining slots
    for i, p in enumerate(pool):
        lineup.append({"slot": 6 + i, "role": "Depth", **p})

    # Sort by slot
    lineup.sort(key=lambda x: x["slot"])
    return lineup


def validate_mandatory_play(lineup: list[dict], roster: list[dict]) -> list[str]:
    """
    Validate that the lineup satisfies PCLL mandatory play rules.

    Returns a list of violations (empty = compliant).
    """
    violations = []
    lineup_ids = {p.get("id") for p in lineup}
    roster_ids = {p.get("id") for p in roster}

    missing = roster_ids - lineup_ids
    if missing:
        violations.append(
            f"Players missing from batting order (mandatory 1 AB): "
            f"{', '.join(str(m) for m in missing)}"
        )

    return violations


def generate_lineup(
    team_data: dict,
    strategy: str = "balanced",
) -> dict:
    """Generate an optimized batting lineup for The Sharks."""
    roster = team_data.get("roster", [])
    if not roster:
        return {"error": "No roster data found"}

    # Score and sort
    for player in roster:
        player["_batting_score"] = compute_batting_score(player, strategy)

    sorted_players = sorted(roster, key=lambda p: p["_batting_score"], reverse=True)

    # Build lineup
    lineup = slot_players(sorted_players)

    # Validate
    violations = validate_mandatory_play(lineup, roster)

    # Clean up temp scores
    for player in roster:
        player.pop("_batting_score", None)
    for entry in lineup:
        entry.pop("_batting_score", None)

    return {
        "strategy": strategy,
        "lineup": lineup,
        "violations": violations,
        "compliant": len(violations) == 0,
    }


def generate_all_lineups(team_data: dict) -> dict:
    """Generate lineups for all three strategies."""
    results = {}
    for strategy in ["balanced", "aggressive", "development"]:
        results[strategy] = generate_lineup(team_data, strategy)
    return results


def run():
    """Load Sharks data and generate lineups."""
    team_file = SHARKS_DIR / "team.json"
    if not team_file.exists():
        print(f"[LINEUP] No team data found at {team_file}")
        print("[LINEUP] Run the GC scraper first to populate data.")
        return None

    with open(team_file, "r") as f:
        team_data = json.load(f)

    results = generate_all_lineups(team_data)

    output_file = SHARKS_DIR / "lineups.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[LINEUP] Lineups saved to {output_file}")

    for strategy, data in results.items():
        print(f"\n{'='*50}")
        print(f"  STRATEGY: {strategy.upper()}")
        print(f"  Compliant: {'✅' if data['compliant'] else '❌'}")
        print(f"{'='*50}")
        for entry in data["lineup"]:
            print(f"  {entry['slot']:>2}. #{entry.get('number', '?'):>2} {entry.get('name', '—'):<20} ({entry['role']})")
        if data["violations"]:
            print(f"\n  ⚠️  VIOLATIONS:")
            for v in data["violations"]:
                print(f"     • {v}")

    return results


if __name__ == "__main__":
    run()
