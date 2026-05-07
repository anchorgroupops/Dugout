"""Tests for sync_daemon data-pipeline helpers.

Covers:
- _merge_batting_with_scorebook  — max() counting stats merge + rate recompute
- _enrich_team_with_app_stats    — app_stats.json overlay keyed by jersey number
- _supplement_enriched_from_base — fill missing fields from base team.json
- _aggregate_opponent_stats_from_games — per-game JSON aggregation
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import sync_daemon

_merge = sync_daemon._merge_batting_with_scorebook
_enrich = sync_daemon._enrich_team_with_app_stats
_supplement = sync_daemon._supplement_enriched_from_base
_aggregate_opp = sync_daemon._aggregate_opponent_stats_from_games


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _row(**kwargs):
    """Minimal batting row dict — avoids digit-start keyword-arg limitation."""
    base = {
        "ab": 4, "h": 2, "1b": 1, "2b": 1, "3b": 0, "hr": 0,
        "bb": 1, "hbp": 0, "so": 1, "rbi": 1, "sb": 0, "r": 1,
        "sac": 0, "pa": 5,
    }
    base.update(kwargs)
    return base


def _rw(**kwargs):
    """Batting row where numeric-key overrides are passed as a plain dict merge."""
    return _row(**kwargs)


# ─── _merge_batting_with_scorebook ────────────────────────────────────────────

class TestMergeBattingWithScorebook:
    def test_returns_tuple_of_dict_and_bool(self):
        merged, changed = _merge(_row(), _row())
        assert isinstance(merged, dict)
        assert isinstance(changed, bool)

    def test_max_rule_on_hits(self):
        cur = _row(h=2, ab=4, pa=5)
        sb = dict(_row(h=3, ab=4, pa=5), **{"1b": 2, "2b": 1})
        merged, _ = _merge(cur, sb)
        assert merged["h"] == 3

    def test_max_rule_on_walks(self):
        cur = _row(bb=1)
        sb = _row(bb=3)
        merged, _ = _merge(cur, sb)
        assert merged["bb"] == 3

    def test_avg_recomputed_correctly(self):
        cur = _row(ab=4, h=2, bb=1, hbp=0, sac=0)
        sb = dict(_row(ab=4, h=3, bb=1, hbp=0, sac=0), **{"1b": 2, "2b": 1})
        merged, _ = _merge(cur, sb)
        assert merged["avg"] == round(3 / 4, 3)

    def test_obp_recomputed_correctly(self):
        cur = _row(ab=4, h=2, bb=2, hbp=0, sac=0, pa=6)
        sb = _row(ab=4, h=2, bb=2, hbp=0, sac=0, pa=6)
        merged, _ = _merge(cur, sb)
        assert merged["obp"] == round((2 + 2 + 0) / 6, 3)

    def test_slg_recomputed(self):
        cur = dict(_row(ab=4, h=2), **{"1b": 1, "2b": 1, "3b": 0, "hr": 0})
        sb = dict(_row(ab=4, h=2), **{"1b": 1, "2b": 1, "3b": 0, "hr": 0})
        merged, _ = _merge(cur, sb)
        assert merged["slg"] == round((1 + 2) / 4, 3)

    def test_ops_is_obp_plus_slg(self):
        merged, _ = _merge(_row(), _row())
        assert abs(merged["ops"] - round(merged["obp"] + merged["slg"], 3)) < 0.001

    def test_changed_true_when_scorebook_has_more_hits(self):
        cur = dict(_row(h=1, ab=4, pa=5), **{"1b": 1})
        sb = dict(_row(h=3, ab=4, pa=5), **{"1b": 3})
        _, changed = _merge(cur, sb)
        assert changed is True

    def test_changed_false_when_identical(self):
        row = _row()
        _, changed = _merge(row, row)
        assert changed is False

    def test_empty_inputs_return_zeros(self):
        merged, _ = _merge({}, {})
        assert merged["h"] == 0
        assert merged["avg"] == 0.0

    def test_none_inputs_treated_as_empty(self):
        merged, _ = _merge(None, None)
        assert merged["ab"] == 0

    def test_compatibility_aliases_present(self):
        merged, _ = _merge(_row(), _row())
        assert "doubles" in merged
        assert "triples" in merged
        assert "singles" in merged

    def test_1b_internally_consistent(self):
        """singles = max(explicit 1b, H - 2B - 3B - HR)."""
        cur = dict(_row(h=4, ab=8, pa=9), **{"1b": 2, "2b": 1, "3b": 1, "hr": 0})
        sb = dict(_row(h=5, ab=8, pa=9), **{"1b": 3, "2b": 1, "3b": 1, "hr": 0})
        merged, _ = _merge(cur, sb)
        min_singles = merged["h"] - merged["2b"] - merged["3b"] - merged["hr"]
        assert merged["1b"] >= max(0, min_singles)

    def test_pa_floor_enforced(self):
        """PA must be at least AB + BB + HBP + SAC."""
        cur = _row(ab=4, bb=2, hbp=1, sac=1, pa=1)
        sb = _row(ab=4, bb=2, hbp=1, sac=1, pa=1)
        merged, _ = _merge(cur, sb)
        assert merged["pa"] >= 4 + 2 + 1 + 1


# ─── _enrich_team_with_app_stats ─────────────────────────────────────────────

class TestEnrichTeamWithAppStats:
    @pytest.fixture(autouse=True)
    def _redirect_sharks_dir(self, tmp_path, monkeypatch):
        self.sharks_dir = tmp_path / "sharks"
        self.sharks_dir.mkdir()
        monkeypatch.setattr(sync_daemon, "SHARKS_DIR", self.sharks_dir)

    def _write_app_stats(self, batting=None, pitching=None, fielding=None):
        data = {"batting": batting or [], "pitching": pitching or [], "fielding": fielding or []}
        (self.sharks_dir / "app_stats.json").write_text(json.dumps(data))

    def _batting_entry(self, number, **kw):
        base = {"number": number, "ab": 12, "h": 5, "bb": 3, "hbp": 0,
                "so": 2, "rbi": 3, "sb": 1, "r": 2, "sac": 0, "hr": 0,
                "doubles": 1, "triples": 0}
        base.update(kw)
        return base

    def test_returns_team_data_unchanged_when_no_file(self):
        team = {"roster": [{"number": "7", "name": "Alice"}]}
        result = _enrich(team)
        assert result is team

    def test_batting_overlaid_by_jersey_number(self):
        self._write_app_stats(batting=[self._batting_entry("7", ab=12, h=5)])
        team = {"roster": [{"number": "7", "name": "Alice"}]}
        result = _enrich(team)
        assert "batting" in result["roster"][0]
        assert result["roster"][0]["batting"]["ab"] == 12
        assert result["roster"][0]["batting"]["h"] == 5

    def test_unmatched_player_not_modified(self):
        self._write_app_stats(batting=[self._batting_entry("99")])
        team = {"roster": [{"number": "7", "name": "Alice"}]}
        result = _enrich(team)
        assert "batting" not in result["roster"][0]

    def test_batting_advanced_overlaid(self):
        entry = self._batting_entry("7", qab_pct=55.0, gb_pct=40.0, fb_pct=30.0)
        self._write_app_stats(batting=[entry])
        team = {"roster": [{"number": "7", "name": "Alice"}]}
        result = _enrich(team)
        adv = result["roster"][0].get("batting_advanced", {})
        assert adv.get("qab_pct") == 55.0

    def test_graceful_on_malformed_app_stats(self):
        (self.sharks_dir / "app_stats.json").write_text("{BROKEN}")
        team = {"roster": [{"number": "7"}]}
        result = _enrich(team)
        assert result is team

    def test_empty_roster_unchanged(self):
        self._write_app_stats(batting=[self._batting_entry("7")])
        team = {"roster": []}
        result = _enrich(team)
        assert result["roster"] == []

    def test_pitching_overlaid(self):
        self._write_app_stats(pitching=[{
            "number": "7", "ip": "3.0", "gp": 2, "gs": 1, "bf": 12,
            "w": 1, "l": 0, "sv": 0, "svo": 0, "bs": 0, "h": 3,
            "r": 1, "er": 1, "bb": 2, "so": 5, "hr": 0,
        }])
        team = {"roster": [{"number": "7", "name": "Pitcher"}]}
        result = _enrich(team)
        assert "pitching" in result["roster"][0]
        assert result["roster"][0]["pitching"]["so"] == 5

    def test_fielding_overlaid(self):
        self._write_app_stats(fielding=[{
            "number": "7", "tc": 10, "po": 8, "a": 2, "e": 0,
            "fpct": 1.000, "dp": 0, "tp": 0,
        }])
        team = {"roster": [{"number": "7", "name": "Fielder"}]}
        result = _enrich(team)
        assert "fielding" in result["roster"][0]


# ─── _supplement_enriched_from_base ──────────────────────────────────────────

class TestSupplementEnrichedFromBase:
    @pytest.fixture(autouse=True)
    def _redirect_sharks_dir(self, tmp_path, monkeypatch):
        self.sharks_dir = tmp_path / "sharks"
        self.sharks_dir.mkdir()
        monkeypatch.setattr(sync_daemon, "SHARKS_DIR", self.sharks_dir)

    def _write_base_team(self, roster):
        (self.sharks_dir / "team.json").write_text(json.dumps({"roster": roster}))

    def test_no_op_when_no_base_file(self):
        team = {"roster": [{"number": "7", "batting_advanced": {"avg": 0.300}}]}
        _supplement(team)  # must not raise

    def test_missing_adv_field_filled_from_base(self):
        self._write_base_team([{
            "number": "7",
            "batting_advanced": {"babip": 0.350, "qab_pct": 60.0},
        }])
        team = {"roster": [{"number": "7", "batting_advanced": {"qab_pct": 55.0}}]}
        _supplement(team)
        adv = team["roster"][0]["batting_advanced"]
        assert adv.get("babip") == 0.350
        assert adv.get("qab_pct") == 55.0  # NOT overwritten

    def test_existing_field_not_overwritten(self):
        self._write_base_team([{"number": "7", "batting_advanced": {"babip": 0.999}}])
        team = {"roster": [{"number": "7", "batting_advanced": {"babip": 0.300}}]}
        _supplement(team)
        assert team["roster"][0]["batting_advanced"]["babip"] == 0.300

    def test_missing_section_filled_from_base(self):
        self._write_base_team([{
            "number": "7",
            "catching": {"cs": 2, "sba": 4},
        }])
        team = {"roster": [{"number": "7"}]}
        _supplement(team)
        assert team["roster"][0].get("catching") == {"cs": 2, "sba": 4}

    def test_unmatched_player_not_modified(self):
        self._write_base_team([{"number": "99", "catching": {"cs": 2}}])
        team = {"roster": [{"number": "7"}]}
        _supplement(team)
        assert "catching" not in team["roster"][0]

    def test_graceful_on_malformed_base_file(self):
        (self.sharks_dir / "team.json").write_text("{BAD JSON}")
        team = {"roster": [{"number": "7"}]}
        _supplement(team)  # must not raise


# ─── _aggregate_opponent_stats_from_games ─────────────────────────────────────

class TestAggregateOpponentStatsFromGames:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.sharks_dir = tmp_path / "sharks"
        self.games_dir = self.sharks_dir / "games"
        self.games_dir.mkdir(parents=True)
        monkeypatch.setattr(sync_daemon, "SHARKS_DIR", self.sharks_dir)

    def _write_game(self, name, opponent, opponent_batting):
        data = {"opponent": opponent, "opponent_batting": opponent_batting}
        (self.games_dir / name).write_text(json.dumps(data))

    def test_empty_games_dir_returns_empty(self):
        assert _aggregate_opp("peppers") == []

    def test_missing_games_dir_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sync_daemon, "SHARKS_DIR", tmp_path / "no_sharks")
        assert _aggregate_opp("peppers") == []

    def test_matching_game_aggregated(self):
        self._write_game("game1.json", "Peppers", [
            {"number": "10", "name": "Bob", "ab": 3, "h": 1, "bb": 0, "hbp": 0, "so": 1},
        ])
        result = _aggregate_opp("peppers")
        assert len(result) == 1
        assert result[0]["h"] == 1

    def test_non_matching_game_excluded(self):
        self._write_game("game1.json", "Wildcats", [
            {"number": "10", "name": "Bob", "ab": 3, "h": 2},
        ])
        result = _aggregate_opp("peppers")
        assert result == []

    def test_multiple_games_accumulated(self):
        for i in (1, 2):
            self._write_game(f"game{i}.json", "Peppers", [
                {"number": "10", "name": "Bob", "ab": 3, "h": 1, "bb": 0, "hbp": 0, "so": 0},
            ])
        result = _aggregate_opp("peppers")
        bob = next(p for p in result if p["name"] == "Bob")
        assert bob["h"] == 2
        assert bob["ab"] == 6

    def test_rate_stats_computed(self):
        self._write_game("game1.json", "Peppers", [
            {"number": "7", "name": "Alice", "ab": 4, "h": 2, "bb": 1, "hbp": 0, "so": 0},
        ])
        result = _aggregate_opp("peppers")
        alice = result[0]
        assert "avg" in alice
        assert "obp" in alice
        assert alice["avg"] == round(2 / 4, 3)

    def test_index_json_skipped(self):
        (self.games_dir / "index.json").write_text(json.dumps({"games": []}))
        self._write_game("game1.json", "Peppers", [
            {"number": "10", "name": "Bob", "ab": 3, "h": 1},
        ])
        result = _aggregate_opp("peppers")
        assert len(result) == 1

    def test_malformed_game_file_skipped_gracefully(self):
        (self.games_dir / "bad.json").write_text("{NOT VALID JSON}")
        self._write_game("good.json", "Peppers", [
            {"number": "3", "name": "Carol", "ab": 2, "h": 1},
        ])
        result = _aggregate_opp("peppers")
        assert len(result) == 1

    def test_players_keyed_by_number(self):
        self._write_game("game1.json", "Peppers", [
            {"number": "7", "name": "Alice", "ab": 3, "h": 1},
            {"number": "9", "name": "Dave", "ab": 3, "h": 2},
        ])
        result = _aggregate_opp("peppers")
        assert len(result) == 2

    def test_slug_partial_match_works(self):
        self._write_game("game1.json", "NWVLL Peppers SB", [
            {"number": "1", "name": "Eve", "ab": 4, "h": 2},
        ])
        result = _aggregate_opp("peppers")
        assert len(result) == 1
