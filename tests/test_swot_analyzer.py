"""Tests for tools/swot_analyzer.py — deterministic SWOT classification."""
from __future__ import annotations

import json

import pytest

from tools.swot_analyzer import (
    _generate_basic_matchups,
    _innings_to_float,
    _n,
    _parse_number,
    _safe_div,
    _swot_rationale_from_team,
    _team_aggregates,
    analyze_matchup,
    analyze_player,
    analyze_team,
    classify_baserunning,
    classify_fielding,
    classify_hitting,
    classify_pitching,
    compute_derived_stats,
    load_team,
)


# ====================================================================
# private helpers
# ====================================================================
class TestSafeDiv:
    def test_normal(self):
        assert _safe_div(4, 2) == 2.0

    def test_zero_denominator(self):
        assert _safe_div(5, 0) == 0.0
        assert _safe_div(5, 0, default=-1) == -1

    def test_negative_denominator_uses_default(self):
        assert _safe_div(1, -1) == 0.0  # denom > 0 check


class TestParseNumber:
    @pytest.mark.parametrize("val,expected", [
        (None, 0.0), ("", 0.0), ("-", 0.0), ("—", 0.0), ("N/A", 0.0),
        (5, 5.0), (3.14, 3.14), (".300", 0.300), ("80%", 80.0), ("garbage", 0.0),
    ])
    def test_various_inputs(self, val, expected):
        assert _parse_number(val) == expected

    def test_default_override(self):
        assert _parse_number(None, default=42) == 42

    def test_unhandled_type_returns_default(self):
        assert _parse_number([1, 2, 3], default=7) == 7


class TestInningsToFloat:
    def test_two_outs(self):
        assert _innings_to_float("4.2") == pytest.approx(14 / 3)

    def test_whole(self):
        assert _innings_to_float(5) == 5.0

    def test_none(self):
        assert _innings_to_float(None) == 0.0

    def test_empty(self):
        assert _innings_to_float("") == 0.0


class TestNone:
    def test_n_none_returns_zero(self):
        assert _n(None) == 0

    def test_n_value_passthrough(self):
        assert _n(5) == 5
        assert _n(0.5) == 0.5


# ====================================================================
# compute_derived_stats
# ====================================================================
class TestComputeDerivedStats:
    def test_full_hitting_computation(self):
        player = {
            "stats": {
                "hitting": {
                    "ab": 10, "h": 4, "bb": 1, "hbp": 0, "k": 2,
                    "doubles": 1, "triples": 0, "hr": 1, "sb": 1, "cs": 0,
                }
            }
        }
        d = compute_derived_stats(player)
        # BA = 4/10, PA=11, OBP=(4+1+0)/11
        assert d["hitting"]["ba"] == 0.400
        assert d["hitting"]["pa"] == 11
        assert d["hitting"]["obp"] == round(5 / 11, 3)
        # singles = 4 - 1 - 0 - 1 = 2; TB = 2 + 2 + 0 + 4 = 8
        assert d["hitting"]["total_bases"] == 8
        assert d["hitting"]["slg"] == round(8 / 10, 3)

    def test_batting_source_fallback(self):
        """batting dict should be used when stats.hitting missing."""
        player = {"batting": {"ab": 10, "h": 3}}
        d = compute_derived_stats(player)
        assert d["hitting"]["ba"] == 0.300

    def test_pitching_era(self):
        player = {"pitching": {"ip": "7", "er": 3, "bb": 2, "h": 6, "so": 5}}
        d = compute_derived_stats(player)
        assert d["pitching"]["era"] == 3.00  # (3 * 7) / 7
        assert d["pitching"]["whip"] == round(8 / 7, 2)

    def test_fielding_fpct_perfect(self):
        player = {"fielding": {"po": 5, "a": 2, "e": 0}}
        d = compute_derived_stats(player)
        assert d["fielding"]["fielding_pct"] == 1.000

    def test_baserunning_success_rate(self):
        player = {"stats": {"hitting": {"sb": 3, "cs": 1}}}
        d = compute_derived_stats(player)
        assert d["baserunning"]["sb_success_rate"] == 0.750

    def test_empty_player_all_zeros(self):
        d = compute_derived_stats({})
        assert d["hitting"]["ba"] == 0.0
        assert d["pitching"]["era"] == 0.0
        assert d["fielding"]["fielding_pct"] == 0.0
        assert d["baserunning"]["sb_success_rate"] == 0.0

    def test_no_sb_no_cs_returns_zero(self):
        d = compute_derived_stats({"stats": {"hitting": {"sb": 0, "cs": 0}}})
        assert d["baserunning"]["sb_success_rate"] == 0.0


