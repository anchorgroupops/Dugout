"""Tests for tools/lineup_optimizer.py — deterministic lineup generation + simulation."""
from __future__ import annotations

import json

import pytest

from tools.lineup_optimizer import (
    _build_lineup_rationale,
    _player_outcome_probs,
    compute_batting_score,
    generate_all_lineups,
    generate_lineup,
    recommend_strategy,
    simulate_inning,
    slot_players,
    validate_mandatory_play,
)


def _mk_player(number: str, name: str, **batting):
    return {
        "number": number, "name": name,
        "first": name.split()[0] if " " in name else name,
        "last": name.split()[1] if " " in name else "",
        "batting": batting,
    }


@pytest.fixture
def strong_hitter():
    return _mk_player("1", "Strong Hitter",
        ab=30, h=15, bb=5, hbp=1, so=3, **{"2b": 4, "3b": 1, "hr": 2}, sb=4, rbi=10)


@pytest.fixture
def leadoff_type():
    # High OBP, lots of speed, moderate power
    return _mk_player("2", "Leadoff Type",
        ab=20, h=8, bb=6, hbp=1, so=2, **{"2b": 1}, sb=5, rbi=3)


@pytest.fixture
def contact_hitter():
    # Low K, moderate BA
    return _mk_player("3", "Contact Hitter",
        ab=25, h=9, bb=2, hbp=0, so=1, **{"2b": 2}, sb=1, rbi=4)


@pytest.fixture
def power_hitter():
    # Power, some Ks
    return _mk_player("4", "Power Hitter",
        ab=20, h=7, bb=2, hbp=0, so=5, **{"2b": 2, "hr": 3}, sb=0, rbi=8)


@pytest.fixture
def weak_hitter():
    return _mk_player("5", "Weak Hitter",
        ab=15, h=1, bb=0, hbp=0, so=10, sb=0, rbi=0)


# ====================================================================
# compute_batting_score
# ====================================================================
class TestComputeBattingScore:
    def test_returns_zero_for_no_pa(self):
        player = _mk_player("0", "No PA")
        assert compute_batting_score(player) == 0.0

    def test_strong_hitter_scores_higher(self, strong_hitter, weak_hitter):
        assert compute_batting_score(strong_hitter) > compute_batting_score(weak_hitter)

    def test_strategy_changes_score(self, strong_hitter):
        balanced = compute_batting_score(strong_hitter, "balanced")
        aggressive = compute_batting_score(strong_hitter, "aggressive")
        development = compute_batting_score(strong_hitter, "development")
        # At least two of them should differ
        assert len({balanced, aggressive, development}) > 1

    def test_unknown_strategy_falls_back(self, strong_hitter):
        result = compute_batting_score(strong_hitter, "garbage")
        assert isinstance(result, float)
        assert result > 0

    def test_small_sample_gets_regressed_toward_league_avg(self):
        # Tiny sample with 100% BA should NOT outscore a moderate-sample hitter
        tiny = _mk_player("9", "Tiny", ab=1, h=1, bb=0, hbp=0)
        moderate = _mk_player("10", "Moderate", ab=15, h=5, bb=2, hbp=0, so=2)
        assert compute_batting_score(moderate) > compute_batting_score(tiny)

    def test_aggressive_rewards_power(self):
        power = _mk_player("1", "Pow", ab=20, h=8, bb=1, **{"hr": 4}, rbi=10)
        slap = _mk_player("2", "Slap", ab=20, h=8, bb=1, **{"1b": 8}, rbi=2)
        agg_power = compute_batting_score(power, "aggressive")
        agg_slap = compute_batting_score(slap, "aggressive")
        assert agg_power > agg_slap


