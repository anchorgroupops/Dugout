"""Tests for tools/notebooklm_sync.py — pure data builder, no external APIs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import notebooklm_sync as ns


# ---------------------------------------------------------------------------
# _read_json
# ---------------------------------------------------------------------------

class TestReadJson:
    def test_reads_valid_json(self, tmp_path):
        p = tmp_path / "f.json"
        p.write_text('{"a": 1}')
        assert ns._read_json(p) == {"a": 1}

    def test_returns_default_on_missing_file(self, tmp_path):
        assert ns._read_json(tmp_path / "nope.json", default=[]) == []

    def test_returns_none_default_by_default(self, tmp_path):
        assert ns._read_json(tmp_path / "nope.json") is None

    def test_returns_default_on_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json {{{")
        assert ns._read_json(p, default={}) == {}


# ---------------------------------------------------------------------------
# _fmt
# ---------------------------------------------------------------------------

class TestFmt:
    def test_none_returns_dash(self):
        assert ns._fmt(None) == "-"

    def test_empty_returns_dash(self):
        assert ns._fmt("") == "-"

    def test_dash_returns_dash(self):
        assert ns._fmt("-") == "-"

    def test_formats_float_three_decimals(self):
        assert ns._fmt(0.333) == "0.333"

    def test_formats_with_custom_decimals(self):
        assert ns._fmt(1.5, decimals=1) == "1.5"

    def test_strips_commas(self):
        assert ns._fmt("1,234.5") == "1234.500"

    def test_non_numeric_returns_str(self):
        assert ns._fmt("abc") == "abc"

    def test_int_input_formatted(self):
        assert ns._fmt(1) == "1.000"


# ---------------------------------------------------------------------------
# _int
# ---------------------------------------------------------------------------

class TestIntHelper:
    def test_none_returns_dash(self):
        assert ns._int(None) == "-"

    def test_empty_returns_dash(self):
        assert ns._int("") == "-"

    def test_dash_returns_dash(self):
        assert ns._int("-") == "-"

    def test_int_returns_str(self):
        assert ns._int(5) == "5"

    def test_float_truncated(self):
        assert ns._int(3.9) == "3"

    def test_string_float(self):
        assert ns._int("2.0") == "2"

    def test_invalid_returns_str(self):
        assert ns._int("abc") == "abc"


# ---------------------------------------------------------------------------
# _player_name
# ---------------------------------------------------------------------------

class TestPlayerName:
    def test_returns_name_key(self):
        assert ns._player_name({"name": "Jane Doe"}) == "Jane Doe"

    def test_falls_back_to_first_last(self):
        assert ns._player_name({"first": "Jane", "last": "Doe"}) == "Jane Doe"

    def test_returns_unknown_when_all_empty(self):
        assert ns._player_name({}) == "Unknown"

    def test_first_only(self):
        assert ns._player_name({"first": "Jane"}) == "Jane"


# ---------------------------------------------------------------------------
# _batting_std_table
# ---------------------------------------------------------------------------

class TestBattingStdTable:
    def test_empty_players_returns_no_data(self):
        result = ns._batting_std_table([])
        assert "_No data_" in result

    def test_includes_player_name(self):
        p = {"name": "Jane", "batting": {"gp": 5, "pa": 10, "ab": 9, "avg": 0.333,
                                          "obp": 0.4, "ops": 0.8, "h": 3, "singles": 2,
                                          "doubles": 1, "triples": 0, "hr": 0,
                                          "rbi": 2, "r": 1, "bb": 1, "so": 1, "sb": 0}}
        result = ns._batting_std_table([p])
        assert "Jane" in result

    def test_uses_batting_subdict(self):
        p = {"name": "Joe", "number": "7",
             "batting": {"gp": 1, "pa": 4, "ab": 4, "avg": 0.25, "obp": 0.25,
                         "ops": 0.5, "h": 1, "1b": 1, "2b": 0, "3b": 0, "hr": 0,
                         "rbi": 0, "r": 1, "bb": 0, "so": 1, "sb": 0}}
        result = ns._batting_std_table([p])
        assert "Joe" in result
        assert "#" in result

    def test_custom_section_name(self):
        result = ns._batting_std_table([], section_name="Custom")
        assert "Custom" in result

    def test_player_without_batting_subdict_uses_top_level(self):
        p = {"name": "Sam", "gp": 1, "pa": 3, "ab": 3, "avg": 0.333,
             "obp": 0.333, "ops": 0.667, "h": 1}
        result = ns._batting_std_table([p])
        assert "Sam" in result

    def test_1b_alias(self):
        p = {"name": "Alex", "batting": {"1b": 2, "2b": 1, "3b": 0}}
        result = ns._batting_std_table([p])
        assert "Alex" in result


# ---------------------------------------------------------------------------
# _batting_adv_table
# ---------------------------------------------------------------------------

class TestBattingAdvTable:
    def test_empty_returns_no_data(self):
        result = ns._batting_adv_table([])
        assert "_No data_" in result

    def test_uses_batting_advanced(self):
        p = {"name": "Jane", "batting_advanced": {"pa": 10, "qab": 5,
             "qab_pct": 50.0, "bb_k": 1.0, "c_pct": 0.8,
             "hhb": 3, "ld_pct": 0.3, "gb_pct": 0.4,
             "fb_pct": 0.3, "babip": 0.35, "ba_risp": 0.4}}
        result = ns._batting_adv_table([p])
        assert "Jane" in result

    def test_falls_back_to_batting_key(self):
        p = {"name": "Sam", "batting": {"pa": 8}}
        result = ns._batting_adv_table([p])
        assert "Sam" in result

    def test_falls_back_to_top_level(self):
        p = {"name": "Roo"}
        result = ns._batting_adv_table([p])
        assert "Roo" in result

    def test_bb_per_k_alias(self):
        p = {"name": "X", "batting": {"bb_per_k": 2.0}}
        result = ns._batting_adv_table([p])
        assert "X" in result


# ---------------------------------------------------------------------------
# _pitching_std_table
# ---------------------------------------------------------------------------

class TestPitchingStdTable:
    def test_empty_returns_no_data(self):
        result = ns._pitching_std_table([])
        assert "_No data_" in result

    def test_player_without_stats_skipped(self):
        p = {"name": "Jane", "pitching": {}}
        result = ns._pitching_std_table([p])
        assert "_No pitchers with data_" in result

    def test_player_with_stats_included(self):
        p = {"name": "Ace", "pitching": {"gp": 3, "gs": 3, "w": 2, "l": 1,
             "sv": 0, "ip": "12.0", "h": 10, "r": 5, "er": 4,
             "bb": 3, "so": 15, "era": 3.00, "whip": 1.08}}
        result = ns._pitching_std_table([p])
        assert "Ace" in result
        assert "_No pitchers with data_" not in result

    def test_player_without_pitching_subdict_uses_top_level(self):
        p = {"name": "Pitcher", "ip": "5.0", "er": 2}
        result = ns._pitching_std_table([p])
        assert "Pitcher" in result


# ---------------------------------------------------------------------------
# _fielding_std_table
# ---------------------------------------------------------------------------

class TestFieldingStdTable:
    def test_empty_returns_no_data(self):
        result = ns._fielding_std_table([])
        assert "_No data_" in result

    def test_player_without_stats_skipped(self):
        p = {"name": "Jane", "fielding": {}}
        result = ns._fielding_std_table([p])
        assert "_No fielding data_" in result

    def test_player_with_stats_included(self):
        p = {"name": "Glove", "fielding": {"tc": 15, "po": 12, "a": 2, "e": 1,
              "fpct": 0.933, "dp": 0}}
        result = ns._fielding_std_table([p])
        assert "Glove" in result

    def test_player_without_fielding_subdict(self):
        p = {"name": "Catcher", "po": 10, "a": 0, "e": 0}
        result = ns._fielding_std_table([p])
        assert "Catcher" in result


# ---------------------------------------------------------------------------
# _game_section
# ---------------------------------------------------------------------------

class TestGameSection:
    def test_basic_game_title(self):
        game = {"date": "2026-04-01", "opponent": "Eagles", "result": "W"}
        result = ns._game_section(game)
        assert "Eagles" in result
        assert "2026-04-01" in result

    def test_no_score_no_crash(self):
        game = {"date": "2026-04-01", "opponent": "Eagles"}
        result = ns._game_section(game)
        assert "Eagles" in result

    def test_score_appended_to_title(self):
        game = {"date": "2026-04-01", "opponent": "Eagles",
                "score": {"sharks": 5, "opponent": 3}}
        result = ns._game_section(game)
        assert "5-3" in result

    def test_infers_win_result(self):
        game = {"date": "2026-04-01", "opponent": "Eagles",
                "score": {"sharks": 7, "opponent": 2}}
        result = ns._game_section(game)
        assert "W" in result

    def test_infers_loss_result(self):
        game = {"date": "2026-04-01", "opponent": "Eagles",
                "score": {"sharks": 1, "opponent": 4}}
        result = ns._game_section(game)
        assert "L" in result

    def test_infers_tie_result(self):
        game = {"date": "2026-04-01", "opponent": "Eagles",
                "score": {"sharks": 3, "opponent": 3}}
        result = ns._game_section(game)
        assert "T" in result

    def test_explicit_result_not_overwritten(self):
        game = {"date": "2026-04-01", "opponent": "Eagles", "result": "W",
                "score": {"sharks": 5, "opponent": 3}}
        result = ns._game_section(game)
        assert "W" in result

    def test_legacy_sharks_batting(self):
        batting = [{"name": "Jane", "batting": {"h": 2}}]
        game = {"date": "2026-04-01", "opponent": "Eagles",
                "sharks_batting": batting}
        result = ns._game_section(game)
        assert "Sharks Batting" in result

    def test_sharks_dict_with_batting(self):
        batting = [{"name": "Jane", "batting": {"h": 2}}]
        game = {"date": "2026-04-01", "opponent": "Eagles",
                "sharks": {"batting": batting}}
        result = ns._game_section(game)
        assert "Sharks Batting" in result

    def test_sharks_dict_with_pitching(self):
        pitching = [{"name": "Ace", "pitching": {"ip": "5.0", "er": 2, "so": 7}}]
        game = {"date": "2026-04-01", "opponent": "Eagles",
                "sharks": {"pitching": pitching}}
        result = ns._game_section(game)
        assert "Sharks Pitching" in result

    def test_opponent_batting_list(self):
        opp_batting = [{"name": "OppPlayer"}]
        game = {"date": "2026-04-01", "opponent": "Rockets",
                "opponent_stats": opp_batting}
        result = ns._game_section(game)
        assert "Rockets Batting" in result

    def test_opponent_stats_dict_with_batting(self):
        opp_batting = [{"name": "OppPlayer"}]
        game = {"date": "2026-04-01", "opponent": "Rockets",
                "opponent_stats": {"batting": opp_batting}}
        result = ns._game_section(game)
        assert "Rockets Batting" in result

    def test_opponent_stats_dict_with_pitching(self):
        opp_batting = [{"name": "OppPlayer"}]
        opp_pitching = [{"name": "OppPitcher", "pitching": {"ip": "3.0", "er": 1, "so": 4}}]
        game = {"date": "2026-04-01", "opponent": "Rockets",
                "opponent_stats": {"batting": opp_batting, "pitching": opp_pitching}}
        result = ns._game_section(game)
        assert "Rockets Pitching" in result

    def test_opponent_batting_legacy_key(self):
        game = {"date": "2026-04-01", "opponent": "Tigers",
                "opponent_batting": [{"name": "T1"}]}
        result = ns._game_section(game)
        assert "Tigers Batting" in result


# ---------------------------------------------------------------------------
# prepare_notebooklm_payload — full integration tests
# ---------------------------------------------------------------------------

def _patch_dirs(monkeypatch, tmp_path):
    """Redirect all module-level path constants to tmp_path."""
    data_dir = tmp_path / "data"
    sharks_dir = data_dir / "sharks"
    players_dir = sharks_dir / "players"
    monkeypatch.setattr(ns, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(ns, "DATA_DIR", data_dir)
    monkeypatch.setattr(ns, "SHARKS_DIR", sharks_dir)
    monkeypatch.setattr(ns, "PLAYERS_DIR", players_dir)
    monkeypatch.setattr(ns, "PAYLOAD_FILE", data_dir / "notebooklm_payload.md")
    return data_dir, sharks_dir, players_dir


class TestPrepareNotebooklmPayload:
    def test_writes_payload_file(self, tmp_path, monkeypatch):
        data_dir, _, _ = _patch_dirs(monkeypatch, tmp_path)
        result = ns.prepare_notebooklm_payload()
        assert result.exists()
        assert result.read_text()

    def test_returns_payload_path(self, tmp_path, monkeypatch):
        data_dir, _, _ = _patch_dirs(monkeypatch, tmp_path)
        result = ns.prepare_notebooklm_payload()
        assert isinstance(result, Path)
        assert result.name == "notebooklm_payload.md"

    def test_minimal_no_data(self, tmp_path, monkeypatch, capsys):
        """No team/game/player files — writes header only, no crash."""
        _patch_dirs(monkeypatch, tmp_path)
        ns.prepare_notebooklm_payload()
        out = capsys.readouterr().out
        assert "NotebookLM" in out

    def test_uses_team_enriched_fallback(self, tmp_path, monkeypatch):
        """Falls through team_web.json to team_enriched.json."""
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        sharks_dir.mkdir(parents=True)
        team_enriched = sharks_dir / "team_enriched.json"
        team_enriched.write_text(json.dumps({
            "team_name": "The Sharks", "season": "Spring 2026", "record": "5-1",
            "roster": [{"name": "Jane", "number": "7",
                        "batting": {"gp": 5, "pa": 10, "ab": 9, "avg": 0.333,
                                    "obp": 0.4, "ops": 0.8, "h": 3, "singles": 2,
                                    "doubles": 1, "triples": 0, "hr": 0,
                                    "rbi": 2, "r": 1, "bb": 1, "so": 1, "sb": 0}}]
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        assert "The Sharks" in content
        assert "Jane" in content

    def test_uses_team_merged_fallback(self, tmp_path, monkeypatch):
        """Falls through both team_web and team_enriched to team_merged.json."""
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        sharks_dir.mkdir(parents=True)
        (sharks_dir / "team_merged.json").write_text(json.dumps({
            "team_name": "Merged Sharks",
            "roster": [{"name": "Merged Player"}]
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        assert "Merged" in content

    def test_uses_team_json_fallback(self, tmp_path, monkeypatch):
        """Falls all the way to team.json."""
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        sharks_dir.mkdir(parents=True)
        (sharks_dir / "team.json").write_text(json.dumps({
            "team_name": "Plain Sharks",
            "roster": [{"name": "Plain Player"}]
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        assert "Plain" in content

    def test_roster_with_pitching_and_fielding(self, tmp_path, monkeypatch):
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        sharks_dir.mkdir(parents=True)
        (sharks_dir / "team.json").write_text(json.dumps({
            "team_name": "Sharks",
            "roster": [
                {"name": "Ace", "pitching": {"gp": 5, "gs": 5, "w": 3, "l": 2,
                  "sv": 0, "ip": "20.0", "h": 15, "r": 8, "er": 6,
                  "bb": 5, "so": 18, "era": 2.7, "whip": 1.0}},
                {"name": "Glove", "fielding": {"tc": 20, "po": 18, "a": 1,
                  "e": 1, "fpct": 0.95, "dp": 0}},
            ]
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        assert "Ace" in content
        assert "Glove" in content

    def test_team_web_json_batting_section(self, tmp_path, monkeypatch):
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        sharks_dir.mkdir(parents=True)
        (sharks_dir / "team_web.json").write_text(json.dumps({
            "batting": [{"name": "WebBatter"}],
            "pitching": [{"name": "WebPitcher", "pitching": {"ip": "5", "er": 1, "so": 5}}],
            "fielding": [{"name": "WebFielder", "fielding": {"tc": 5, "po": 5, "a": 0, "e": 0}}],
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        assert "WebBatter" in content
        assert "WebPitcher" in content
        assert "WebFielder" in content

    def test_game_files_included(self, tmp_path, monkeypatch):
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        games_dir = sharks_dir / "games"
        games_dir.mkdir(parents=True)
        (games_dir / "game1.json").write_text(json.dumps({
            "date": "2026-04-01", "opponent": "Eagles",
            "sharks_batting": [{"name": "Jane"}]
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        assert "Eagles" in content

    def test_game_file_skipped_when_no_batting_and_no_date(self, tmp_path, monkeypatch):
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        games_dir = sharks_dir / "games"
        games_dir.mkdir(parents=True)
        (games_dir / "game_empty.json").write_text(json.dumps({}))
        result = ns.prepare_notebooklm_payload()
        # Should not crash; empty game ignored
        assert result.exists()

    def test_game_file_with_date_but_no_batting_included(self, tmp_path, monkeypatch):
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        games_dir = sharks_dir / "games"
        games_dir.mkdir(parents=True)
        (games_dir / "game_dateonly.json").write_text(json.dumps({
            "date": "2026-04-05", "opponent": "Bears"
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        assert "Bears" in content

    def test_game_section_exception_writes_error(self, tmp_path, monkeypatch):
        """When _game_section raises, error line is written."""
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        games_dir = sharks_dir / "games"
        games_dir.mkdir(parents=True)
        (games_dir / "game_bad.json").write_text(json.dumps({
            "date": "2026-04-01", "sharks_batting": [{"name": "X"}]
        }))
        original_game_section = ns._game_section
        def bad_game_section(g):
            raise RuntimeError("parse error")
        monkeypatch.setattr(ns, "_game_section", bad_game_section)
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        assert "parse error" in content

    def test_index_json_excluded_from_game_files(self, tmp_path, monkeypatch):
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        games_dir = sharks_dir / "games"
        games_dir.mkdir(parents=True)
        (games_dir / "index.json").write_text(json.dumps({"games": []}))
        result = ns.prepare_notebooklm_payload()
        # Should not crash and index.json content not misread as game
        assert result.exists()

    def test_player_files_included(self, tmp_path, monkeypatch):
        data_dir, sharks_dir, players_dir = _patch_dirs(monkeypatch, tmp_path)
        players_dir.mkdir(parents=True)
        (players_dir / "jane.json").write_text(json.dumps({
            "name": "Jane Doe", "number": "7",
            "games": [{"date": "2026-04-01", "opponent": "Eagles",
                       "batting": {"ab": 3, "h": 1, "bb": 0,
                                   "rbi": 1, "r": 1, "sb": 0, "avg": 0.333}}]
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        assert "Jane Doe" in content

    def test_player_file_no_games_skipped(self, tmp_path, monkeypatch):
        data_dir, sharks_dir, players_dir = _patch_dirs(monkeypatch, tmp_path)
        players_dir.mkdir(parents=True)
        (players_dir / "bench.json").write_text(json.dumps({"name": "Bench Warmer"}))
        result = ns.prepare_notebooklm_payload()
        # bench player has no games, should not appear in game-by-game section
        assert result.exists()

    def test_opponents_dir_included(self, tmp_path, monkeypatch):
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        opp_dir = data_dir / "opponents"
        opp_dir.mkdir(parents=True)
        (opp_dir / "eagles.json").write_text(json.dumps({
            "team_name": "Eagles",
            "batting": [{"name": "Eagle1"}]
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        assert "Eagles" in content

    def test_opponent_from_game_files_aggregated(self, tmp_path, monkeypatch):
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        games_dir = sharks_dir / "games"
        games_dir.mkdir(parents=True)
        (games_dir / "game1.json").write_text(json.dumps({
            "date": "2026-04-01", "opponent": "Rockets",
            "opponent_batting": [{"name": "Rocket1"}]
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        assert "Rockets" in content

    def test_opp_file_skipped_when_already_in_agg(self, tmp_path, monkeypatch):
        """Opponent in opp_agg from game files → opp file skipped to avoid duplication."""
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        games_dir = sharks_dir / "games"
        games_dir.mkdir(parents=True)
        opp_dir = data_dir / "opponents"
        opp_dir.mkdir(parents=True)
        # Rockets appear in both game-based agg AND opponents dir
        (games_dir / "game1.json").write_text(json.dumps({
            "date": "2026-04-01", "opponent": "Rockets",
            "opponent_batting": [{"name": "Rocket1"}]
        }))
        (opp_dir / "rockets.json").write_text(json.dumps({
            "team_name": "Rockets",
            "batting": [{"name": "Rocket2"}]
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        # "Rockets (from opponents dir)" should NOT appear since already in agg
        assert "from opponents dir" not in content

    def test_opp_file_without_team_name_uses_stem(self, tmp_path, monkeypatch):
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        opp_dir = data_dir / "opponents"
        opp_dir.mkdir(parents=True)
        (opp_dir / "blue_jays.json").write_text(json.dumps({
            "roster": [{"name": "BJ Player"}]
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        assert "Blue Jays" in content

    def test_swot_analysis_included(self, tmp_path, monkeypatch):
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        sharks_dir.mkdir(parents=True)
        (sharks_dir / "swot_analysis.json").write_text(json.dumps({
            "strengths": [{"title": "Speed", "description": "Fastest team"}],
            "weaknesses": ["Poor bunting"],
            "opportunities": [],
            "threats": ["Rain"]
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        assert "SWOT" in content
        assert "Speed" in content
        assert "Poor bunting" in content

    def test_swot_dict_items(self, tmp_path, monkeypatch):
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        sharks_dir.mkdir(parents=True)
        (sharks_dir / "swot_analysis.json").write_text(json.dumps({
            "strengths": [{"title": "Defense", "description": "Great fielding"}],
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        assert "Defense" in content
        assert "Great fielding" in content

    def test_opponent_batting_via_opponent_stats_key(self, tmp_path, monkeypatch):
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        games_dir = sharks_dir / "games"
        games_dir.mkdir(parents=True)
        (games_dir / "game1.json").write_text(json.dumps({
            "date": "2026-04-01", "opponent": "Storm",
            "opponent_stats": {"batting": [{"name": "Storm1"}]}
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        assert "Storm" in content

    def test_game_file_no_batting_no_date_skipped(self, tmp_path, monkeypatch):
        """Line 305: game with no batting AND no date is skipped (continue branch)."""
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        games_dir = sharks_dir / "games"
        games_dir.mkdir(parents=True)
        # Has opponent but no date and no batting data — should be skipped
        (games_dir / "future_game.json").write_text(json.dumps({
            "opponent": "Future Team",
            "date": "",  # empty date
        }))
        result = ns.prepare_notebooklm_payload()
        content = result.read_text()
        # Future Team should not appear since game was skipped
        assert "Future Team" not in content

    def test_empty_opp_file_skipped(self, tmp_path, monkeypatch):
        """Line 374: opponent file that returns empty dict is skipped (continue)."""
        data_dir, sharks_dir, _ = _patch_dirs(monkeypatch, tmp_path)
        opp_dir = data_dir / "opponents"
        opp_dir.mkdir(parents=True)
        # Write a valid JSON file but with empty content (triggers continue on line 374)
        (opp_dir / "empty_opp.json").write_text("{}")
        result = ns.prepare_notebooklm_payload()
        # Should not crash; empty opp ignored
        assert result.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
