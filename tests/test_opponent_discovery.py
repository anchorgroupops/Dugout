"""Tests for pure helper functions in tools/opponent_discovery.py.

No external API calls are made; only deterministic, in-process logic is tested.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from opponent_discovery import (
    _clean_name,
    _extract_line_score_side,
    _record_to_string,
    _safe_int,
    _slug,
)


# ====================================================================
# _clean_name
# ====================================================================
class TestCleanName:
    def test_strips_at_sign_prefix(self):
        assert _clean_name("@ Riptide Rebels") == "Riptide Rebels"

    def test_strips_vs_dot_space_prefix(self):
        assert _clean_name("vs. Peppers") == "Peppers"

    def test_strips_vs_space_prefix(self):
        assert _clean_name("vs Ravens") == "Ravens"

    def test_strips_at_word_prefix(self):
        assert _clean_name("at Wildcats") == "Wildcats"

    def test_preserves_name_without_prefix(self):
        assert _clean_name("Sharks") == "Sharks"

    def test_handles_empty_string(self):
        assert _clean_name("") == ""

    def test_handles_none_like_empty(self):
        # _clean_name does (name or "").strip() so None resolves to ""
        assert _clean_name(None) == ""  # type: ignore[arg-type]

    def test_strips_surrounding_whitespace(self):
        assert _clean_name("  vs. Ravens  ") == "Ravens"

    def test_case_insensitive_at_sign(self):
        # prefix detection uses .lower()
        assert _clean_name("@ Hawks") == "Hawks"

    def test_case_insensitive_vs_dot(self):
        assert _clean_name("Vs. Ravens") == "Ravens"

    def test_case_insensitive_vs_space(self):
        assert _clean_name("VS Ravens") == "Ravens"

    def test_case_insensitive_at_word(self):
        assert _clean_name("At Peppers") == "Peppers"

    def test_does_not_strip_mid_word_at(self):
        # "at" only matches as a prefix, not mid-string
        assert _clean_name("Pirate") == "Pirate"

    def test_only_first_matching_prefix_removed(self):
        # A single pass strips one matching prefix; the rest of the string is kept intact.
        result = _clean_name("vs. vs. Ravens")
        assert result == "vs. Ravens"


# ====================================================================
# _slug
# ====================================================================
class TestSlug:
    def test_riptide_override(self):
        assert _slug("Riptide Rebels") == "riptide_rebels"

    def test_riptide_fragment_in_longer_name(self):
        assert _slug("Palm Coast Riptide") == "riptide_rebels"

    def test_pepper_override(self):
        assert _slug("Hot Peppers") == "peppers"

    def test_pepper_fragment(self):
        assert _slug("pepper squad") == "peppers"

    def test_raven_override(self):
        assert _slug("Ravens FC") == "ravens"

    def test_raven_fragment(self):
        assert _slug("raven") == "ravens"

    def test_wildcat_override(self):
        assert _slug("Wildcats") == "wildcats"

    def test_sharks_override(self):
        assert _slug("Sharks") == "sharks"

    def test_nwvll_override_direct(self):
        assert _slug("NWVLL") == "nwvll"

    def test_stihler_maps_to_nwvll(self):
        assert _slug("Stihler Athletics") == "nwvll"

    def test_five_star_maps_to_nwvll(self):
        assert _slug("5 Star Travel") == "nwvll"

    def test_regular_name_no_override_is_lowercase(self):
        result = _slug("Blue Jays")
        assert result == result.lower()

    def test_regular_name_no_override_only_alnum_underscore(self):
        import re
        result = _slug("Blue Jays")
        assert re.fullmatch(r"[a-z0-9_]+", result)

    def test_regular_name_spaces_become_underscores(self):
        assert _slug("Blue Jays") == "blue_jays"

    def test_leading_trailing_underscores_stripped(self):
        # Special characters at start/end should not leave dangling underscores.
        result = _slug("--Cardinals--")
        assert not result.startswith("_")
        assert not result.endswith("_")

    def test_strips_at_prefix_before_slugging(self):
        # _slug calls _clean_name internally
        assert _slug("@ Blue Jays") == "blue_jays"

    def test_vs_prefix_stripped_before_slugging(self):
        assert _slug("vs. Blue Jays") == "blue_jays"

    def test_empty_name_returns_unknown(self):
        assert _slug("") == "unknown"

    def test_slug_truncated_to_48_chars(self):
        long_name = "A" * 60
        assert len(_slug(long_name)) <= 48


# ====================================================================
# _record_to_string
# ====================================================================
class TestRecordToString:
    def test_normal_win_loss(self):
        assert _record_to_string({"win": 5, "loss": 3, "tie": 0}) == "5-3"

    def test_includes_tie_when_nonzero(self):
        assert _record_to_string({"win": 5, "loss": 3, "tie": 1}) == "5-3-1"

    def test_all_zeros(self):
        assert _record_to_string({"win": 0, "loss": 0, "tie": 0}) == "0-0"

    def test_non_dict_returns_zero_zero(self):
        assert _record_to_string("5-3") == "0-0"
        assert _record_to_string(None) == "0-0"
        assert _record_to_string([5, 3]) == "0-0"

    def test_missing_keys_default_to_zero(self):
        # dict without tie key should behave as tie=0
        assert _record_to_string({"win": 4, "loss": 2}) == "4-2"

    def test_none_values_in_dict_treated_as_zero(self):
        # The implementation does int(rec.get("win", 0) or 0) so None → 0
        assert _record_to_string({"win": None, "loss": None, "tie": None}) == "0-0"

    def test_large_numbers(self):
        assert _record_to_string({"win": 100, "loss": 0, "tie": 0}) == "100-0"

    def test_tie_zero_not_appended(self):
        result = _record_to_string({"win": 3, "loss": 1, "tie": 0})
        assert result.count("-") == 1


# ====================================================================
# _safe_int
# ====================================================================
class TestSafeInt:
    def test_int_passthrough(self):
        assert _safe_int(7) == 7

    def test_float_truncates(self):
        assert _safe_int(3.9) == 3

    def test_numeric_string(self):
        assert _safe_int("5") == 5

    def test_none_returns_default(self):
        assert _safe_int(None) == 0

    def test_empty_string_returns_default(self):
        assert _safe_int("") == 0

    def test_non_numeric_string_returns_default(self):
        assert _safe_int("abc") == 0

    def test_float_string_truncates(self):
        assert _safe_int("3.7") == 3

    def test_custom_default(self):
        assert _safe_int(None, default=-1) == -1
        assert _safe_int("", default=99) == 99
        assert _safe_int("bad", default=42) == 42

    def test_zero(self):
        assert _safe_int(0) == 0

    def test_negative_int(self):
        assert _safe_int(-4) == -4

    def test_negative_float_string(self):
        assert _safe_int("-2.5") == -2

    def test_boolean_true_is_one(self):
        # bool is a subclass of int in Python
        assert _safe_int(True) == 1

    def test_boolean_false_is_zero(self):
        assert _safe_int(False) == 0


# ====================================================================
# _extract_line_score_side
# ====================================================================
class TestExtractLineScoreSide:
    def test_happy_path_all_fields(self):
        side = {
            "totals": [7, 10, 2],
            "scores": [0, 3, 0, 4, 0],
        }
        runs, hits, errors, inning_scores = _extract_line_score_side(side)
        assert runs == 7
        assert hits == 10
        assert errors == 2
        assert inning_scores == [0, 3, 0, 4, 0]

    def test_empty_dict_returns_none_tuple(self):
        runs, hits, errors, inning_scores = _extract_line_score_side({})
        assert runs is None
        assert hits is None
        assert errors is None
        assert inning_scores == []

    def test_non_dict_returns_none_tuple(self):
        runs, hits, errors, inning_scores = _extract_line_score_side(None)  # type: ignore[arg-type]
        assert runs is None
        assert hits is None
        assert errors is None
        assert inning_scores == []

    def test_missing_totals_key_all_none(self):
        side = {"scores": [1, 2, 3]}
        runs, hits, errors, inning_scores = _extract_line_score_side(side)
        assert runs is None
        assert hits is None
        assert errors is None
        assert inning_scores == [1, 2, 3]

    def test_totals_with_only_one_element(self):
        side = {"totals": [5], "scores": [2, 3]}
        runs, hits, errors, inning_scores = _extract_line_score_side(side)
        assert runs == 5
        assert hits is None
        assert errors is None
        assert inning_scores == [2, 3]

    def test_totals_with_two_elements(self):
        side = {"totals": [4, 8], "scores": []}
        runs, hits, errors, inning_scores = _extract_line_score_side(side)
        assert runs == 4
        assert hits == 8
        assert errors is None
        assert inning_scores == []

    def test_missing_scores_key_returns_empty_list(self):
        side = {"totals": [3, 6, 1]}
        runs, hits, errors, inning_scores = _extract_line_score_side(side)
        assert runs == 3
        assert hits == 6
        assert errors == 1
        assert inning_scores == []

    def test_string_values_in_totals_are_converted(self):
        side = {"totals": ["6", "9", "1"], "scores": ["2", "4"]}
        runs, hits, errors, inning_scores = _extract_line_score_side(side)
        assert runs == 6
        assert hits == 9
        assert errors == 1
        assert inning_scores == [2, 4]

    def test_float_values_in_totals_are_truncated(self):
        side = {"totals": [3.9, 7.1, 0.5], "scores": [1.1, 2.9]}
        runs, hits, errors, inning_scores = _extract_line_score_side(side)
        assert runs == 3
        assert hits == 7
        assert errors == 0
        assert inning_scores == [1, 2]

    def test_totals_not_a_list_treated_as_empty(self):
        # If totals is not a list, the implementation falls back to []
        side = {"totals": {"runs": 5}, "scores": [1, 2]}
        runs, hits, errors, inning_scores = _extract_line_score_side(side)
        assert runs is None
        assert hits is None
        assert errors is None
        assert inning_scores == [1, 2]

    def test_scores_not_a_list_treated_as_empty(self):
        side = {"totals": [5, 8, 2], "scores": "invalid"}
        runs, hits, errors, inning_scores = _extract_line_score_side(side)
        assert runs == 5
        assert hits == 8
        assert errors == 2
        assert inning_scores == []

    def test_zero_runs_distinguishable_from_none(self):
        # totals[0] = 0 should give runs=0, not None
        side = {"totals": [0, 0, 0], "scores": []}
        runs, hits, errors, inning_scores = _extract_line_score_side(side)
        assert runs == 0
        assert hits == 0
        assert errors == 0
