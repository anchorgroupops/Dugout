"""
Lineup Optimizer for Softball
Generates optimal batting orders based on player stats and PCLL rules.
Enforces mandatory play requirements (1 AB + 6 defensive outs per player).
"""

import json
import random
from pathlib import Path

from logger import log_decision
from stats_normalizer import normalize_player_batting, normalize_player_batting_advanced

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
    # Preferred source order is enforced inside normalize_player_batting():
    # player.batting -> player.stats.hitting -> player legacy flat fields.
    hitting = normalize_player_batting(player)
    hitting_adv = normalize_player_batting_advanced(player)
    ab = hitting.get("ab", 0)
    h = hitting.get("h", 0)
    bb = hitting.get("bb", 0)
    hbp = hitting.get("hbp", 0)
    k = hitting.get("so", 0)
    doubles = hitting.get("doubles", hitting.get("2b", 0))
    triples = hitting.get("triples", hitting.get("3b", 0))
    hr = hitting.get("hr", 0)
    sb = hitting.get("sb", 0)
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
    q_pct = hitting_adv.get("qab_pct", 0.0)  # quality at-bat ratio
    contact_quality = hitting_adv.get("c_pct", 0.0)
    line_drive_rate = hitting_adv.get("ld_pct", 0.0)
    discipline_ratio = hitting_adv.get("bb_per_k", 0.0)
    pa_per_bb = hitting_adv.get("pa_per_bb", 0.0)
    pa_per_bb_bonus = (1 / pa_per_bb) if pa_per_bb > 0 else 0.0

    if strategy == "balanced":
        # OBP is king, then SLG, then contact, then speed
        score = (
            (obp * 34)
            + (slg * 22)
            + ((1 - k_rate) * 18)
            + (sb / max(pa, 1) * 10)
            + (q_pct * 8)
            + (contact_quality * 5)
            + (line_drive_rate * 3)
        )
    elif strategy == "aggressive":
        # Maximize run production: SLG + RBI rate
        rbi_rate = rbi / pa
        score = (
            (slg * 33)
            + (obp * 23)
            + (rbi_rate * 20)
            + ((1 - k_rate) * 10)
            + (line_drive_rate * 8)
            + (contact_quality * 4)
            + (q_pct * 2)
        )
    elif strategy == "development":
        # Flatten the curve — give everyone more balanced placement
        score = (
            (obp * 28)
            + (ba * 22)
            + ((1 - k_rate) * 16)
            + (sb / max(pa, 1) * 10)
            + (q_pct * 14)
            + (discipline_ratio * 6)
            + (pa_per_bb_bonus * 4)
        )
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
        hitting = normalize_player_batting(p)
        hitting_adv = normalize_player_batting_advanced(p)
        ab = hitting.get("ab", 0)
        h = hitting.get("h", 0)
        bb = hitting.get("bb", 0)
        hbp = hitting.get("hbp", 0)
        sb = hitting.get("sb", 0)
        pa = ab + bb + hbp
        obp = (h + bb + hbp) / pa if pa > 0 else 0
        speed = sb / max(pa, 1)
        qab_pct = hitting_adv.get("qab_pct", 0.0)
        leadoff_scores.append((i, obp * 0.55 + speed * 0.30 + qab_pct * 0.15))

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
            hitting = normalize_player_batting(p)
            hitting_adv = normalize_player_batting_advanced(p)
            ab = hitting.get("ab", 0)
            h = hitting.get("h", 0)
            k = hitting.get("so", 0)
            bb = hitting.get("bb", 0)
            hbp = hitting.get("hbp", 0)
            pa = ab + bb + hbp
            ba = h / ab if ab > 0 else 0
            k_rate = k / pa if pa > 0 else 1
            contact_quality = hitting_adv.get("c_pct", 0.0)
            contact_scores.append((i, ba * 0.4 + (1 - k_rate) * 0.45 + contact_quality * 0.15))
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
    def _pid(p: dict) -> str:
        if p.get("id"):
            return str(p.get("id"))
        name = f"{p.get('first', '')} {p.get('last', '')}".strip().lower()
        num = str(p.get("number", "")).strip()
        return f"{name}|{num}"

    lineup_ids = {_pid(p) for p in lineup}
    roster_ids = {_pid(p) for p in roster}

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
    roster = team_data.get("roster", team_data.get("players", []))
    if not roster:
        return {"strategy": strategy, "lineup": [], "violations": ["No roster data found"], "compliant": False}

    def _derive_display_rates(hitting: dict) -> tuple[float, float, float, int]:
        ab = hitting.get("ab", 0)
        h = hitting.get("h", 0)
        bb = hitting.get("bb", 0)
        hbp = hitting.get("hbp", 0)
        sac = hitting.get("sac", 0)
        one_b = hitting.get("1b", hitting.get("singles", 0))
        two_b = hitting.get("2b", hitting.get("doubles", 0))
        three_b = hitting.get("3b", hitting.get("triples", 0))
        hr = hitting.get("hr", 0)
        pa = hitting.get("pa", 0) or (ab + bb + hbp + sac)
        tb = one_b + 2 * two_b + 3 * three_b + 4 * hr
        avg = hitting.get("avg")
        obp = hitting.get("obp")
        slg = hitting.get("slg")
        if avg in (None, "", "-", "—"):
            avg = (h / ab) if ab > 0 else 0.0
        if obp in (None, "", "-", "—"):
            obp = ((h + bb + hbp) / pa) if pa > 0 else 0.0
        if slg in (None, "", "-", "—"):
            slg = (tb / ab) if ab > 0 else 0.0
        return round(float(avg), 3), round(float(obp), 3), round(float(slg), 3), int(pa)

    # Attach key display stats to each player before scoring (carried into lineup entries)
    for player in roster:
        hitting = normalize_player_batting(player)
        avg, obp, slg, pa = _derive_display_rates(hitting)
        player["_display_avg"] = avg
        player["_display_obp"] = obp
        player["_display_slg"] = slg
        player["_display_pa"] = pa

    # Score, sort and ensure names
    for player in roster:
        player["_batting_score"] = compute_batting_score(player, strategy)
        if "name" not in player:
            player["name"] = f"{player.get('first', '')} {player.get('last', '')}".strip()

    sorted_players = sorted(roster, key=lambda p: p["_batting_score"], reverse=True)

    # Build lineup
    lineup = slot_players(sorted_players)

    # Validate
    violations = validate_mandatory_play(lineup, roster)

    # Clean up temp keys from roster pool
    for player in roster:
        player.pop("_batting_score", None)
        for k in ("_display_avg", "_display_obp", "_display_slg", "_display_pa"):
            player.pop(k, None)
    for entry in lineup:
        entry.pop("_batting_score", None)
        # Promote computed display stats and clean private keys
        entry["avg"] = entry.pop("_display_avg", 0.0)
        entry["obp"] = entry.pop("_display_obp", 0.0)
        entry["slg"] = entry.pop("_display_slg", 0.0)
        entry["pa"]  = entry.pop("_display_pa", 0)

    return {
        "strategy": strategy,
        "lineup": lineup,
        "violations": violations,
        "compliant": len(violations) == 0,
    }