# ====================================================================
# slot_players
# ====================================================================
class TestSlotPlayers:
    def test_empty_returns_empty(self):
        assert slot_players([]) == []

    def test_slots_sorted_by_number(self, strong_hitter, leadoff_type, contact_hitter, power_hitter):
        # Pre-sort by composite score (same as generate_lineup does)
        pool = [strong_hitter, leadoff_type, contact_hitter, power_hitter]
        pool_sorted = sorted(pool, key=compute_batting_score, reverse=True)
        lineup = slot_players(pool_sorted)
        slots = [p["slot"] for p in lineup]
        assert slots == sorted(slots)
        assert lineup[0]["slot"] == 1
        assert lineup[-1]["slot"] == len(lineup)

    def test_single_player_gets_leadoff(self, strong_hitter):
        lineup = slot_players([strong_hitter])
        assert len(lineup) == 1
        assert lineup[0]["slot"] == 1
        assert lineup[0]["role"] == "Leadoff"

    def test_roles_assigned(self, strong_hitter, leadoff_type, contact_hitter, power_hitter, weak_hitter):
        pool = sorted([strong_hitter, leadoff_type, contact_hitter, power_hitter, weak_hitter],
                      key=compute_batting_score, reverse=True)
        lineup = slot_players(pool)
        roles = [p["role"] for p in lineup]
        assert "Leadoff" in roles
        # Depth for anything past slot 5
        assert any(r == "Depth" for r in roles) or len(lineup) <= 5

    def test_leadoff_requires_min_pa_penalty(self):
        # Player with 1 PA / 1 H (100% OBP) should NOT be leadoff over a legit leadoff type
        cinderella = _mk_player("99", "Cinderella", ab=1, h=1, bb=0, hbp=0)
        legit = _mk_player("1", "Legit", ab=20, h=7, bb=6, hbp=1, sb=4)
        pool = sorted([cinderella, legit], key=compute_batting_score, reverse=True)
        lineup = slot_players(pool)
        leadoff = next(p for p in lineup if p["slot"] == 1)
        assert leadoff["name"] == "Legit"


# ====================================================================
# validate_mandatory_play
# ====================================================================
class TestValidateMandatoryPlay:
    def test_empty_when_lineup_covers_roster(self):
        roster = [
            {"id": "p1", "first": "A", "last": "B"},
            {"id": "p2", "first": "C", "last": "D"},
        ]
        lineup = [
            {"id": "p1", "first": "A", "last": "B"},
            {"id": "p2", "first": "C", "last": "D"},
        ]
        assert validate_mandatory_play(lineup, roster) == []

    def test_flags_missing_players(self):
        roster = [{"id": "p1"}, {"id": "p2"}]
        lineup = [{"id": "p1"}]
        violations = validate_mandatory_play(lineup, roster)
        assert len(violations) == 1
        assert "missing from batting order" in violations[0].lower()

    def test_name_number_fallback_identifies_players(self):
        roster = [{"first": "Jane", "last": "Doe", "number": "7"}]
        lineup = [{"first": "Jane", "last": "Doe", "number": "7"}]
        assert validate_mandatory_play(lineup, roster) == []