# ====================================================================
# classify_hitting
# ====================================================================
class TestClassifyHitting:
    def _derived(self, **hitting_overrides):
        base = {
            "hitting": {
                "ba": 0.300, "obp": 0.400, "slg": 0.400, "ops": 0.800,
                "k_rate": 0.20, "bb_rate": 0.10, "pa": 20, "total_bases": 10,
            }
        }
        base["hitting"].update(hitting_overrides)
        return base

    def test_below_min_pa_no_classification(self):
        d = self._derived(pa=3, ba=0.500)
        assert classify_hitting(d) == ([], [])

    def test_elite_hitting_flagged_strong(self):
        d = self._derived(ba=0.400, obp=0.500, slg=0.600, ops=1.100, pa=20)
        strengths, weaknesses = classify_hitting(d)
        assert len(strengths) >= 4
        assert any("High batting average" in s for s in strengths)
        assert weaknesses == []

    def test_poor_hitting_flagged_weak(self):
        d = self._derived(ba=0.150, obp=0.200, slg=0.200, ops=0.400, k_rate=0.45, bb_rate=0.02)
        strengths, weaknesses = classify_hitting(d)
        assert len(weaknesses) >= 4

    def test_middle_stats_not_flagged(self):
        d = self._derived(ba=0.250, obp=0.320, slg=0.320, ops=0.640, k_rate=0.30, bb_rate=0.08)
        strengths, weaknesses = classify_hitting(d)
        assert strengths == [] and weaknesses == []

    def test_low_k_rate_is_strength(self):
        d = self._derived(k_rate=0.15)
        strengths, _ = classify_hitting(d)
        assert any("Low strikeout rate" in s for s in strengths)

    def test_high_bb_rate_is_strength(self):
        d = self._derived(bb_rate=0.15)
        strengths, _ = classify_hitting(d)
        assert any("plate discipline" in s.lower() for s in strengths)


# ====================================================================
# classify_pitching
# ====================================================================
class TestClassifyPitching:
    def _derived(self, **overrides):
        base = {"pitching": {"era": 4.00, "whip": 1.50, "k_per_ip": 0.80, "bb_per_ip": 0.50}}
        base["pitching"].update(overrides)
        return base

    def test_below_min_ip_no_classification(self):
        d = self._derived()
        assert classify_pitching(d, raw_ip=1.0) == ([], [])

    def test_dominant_pitching(self):
        d = self._derived(era=2.0, whip=1.0, k_per_ip=1.2, bb_per_ip=0.2)
        strengths, _ = classify_pitching(d, raw_ip=5.0)
        assert len(strengths) == 4

    def test_weak_pitching(self):
        d = self._derived(era=7.0, whip=2.0, k_per_ip=0.3, bb_per_ip=1.0)
        _, weaknesses = classify_pitching(d, raw_ip=5.0)
        assert len(weaknesses) == 4

    def test_middle_pitching(self):
        d = self._derived(era=4.0, whip=1.5, k_per_ip=0.75, bb_per_ip=0.5)
        strengths, weaknesses = classify_pitching(d, raw_ip=5.0)
        assert strengths == [] and weaknesses == []


# ====================================================================
# classify_fielding / classify_baserunning
# ====================================================================
class TestClassifyFielding:
    def test_reliable(self):
        s, w = classify_fielding({"fielding": {"fielding_pct": 0.980}})
        assert s and not w

    def test_error_prone(self):
        s, w = classify_fielding({"fielding": {"fielding_pct": 0.850}})
        assert w and not s

    def test_middle(self):
        s, w = classify_fielding({"fielding": {"fielding_pct": 0.920}})
        assert not s and not w