def _player_outcome_probs(player: dict) -> dict[str, float]:
    """Derive outcome probabilities from a player's batting stats."""
    hitting = normalize_player_batting(player)
    ab = hitting.get("ab", 0)
    h = hitting.get("h", 0)
    bb = hitting.get("bb", 0)
    hbp = hitting.get("hbp", 0)
    doubles = hitting.get("doubles", hitting.get("2b", 0))
    triples = hitting.get("triples", hitting.get("3b", 0))
    hr = hitting.get("hr", 0)
    pa = ab + bb + hbp
    if pa < 3:
        # Not enough data — use league-average youth rates
        return {"single": 0.18, "double": 0.04, "triple": 0.01, "hr": 0.005, "bb": 0.12, "out": 0.645}
    singles = h - doubles - triples - hr
    return {
        "single": max(singles, 0) / pa,
        "double": doubles / pa,
        "triple": triples / pa,
        "hr": hr / pa,
        "bb": (bb + hbp) / pa,
        "out": max(1.0 - (h + bb + hbp) / pa, 0.0),
    }


def simulate_inning(lineup: list[dict], num_simulations: int = 1000, seed: int = 42) -> float:
    """Monte Carlo simulation of runs scored per game (6 innings).

    Each batter's plate appearance uses their real outcome probabilities.
    Baserunner advancement: single=1 base, double=2, triple=3, hr=clears.
    Deterministic via fixed seed.
    """
    rng = random.Random(seed)
    if not lineup:
        return 0.0

    probs_list = []
    for entry in lineup:
        p = _player_outcome_probs(entry)
        # Build cumulative distribution
        cumulative = []
        running = 0.0
        for outcome in ("single", "double", "triple", "hr", "bb", "out"):
            running += p.get(outcome, 0)
            cumulative.append((running, outcome))
        # Normalize
        if cumulative:
            total = cumulative[-1][0]
            if total > 0:
                cumulative = [(c / total, o) for c, o in cumulative]
        probs_list.append(cumulative)

    total_runs = 0
    innings_per_game = 6
    num_batters = len(probs_list)

    for _ in range(num_simulations):
        batter_idx = 0
        game_runs = 0
        for _ in range(innings_per_game):
            outs = 0
            bases = [False, False, False]  # 1st, 2nd, 3rd
            while outs < 3:
                roll = rng.random()
                cum = probs_list[batter_idx % num_batters]
                outcome = "out"
                for threshold, o in cum:
                    if roll <= threshold:
                        outcome = o
                        break
                batter_idx += 1

                if outcome == "out":
                    outs += 1
                elif outcome == "bb" or outcome == "single":
                    # Advance each runner 1 base
                    if bases[2]:
                        game_runs += 1
                    bases[2] = bases[1]
                    bases[1] = bases[0]
                    bases[0] = True
                elif outcome == "double":
                    if bases[2]:
                        game_runs += 1
                    if bases[1]:
                        game_runs += 1
                    bases[2] = bases[0]
                    bases[1] = True
                    bases[0] = False
                elif outcome == "triple":
                    game_runs += sum(bases)
                    bases = [False, False, True]
                elif outcome == "hr":
                    game_runs += sum(bases) + 1
                    bases = [False, False, False]

        total_runs += game_runs

    return round(total_runs / num_simulations, 2)