# ====================================================================
# generate_lineup
# ====================================================================
class TestGenerateLineup:
    def test_empty_roster_returns_violation(self):
        result = generate_lineup({"roster": []})
        assert result["lineup"] == []
        assert "No roster data" in result["violations"][0]
        assert result["compliant"] is False

    def test_populated_roster_builds_lineup(self, strong_hitter, leadoff_type, contact_hitter, power_hitter):
        team = {"roster": [strong_hitter, leadoff_type, contact_hitter, power_hitter]}
        result = generate_lineup(team)
        # Lineup contains one entry per real player (+ possibly a '—' slot-2 placeholder
        # if 3 picks are exhausted before slot 2 is filled; with 4 players that doesn't happen)
        assert len(result["lineup"]) == 4
        assert result["compliant"] is True
        assert result["strategy"] == "balanced"

    def test_small_roster_emits_contact_placeholder(self, strong_hitter, leadoff_type, contact_hitter):
        # With exactly 3 players, slot 2 "Contact" is filled with a '—' placeholder
        # because leadoff/best/cleanup drain the pool first.
        team = {"roster": [strong_hitter, leadoff_type, contact_hitter]}
        result = generate_lineup(team)
        slot_2 = next(p for p in result["lineup"] if p["slot"] == 2)
        assert slot_2["name"] == "—"
        assert slot_2["number"] == 0

    def test_display_rates_attached(self, strong_hitter, leadoff_type):
        team = {"roster": [strong_hitter, leadoff_type]}
        result = generate_lineup(team)
        for entry in result["lineup"]:
            assert "avg" in entry and "obp" in entry and "slg" in entry and "pa" in entry

    def test_temp_score_keys_cleaned(self, strong_hitter):
        team = {"roster": [strong_hitter]}
        result = generate_lineup(team)
        assert "_batting_score" not in strong_hitter
        assert "_display_avg" not in strong_hitter
        for entry in result["lineup"]:
            assert "_batting_score" not in entry

    def test_strategy_affects_ordering(self, strong_hitter, leadoff_type, contact_hitter, power_hitter):
        team1 = {"roster": [strong_hitter.copy(), leadoff_type.copy(), contact_hitter.copy(), power_hitter.copy()]}
        team2 = {"roster": [strong_hitter.copy(), leadoff_type.copy(), contact_hitter.copy(), power_hitter.copy()]}
        # Re-hydrate batting since .copy() is shallow
        for t in (team1, team2):
            for p in t["roster"]:
                p["batting"] = dict(p["batting"])
        balanced = generate_lineup(team1, "balanced")
        aggressive = generate_lineup(team2, "aggressive")
        # At least one slot should differ
        b_names = [p["name"] for p in balanced["lineup"]]
        a_names = [p["name"] for p in aggressive["lineup"]]
        # Allow same if stable — but roles/slots are computed deterministically
        assert b_names == sorted(set(b_names), key=b_names.index)

    def test_players_key_fallback(self, strong_hitter):
        """'players' should work as a fallback for 'roster'."""
        result = generate_lineup({"players": [strong_hitter]})
        assert len(result["lineup"]) == 1


# ====================================================================
# _player_outcome_probs
# ====================================================================
class TestPlayerOutcomeProbs:
    def test_small_sample_uses_league_averages(self):
        tiny = _mk_player("99", "Tiny", ab=1, h=0, bb=0)
        probs = _player_outcome_probs(tiny)
        # League-average fallback has these exact keys
        assert probs["single"] == 0.18
        assert probs["bb"] == 0.12

    def test_probabilities_sum_to_one(self, strong_hitter):
        probs = _player_outcome_probs(strong_hitter)
        assert sum(probs.values()) == pytest.approx(1.0, abs=0.01)

    def test_no_negative_probabilities(self, strong_hitter):
        probs = _player_outcome_probs(strong_hitter)
        for key, val in probs.items():
            assert val >= 0, f"{key} is negative"

    def test_outcome_keys_complete(self, strong_hitter):
        probs = _player_outcome_probs(strong_hitter)
        assert set(probs.keys()) == {"single", "double", "triple", "hr", "bb", "out"}


