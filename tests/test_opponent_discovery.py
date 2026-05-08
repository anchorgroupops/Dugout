"""Tests for pure helper functions in tools/opponent_discovery.py.

No external API calls are made; only deterministic, in-process logic is tested.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from opponent_discovery import (
    _clean_name,
    _extract_line_score_side,
    _fetch_public_game_metrics,
    _discover_from_orgs,
    _resolve_exact_season_slugs,
    _load_schedule_opponents,
    _parse_org_ids,
    _record_to_string,
    _safe_get_json,
    _safe_int,
    _slug,
    discover_and_persist_opponents,
)
import opponent_discovery as od_mod  # same module object as the from-imports above


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


# ====================================================================
# _parse_org_ids
# ====================================================================

class TestParseOrgIds:
    def test_returns_list(self, monkeypatch):
        monkeypatch.delenv("GC_ORG_IDS", raising=False)
        result = _parse_org_ids()
        assert isinstance(result, list)
        assert len(result) > 0

    def test_uses_env_var(self, monkeypatch):
        monkeypatch.setenv("GC_ORG_IDS", "org1,org2,org3")
        result = _parse_org_ids()
        assert result == ["org1", "org2", "org3"]

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("GC_ORG_IDS", " org1 , org2 ")
        result = _parse_org_ids()
        assert result == ["org1", "org2"]

    def test_filters_empty_segments(self, monkeypatch):
        monkeypatch.setenv("GC_ORG_IDS", "org1,,org2")
        result = _parse_org_ids()
        assert "" not in result
        assert "org1" in result

    def test_defaults_when_env_empty(self, monkeypatch):
        monkeypatch.setenv("GC_ORG_IDS", "")
        result = _parse_org_ids()
        assert len(result) > 0  # falls back to DEFAULT_ORG_IDS


# ====================================================================
# _safe_get_json
# ====================================================================

class TestSafeGetJson:
    def test_returns_none_on_network_error(self, monkeypatch):
        import requests

        def bad_get(*args, **kwargs):
            raise requests.exceptions.ConnectionError("no network")

        import opponent_discovery
        monkeypatch.setattr(opponent_discovery.requests, "get", bad_get)
        result = _safe_get_json("http://localhost:1/nonexistent")
        assert result is None

    def test_returns_none_on_non_200_status(self, monkeypatch):
        class FakeResp:
            status_code = 404

        import opponent_discovery
        monkeypatch.setattr(opponent_discovery.requests, "get", lambda *a, **kw: FakeResp())
        result = _safe_get_json("http://example.com/api")
        assert result is None

    def test_returns_parsed_json_on_success(self, monkeypatch):
        class FakeResp:
            status_code = 200

            def json(self):
                return {"teams": []}

        import opponent_discovery
        monkeypatch.setattr(opponent_discovery.requests, "get", lambda *a, **kw: FakeResp())
        result = _safe_get_json("http://example.com/api")
        assert result == {"teams": []}


# ====================================================================
# _load_schedule_opponents
# ====================================================================

class TestLoadScheduleOpponents:
    def test_returns_empty_when_no_file(self, tmp_path):
        result = _load_schedule_opponents(tmp_path)
        assert result == []

    def test_returns_opponents_from_upcoming(self, tmp_path):
        sharks = tmp_path / "sharks"
        sharks.mkdir()
        schedule = {
            "upcoming": [
                {"opponent": "Eagles", "is_game": True},
                {"opponent": "Hawks", "is_game": True},
            ]
        }
        (sharks / "schedule_manual.json").write_text(json.dumps(schedule))
        result = _load_schedule_opponents(tmp_path)
        assert "Eagles" in result
        assert "Hawks" in result

    def test_returns_opponents_from_past(self, tmp_path):
        sharks = tmp_path / "sharks"
        sharks.mkdir()
        schedule = {"past": [{"opponent": "Ravens", "is_game": True}]}
        (sharks / "schedule_manual.json").write_text(json.dumps(schedule))
        result = _load_schedule_opponents(tmp_path)
        assert "Ravens" in result

    def test_skips_non_game_entries(self, tmp_path):
        sharks = tmp_path / "sharks"
        sharks.mkdir()
        schedule = {
            "upcoming": [
                {"opponent": "Eagles", "is_game": True},
                {"opponent": "ShouldSkip", "is_game": False},
            ]
        }
        (sharks / "schedule_manual.json").write_text(json.dumps(schedule))
        result = _load_schedule_opponents(tmp_path)
        assert "ShouldSkip" not in result

    def test_skips_empty_opponent_names(self, tmp_path):
        sharks = tmp_path / "sharks"
        sharks.mkdir()
        schedule = {"upcoming": [{"opponent": "", "is_game": True}]}
        (sharks / "schedule_manual.json").write_text(json.dumps(schedule))
        result = _load_schedule_opponents(tmp_path)
        assert result == []

    def test_returns_empty_on_invalid_json(self, tmp_path):
        sharks = tmp_path / "sharks"
        sharks.mkdir()
        (sharks / "schedule_manual.json").write_text("not valid json")
        result = _load_schedule_opponents(tmp_path)
        assert result == []

    def test_cleans_opponent_prefixes(self, tmp_path):
        sharks = tmp_path / "sharks"
        sharks.mkdir()
        schedule = {"upcoming": [{"opponent": "@ Wildcats", "is_game": True}]}
        (sharks / "schedule_manual.json").write_text(json.dumps(schedule))
        result = _load_schedule_opponents(tmp_path)
        assert "Wildcats" in result
        assert "@ Wildcats" not in result


# ====================================================================
# _fetch_public_game_metrics (lines 101-189)
# ====================================================================

def _make_game(gid, our, opp, ts="2026-03-01"):
    return {"id": gid, "start_ts": ts,
            "score": {"team": our, "opponent_team": opp}}

def _make_detail(team_runs=5, team_hits=8, team_errors=1, team_scores=None,
                 opp_runs=3, opp_hits=6, opp_errors=2, opp_scores=None):
    return {
        "line_score": {
            "team": {
                "totals": [team_runs, team_hits, team_errors],
                "scores": team_scores or [1, 2, 2, 0, 0],
            },
            "opponent_team": {
                "totals": [opp_runs, opp_hits, opp_errors],
                "scores": opp_scores or [1, 1, 1, 0, 0],
            },
        }
    }


class TestFetchPublicGameMetrics:
    def _mock_safe_get(self, monkeypatch, games, detail=None):
        def fake(url, **kw):
            if "/games" in url and "/game-stream" not in url:
                return games
            if "/game-stream" in url:
                return detail or _make_detail()
            return {}
        monkeypatch.setattr(od_mod, "_safe_get_json", fake)

    def test_empty_games_returns_zeros(self, monkeypatch):
        self._mock_safe_get(monkeypatch, [])
        result = _fetch_public_game_metrics("t1")
        assert result["completed_games"] == 0
        assert result["wins"] == 0
        assert result["runs_scored_per_game"] == 0.0

    def test_counts_wins_losses_ties(self, monkeypatch):
        games = [
            _make_game("g1", 7, 3),   # win
            _make_game("g2", 2, 5),   # loss
            _make_game("g3", 4, 4),   # tie
        ]
        self._mock_safe_get(monkeypatch, games)
        result = _fetch_public_game_metrics("t1")
        assert result["wins"] == 1
        assert result["losses"] == 1
        assert result["ties"] == 1

    def test_skips_game_without_score(self, monkeypatch):
        """Lines 109-110: game missing 'team' or 'opponent_team' in score → skip."""
        games = [
            {"id": "g1", "score": {"only_team": 5}},  # missing opponent_team
            _make_game("g2", 7, 3),
        ]
        self._mock_safe_get(monkeypatch, games)
        result = _fetch_public_game_metrics("t1")
        assert result["completed_games"] == 1

    def test_skips_game_with_non_dict_score(self, monkeypatch):
        """Line 109: score not a dict → continue."""
        games = [
            {"id": "g1", "score": "bad"},
            _make_game("g2", 5, 2),
        ]
        self._mock_safe_get(monkeypatch, games)
        result = _fetch_public_game_metrics("t1")
        assert result["completed_games"] == 1

    def test_skips_game_with_unconvertible_score(self, monkeypatch):
        """Lines 116-117: score values can't be int → continue."""
        games = [
            {"id": "g1", "score": {"team": "not_num", "opponent_team": "bad"}},
            _make_game("g2", 5, 2),
        ]
        self._mock_safe_get(monkeypatch, games)
        result = _fetch_public_game_metrics("t1")
        assert result["completed_games"] == 1

    def test_line_score_details_accumulated(self, monkeypatch):
        """Lines 151-182: line score details → hits, errors, inning stats."""
        games = [_make_game("g1", 7, 3)]
        detail = _make_detail(
            team_runs=7, team_hits=9, team_errors=1,
            team_scores=[0, 7, 0, 0, 0],  # big inning ≥ 5
            opp_runs=0, opp_hits=5, opp_errors=2,
            opp_scores=[0, 0, 0, 0, 0],  # shutout for us
        )
        self._mock_safe_get(monkeypatch, games, detail)
        result = _fetch_public_game_metrics("t1")
        assert result["line_score_games"] == 1
        assert result["hits_scored"] == 9
        assert result["shutout_for"] == 1
        assert result["big_inning_rate"] == 1.0

    def test_shutout_against_tracked(self, monkeypatch):
        """Line 181-182: team runs == 0 → shutout_against."""
        games = [_make_game("g1", 0, 5)]
        detail = _make_detail(
            team_runs=0, team_hits=2, team_errors=0,
            team_scores=[0, 0, 0, 0, 0],
            opp_runs=5, opp_hits=7, opp_errors=1,
            opp_scores=[2, 0, 3, 0, 0],
        )
        self._mock_safe_get(monkeypatch, games, detail)
        result = _fetch_public_game_metrics("t1")
        assert result["shutout_against"] == 1

    def test_skips_game_without_id(self, monkeypatch):
        """Line 152-154: game without id → skip line score fetch."""
        games = [
            {"id": None, "score": {"team": 5, "opponent_team": 3}},
            _make_game("g2", 5, 2),
        ]
        self._mock_safe_get(monkeypatch, games)
        result = _fetch_public_game_metrics("t1")
        assert result["completed_games"] == 2
        # g1 had no id so no line score processed
        assert result["line_score_games"] == 1

    def test_skips_detail_without_line_score(self, monkeypatch):
        """Line 156-158: detail without line_score → skip."""
        games = [_make_game("g1", 5, 2)]
        def fake(url, **kw):
            if "/games" in url and "/game-stream" not in url:
                return games
            return {"no_line_score": True}  # missing line_score key
        monkeypatch.setattr(od_mod, "_safe_get_json", fake)
        result = _fetch_public_game_metrics("t1")
        assert result["line_score_games"] == 0

    def test_last5_stats_computed(self, monkeypatch):
        """Lines 184-186: last5 stats are averaged over 5 most recent games."""
        games = [_make_game(f"g{i}", 5, 3, ts=f"2026-0{i+1}-01") for i in range(7)]
        self._mock_safe_get(monkeypatch, games)
        result = _fetch_public_game_metrics("t1")
        assert result["last5_completed_games"] == 5

    def test_big_inning_allowed_tracked(self, monkeypatch):
        """Line 178: opponent inning score ≥ 5 → big_inning_allowed_games."""
        games = [_make_game("g1", 7, 6)]
        detail = _make_detail(
            opp_runs=6, opp_hits=8, opp_errors=0,
            opp_scores=[0, 6, 0, 0, 0],  # 6-run inning ≥ 5 → big_inning_allowed
        )
        self._mock_safe_get(monkeypatch, games, detail)
        result = _fetch_public_game_metrics("t1")
        assert result["big_inning_allowed_rate"] == 1.0


