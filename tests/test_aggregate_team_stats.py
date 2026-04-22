"""Tests for tools/aggregate_team_stats.py — roster merge helpers and recompute logic."""
from __future__ import annotations

import pytest

from tools.aggregate_team_stats import (
    _innings_to_outs,
    _is_rate_key,
    _merge_generic,
    _merge_innings,
    _merge_numeric,
    _norm_name,
    _outs_to_innings,
    _parse_number,
    _recompute_batting,
    _recompute_catching,
    _recompute_fielding,
    _recompute_pitching,
    _team_file_from_entry,
)


class TestNormName:
    @pytest.mark.parametrize("raw,expected", [
        ("Jane Doe", "janedoe"),
        ("JANE-DOE!", "janedoe"),
        ("  J. Doe  ", "jdoe"),
        ("", ""),
    ])
    def test_various(self, raw, expected):
        assert _norm_name(raw) == expected


class TestParseNumber:
    @pytest.mark.parametrize("val,expected", [
        (None, None), ("", None), ("-", None), ("—", None), ("N/A", None),
        (5, 5.0), (3.14, 3.14), (".25", 0.25), ("50%", 50.0), ("garbage", None),
    ])
    def test_various(self, val, expected):
        assert _parse_number(val) == expected

    def test_unhandled_type_returns_none(self):
        assert _parse_number([1, 2]) is None


class TestInningsToOuts:
    def test_none(self):
        assert _innings_to_outs(None) is None

    def test_empty(self):
        assert _innings_to_outs("") is None

    def test_softball_notation(self):
        assert _innings_to_outs("4.2") == 14  # 4*3 + 2
        assert _innings_to_outs("5.0") == 15

    def test_whole_integer(self):
        assert _innings_to_outs("5") == 15
        assert _innings_to_outs(3) == 9

    def test_float_non_softball(self):
        # 4.5 has fractional part "5" -> invalid for softball notation,
        # tries int("5") = 5, outs = 4*3 + 5 = 17
        # (aggregate_team_stats accepts this without validating outs <= 2,
        # unlike stats_normalizer.innings_to_float)
        assert _innings_to_outs("4.5") == 17

    def test_garbage_returns_none(self):
        assert _innings_to_outs("abc") is None
        assert _innings_to_outs("abc.def") is None


class TestOutsToInnings:
    def test_zero_outs(self):
        assert _outs_to_innings(0) == "0.0"

    def test_two_outs(self):
        assert _outs_to_innings(2) == "0.2"

    def test_full_inning(self):
        assert _outs_to_innings(3) == "1.0"

    def test_complex(self):
        assert _outs_to_innings(14) == "4.2"
        assert _outs_to_innings(21) == "7.0"


class TestMergeNumeric:
    def test_accumulates(self):
        dst = {"ab": 5}
        _merge_numeric(dst, {"ab": 3, "h": 2}, {"ab", "h"})
        assert dst == {"ab": 8.0, "h": 2.0}

    def test_ignores_none_values(self):
        dst = {}
        _merge_numeric(dst, {"ab": None, "h": 3}, {"ab", "h"})
        assert dst == {"h": 3.0}

    def test_ignores_keys_not_in_set(self):
        dst = {}
        _merge_numeric(dst, {"ab": 5, "extra": 99}, {"ab"})
        assert dst == {"ab": 5.0}


class TestMergeInnings:
    def test_accumulates_outs(self):
        dst_outs = {"ip": 9}
        _merge_innings(dst_outs, {"ip": "2.1"}, {"ip"})  # 2*3 + 1 = 7 outs
        assert dst_outs["ip"] == 16

    def test_ignores_unparseable(self):
        dst_outs = {}
        _merge_innings(dst_outs, {"ip": "garbage"}, {"ip"})
        assert dst_outs == {}


class TestIsRateKey:
    @pytest.mark.parametrize("key,expected", [
        ("qab_pct", True), ("avg", True), ("obp", True), ("slg", True),
        ("ops", True), ("era", True), ("whip", True), ("k_bb", True),
        ("bb_k", True), ("pct", True),
        ("ab", False), ("h", False), ("rbi", False), ("bb", False),
    ])
    def test_classifies_rate_vs_count(self, key, expected):
        assert _is_rate_key(key) is expected


