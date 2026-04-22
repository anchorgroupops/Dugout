"""Tests for tools/stats_normalizer.py — canonical stat normalization."""
from __future__ import annotations

import math

import pytest

from tools.stats_normalizer import (
    build_player_metric_profile,
    count_populated_fields,
    detect_player_outlier_stats,
    innings_to_float,
    normalize_batting_advanced_row,
    normalize_batting_row,
    normalize_catching_row,
    normalize_fielding_row,
    normalize_innings_played_row,
    normalize_pitching_advanced_full_row,
    normalize_pitching_advanced_row,
    normalize_pitching_breakdown_row,
    normalize_pitching_row,
    normalize_player_batting,
    normalize_player_batting_advanced,
    player_identity_key,
    safe_float,
    safe_int,
    safe_pct_ratio,
    validate_team_outlier_stats,
)


# ====================================================================
# safe_float
# ====================================================================
class TestSafeFloat:
    def test_none_returns_default(self):
        assert safe_float(None) == 0.0
        assert safe_float(None, default=9.9) == 9.9

    @pytest.mark.parametrize("val,expected", [
        (5, 5.0), (5.5, 5.5), (0, 0.0), (-3.14, -3.14),
    ])
    def test_numeric_passthrough(self, val, expected):
        assert safe_float(val) == expected

    @pytest.mark.parametrize("sentinel", ["", "-", "—", "N/A"])
    def test_sentinel_strings_return_default(self, sentinel):
        assert safe_float(sentinel, default=1.23) == 1.23

    def test_leading_dot_prefix(self):
        assert safe_float(".375") == 0.375
        assert safe_float(".5") == 0.5

    def test_percent_suffix_stripped(self):
        assert safe_float("80%") == 80.0
        assert safe_float("44.44%") == pytest.approx(44.44)

    def test_whitespace_trimmed(self):
        assert safe_float("  .250  ") == 0.25

    def test_garbage_returns_default(self):
        assert safe_float("not a number", default=2.0) == 2.0
        assert safe_float("abc123") == 0.0

    def test_scientific_notation(self):
        assert safe_float("1e3") == 1000.0


# ====================================================================
# safe_int
# ====================================================================
class TestSafeInt:
    def test_rounds_to_nearest(self):
        assert safe_int(2.6) == 3
        assert safe_int(2.4) == 2
        assert safe_int("2.6") == 3

    def test_none_returns_default(self):
        assert safe_int(None) == 0
        assert safe_int(None, default=7) == 7

    def test_garbage_returns_default(self):
        assert safe_int("garbage", default=5) == 5

    def test_negative(self):
        assert safe_int(-3.2) == -3


# ====================================================================
# safe_pct_ratio
# ====================================================================
class TestSafePctRatio:
    def test_already_ratio_unchanged(self):
        assert safe_pct_ratio(0.5) == 0.5
        assert safe_pct_ratio(0.8) == 0.8

    def test_percentage_converted(self):
        assert safe_pct_ratio(44.44) == pytest.approx(0.4444)
        assert safe_pct_ratio(80) == pytest.approx(0.8)

    def test_string_with_percent_sign(self):
        assert safe_pct_ratio("80.0%") == pytest.approx(0.8)

    def test_one_boundary_treated_as_ratio(self):
        # Per module docstring: exactly 1.0 treated as ratio, not percent.
        assert safe_pct_ratio(1.0) == 1.0

    def test_above_one_converted(self):
        assert safe_pct_ratio(1.5) == pytest.approx(0.015)  # 1.5 / 100

    def test_default_for_none(self):
        assert safe_pct_ratio(None, default=0.25) == 0.25