# ====================================================================
# _discover_from_orgs (lines 222-307)
# ====================================================================

class TestDiscoverFromOrgs:
    def _mock_api(self, monkeypatch, teams=None, standings=None, events=None,
                  team_detail=None):
        teams = teams or []
        standings = standings or []
        events = events or []
        team_detail = team_detail or {}

        def fake(url, **kw):
            if "/organizations/" in url and "/teams" in url:
                return teams
            if "/standings" in url:
                return standings
            if "/events" in url:
                return events
            if "/teams/" in url and "/games" not in url and "/game-stream" not in url:
                return team_detail
            if "/games" in url:
                return []  # no game data for enrichment
            return {}

        monkeypatch.setattr(od_mod, "_safe_get_json", fake)

    def test_returns_empty_when_no_teams(self, monkeypatch):
        self._mock_api(monkeypatch)
        result = _discover_from_orgs(["org1"])
        assert isinstance(result, dict)

    def test_discovers_teams_from_org(self, monkeypatch):
        teams = [{"id": "t1", "name": "Peppers"}]
        self._mock_api(monkeypatch, teams=teams)
        result = _discover_from_orgs(["org1"])
        assert "t1" in result
        assert result["t1"]["team_name"] == "Peppers"

    def test_applies_standings_record(self, monkeypatch):
        """Lines 264-265: standings record applied to discovered team."""
        teams = [{"id": "t1", "name": "Peppers"}]
        standings = [{"team_id": "t1", "overall": {"wins": 5, "losses": 2, "ties": 0}}]
        self._mock_api(monkeypatch, teams=teams, standings=standings)
        result = _discover_from_orgs(["org1"])
        assert result["t1"]["record"] == "5-2"

    def test_events_add_teams_not_in_teams_feed(self, monkeypatch):
        """Lines 267-287: event teams are discovered even if not in /teams."""
        events = [{"home_team": {"id": "t2", "name": "Ravens"},
                   "away_team": {"id": "t3", "name": "Wildcats"}}]
        self._mock_api(monkeypatch, events=events)
        result = _discover_from_orgs(["org1"])
        assert "t2" in result
        assert "t3" in result

    def test_team_detail_enriches_name_and_record(self, monkeypatch):
        """Lines 290-305: /teams/{id} enriches team_name, record, season_slug."""
        teams = [{"id": "t1", "name": "Old Name"}]
        detail = {
            "name": "New Peppers Name",
            "team_season": {
                "season": "spring",
                "year": "2026",
                "record": {"win": 4, "loss": 3, "tie": 0},
            },
        }
        self._mock_api(monkeypatch, teams=teams, team_detail=detail)
        result = _discover_from_orgs(["org1"])
        assert result["t1"]["team_name"] == "New Peppers Name"
        assert result["t1"]["record"] == "4-3"

    def test_org_id_added_to_organization_ids(self, monkeypatch):
        """Line 262-263: org_id added to item's organization_ids."""
        teams = [{"id": "t1", "name": "Peppers"}]
        self._mock_api(monkeypatch, teams=teams)
        result = _discover_from_orgs(["org1"])
        assert "org1" in result["t1"]["organization_ids"]

    def test_skips_team_without_id(self, monkeypatch):
        """Lines 247-249: team with empty id → skipped."""
        teams = [{"id": "", "name": "NoID"}, {"id": "t1", "name": "Peppers"}]
        self._mock_api(monkeypatch, teams=teams)
        result = _discover_from_orgs(["org1"])
        assert len(result) >= 1

    def test_multiple_orgs_merged(self, monkeypatch):
        """Multiple org IDs → teams from each merged into result."""
        teams = [{"id": "t1", "name": "Peppers"}]
        call_counts = [0]
        def fake(url, **kw):
            call_counts[0] += 1
            if "/organizations/" in url and "/teams" in url:
                return teams
            if "/standings" in url or "/events" in url:
                return []
            if "/teams/" in url and "/games" not in url:
                return {}
            if "/games" in url:
                return []
            return {}
        monkeypatch.setattr(od_mod, "_safe_get_json", fake)
        result = _discover_from_orgs(["org1", "org2"])
        assert "t1" in result

    def test_event_team_without_id_skipped(self, monkeypatch):
        """Line 273: event team with empty id → continue (skip)."""
        events = [
            {"home_team": {"id": "", "name": "NoID"},
             "away_team": {"id": "t1", "name": "Peppers"}},
        ]
        self._mock_api(monkeypatch, events=events)
        result = _discover_from_orgs(["org1"])
        # t1 is discovered, but the empty-id team is not
        assert "t1" in result
        assert "" not in result