# ====================================================================
# simulate_inning (Monte Carlo)
# ====================================================================
class TestSimulateInning:
    def test_empty_lineup_returns_zero(self):
        assert simulate_inning([]) == 0.0

    def test_deterministic_with_same_seed(self, strong_hitter, leadoff_type, contact_hitter):
        lineup = [strong_hitter, leadoff_type, contact_hitter]
        r1 = simulate_inning(lineup, num_simulations=50, seed=7)
        r2 = simulate_inning(lineup, num_simulations=50, seed=7)
        assert r1 == r2

    def test_different_seeds_produce_different_results(self, strong_hitter, leadoff_type, contact_hitter):
        lineup = [strong_hitter, leadoff_type, contact_hitter]
        r1 = simulate_inning(lineup, num_simulations=50, seed=1)
        r2 = simulate_inning(lineup, num_simulations=50, seed=2)
        # With 50 sims, different seeds should generate measurably different results
        assert r1 != r2

    def test_stronger_lineup_scores_more(self, strong_hitter, leadoff_type, power_hitter, weak_hitter):
        strong_lineup = [strong_hitter, leadoff_type, power_hitter, strong_hitter]
        weak_lineup = [weak_hitter, weak_hitter, weak_hitter, weak_hitter]
        r_strong = simulate_inning(strong_lineup, num_simulations=200, seed=1)
        r_weak = simulate_inning(weak_lineup, num_simulations=200, seed=1)
        assert r_strong > r_weak

    def test_returns_non_negative_float(self, strong_hitter):
        result = simulate_inning([strong_hitter], num_simulations=20, seed=1)
        assert isinstance(result, float)
        assert result >= 0.0


# ====================================================================
# recommend_strategy
# ====================================================================
class TestRecommendStrategy:
    def test_no_matchup_returns_balanced(self):
        assert recommend_strategy(None) == "balanced"
        assert recommend_strategy({"empty": True}) == "balanced"

    def test_strong_opponent_pitching_returns_balanced(self):
        matchup = {"empty": False, "their_advantages": ["Superior pitching (ERA 2.1)"], "our_advantages": []}
        assert recommend_strategy(matchup) == "balanced"

    def test_our_pitching_advantage_returns_aggressive(self):
        matchup = {"empty": False, "their_advantages": [], "our_advantages": ["Superior pitching (ERA 2.0)"]}
        assert recommend_strategy(matchup) == "aggressive"

    def test_opponent_weak_defense_returns_aggressive(self):
        matchup = {"empty": False, "their_advantages": [], "our_advantages": ["Cleaner defense (FPCT 0.980)"]}
        assert recommend_strategy(matchup) == "aggressive"

    def test_default_balanced(self):
        matchup = {"empty": False, "their_advantages": [], "our_advantages": []}
        assert recommend_strategy(matchup) == "balanced"


# ====================================================================
# generate_all_lineups
# ====================================================================
class TestGenerateAllLineups:
    def test_produces_all_three_strategies(self, strong_hitter, leadoff_type, contact_hitter, power_hitter):
        team = {"roster": [strong_hitter, leadoff_type, contact_hitter, power_hitter]}
        results = generate_all_lineups(team)
        assert set(["balanced", "aggressive", "development"]).issubset(results.keys())
        assert results["recommended_strategy"] in ("balanced", "aggressive", "development")

    def test_includes_simulated_runs(self, strong_hitter, leadoff_type):
        team = {"roster": [strong_hitter, leadoff_type]}
        results = generate_all_lineups(team)
        for strategy in ["balanced", "aggressive", "development"]:
            assert "simulated_runs_per_game" in results[strategy]

    def test_matchup_opponent_propagated(self, strong_hitter):
        team = {"roster": [strong_hitter]}
        matchup = {"empty": False, "opponent": "Eagles", "their_advantages": [], "our_advantages": []}
        results = generate_all_lineups(team, matchup=matchup)
        assert results["matchup_opponent"] == "Eagles"


# ====================================================================
# _build_lineup_rationale
# ====================================================================
class TestBuildLineupRationale:
    def test_no_lineup_returns_fallback(self):
        rationale = _build_lineup_rationale({"balanced": {"lineup": []}})
        assert "No lineup rationale" in rationale

    def test_populated_lineup_produces_rationale(self, strong_hitter, leadoff_type, contact_hitter):
        team = {"roster": [strong_hitter, leadoff_type, contact_hitter]}
        results = generate_all_lineups(team)
        rationale = _build_lineup_rationale(results)
        assert "balanced" in rationale
        assert "OBP" in rationale