def recommend_strategy(matchup: dict | None = None) -> str:
    """Auto-select lineup strategy based on opponent matchup data.

    - Strong opponent pitching (low ERA, high K) → 'balanced' (OBP/contact focus)
    - Weak opponent pitching → 'aggressive' (capitalize with power)
    - Insufficient data / development game → 'balanced' (safe default)
    """
    if not matchup or matchup.get("empty"):
        return "balanced"

    their_advantages = [a.lower() for a in matchup.get("their_advantages", [])]
    our_advantages = [a.lower() for a in matchup.get("our_advantages", [])]

    # Detect strong opponent pitching
    opp_strong_pitching = any(
        kw in adv for adv in their_advantages
        for kw in ("era", "whip", "strikeout", "pitching")
    )
    # Detect weak opponent pitching
    our_pitching_advantage = any(
        kw in adv for adv in our_advantages
        for kw in ("era", "whip", "strikeout", "pitching")
    )
    # Detect weak opponent defense
    opp_weak_defense = any(
        kw in adv for adv in our_advantages
        for kw in ("fielding", "error", "defense")
    )

    if opp_strong_pitching:
        return "balanced"
    if our_pitching_advantage or opp_weak_defense:
        return "aggressive"
    return "balanced"


def generate_all_lineups(team_data: dict, matchup: dict | None = None) -> dict:
    """Generate lineups for all three strategies, with a recommended pick."""
    recommended = recommend_strategy(matchup)
    results = {}
    for strategy in ["balanced", "aggressive", "development"]:
        lineup_result = generate_lineup(team_data, strategy)
        lineup_result["simulated_runs_per_game"] = simulate_inning(lineup_result.get("lineup", []))
        results[strategy] = lineup_result
    results["recommended_strategy"] = recommended
    if matchup and not matchup.get("empty"):
        results["matchup_opponent"] = matchup.get("opponent", "")
    return results