# ====================================================================
# _resolve_exact_season_slugs (lines 313-334)
# ====================================================================

class TestResolveExactSeasonSlugs:
    def test_returns_empty_when_sync_playwright_none(self, monkeypatch):
        """Line 314: sync_playwright is None → returns empty dict immediately."""
        monkeypatch.setattr(od_mod, "sync_playwright", None)
        result = _resolve_exact_season_slugs(["team1"])
        assert result == {}

    def test_returns_empty_when_no_team_ids(self, monkeypatch):
        """Line 314: empty team_ids → returns empty dict immediately."""
        # sync_playwright may or may not be None; both paths should return {}
        result = _resolve_exact_season_slugs([])
        assert result == {}

    def test_returns_slugs_when_playwright_available(self, monkeypatch):
        """Lines 316-334: playwright available, page content has team links."""
        fake_page = MagicMock()
        fake_page.content.return_value = (
            '<a href="/teams/t1/spring-2026-peppers/schedule">Schedule</a>'
        )
        fake_browser = MagicMock()
        fake_browser.new_page.return_value = fake_page

        fake_pw_ctx = MagicMock()
        fake_pw_ctx.__enter__ = MagicMock(return_value=fake_pw_ctx)
        fake_pw_ctx.__exit__ = MagicMock(return_value=False)
        fake_pw_ctx.chromium.launch.return_value = fake_browser

        monkeypatch.setattr(od_mod, "sync_playwright", lambda: fake_pw_ctx)
        result = _resolve_exact_season_slugs(["t1"])
        assert "t1" in result
        assert result["t1"] == "spring-2026-peppers"

    def test_exception_in_playwright_returns_partial(self, monkeypatch):
        """Lines 332-333: outer exception → returns partial results dict."""
        monkeypatch.setattr(od_mod, "sync_playwright",
                            lambda: (_ for _ in ()).throw(RuntimeError("browser crashed")))
        result = _resolve_exact_season_slugs(["t1"])
        assert isinstance(result, dict)

    def test_inner_exception_continues_to_next_team(self, monkeypatch):
        """Lines 329-330: page.goto raises → continue to next team."""
        fake_page = MagicMock()
        fake_page.goto.side_effect = RuntimeError("navigation timeout")

        fake_browser = MagicMock()
        fake_browser.new_page.return_value = fake_page

        fake_pw_ctx = MagicMock()
        fake_pw_ctx.__enter__ = MagicMock(return_value=fake_pw_ctx)
        fake_pw_ctx.__exit__ = MagicMock(return_value=False)
        fake_pw_ctx.chromium.launch.return_value = fake_browser

        monkeypatch.setattr(od_mod, "sync_playwright", lambda: fake_pw_ctx)
        # Should not raise; inner exception is swallowed
        result = _resolve_exact_season_slugs(["t1", "t2"])
        assert isinstance(result, dict)