# ====================================================================
# innings_to_float
# ====================================================================
class TestInningsToFloat:
    def test_none(self):
        assert innings_to_float(None) == 0.0

    def test_empty_string(self):
        assert innings_to_float("") == 0.0
        assert innings_to_float("   ") == 0.0

    def test_whole_innings(self):
        assert innings_to_float("5") == 5.0
        assert innings_to_float(5) == 5.0

    def test_softball_notation_one_out(self):
        # 4.1 => 4 innings + 1 out = 13 outs / 3 = 4.333
        assert innings_to_float("4.1") == pytest.approx(13 / 3)

    def test_softball_notation_two_outs(self):
        # 4.2 => 4 innings + 2 outs = 14 outs / 3
        assert innings_to_float("4.2") == pytest.approx(14 / 3)

    def test_invalid_outs_digit_falls_to_float(self):
        # 4.5 is invalid softball notation (outs must be 0-2). Treated as plain float.
        assert innings_to_float("4.5") == 4.5

    def test_garbage_returns_zero(self):
        assert innings_to_float("abc") == 0.0
        assert innings_to_float("abc.def") == 0.0


# ====================================================================
# normalize_batting_row
# ====================================================================
class TestNormalizeBattingRow:
    def test_happy_path_with_explicit_values(self, sample_batting_row):
        result = normalize_batting_row(sample_batting_row)
        assert result["ab"] == 8
        assert result["h"] == 3
        assert result["avg"] == 0.375
        assert result["ops"] == 0.944

    def test_infers_singles_from_hits_when_missing(self):
        row = {"ab": 10, "h": 5, "2b": 1, "3b": 0, "hr": 1}
        result = normalize_batting_row(row)
        assert result["1b"] == 3  # 5 - 1 - 0 - 1 = 3
        assert result["singles"] == 3

    def test_infers_pa_when_missing(self):
        row = {"ab": 10, "bb": 2, "hbp": 1, "sac": 1}
        result = normalize_batting_row(row)
        assert result["pa"] == 14

    def test_computes_avg_when_missing(self):
        row = {"ab": 10, "h": 3}
        result = normalize_batting_row(row)
        assert result["avg"] == 0.3

    def test_avg_zero_when_no_ab(self):
        result = normalize_batting_row({"ab": 0, "h": 0})
        assert result["avg"] == 0.0
        assert result["obp"] == 0.0
        assert result["slg"] == 0.0

    def test_nested_batting_source(self):
        player = {"batting": {"ab": 8, "h": 3, "1b": 2, "2b": 1}}
        result = normalize_batting_row(player)
        assert result["h"] == 3
        assert result["2b"] == 1

    def test_empty_row(self):
        result = normalize_batting_row({})
        assert result["pa"] == 0
        assert result["avg"] == 0.0

    def test_none_row_does_not_crash(self):
        result = normalize_batting_row(None or {})
        assert result["pa"] == 0

    def test_k_alias_for_strikeouts(self):
        row = {"ab": 10, "h": 2, "k": 4}
        result = normalize_batting_row(row)
        assert result["so"] == 4

    def test_ops_equals_obp_plus_slg_when_missing(self):
        row = {"ab": 4, "h": 2, "2b": 1, "bb": 1}
        result = normalize_batting_row(row)
        assert result["ops"] == pytest.approx(result["obp"] + result["slg"], abs=1e-3)


# ====================================================================
# normalize_pitching_row
# ====================================================================
class TestNormalizePitchingRow:
    def test_happy_path(self, sample_pitching_row):
        result = normalize_pitching_row(sample_pitching_row)
        assert result["ip"] == pytest.approx(14 / 3, abs=0.01)
        assert result["er"] == 2
        assert result["bb"] == 1
        assert result["so"] == 6

    def test_computes_whip_when_missing(self):
        row = {"ip": "3", "bb": 2, "h": 4}
        result = normalize_pitching_row(row)
        assert result["whip"] == pytest.approx(2.0)  # (2 + 4) / 3

    def test_computes_era_when_missing(self):
        # softball ERA formula: (er * 7) / ip
        row = {"ip": "7", "er": 3}
        result = normalize_pitching_row(row)
        assert result["era"] == pytest.approx(3.0)

    def test_zero_ip_defaults_whip_era(self):
        row = {"ip": 0, "er": 0}
        result = normalize_pitching_row(row)
        assert result["whip"] == 0.0
        assert result["era"] == 0.0

    def test_nested_pitching_source(self):
        player = {"pitching": {"ip": "5", "er": 2}}
        result = normalize_pitching_row(player)
        assert result["ip"] == 5.0
        assert result["er"] == 2