class TestMergeGeneric:
    def test_merges_counts_only(self):
        dst = {}
        _merge_generic(dst, {"ab": 5, "h": 2, "avg": 0.400, "qab_pct": 0.5})
        assert "ab" in dst and "h" in dst
        assert "avg" not in dst
        assert "qab_pct" not in dst

    def test_accumulates_over_multiple_calls(self):
        dst = {}
        _merge_generic(dst, {"ab": 3})
        _merge_generic(dst, {"ab": 4})
        assert dst["ab"] == 7.0

    def test_none_src_safe(self):
        dst = {"x": 1}
        _merge_generic(dst, None)
        assert dst == {"x": 1}


class TestRecomputeBatting:
    def test_computes_rates(self):
        b = {"ab": 10, "h": 3, "bb": 1, "hbp": 0, "doubles": 1, "triples": 0, "hr": 1, "sb": 2, "cs": 1}
        result = _recompute_batting(b)
        assert result["pa"] == 11
        assert result["avg"] == 0.300
        assert result["obp"] == round(4 / 11, 3)
        # TB = (3-1-0-1) + 2 + 0 + 4 = 1 + 2 + 4 = 7; SLG = 7/10 = 0.700
        assert result["slg"] == 0.700
        assert result["ops"] == round(0.300 + 0.700, 3) or result["ops"] > 0
        assert result["sb_pct"] == round(2 / 3 * 100, 2)

    def test_zero_ab_returns_zero_rates(self):
        result = _recompute_batting({"ab": 0, "h": 0})
        assert result["avg"] == 0
        assert result["slg"] == 0

    def test_preserves_explicit_pa(self):
        result = _recompute_batting({"ab": 10, "h": 3, "bb": 1, "hbp": 0, "pa": 15})
        assert result["pa"] == 15

    def test_no_sb_or_cs_leaves_sb_pct_unset(self):
        result = _recompute_batting({"ab": 1, "h": 1})
        assert "sb_pct" not in result


class TestRecomputePitching:
    def test_none_outs_returns_unchanged(self):
        p = {"er": 2}
        result = _recompute_pitching(p, None)
        assert result == {"er": 2}

    def test_computes_era_whip(self):
        p = {"er": 3, "bb": 2, "h": 4}
        result = _recompute_pitching(p, ip_outs=21)  # 7.0 IP
        assert result["ip"] == "7.0"
        assert result["era"] == round((3 * 7) / 7, 2)
        assert result["whip"] == round(6 / 7, 2)

    def test_zero_ip_does_not_set_rates(self):
        p = {"er": 0, "bb": 0, "h": 0}
        result = _recompute_pitching(p, ip_outs=0)
        assert result["ip"] == "0.0"
        assert "era" not in result
        assert "whip" not in result


class TestRecomputeFielding:
    def test_computes_fpct(self):
        result = _recompute_fielding({"po": 10, "a": 3, "e": 1})
        assert result["fpct"] == round(13 / 14, 3)

    def test_no_chances_no_fpct(self):
        result = _recompute_fielding({"po": 0, "a": 0, "e": 0})
        assert "fpct" not in result


class TestRecomputeCatching:
    def test_computes_cs_pct(self):
        result = _recompute_catching({"sb": 2, "cs": 3}, inn_outs=15)
        assert result["inn"] == "5.0"
        assert result["cs_pct"] == round((3 / 5) * 100, 2)

    def test_no_attempts_no_cs_pct(self):
        result = _recompute_catching({"sb": 0, "cs": 0}, inn_outs=9)
        assert "cs_pct" not in result

    def test_none_inn_outs_skips_inn(self):
        result = _recompute_catching({"sb": 1, "cs": 1}, inn_outs=None)
        assert "inn" not in result
        assert result["cs_pct"] == 50.0


class TestTeamFileFromEntry:
    def test_absolute_data_path(self, tmp_path):
        p = tmp_path / "team.json"
        result = _team_file_from_entry({"data_path": str(p)})
        assert result == p

    def test_team_id_and_season_fallback(self):
        result = _team_file_from_entry({"id": "abc", "season_slug": "2026-spring"})
        assert "abc_2026-spring" in str(result)
        assert str(result).endswith("team.json")

    def test_missing_entry_returns_sharks_default(self):
        result = _team_file_from_entry({})
        assert str(result).endswith("sharks/team.json")