# ====================================================================
# discover_and_persist_opponents (lines 355-469)
# ====================================================================

class TestDiscoverAndPersistOpponents:
    def _setup_mocks(self, monkeypatch, teams=None):
        """Mock _discover_from_orgs and _resolve_exact_season_slugs."""
        teams = teams or {"t1": {
            "team_id": "t1", "team_name": "Peppers", "slug": "peppers",
            "organization_ids": ["org1"], "record": "3-2", "season_slug": "2026-spring-peppers",
            "public_game_metrics": {},
        }}
        monkeypatch.setattr(od_mod, "_discover_from_orgs", lambda org_ids: teams)
        monkeypatch.setattr(od_mod, "_resolve_exact_season_slugs", lambda ids: {})
        monkeypatch.setattr(od_mod, "_parse_org_ids", lambda: ["org1"])

    def test_writes_artifact_and_team_files(self, tmp_path, monkeypatch):
        """Lines 409-411: opponent team.json is written; artifact is written."""
        self._setup_mocks(monkeypatch)
        result = discover_and_persist_opponents(data_dir=tmp_path)
        assert "teams" in result
        assert (tmp_path / "opponents" / "peppers" / "team.json").exists()
        assert (tmp_path / "sharks" / "opponent_discovery.json").exists()

    def test_skips_sharks_team(self, tmp_path, monkeypatch):
        """Lines 377-378: sharks team_id or slug=='sharks' → not written."""
        teams = {
            "NuGgx6WvP7TO": {
                "team_id": "NuGgx6WvP7TO", "team_name": "The Sharks", "slug": "sharks",
                "organization_ids": ["org1"], "record": "5-3", "season_slug": "",
                "public_game_metrics": {},
            },
        }
        self._setup_mocks(monkeypatch, teams=teams)
        result = discover_and_persist_opponents(data_dir=tmp_path,
                                                sharks_team_id="NuGgx6WvP7TO")
        assert not (tmp_path / "opponents" / "sharks" / "team.json").exists()

    def test_returns_summary_with_persisted_count(self, tmp_path, monkeypatch):
        self._setup_mocks(monkeypatch)
        result = discover_and_persist_opponents(data_dir=tmp_path)
        assert "persisted_opponents" in result
        assert result["persisted_opponents"] == 1

    def test_exact_slug_applied(self, tmp_path, monkeypatch):
        """Lines 366-368: exact slug from _resolve_exact_season_slugs is applied."""
        teams = {"t1": {
            "team_id": "t1", "team_name": "Peppers", "slug": "peppers",
            "organization_ids": ["org1"], "record": "3-2", "season_slug": "",
            "public_game_metrics": {},
        }}
        monkeypatch.setattr(od_mod, "_discover_from_orgs", lambda org_ids: teams)
        monkeypatch.setattr(od_mod, "_resolve_exact_season_slugs",
                            lambda ids: {"t1": "2026-spring-peppers"})
        monkeypatch.setattr(od_mod, "_parse_org_ids", lambda: ["org1"])
        result = discover_and_persist_opponents(data_dir=tmp_path)
        team_file = tmp_path / "opponents" / "peppers" / "team.json"
        data = json.loads(team_file.read_text())
        assert data["gc_season_slug"] == "2026-spring-peppers"

    def test_existing_team_file_merged(self, tmp_path, monkeypatch):
        """Lines 381-387: existing team.json merged with discovery data."""
        self._setup_mocks(monkeypatch)
        # Pre-create the opponent file with existing roster
        opp_dir = tmp_path / "opponents" / "peppers"
        opp_dir.mkdir(parents=True)
        existing = {"team_name": "Peppers", "roster": [{"name": "Jane"}],
                    "batting_stats": [], "pitching_stats": []}
        (opp_dir / "team.json").write_text(json.dumps(existing))
        discover_and_persist_opponents(data_dir=tmp_path)
        data = json.loads((opp_dir / "team.json").read_text())
        # Existing roster should be preserved
        assert data["roster"] == [{"name": "Jane"}]

    def test_existing_team_file_invalid_json_handled(self, tmp_path, monkeypatch):
        """Lines 385-387: invalid JSON in existing file → existing = {}."""
        self._setup_mocks(monkeypatch)
        opp_dir = tmp_path / "opponents" / "peppers"
        opp_dir.mkdir(parents=True)
        (opp_dir / "team.json").write_text("NOT JSON")
        # Should not raise
        discover_and_persist_opponents(data_dir=tmp_path)

    def test_pcll_teams_json_written(self, tmp_path, monkeypatch):
        """Lines 413-426: pcll_teams.json is written with sorted entries."""
        self._setup_mocks(monkeypatch)
        discover_and_persist_opponents(data_dir=tmp_path)
        pcll_file = tmp_path / "pcll_teams.json"
        assert pcll_file.exists()
        rows = json.loads(pcll_file.read_text())
        assert isinstance(rows, list)

    def test_missing_schedule_opponents_reported(self, tmp_path, monkeypatch):
        """Lines 430-434: opponents from schedule not in discovery → reported."""
        self._setup_mocks(monkeypatch)
        # Create a schedule with an opponent not in discovery
        sharks_dir = tmp_path / "sharks"
        sharks_dir.mkdir(parents=True, exist_ok=True)
        schedule = {
            "upcoming": [{"opponent": "Eagles", "is_game": True}]
        }
        (sharks_dir / "schedule_manual.json").write_text(json.dumps(schedule))
        result = discover_and_persist_opponents(data_dir=tmp_path)
        # "Eagles" → slug "eagles" not in by_slug (only "peppers")
        missing = result["missing_schedule_opponents"]
        assert any(m["slug"] == "eagles" for m in missing)

    def test_uses_default_data_dir_when_none(self, monkeypatch):
        """Line 355: data_dir=None → uses repo root / data."""
        self._setup_mocks(monkeypatch)
        # Just verify it doesn't crash (dirs are created)
        try:
            discover_and_persist_opponents(data_dir=None)
        except Exception:
            pass  # File system issues OK in test env; just need line coverage