class TestClassifyBaserunning:
    def test_effective(self):
        s, w = classify_baserunning({"baserunning": {"sb_success_rate": 0.80}})
        assert s and not w

    def test_inefficient(self):
        s, w = classify_baserunning({"baserunning": {"sb_success_rate": 0.40}})
        assert w and not s

    def test_middle(self):
        s, w = classify_baserunning({"baserunning": {"sb_success_rate": 0.60}})
        assert not s and not w


# ====================================================================
# analyze_player
# ====================================================================
class TestAnalyzePlayer:
    def test_produces_full_swot_structure(self, sample_player):
        result = analyze_player(sample_player)
        assert result["name"] == "Jane Doe"
        assert set(result["swot"].keys()) == {"strengths", "weaknesses", "opportunities", "threats"}
        # SWOT values capped at 3 items
        for section in result["swot"].values():
            assert len(section) <= 3

    def test_builds_name_from_first_last(self):
        player = {"first": "Bob", "last": "Jones", "batting": {"ab": 10, "h": 3}}
        result = analyze_player(player)
        assert result["name"] == "Bob Jones"

    def test_defaults_to_unknown_name(self):
        result = analyze_player({})
        assert result["name"] == "Unknown"

    def test_limited_pa_adds_opportunity(self):
        player = {"batting": {"ab": 5, "h": 2}}
        result = analyze_player(player)
        opps = " ".join(result["swot"]["opportunities"]).lower()
        assert "plate appearances" in opps or "sample size" in opps

    def test_high_k_rate_adds_threat(self):
        player = {"batting": {"ab": 20, "h": 3, "k": 10, "bb": 1}}
        result = analyze_player(player)
        threats = " ".join(result["swot"]["threats"]).lower()
        assert "strikeout" in threats

    def test_advanced_qab_high_is_strength(self):
        player = {
            "batting": {"ab": 20, "h": 6, "bb": 3, "pa": 23},
            "batting_advanced": {"qab": 15, "pa": 23, "qab_pct": 0.65},
        }
        result = analyze_player(player)
        strengths = " ".join(result["swot"]["strengths"]).lower()
        assert "quality at-bat" in strengths


# ====================================================================
# analyze_team
# ====================================================================
class TestAnalyzeTeam:
    def test_empty_roster(self):
        result = analyze_team({"team_name": "Empty", "roster": []})
        assert result["team_name"] == "Empty"
        assert result["player_analyses"] == []
        assert "Insufficient data" in result["team_swot"]["strengths"][0]

    def test_team_aggregates_from_players(self, sample_roster):
        result = analyze_team({"team_name": "Sharks", "roster": sample_roster})
        assert result["team_name"] == "Sharks"
        assert len(result["player_analyses"]) == 3
        assert isinstance(result["team_swot"]["strengths"], list)
        assert isinstance(result["team_swot"]["threats"], list)


