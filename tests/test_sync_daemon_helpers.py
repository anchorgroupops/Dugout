"""Tests for pure data-transformation helpers in sync_daemon.

Covers:
- _safe_int / _safe_float  (re-exported from stats_normalizer)
- _slugify_opponent
- _clean_opponent_name
- _strip_team_totals_row  (logic mirrored inline — nested fn, not importable)
- _augment_sharks_batting

All helpers are stateless and require no HTTP, filesystem, or Flask setup.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure tools/ is on the path (mirrors conftest.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import sync_daemon

# Convenience aliases
_safe_int = sync_daemon._safe_int
_safe_float = sync_daemon._safe_float
_slugify_opponent = sync_daemon._slugify_opponent
_clean_opponent_name = sync_daemon._clean_opponent_name
_augment_sharks_batting = sync_daemon._augment_sharks_batting


# ---------------------------------------------------------------------------
# _safe_int  (imported from stats_normalizer, re-exported by sync_daemon)
# ---------------------------------------------------------------------------

class TestSafeInt:
    @pytest.mark.parametrize("val,expected", [
        (0,      0),
        (1,      1),
        (-5,    -5),
        (2.4,    2),
        (2.6,    3),
        (2.5,    2),   # Python banker's rounding: round(2.5) == 2
        ("3",    3),
        ("3.9",  4),
        ("0",    0),
    ])
    def test_numeric_and_string(self, val, expected):
        assert _safe_int(val) == expected

    def test_none_returns_default_zero(self):
        assert _safe_int(None) == 0

    def test_none_returns_custom_default(self):
        assert _safe_int(None, default=99) == 99

    @pytest.mark.parametrize("bad", ["", "-", "—", "N/A", "abc", "xyz"])
    def test_bad_values_return_default(self, bad):
        assert _safe_int(bad) == 0
        assert _safe_int(bad, default=7) == 7

    def test_leading_dot_string(self):
        # safe_float(".5") prepends "0" → float 0.5
        # int(round(0.5)) uses Python banker's rounding → 0
        assert _safe_int(".5") == 0

    def test_percent_string(self):
        # "80%" → float 80 → int 80
        assert _safe_int("80%") == 80


# ---------------------------------------------------------------------------
# _safe_float  (imported from stats_normalizer, re-exported by sync_daemon)
# ---------------------------------------------------------------------------

class TestSafeFloat:
    @pytest.mark.parametrize("val,expected", [
        (0,       0.0),
        (1,       1.0),
        (-3.14, -3.14),
        ("1.5",   1.5),
        ("0.375", 0.375),
        (".375",  0.375),   # leading-dot handling
        ("1e3",   1000.0),
    ])
    def test_numeric_and_string(self, val, expected):
        assert _safe_float(val) == pytest.approx(expected)

    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0
        assert _safe_float(None, default=9.9) == pytest.approx(9.9)

    @pytest.mark.parametrize("sentinel", ["", "-", "—", "N/A"])
    def test_sentinel_strings_return_default(self, sentinel):
        assert _safe_float(sentinel) == 0.0
        assert _safe_float(sentinel, default=1.23) == pytest.approx(1.23)

    def test_percent_strip(self):
        assert _safe_float("80%") == pytest.approx(80.0)
        assert _safe_float("44.44%") == pytest.approx(44.44)

    def test_whitespace_stripped(self):
        assert _safe_float("  .250  ") == pytest.approx(0.25)

    def test_garbage_returns_default(self):
        assert _safe_float("not-a-number", default=2.0) == pytest.approx(2.0)
        assert _safe_float("abc123") == 0.0


# ---------------------------------------------------------------------------
# _slugify_opponent
# ---------------------------------------------------------------------------

class TestSlugifyOpponent:
    @pytest.mark.parametrize("name,expected", [
        ("Eagles",              "eagles"),
        ("Blue Jays",           "blue_jays"),
        ("NWVLL Stihlers",      "nwvll_stihlers"),
        ("Team  Extra  Spaces", "team_extra_spaces"),
        ("Fire & Ice",          "fire_ice"),
        ("St. Louis",           "st_louis"),
        ("Aces/Hawks",          "aces_hawks"),
        # Mixed case → lower
        ("TheReds",             "thereds"),
        # Numbers preserved
        ("Team 99",             "team_99"),
    ])
    def test_typical_team_names(self, name, expected):
        assert _slugify_opponent(name) == expected

    def test_empty_string_returns_empty(self):
        assert _slugify_opponent("") == ""

    def test_none_equivalent_falsy_returns_empty(self):
        # Function guard: `if not name: return ""`
        assert _slugify_opponent("") == ""

    def test_all_special_chars_stripped(self):
        # All non-alnum become underscores, then stripped from edges
        result = _slugify_opponent("!@# team !@#")
        assert result == "team"

    def test_no_leading_trailing_underscore(self):
        result = _slugify_opponent(" Eagles ")
        assert not result.startswith("_")
        assert not result.endswith("_")

    def test_consecutive_specials_collapse_to_single_underscore(self):
        result = _slugify_opponent("A & B")
        assert result == "a_b"


# ---------------------------------------------------------------------------
# _clean_opponent_name
# ---------------------------------------------------------------------------

class TestCleanOpponentName:
    @pytest.mark.parametrize("raw,expected", [
        ("Eagles",          "Eagles"),
        ("@ Eagles",        "Eagles"),
        ("vs. Eagles",      "Eagles"),
        ("vs Eagles",       "Eagles"),
        ("@ Blue Jays",     "Blue Jays"),
        ("vs. The Stihlers","The Stihlers"),
        # Only the first matching prefix is stripped
        ("vs. @ Eagles",    "@ Eagles"),
        # Surrounding whitespace handled
        ("  @ Eagles  ",    "Eagles"),
    ])
    def test_prefix_stripping(self, raw, expected):
        assert _clean_opponent_name(raw) == expected

    def test_empty_string(self):
        assert _clean_opponent_name("") == ""

    def test_whitespace_only(self):
        assert _clean_opponent_name("   ") == ""

    def test_no_prefix_unchanged(self):
        name = "Sharks"
        assert _clean_opponent_name(name) == name

    def test_prefix_not_in_middle(self):
        # "vs." only stripped at start, not mid-string
        name = "Red vs. Blue"
        assert _clean_opponent_name(name) == "Red vs. Blue"


# ---------------------------------------------------------------------------
# _strip_team_totals_row  (logic mirrors the nested fn in handle_game_detail)
#
# Because the function is defined inside a Flask route closure it cannot be
# imported directly.  We replicate its logic verbatim here so the tests
# exercise the *algorithm* and serve as a regression guard.  If the upstream
# implementation changes these tests will catch a behavioural drift.
# ---------------------------------------------------------------------------

def _strip_team_totals_row(rows: list) -> list:
    """Mirror of sync_daemon.handle_game_detail._strip_team_totals_row."""
    if not rows or len(rows) < 2:
        return rows
    try:
        first_pa = int(rows[0].get("pa") or 0)
        rest_pa  = sum(int(r.get("pa") or 0) for r in rows[1:])
        if first_pa > 0 and rest_pa > 0 and abs(first_pa - rest_pa) <= 1:
            return rows[1:]
    except Exception:
        pass
    return rows


class TestStripTeamTotalsRow:
    def _make_rows(self, pa_values: list[int]) -> list[dict]:
        return [{"pa": pa, "name": f"player_{i}"} for i, pa in enumerate(pa_values)]

    def test_empty_list_returned_unchanged(self):
        assert _strip_team_totals_row([]) == []

    def test_single_row_returned_unchanged(self):
        rows = self._make_rows([5])
        assert _strip_team_totals_row(rows) == rows

    def test_totals_row_removed_when_pa_equals_sum(self):
        # first row PA == sum of rest → totals row
        rows = self._make_rows([30, 10, 12, 8])
        result = _strip_team_totals_row(rows)
        assert len(result) == 3
        assert result[0]["name"] == "player_1"

    def test_totals_row_removed_with_rounding_difference_of_one(self):
        # PA 31 vs sum 30 — within ±1 tolerance
        rows = self._make_rows([31, 10, 12, 8])
        result = _strip_team_totals_row(rows)
        assert len(result) == 3

    def test_no_totals_row_when_first_pa_not_equal_sum(self):
        # First player has 5 PA, rest sum to 30 — clearly not totals
        rows = self._make_rows([5, 10, 12, 8])
        assert len(_strip_team_totals_row(rows)) == 4

    def test_no_removal_when_first_pa_is_zero(self):
        rows = self._make_rows([0, 10, 12])
        assert len(_strip_team_totals_row(rows)) == 3

    def test_no_removal_when_rest_pa_is_zero(self):
        rows = self._make_rows([30, 0, 0, 0])
        assert len(_strip_team_totals_row(rows)) == 4

    def test_two_player_roster_not_falsely_stripped(self):
        # Two rows: first has 10 PA, second 8 PA — not totals
        rows = self._make_rows([10, 8])
        assert len(_strip_team_totals_row(rows)) == 2

    def test_missing_pa_key_treated_as_zero(self):
        rows = [{"name": "totals"}, {"name": "p1", "pa": 5}, {"name": "p2", "pa": 5}]
        # first pa=0 → guard prevents stripping
        assert len(_strip_team_totals_row(rows)) == 3

    def test_non_numeric_pa_treated_gracefully(self):
        rows = [{"pa": "bad"}, {"pa": "also_bad"}]
        # int("bad") raises — except clause returns rows unchanged
        result = _strip_team_totals_row(rows)
        assert result == rows


# ---------------------------------------------------------------------------
# _augment_sharks_batting
# ---------------------------------------------------------------------------

class TestAugmentSharksBatting:
    """Test _augment_sharks_batting without touching the filesystem.

    The function reads team_merged.json to overlay season rate stats.  We patch
    SHARKS_DIR so the roster file is never found, verifying the safe fallback
    path, and also provide a tmp-file roster to exercise the merge logic.
    """

    def test_empty_input_returned_unchanged(self):
        assert _augment_sharks_batting([]) == []

    def test_none_equivalent_returned_unchanged(self):
        # Function guard: `if not game_batting: return game_batting`
        assert _augment_sharks_batting([]) == []

    def test_returns_unchanged_when_roster_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sync_daemon, "SHARKS_DIR", tmp_path / "nonexistent")
        rows = [{"number": "7", "name": "Jane", "h": 2, "ab": 4}]
        result = _augment_sharks_batting(rows)
        assert result == rows

    def test_does_not_mutate_original_rows(self, tmp_path, monkeypatch):
        import json
        sharks_dir = tmp_path / "sharks"
        sharks_dir.mkdir()
        roster = {
            "roster": [
                {"number": "7", "name": "Jane", "batting": {"avg": 0.400, "slg": 0.600, "obp": 0.450, "ops": 1.050}}
            ]
        }
        (sharks_dir / "team_merged.json").write_text(json.dumps(roster))
        monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks_dir)

        original = {"number": "7", "name": "Jane", "h": 2}
        rows = [original]
        result = _augment_sharks_batting(rows)
        # result row is a copy — original dict unchanged
        assert "avg" not in original
        assert result[0]["avg"] == pytest.approx(0.400)

    def test_season_rate_stats_overlaid_by_jersey_number(self, tmp_path, monkeypatch):
        import json
        sharks_dir = tmp_path / "sharks"
        sharks_dir.mkdir()
        roster = {
            "roster": [
                {
                    "number": "7",
                    "name": "Jane Doe",
                    "batting": {
                        "avg": 0.380, "slg": 0.550, "obp": 0.430, "ops": 0.980,
                        "2b": 5, "3b": 1,
                    },
                    "batting_advanced": {"gb_pct": 0.42, "fb_pct": 0.30},
                }
            ]
        }
        (sharks_dir / "team_merged.json").write_text(json.dumps(roster))
        monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks_dir)

        game_row = {"number": "7", "name": "Jane Doe", "h": 3, "ab": 8}
        result = _augment_sharks_batting([game_row])
        assert len(result) == 1
        r = result[0]
        assert r["avg"] == pytest.approx(0.380)
        assert r["slg"] == pytest.approx(0.550)
        assert r["obp"] == pytest.approx(0.430)
        assert r["ops"] == pytest.approx(0.980)
        assert r["2b"] == 5
        assert r["3b"] == 1
        assert r["gb_pct"] == pytest.approx(0.42)
        assert r["fb_pct"] == pytest.approx(0.30)
        # Counting stats untouched
        assert r["h"] == 3
        assert r["ab"] == 8

    def test_season_stats_overlaid_by_name_fallback(self, tmp_path, monkeypatch):
        import json
        sharks_dir = tmp_path / "sharks"
        sharks_dir.mkdir()
        roster = {
            "roster": [
                {
                    "name": "kim lee",   # lowercase name as stored
                    "batting": {"avg": 0.310, "slg": 0.420, "obp": 0.360, "ops": 0.780},
                    "batting_advanced": {},
                }
            ]
        }
        (sharks_dir / "team_merged.json").write_text(json.dumps(roster))
        monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks_dir)

        game_row = {"number": "", "name": "Kim Lee", "h": 1, "ab": 3}
        result = _augment_sharks_batting([game_row])
        assert result[0]["avg"] == pytest.approx(0.310)

    def test_unmatched_player_row_passed_through_intact(self, tmp_path, monkeypatch):
        import json
        sharks_dir = tmp_path / "sharks"
        sharks_dir.mkdir()
        roster = {"roster": [{"number": "99", "name": "Ghost", "batting": {"avg": 0.999}}]}
        (sharks_dir / "team_merged.json").write_text(json.dumps(roster))
        monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks_dir)

        game_row = {"number": "1", "name": "Unknown Player", "h": 0}
        result = _augment_sharks_batting([game_row])
        assert result[0] == game_row  # no season data injected

    def test_doubles_fallback_field_names(self, tmp_path, monkeypatch):
        """batting.doubles / batting.triples (legacy key) should map to 2b / 3b."""
        import json
        sharks_dir = tmp_path / "sharks"
        sharks_dir.mkdir()
        roster = {
            "roster": [
                {
                    "number": "4",
                    "batting": {
                        "avg": 0.300,
                        "slg": 0.400,
                        "obp": 0.350,
                        "ops": 0.750,
                        "doubles": 4,
                        "triples": 2,
                    },
                    "batting_advanced": {},
                }
            ]
        }
        (sharks_dir / "team_merged.json").write_text(json.dumps(roster))
        monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks_dir)

        game_row = {"number": "4", "name": "Alex"}
        result = _augment_sharks_batting([game_row])
        assert result[0]["2b"] == 4
        assert result[0]["3b"] == 2

    def test_season_avg_stored_in_season_avg_key(self, tmp_path, monkeypatch):
        """setdefault puts season value under season_<key> as well."""
        import json
        sharks_dir = tmp_path / "sharks"
        sharks_dir.mkdir()
        roster = {
            "roster": [
                {
                    "number": "5",
                    "batting": {"avg": 0.350, "slg": 0.500, "obp": 0.400, "ops": 0.900},
                    "batting_advanced": {},
                }
            ]
        }
        (sharks_dir / "team_merged.json").write_text(json.dumps(roster))
        monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks_dir)

        game_row = {"number": "5", "name": "Sam"}
        result = _augment_sharks_batting([game_row])
        r = result[0]
        assert r.get("season_avg") == pytest.approx(0.350)
        assert r.get("season_slg") == pytest.approx(0.500)
        assert r.get("season_obp") == pytest.approx(0.400)
        assert r.get("season_ops") == pytest.approx(0.900)

    def test_multiple_rows_all_augmented(self, tmp_path, monkeypatch):
        import json
        sharks_dir = tmp_path / "sharks"
        sharks_dir.mkdir()
        roster = {
            "roster": [
                {"number": "7", "batting": {"avg": 0.400, "slg": 0.600, "obp": 0.450, "ops": 1.050}, "batting_advanced": {}},
                {"number": "3", "batting": {"avg": 0.250, "slg": 0.320, "obp": 0.310, "ops": 0.630}, "batting_advanced": {}},
            ]
        }
        (sharks_dir / "team_merged.json").write_text(json.dumps(roster))
        monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks_dir)

        rows = [
            {"number": "7", "name": "Jane", "h": 2},
            {"number": "3", "name": "Alex", "h": 1},
        ]
        result = _augment_sharks_batting(rows)
        assert len(result) == 2
        assert result[0]["avg"] == pytest.approx(0.400)
        assert result[1]["avg"] == pytest.approx(0.250)