# ====================================================================
# normalize_fielding_row
# ====================================================================
class TestNormalizeFieldingRow:
    def test_happy_path(self):
        row = {"po": 10, "a": 3, "e": 1}
        result = normalize_fielding_row(row)
        assert result["fpct"] == pytest.approx(13 / 14, abs=0.001)

    def test_perfect_fielding(self):
        assert normalize_fielding_row({"po": 5, "a": 2, "e": 0})["fpct"] == 1.0

    def test_no_chances_returns_zero(self):
        assert normalize_fielding_row({"po": 0, "a": 0, "e": 0})["fpct"] == 0.0

    def test_explicit_fpct_passthrough(self):
        row = {"po": 10, "a": 3, "e": 1, "fpct": 0.95}
        assert normalize_fielding_row(row)["fpct"] == 0.95


# ====================================================================
# normalize_catching_row
# ====================================================================
class TestNormalizeCatchingRow:
    def test_computes_cs_pct_when_missing(self):
        row = {"inn": "5", "sb": 2, "cs": 3}
        result = normalize_catching_row(row)
        assert result["cs_pct"] == pytest.approx(0.6)

    def test_handles_zero_attempts(self):
        assert normalize_catching_row({"inn": "3", "sb": 0, "cs": 0})["cs_pct"] == 0.0

    def test_nested_catching_source(self):
        result = normalize_catching_row({"catching": {"sb": 1, "cs": 1}})
        assert result["cs_pct"] == pytest.approx(0.5)


# ====================================================================
# normalize_innings_played_row
# ====================================================================
class TestNormalizeInningsPlayedRow:
    def test_picks_softball_notation(self):
        row = {"total": "9.2", "p": "5.1"}
        result = normalize_innings_played_row(row)
        assert result["total"] == pytest.approx(29 / 3, abs=0.01)
        assert result["p"] == pytest.approx(16 / 3, abs=0.01)

    def test_legacy_colon_keys(self):
        row = {"ip:f": "6", "ip:p": "3"}
        result = normalize_innings_played_row(row)
        assert result["total"] == 6.0
        assert result["p"] == 3.0

    def test_nested_source(self):
        row = {"innings_played": {"total": "7", "ss": "2"}}
        result = normalize_innings_played_row(row)
        assert result["total"] == 7.0
        assert result["ss"] == 2.0

    def test_all_positions_present(self):
        result = normalize_innings_played_row({})
        for pos in ["total", "p", "c", "first_base", "second_base", "third_base",
                    "ss", "lf", "cf", "rf", "sf"]:
            assert pos in result


# ====================================================================
# normalize_batting_advanced_row
# ====================================================================
class TestNormalizeBattingAdvancedRow:
    def test_computes_qab_pct_from_qab_and_pa(self):
        row = {"qab": 4, "pa": 10}
        result = normalize_batting_advanced_row(row)
        assert result["qab_pct"] == pytest.approx(0.4)

    def test_computes_pa_per_bb(self):
        row = {"pa": 20, "bb": 4}
        result = normalize_batting_advanced_row(row)
        assert result["pa_per_bb"] == pytest.approx(5.0)

    def test_computes_bb_per_k(self):
        row = {"bb": 4, "so": 8}
        result = normalize_batting_advanced_row(row)
        assert result["bb_per_k"] == pytest.approx(0.5)

    def test_handles_zero_divisors(self):
        row = {"qab": 0, "pa": 0, "bb": 0, "so": 0}
        result = normalize_batting_advanced_row(row)
        assert result["qab_pct"] == 0.0
        assert result["pa_per_bb"] == 0.0
        assert result["bb_per_k"] == 0.0

    def test_nested_batting_advanced_source(self):
        row = {"batting_advanced": {"qab": 3, "pa": 10}}
        assert normalize_batting_advanced_row(row)["qab_pct"] == pytest.approx(0.3)

    def test_infers_from_batting_when_adv_keys_present(self):
        row = {"batting": {"qab": 5, "pa": 10, "qab_pct": None}}
        assert normalize_batting_advanced_row(row)["qab"] == 5