# ====================================================================
# _team_aggregates
# ====================================================================
class TestTeamAggregates:
    def test_sharks_merged_roster(self, sample_roster):
        agg = _team_aggregates({"roster": sample_roster})
        assert agg["roster_size"] == 3
        assert agg["batting"]["ab"] > 0
        assert agg["batting"]["h"] > 0
        assert agg["batting"]["avg"] is not None

    def test_empty_team(self):
        agg = _team_aggregates({"roster": []})
        assert agg["roster_size"] == 0
        assert agg["batting"]["avg"] is None
        assert agg["batting"]["ab"] == 0

    def test_top_level_batting_stats_fallback(self):
        team = {
            "roster": [],  # no per-player batting
            "batting_stats": [
                {"ab": 10, "h": 3, "bb": 1},
                {"ab": 8, "h": 4, "bb": 0},
            ],
        }
        agg = _team_aggregates(team)
        assert agg["batting"]["ab"] == 18
        assert agg["batting"]["h"] == 7

    def test_team_totals_preferred(self):
        team = {
            "roster": [{"batting": {"ab": 10, "h": 1}}],  # would give avg=0.100
            "team_totals": {"batting": {"ab": 20, "h": 8, "bb": 2, "hbp": 0}},
        }
        agg = _team_aggregates(team)
        assert agg["batting"]["ab"] == 20
        assert agg["batting"]["h"] == 8
        assert agg["batting"]["avg"] == 0.400  # from team_totals, not roster

    def test_fielding_aggregates(self):
        team = {
            "roster": [
                {"fielding": {"po": 5, "a": 2, "e": 0}},
                {"fielding": {"po": 3, "a": 1, "e": 1}},
            ]
        }
        agg = _team_aggregates(team)
        assert agg["fielding"]["errors"] == 1
        assert agg["fielding"]["fpct"] == round(11 / 12, 3)

    def test_pitching_aggregates(self):
        team = {
            "roster": [
                {"pitching": {"ip": "7", "er": 2, "bb": 1, "h": 5, "so": 6}},
                {"pitching": {"ip": "5", "er": 3, "bb": 2, "h": 4, "so": 3}},
            ]
        }
        agg = _team_aggregates(team)
        assert agg["pitching"]["ip"] == 12.0
        assert agg["pitching"]["era"] is not None

    def test_advanced_stats_returned_none_without_real_data(self, sample_roster):
        """When roster has no QAB/C% fields, advanced metrics should be None."""
        agg = _team_aggregates({"roster": sample_roster})
        assert agg["batting_advanced"]["qab_pct"] is None
        assert agg["batting_advanced"]["c_pct"] is None

    def test_advanced_stats_returned_when_real_data_present(self):
        team = {
            "roster": [
                {"batting": {"ab": 10, "h": 3, "pa": 12}, "batting_advanced": {"qab": 6, "pa": 12, "c_pct": 0.55}},
                {"batting": {"ab": 12, "h": 4, "pa": 14}, "batting_advanced": {"qab": 7, "pa": 14, "c_pct": 0.60}},
            ]
        }
        agg = _team_aggregates(team)
        assert agg["batting_advanced"]["qab_pct"] is not None


# ====================================================================
# _generate_basic_matchups
# ====================================================================
class TestGenerateBasicMatchups:
    def test_high_walk_rate_flagged(self):
        them = {"batting": {"bb": 6, "pa": 20, "ab": 14, "k": 2, "sb": 0, "obp": 0.30, "avg": 0.20}}
        insights = _generate_basic_matchups({}, them)
        assert any("walks" in i.lower() for i in insights)

    def test_no_data_fallback_message(self):
        insights = _generate_basic_matchups({}, {"batting": {}})
        assert any("limited data" in i.lower() for i in insights)

    def test_high_avg_flagged(self):
        them = {"batting": {"bb": 0, "pa": 20, "ab": 18, "k": 0, "sb": 0, "obp": 0.3, "avg": 0.400}}
        insights = _generate_basic_matchups({}, them)
        assert any("solid contact" in i.lower() or "easy to hit" in i.lower() for i in insights)

    def test_stolen_bases_flagged(self):
        them = {"batting": {"bb": 0, "pa": 20, "ab": 20, "k": 0, "sb": 3, "obp": 0.3, "avg": 0.2}}
        insights = _generate_basic_matchups({}, them)
        assert any("stolen bases" in i.lower() for i in insights)

    def test_high_obp_flagged(self):
        them = {"batting": {"bb": 5, "pa": 20, "ab": 15, "k": 0, "sb": 0, "obp": 0.500, "avg": 0.200}}
        insights = _generate_basic_matchups({}, them)
        assert any("on-base" in i.lower() for i in insights)