def _build_lineup_rationale(results: dict) -> str:
    parts = []
    for strategy in ["balanced", "aggressive", "development"]:
        lineup = (results.get(strategy) or {}).get("lineup", [])
        top = lineup[:3]
        if not top:
            continue
        top_text = ", ".join(
            f"#{p.get('number', '?')} {p.get('name', 'Unknown')} (OBP {p.get('obp', 0)}, SLG {p.get('slg', 0)}, PA {p.get('pa', 0)})"
            for p in top
        )
        parts.append(f"{strategy}: {top_text}")
    if not parts:
        return "No lineup rationale available because no lineup entries were generated."
    return "Top-order placements were driven by batting production metrics. " + " | ".join(parts)


def run():
    """Load Sharks data and generate lineups."""
    # Prefer enriched file (app_stats applied) for most current stats
    team_file = SHARKS_DIR / "team_enriched.json"
    if not team_file.exists():
        team_file = SHARKS_DIR / "team_merged.json"
    if not team_file.exists():
        team_file = SHARKS_DIR / "team.json"
    if not team_file.exists():
        print(f"[LINEUP] No team data found at {team_file}")
        print("[LINEUP] Run the GC scraper first to populate data.")
        return None

    with open(team_file, "r") as f:
        team_data = json.load(f)

    # ── Availability Filter ────────────────────────────────────────────────
    availability_file = SHARKS_DIR / "availability.json"
    if availability_file.exists():
        with open(availability_file, "r") as f:
            availability = json.load(f)
        
        original_roster = team_data.get("roster", [])
        active_roster = []
        for p in original_roster:
            name = f"{p.get('first', '')} {p.get('last', '')}".strip()
            if availability.get(name, True): # Default to active if not in file
                active_roster.append(p)
        
        print(f"[LINEUP] Filtered roster: {len(active_roster)}/{len(original_roster)} players active.")
        team_data["roster"] = active_roster

    # ── Matchup-Aware Strategy ──────────────────────────────────────────────
    matchup = None
    try:
        from practice_gen import _resolve_next_opponent_matchup
        matchup = _resolve_next_opponent_matchup()
        if matchup and not matchup.get("empty"):
            print(f"[LINEUP] Next opponent: {matchup.get('opponent', '?')} — recommending strategy")
    except Exception:
        pass

    results = generate_all_lineups(team_data, matchup=matchup)
    if results.get("recommended_strategy"):
        print(f"[LINEUP] Recommended strategy: {results['recommended_strategy']}")

    output_file = SHARKS_DIR / "lineups.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[LINEUP] Lineups saved to {output_file}")

    try:
        rationale = _build_lineup_rationale(results)
        output_summary = {}
        for strategy, payload in results.items():
            output_summary[strategy] = {
                "compliant": bool(payload.get("compliant", False)),
                "top_3": [
                    {
                        "slot": p.get("slot"),
                        "number": p.get("number"),
                        "name": p.get("name"),
                        "obp": p.get("obp"),
                        "slg": p.get("slg"),
                        "pa": p.get("pa"),
                    }
                    for p in payload.get("lineup", [])[:3]
                ],
            }
        log_decision(
            category="lineup_optimizer",
            input_data={"active_roster_size": len(team_data.get("roster", []))},
            output_data=output_summary,
            rationale=rationale,
        )
    except Exception as e:
        print(f"[LINEUP] Audit log skipped: {e}")

    for strategy, data in results.items():
        print(f"\n{'='*50}")
        print(f"  STRATEGY: {strategy.upper()}")
        if "compliant" not in data:
            print(f"  ERROR: {data.get('error', 'unknown')}")
            continue
        print(f"  Compliant: {'[PASS]' if data['compliant'] else '[FAIL]'}")
        print(f"{'='*50}")
        for entry in data["lineup"]:
            num = entry.get('number') or '?'
            name = entry.get('name') or '—'
            print(f"  {entry['slot']:>2}. #{num:>2} {name:<20} ({entry['role']})")
        if data["violations"]:
            print(f"\n  VIOLATIONS:")
            for v in data["violations"]:
                print(f"     - {v}")

    return results


if __name__ == "__main__":
    run()