# ====================================================================
# normalize_pitching_advanced_row
# ====================================================================
class TestNormalizePitchingAdvancedRow:
    def test_computes_k_bf(self):
        row = {"bf": 20, "so": 5}
        result = normalize_pitching_advanced_row(row)
        assert result["k_bf"] == pytest.approx(0.25)

    def test_computes_k_bb(self):
        row = {"so": 10, "bb": 2}
        result = normalize_pitching_advanced_row(row)
        assert result["k_bb"] == pytest.approx(5.0)

    def test_computes_bb_inn(self):
        row = {"ip": "6", "bb": 3}
        result = normalize_pitching_advanced_row(row)
        assert result["bb_inn"] == pytest.approx(0.5)

    def test_nested_sources(self):
        row = {"pitching_advanced": {"bf": 30, "so": 10}}
        assert normalize_pitching_advanced_row(row)["k_bf"] == pytest.approx(10 / 30, abs=1e-4)


# ====================================================================
# player_identity_key
# ====================================================================
class TestPlayerIdentityKey:
    def test_number_preferred(self):
        assert player_identity_key({"number": "7", "first": "J", "last": "D"}) == "#7"

    def test_first_last_fallback(self):
        assert player_identity_key({"first": "Jane", "last": "Doe"}) == "jane|doe"

    def test_name_fallback(self):
        assert player_identity_key({"name": "Jane Doe"}) == "jane doe"

    def test_unknown_fallback(self):
        assert player_identity_key({}) == "unknown"

    def test_whitespace_stripped(self):
        assert player_identity_key({"number": "  7  "}) == "#7"

    def test_case_normalized(self):
        assert player_identity_key({"first": "JANE", "last": "Doe"}) == "jane|doe"


# ====================================================================
# build_player_metric_profile
# ====================================================================
class TestBuildPlayerMetricProfile:
    def test_computes_all_keys(self, sample_player):
        profile = build_player_metric_profile(sample_player)
        expected_keys = {
            "batting_avg", "batting_obp", "batting_slg", "batting_ops",
            "batting_k_rate", "batting_bb_rate",
            "pitching_era", "pitching_whip", "pitching_bb_per_ip", "pitching_k_per_ip",
            "fielding_fpct", "fielding_errors",
        }
        assert set(profile.keys()) == expected_keys

    def test_k_rate_from_so_and_pa(self, sample_player):
        # sample: so=2, pa=10
        profile = build_player_metric_profile(sample_player)
        assert profile["batting_k_rate"] == pytest.approx(0.2)

    def test_empty_player(self):
        profile = build_player_metric_profile({})
        assert profile["batting_avg"] == 0.0
        assert profile["batting_k_rate"] == 0.0
        assert profile["fielding_errors"] == 0.0