# ====================================================================
# analyze_matchup
# ====================================================================
class TestAnalyzeMatchup:
    def test_insufficient_opponent_data_returns_empty(self):
        us = {"team_name": "Sharks", "roster": [{"batting": {"ab": 20, "h": 8}}]}
        them = {"team_name": "Opp", "roster": [{"batting": {"ab": 2, "h": 0}}]}
        result = analyze_matchup(us, them)
        assert result["empty"] is True
        assert result["reason"] == "insufficient_data"
        assert result["our_advantages"] == []

    def test_meaningful_sample_generates_advantages(self):
        us = {
            "team_name": "Sharks",
            "roster": [
                {"batting": {"ab": 15, "h": 6, "bb": 2, "hbp": 0, "k": 1, "sb": 1, "2b": 2, "hr": 1, "rbi": 3, "r": 2}},
                {"batting": {"ab": 14, "h": 5, "bb": 2, "hbp": 0, "k": 2, "sb": 0, "2b": 1, "rbi": 2, "r": 1}},
            ],
        }
        them = {
            "team_name": "Opp",
            "roster": [
                {"batting": {"ab": 15, "h": 2, "bb": 1, "hbp": 0, "k": 5, "sb": 0}},
                {"batting": {"ab": 14, "h": 2, "bb": 0, "hbp": 0, "k": 6, "sb": 0}},
            ],
        }
        result = analyze_matchup(us, them)
        assert result["empty"] is False
        # We have clearly higher avg; should appear as our advantage
        assert any("batting average" in a.lower() for a in result["our_advantages"])
        assert result["batting_sample_limited"] is False

    def test_limited_ab_sample_suppresses_false_advantages(self):
        # their_pa computed as ab + bb + hbp inside _team_aggregates; must be >= 10 to avoid empty gate,
        # but their_ab must be < 10 to trigger batting_sample_limited.
        us = {"roster": [{"batting": {"ab": 20, "h": 8, "bb": 2}}]}
        them = {"roster": [{"batting": {"ab": 8, "h": 0, "bb": 3}}]}  # pa=11, ab=8
        result = analyze_matchup(us, them)
        assert result["empty"] is False
        assert result["batting_sample_limited"] is True
        assert all("batting average" not in a.lower() for a in result["our_advantages"])

    def test_recommendation_always_string(self):
        us = {"roster": [{"batting": {"ab": 15, "h": 5, "bb": 2}}]}
        them = {"roster": [{"batting": {"ab": 15, "h": 5, "bb": 2}}]}
        result = analyze_matchup(us, them)
        assert isinstance(result["recommendation"], str)

    def test_names_propagate(self):
        us = {"team_name": "Sharks", "roster": [{"batting": {"ab": 12, "h": 4}}]}
        them = {"team_name": "Eagles", "roster": [{"batting": {"ab": 12, "h": 4}}]}
        result = analyze_matchup(us, them)
        assert result["our_team"] == "Sharks"
        assert result["opponent"] == "Eagles"


# ====================================================================
# _swot_rationale_from_team
# ====================================================================
class TestSwotRationale:
    def test_no_players_returns_fallback(self):
        rationale = _swot_rationale_from_team({"player_analyses": []})
        assert "No player analyses" in rationale

    def test_with_players_produces_signals(self, sample_roster):
        result = analyze_team({"team_name": "Sharks", "roster": sample_roster})
        rationale = _swot_rationale_from_team(result)
        assert "OPS" in rationale
        assert "K%" in rationale
        assert "FPCT" in rationale


# ====================================================================
# load_team
# ====================================================================
class TestLoadTeam:
    def test_returns_none_when_missing(self, tmp_path):
        assert load_team(tmp_path) is None

    def test_prefers_enriched(self, tmp_path):
        enriched = tmp_path / "team_enriched.json"
        plain = tmp_path / "team.json"
        enriched.write_text(json.dumps({"team_name": "Enriched"}))
        plain.write_text(json.dumps({"team_name": "Plain"}))
        assert load_team(tmp_path)["team_name"] == "Enriched"

    def test_falls_back_to_plain(self, tmp_path):
        (tmp_path / "team.json").write_text(json.dumps({"team_name": "Plain"}))
        assert load_team(tmp_path)["team_name"] == "Plain"

    def test_prefer_merged_uses_merged(self, tmp_path):
        (tmp_path / "team.json").write_text(json.dumps({"team_name": "Plain"}))
        (tmp_path / "team_merged.json").write_text(json.dumps({"team_name": "Merged"}))
        assert load_team(tmp_path, prefer_merged=True)["team_name"] == "Merged"

    def test_prefer_merged_falls_back(self, tmp_path):
        (tmp_path / "team.json").write_text(json.dumps({"team_name": "Plain"}))
        assert load_team(tmp_path, prefer_merged=True)["team_name"] == "Plain"
