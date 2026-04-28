"""Tests for tools/gc_csv_ingest.py — GC CSV parsing and team JSON assembly."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tools.gc_csv_ingest import (
    _has_data,
    _merge_players,
    _val,
    build_app_stats_json,
    build_team_json,
    parse_gc_csv,
    parse_player_row,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(positions: dict | None = None) -> list[str]:
    """200-element CSV row of empty strings with selective overrides by column index."""
    row = [""] * 200
    for idx, val in (positions or {}).items():
        row[int(idx)] = str(val)
    return row


_BATTER_DEFAULTS: dict[int, str] = {
    # Identity
    0: "7", 1: "Smith", 2: "Jane",
    # Batting standard (cols 3-28)
    3: "8", 4: "30", 5: "26",              # gp, pa, ab
    6: ".346", 7: ".400", 8: ".723", 9: ".423",  # avg, obp, ops, slg
    10: "9", 11: "6", 12: "2", 13: "1", 14: "0",  # h, 1b, 2b, 3b, hr
    15: "5", 16: "4",                       # rbi, r
    17: "3", 18: "4", 19: "0",             # bb, so, kl
    20: "1", 21: "0", 22: "0",             # hbp, sac, sf
    23: "0", 24: "0",                       # roe, fc
    25: "2", 26: "100.0", 27: "0", 28: "0",  # sb, sb_pct, cs, pik
    # Fielding (cols 174-180)
    174: "15", 175: "3", 176: "12", 177: ".933", 178: "1", 179: "0", 180: "0",
    # Innings played total (col 199)
    199: "40.0",
}

_PITCH_EXTRA: dict[int, str] = {
    0: "11", 1: "Jones", 2: "Amy",
    54: "12.1",   # ip
    55: "5",      # gp
    56: "5",      # gs
    57: "45",     # bf
    58: "200",    # np
    59: "3",      # w
    60: "1",      # l
    61: "0",      # sv
    62: "0",      # svo
    63: "0",      # bs
    65: "8",      # h
    66: "4",      # r
    67: "3",      # er
    68: "2",      # bb
    69: "15",     # so
    70: "0",      # kl
    71: "1",      # hbp
    72: "2.19",   # era
    73: "0.81",   # whip
    74: "5",      # lob
    75: "0",      # bk
    76: "0",      # pik
    77: "0",      # cs
    78: "0",      # sb
    79: "",       # sb_pct
    80: "1",      # wp
    81: ".178",   # baa (pitching_advanced col)
}

_CATCH_EXTRA: dict[int, str] = {
    0: "3", 1: "Lee", 2: "Kim",
    181: "30.0",  # inn
    182: "1",     # pb
    183: "3",     # sb
    184: "5",     # sb_att
    185: "2",     # cs
    186: ".400",  # cs_pct
    187: "0",     # pik
    188: "0",     # ci
}


def _batter_row(extra: dict | None = None) -> list[str]:
    """Complete, valid batter-only row (no pitching data)."""
    positions = {**_BATTER_DEFAULTS, **(extra or {})}
    return _make_row(positions)


def _pitcher_row(extra: dict | None = None) -> list[str]:
    """Row with pitching data populated."""
    positions = {**_BATTER_DEFAULTS, **_PITCH_EXTRA, **(extra or {})}
    return _make_row(positions)


def _catcher_row(extra: dict | None = None) -> list[str]:
    """Row with catching stats populated."""
    positions = {**_BATTER_DEFAULTS, **_CATCH_EXTRA, **(extra or {})}
    return _make_row(positions)


# ---------------------------------------------------------------------------
# _val — sentinel and bounds handling
# ---------------------------------------------------------------------------

class TestVal:
    def test_normal_string(self):
        row = ["hello", "world"]
        assert _val(row, 0) == "hello"
        assert _val(row, 1) == "world"

    @pytest.mark.parametrize("sentinel", ["", "-", "—", "N/A"])
    def test_sentinels_collapse_to_empty(self, sentinel):
        row = [sentinel]
        assert _val(row, 0) == ""

    def test_whitespace_is_stripped(self):
        assert _val(["  .346  "], 0) == ".346"

    def test_index_beyond_row_returns_empty(self):
        assert _val(["a", "b"], 99) == ""

    def test_numeric_string_passthrough(self):
        row = _batter_row()
        assert _val(row, 4) == "30"   # pa


# ---------------------------------------------------------------------------
# _has_data — section emptiness check
# ---------------------------------------------------------------------------

class TestHasData:
    def test_all_empty(self):
        assert _has_data({"a": "", "b": "", "c": ""}) is False

    def test_any_populated(self):
        assert _has_data({"a": "", "b": "5", "c": ""}) is True

    def test_single_non_empty(self):
        assert _has_data({"x": "0"}) is True   # "0" is not ""

    def test_empty_dict(self):
        assert _has_data({}) is False


# ---------------------------------------------------------------------------
# parse_player_row — row-level parsing
# ---------------------------------------------------------------------------

class TestParsePlayerRow:
    def test_batter_only_returns_dict(self):
        player = parse_player_row(_batter_row(), core_set=set())
        assert player is not None
        assert player["first"] == "Jane"
        assert player["last"] == "Smith"
        assert player["number"] == "7"

    def test_batting_counts_parsed(self):
        player = parse_player_row(_batter_row(), core_set=set())
        b = player["batting"]
        assert b["pa"] == 30
        assert b["ab"] == 26
        assert b["h"] == 9
        assert b["doubles"] == 2
        assert b["triples"] == 1

    def test_batting_rate_stats_parsed(self):
        player = parse_player_row(_batter_row(), core_set=set())
        b = player["batting"]
        assert b["avg"] == pytest.approx(0.346)
        assert b["obp"] == pytest.approx(0.400)

    def test_no_pitching_when_ip_empty(self):
        player = parse_player_row(_batter_row(), core_set=set())
        assert player["pitching"] is None
        assert player["pitching_advanced"] is None
        assert player["pitching_breakdown"] is None

    def test_pitcher_row_has_pitching(self):
        player = parse_player_row(_pitcher_row(), core_set=set())
        assert player["pitching"] is not None
        p = player["pitching"]
        assert p["ip"] == "12.1"
        assert p["era"] == pytest.approx(2.19)
        assert p["w"] == 3

    def test_pitcher_pitching_advanced(self):
        player = parse_player_row(_pitcher_row(), core_set=set())
        assert player["pitching_advanced"] is not None

    def test_totals_row_skipped(self):
        row = _make_row({0: "Totals"})
        assert parse_player_row(row, core_set=set()) is None

    def test_glossary_row_skipped(self):
        row = _make_row({0: "Glossary"})
        assert parse_player_row(row, core_set=set()) is None

    def test_all_empty_row_skipped(self):
        row = _make_row()
        assert parse_player_row(row, core_set=set()) is None

    def test_catcher_row_has_catching(self):
        player = parse_player_row(_catcher_row(), core_set=set())
        assert player["catching"] is not None
        c = player["catching"]
        assert c["inn"] == "30.0"
        assert c["cs"] == 2

    def test_non_catcher_has_no_catching(self):
        player = parse_player_row(_batter_row(), core_set=set())
        assert player["catching"] is None

    def test_core_flag_set_when_in_core_set(self):
        player = parse_player_row(_batter_row(), core_set={"jane smith"})
        assert player["core"] is True
        assert player["borrowed"] is False

    def test_borrowed_flag_set_when_not_in_core_set(self):
        player = parse_player_row(_batter_row(), core_set=set())
        assert player["core"] is False
        assert player["borrowed"] is True

    def test_games_played_from_batting_gp(self):
        player = parse_player_row(_batter_row(), core_set=set())
        assert player["games_played"] == 8

    def test_innings_played_populated(self):
        player = parse_player_row(_batter_row(), core_set=set())
        assert player["innings_played"]["total"] == "40.0"

    def test_fielding_populated(self):
        player = parse_player_row(_batter_row(), core_set=set())
        f = player["fielding"]
        assert f["po"] == 12
        assert f["a"] == 3
        assert f["e"] == 1
        assert f["fpct"] == pytest.approx(0.933)

    def test_ip_zero_treated_as_no_pitching(self):
        row = _pitcher_row({54: "0.0"})
        player = parse_player_row(row, core_set=set())
        assert player["pitching"] is None


# ---------------------------------------------------------------------------
# _merge_players — duplicate jersey number merging
# ---------------------------------------------------------------------------

class TestMergePlayers:
    def _player(self, ab, h, bb, hbp, pa, singles, doubles, triples, hr):
        batting = {
            "ab": ab, "h": h, "bb": bb, "hbp": hbp, "pa": pa,
            "singles": singles, "doubles": doubles, "triples": triples, "hr": hr,
            **{k: 0 for k in ["gp", "r", "rbi", "so", "kl", "sac", "sf",
                               "roe", "fc", "sb", "cs", "pik"]},
        }
        return {
            "first": "X", "last": "Y", "number": "7",
            "games_played": batting["gp"],
            "batting": batting,
            "batting_advanced": None,
            "pitching": None,
            "pitching_advanced": None,
            "fielding": None,
            "catching": None,
            "innings_played": None,
        }

    def test_counting_stats_summed(self):
        p1 = self._player(ab=10, h=3, bb=1, hbp=0, pa=12, singles=2, doubles=1, triples=0, hr=0)
        p2 = self._player(ab=8,  h=2, bb=2, hbp=1, pa=12, singles=2, doubles=0, triples=0, hr=0)
        merged = _merge_players(p1, p2)
        b = merged["batting"]
        assert b["ab"] == 18
        assert b["h"] == 5
        assert b["bb"] == 3

    def test_avg_recalculated(self):
        p1 = self._player(ab=10, h=5, bb=0, hbp=0, pa=10, singles=5, doubles=0, triples=0, hr=0)
        p2 = self._player(ab=10, h=3, bb=0, hbp=0, pa=10, singles=3, doubles=0, triples=0, hr=0)
        merged = _merge_players(p1, p2)
        assert merged["batting"]["avg"] == pytest.approx(8 / 20)

    def test_obp_recalculated(self):
        p1 = self._player(ab=10, h=3, bb=2, hbp=1, pa=14, singles=3, doubles=0, triples=0, hr=0)
        p2 = self._player(ab=10, h=4, bb=1, hbp=0, pa=12, singles=4, doubles=0, triples=0, hr=0)
        merged = _merge_players(p1, p2)
        b = merged["batting"]
        expected_obp = (7 + 3 + 1) / 26
        assert b["obp"] == pytest.approx(expected_obp, abs=1e-3)

    def test_slg_recalculated(self):
        # tb = singles(1+2=3) + 2*doubles(1) + 3*triples(1) + 4*hr = 3+2+3 = 8
        p1 = self._player(ab=10, h=3, bb=0, hbp=0, pa=10, singles=1, doubles=1, triples=1, hr=0)
        p2 = self._player(ab=10, h=2, bb=0, hbp=0, pa=10, singles=2, doubles=0, triples=0, hr=0)
        merged = _merge_players(p1, p2)
        b = merged["batting"]
        expected_slg = 8 / 20
        assert b["slg"] == pytest.approx(expected_slg, abs=1e-3)

    def test_ops_is_obp_plus_slg(self):
        p1 = self._player(ab=20, h=6, bb=2, hbp=0, pa=22, singles=4, doubles=2, triples=0, hr=0)
        p2 = self._player(ab=10, h=3, bb=1, hbp=0, pa=11, singles=3, doubles=0, triples=0, hr=0)
        merged = _merge_players(p1, p2)
        b = merged["batting"]
        assert b["ops"] == pytest.approx(b["obp"] + b["slg"], abs=1e-3)

    def test_zero_ab_no_divide_error(self):
        p1 = self._player(ab=0, h=0, bb=0, hbp=0, pa=0, singles=0, doubles=0, triples=0, hr=0)
        p2 = self._player(ab=0, h=0, bb=0, hbp=0, pa=0, singles=0, doubles=0, triples=0, hr=0)
        merged = _merge_players(p1, p2)
        b = merged["batting"]
        assert b["avg"] == 0.0
        assert b["slg"] == 0.0

    def test_zero_pa_no_divide_error(self):
        p1 = self._player(ab=0, h=0, bb=0, hbp=0, pa=0, singles=0, doubles=0, triples=0, hr=0)
        p2 = self._player(ab=0, h=0, bb=0, hbp=0, pa=0, singles=0, doubles=0, triples=0, hr=0)
        merged = _merge_players(p1, p2)
        assert merged["batting"]["obp"] == 0.0

    def test_last_name_preserved_if_first_is_blank(self):
        p1 = self._player(ab=5, h=1, bb=0, hbp=0, pa=5, singles=1, doubles=0, triples=0, hr=0)
        p1["last"] = ""
        p2 = self._player(ab=5, h=1, bb=0, hbp=0, pa=5, singles=1, doubles=0, triples=0, hr=0)
        p2["last"] = "Garcia"
        merged = _merge_players(p1, p2)
        assert merged["last"] == "Garcia"

    def test_pitching_section_filled_from_second_entry(self):
        p1 = self._player(ab=5, h=1, bb=0, hbp=0, pa=5, singles=1, doubles=0, triples=0, hr=0)
        p1["pitching"] = None
        p2 = self._player(ab=5, h=1, bb=0, hbp=0, pa=5, singles=1, doubles=0, triples=0, hr=0)
        p2["pitching"] = {"ip": "3.0", "era": 2.0}
        merged = _merge_players(p1, p2)
        assert merged["pitching"] == {"ip": "3.0", "era": 2.0}


# ---------------------------------------------------------------------------
# build_app_stats_json — output shape and name abbreviation
# ---------------------------------------------------------------------------

class TestBuildAppStatsJson:
    def _minimal_roster(self):
        return [
            {
                "first": "Emma", "last": "Hourahan", "number": "4",
                "batting": {
                    "gp": 8, "pa": 28, "ab": 24, "avg": 0.333, "obp": 0.400,
                    "ops": 0.800, "slg": 0.400, "h": 8,
                    "singles": 5, "doubles": 2, "triples": 0, "hr": 1,
                    "rbi": 6, "bb": 3, "hbp": 1, "so": 3, "sb": 2, "cs": 0,
                },
                "batting_advanced": {
                    "qab": 12, "qab_pct": 0.429, "pa_per_bb": 9.3,
                    "bb_per_k": 1.0, "c_pct": 0.800, "hhb": 4, "ld_pct": 0.25,
                },
                "pitching": None,
                "fielding": {"tc": 20, "po": 18, "a": 2, "fpct": 0.950, "e": 1, "dp": 0, "tp": 0},
                "catching": None,
            }
        ]

    def test_returns_batting_pitching_fielding_keys(self):
        result = build_app_stats_json(self._minimal_roster())
        assert "batting" in result
        assert "pitching" in result
        assert "fielding" in result

    def test_abbreviated_name_format(self):
        result = build_app_stats_json(self._minimal_roster())
        assert result["batting"][0]["name"] == "E Hourahan"

    def test_no_pitching_entry_for_batter_only(self):
        result = build_app_stats_json(self._minimal_roster())
        assert result["pitching"] == []

    def test_fielding_entry_present(self):
        result = build_app_stats_json(self._minimal_roster())
        assert len(result["fielding"]) == 1
        assert result["fielding"][0]["po"] == "18"

    def test_advanced_batting_fields_included(self):
        result = build_app_stats_json(self._minimal_roster())
        entry = result["batting"][0]
        assert entry["qab"] == "12"
        assert entry["ld_pct"] == "0.25"

    def test_pitcher_included_in_pitching_list(self):
        roster = self._minimal_roster()
        roster[0]["pitching"] = {
            "ip": "5.0", "gp": 3, "gs": 3, "bf": 20, "np": 80,
            "w": 2, "l": 0, "sv": 0, "svo": 0, "bs": 0,
            "h": 4, "r": 2, "er": 2, "bb": 1, "so": 10,
            "hbp": 0, "era": 3.60, "whip": 1.00, "wp": 0, "bk": 0,
            "lob": 3, "sb": 0, "cs": 0, "baa": 0.200,
        }
        result = build_app_stats_json(roster)
        assert len(result["pitching"]) == 1
        assert result["pitching"][0]["ip"] == "5.0"
        assert result["pitching"][0]["era"] == "3.6"

    def test_player_with_no_last_name(self):
        roster = [{
            "first": "Zoe", "last": "", "number": "9",
            "batting": {"gp": 1, "pa": 4, "ab": 3, "avg": 0.0, "obp": 0.0,
                        "ops": 0.0, "slg": 0.0, "h": 0, "singles": 0,
                        "doubles": 0, "triples": 0, "hr": 0, "rbi": 0,
                        "bb": 0, "hbp": 0, "so": 2, "sb": 0, "cs": 0},
            "batting_advanced": None,
            "pitching": None,
            "fielding": None,
            "catching": None,
        }]
        result = build_app_stats_json(roster)
        assert result["batting"][0]["name"] == "Zoe"


# ---------------------------------------------------------------------------
# parse_gc_csv — end-to-end CSV file parsing
# ---------------------------------------------------------------------------

class TestParseGcCsv:
    def _write_csv(self, tmp_path: Path, data_rows: list[list[str]]) -> Path:
        """Write a valid GC-format CSV (2-row header + data rows)."""
        csv_path = tmp_path / "test_export.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Section labels"] + [""] * 199)
            writer.writerow(["#", "Last", "First"] + ["stat"] * 197)
            for row in data_rows:
                writer.writerow(row)
        return csv_path

    def test_parses_single_player(self, tmp_path):
        csv_path = self._write_csv(tmp_path, [_batter_row()])
        roster = parse_gc_csv(csv_path, team_dir=tmp_path)
        assert len(roster) == 1
        assert roster[0]["first"] == "Jane"

    def test_skips_totals_row(self, tmp_path):
        totals = _make_row({0: "Totals"})
        csv_path = self._write_csv(tmp_path, [_batter_row(), totals])
        roster = parse_gc_csv(csv_path, team_dir=tmp_path)
        assert len(roster) == 1

    def test_merges_duplicate_jersey_numbers(self, tmp_path):
        row1 = _batter_row({0: "11", 1: "Alpha", 2: "Ann", 4: "10", 5: "8", 10: "3"})
        row2 = _batter_row({0: "11", 1: "Alpha", 2: "Ann", 4: "8",  5: "6", 10: "2"})
        csv_path = self._write_csv(tmp_path, [row1, row2])
        roster = parse_gc_csv(csv_path, team_dir=tmp_path)
        assert len(roster) == 1
        assert roster[0]["batting"]["pa"] == 18
        assert roster[0]["batting"]["h"] == 5

    def test_multiple_distinct_players(self, tmp_path):
        row_a = _batter_row({0: "3", 1: "Lee", 2: "Kim"})
        row_b = _batter_row({0: "5", 1: "Park", 2: "Alex"})
        csv_path = self._write_csv(tmp_path, [row_a, row_b])
        roster = parse_gc_csv(csv_path, team_dir=tmp_path)
        assert len(roster) == 2

    def test_player_without_number_collected_separately(self, tmp_path):
        no_num = _batter_row({0: "", 1: "Anon", 2: "Player"})
        csv_path = self._write_csv(tmp_path, [_batter_row(), no_num])
        roster = parse_gc_csv(csv_path, team_dir=tmp_path)
        assert len(roster) == 2