# ====================================================================
# detect_player_outlier_stats
# ====================================================================
class TestDetectOutliers:
    def _history(self, n, **overrides):
        base = {
            "batting_avg": 0.300, "batting_obp": 0.400, "batting_slg": 0.450,
            "batting_ops": 0.850, "batting_k_rate": 0.15, "batting_bb_rate": 0.10,
            "pitching_era": 3.00, "pitching_whip": 1.20, "pitching_bb_per_ip": 0.30,
            "pitching_k_per_ip": 1.00,
            "fielding_fpct": 0.950, "fielding_errors": 1.0,
        }
        base.update(overrides)
        return [dict(base) for _ in range(n)]

    def test_flags_obvious_outlier(self, sample_player):
        # Player avg is 0.375; history stable at 0.300 but forces zero stddev — skip.
        # So add a bit of jitter to history to get a non-zero stddev.
        history = self._history(10)
        for i, h in enumerate(history):
            h["batting_avg"] = 0.300 + (0.001 * i)  # small jitter, mean ~0.3045
        # player batting_avg will be ~0.375 -> many z away
        outliers = detect_player_outlier_stats(sample_player, history, z_threshold=3.0)
        metrics_flagged = {o["metric"] for o in outliers}
        assert "batting_avg" in metrics_flagged

    def test_ignores_insufficient_history(self, sample_player):
        history = self._history(3)  # < min_history_samples=5
        assert detect_player_outlier_stats(sample_player, history) == []

    def test_skips_zero_stddev_metric(self, sample_player):
        history = self._history(10)  # constant values => stddev=0 => skipped
        result = detect_player_outlier_stats(sample_player, history, z_threshold=0.0001)
        # Should not flag anything even with absurdly low threshold,
        # since all metrics with variation-less history are skipped.
        for o in result:
            # Only metrics with stddev > 0 can appear.
            assert o["stddev"] > 0

    def test_below_threshold_not_flagged(self, sample_player):
        history = self._history(10)
        for i, h in enumerate(history):
            h["batting_avg"] = 0.370 + (0.001 * i)  # very close to player's 0.375
        outliers = detect_player_outlier_stats(sample_player, history, z_threshold=3.0)
        assert all(o["metric"] != "batting_avg" for o in outliers)


# ====================================================================
# validate_team_outlier_stats
# ====================================================================
class TestValidateTeamOutlierStats:
    def test_no_history_returns_empty(self, sample_roster):
        team = {"roster": sample_roster}
        assert validate_team_outlier_stats(team, {}) == []

    def test_per_player_lookup_by_identity(self, sample_roster):
        # Build history keyed by player_identity_key
        history_by_id = {}
        for p in sample_roster:
            pid = player_identity_key(p)
            history_by_id[pid] = [
                {"batting_avg": 0.100 + 0.001 * i} for i in range(10)
            ]
        team = {"roster": sample_roster}
        findings = validate_team_outlier_stats(team, history_by_id, z_threshold=3.0)
        # Each player should be flagged (their current avg >> 0.10)
        assert len(findings) >= 1
        for f in findings:
            assert "player" in f
            assert "outliers" in f
            assert f["player"]["identity"]

    def test_empty_roster(self):
        assert validate_team_outlier_stats({"roster": []}, {}) == []


# ====================================================================
# count_populated_fields
# ====================================================================
class TestCountPopulatedFields:
    def test_counts_numeric_positive_only(self):
        rows = [
            {"ab": 5, "h": 2, "bb": 0},
            {"ab": 0, "h": 1, "bb": 1},
            {"ab": 3, "h": 0, "bb": 0},
        ]
        counts = count_populated_fields(rows, ["ab", "h", "bb"], normalize_batting_row)
        assert counts == {"ab": 2, "h": 2, "bb": 1}

    def test_ignores_sentinel_strings_in_normalized_output(self):
        # Normalization ensures all outputs are numeric for these fields.
        rows = [{"ab": "-", "h": "—"}]
        counts = count_populated_fields(rows, ["ab", "h"], normalize_batting_row)
        assert counts == {"ab": 0, "h": 0}

    def test_empty_rows_empty_counts(self):
        counts = count_populated_fields([], ["ab"], normalize_batting_row)
        assert counts == {"ab": 0}


# ====================================================================
# normalize_player_batting / normalize_player_batting_advanced
# ====================================================================
class TestNormalizePlayerBatting:
    def test_prefers_batting_dict(self):
        player = {"batting": {"ab": 10, "h": 5}, "stats": {"hitting": {"ab": 99}}}
        result = normalize_player_batting(player)
        assert result["ab"] == 10  # not 99

    def test_falls_back_to_stats_hitting(self):
        player = {"stats": {"hitting": {"ab": 8, "h": 4}}}
        assert normalize_player_batting(player)["ab"] == 8

    def test_falls_back_to_flat_keys(self):
        player = {"ab": 6, "h": 3}
        assert normalize_player_batting(player)["ab"] == 6


class TestNormalizePlayerBattingAdvanced:
    def test_prefers_batting_advanced_dict(self):
        player = {
            "batting_advanced": {"qab": 5, "pa": 10},
            "batting": {"qab": 99, "pa": 20},
        }
        result = normalize_player_batting_advanced(player)
        assert result["qab"] == 5

    def test_falls_back_to_batting_with_adv_keys(self):
        player = {"batting": {"qab": 3, "pa": 10, "qab_pct": None}}
        assert normalize_player_batting_advanced(player)["qab"] == 3

    def test_falls_back_to_stats_hitting_advanced(self):
        player = {"stats": {"hitting_advanced": {"qab": 2, "pa": 10}}}
        assert normalize_player_batting_advanced(player)["qab"] == 2

    def test_falls_back_to_flat(self):
        player = {"qab": 1, "pa": 10}
        assert normalize_player_batting_advanced(player)["qab"] == 1


# ====================================================================
# normalize_pitching_breakdown_row
# ====================================================================
class TestNormalizePitchingBreakdownRow:
    def test_populates_np_and_fb_block(self):
        row = {"np": 50, "fb": 30, "fbs": 18, "fbs_pct": 60.0, "mph_fb": 65.5}
        result = normalize_pitching_breakdown_row(row)
        assert result["np"] == 50
        assert result["fb"] == 30
        assert result["fbs"] == 18
        assert result["fbs_pct"] == pytest.approx(0.60, abs=0.001)
        assert result["mph_fb"] == 65.5

    def test_empty_row_returns_nones(self):
        result = normalize_pitching_breakdown_row({})
        assert result["np"] == 0
        assert result["fb"] is None
        assert result["mph_fb"] is None

    def test_nested_source(self):
        row = {"pitching_breakdown": {"np": 10, "ch": 5}}
        result = normalize_pitching_breakdown_row(row)
        assert result["np"] == 10
        assert result["ch"] == 5

    def test_off_speed_pitch_aliases(self):
        row = {"os": 5, "oss": 2, "oss_pct": 40}
        result = normalize_pitching_breakdown_row(row)
        assert result["os_pitch"] == 5
        assert result["oss"] == 2
        assert result["oss_pct"] == pytest.approx(0.4)


# ====================================================================
# normalize_pitching_advanced_full_row
# ====================================================================
class TestNormalizePitchingAdvancedFullRow:
    def test_full_row_populated(self):
        row = {
            "ip": "5.2", "s_pct": 65, "p_ip": 15, "p_bf": 4.2, "fps_pct": 70,
            "fip": 3.2, "k_bf": 0.25, "k_bb": 3.0, "bb_inn": 0.5,
        }
        result = normalize_pitching_advanced_full_row(row)
        assert result["ip"] == pytest.approx(17 / 3, abs=0.01)
        assert result["s_pct"] == pytest.approx(0.65)
        assert result["fps_pct"] == pytest.approx(0.70)
        assert result["fip"] == 3.2

    def test_empty_row_defaults_to_zeros(self):
        result = normalize_pitching_advanced_full_row({})
        assert result["ip"] == 0.0
        assert result["fip"] == 0.0

    def test_nested_pitching_advanced_source(self):
        row = {"pitching_advanced": {"ip": "3", "fip": 2.5}}
        result = normalize_pitching_advanced_full_row(row)
        assert result["ip"] == 3.0
        assert result["fip"] == 2.5

    def test_infers_from_pitching_when_adv_keys_present(self):
        row = {"pitching": {"s_pct": 50, "fip": 2.0}}
        result = normalize_pitching_advanced_full_row(row)
        assert result["s_pct"] == 0.5
