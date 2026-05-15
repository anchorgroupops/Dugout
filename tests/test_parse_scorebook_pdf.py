"""Tests for pure functions in tools/parse_scorebook_pdf.py.

pdfplumber is patched before the import so tests run without the library
being installed.
"""
from __future__ import annotations

import sys
import unittest.mock as mock
from pathlib import Path

# Patch pdfplumber before the module is imported so the sys.exit(1) branch
# is never triggered.
sys.modules.setdefault("pdfplumber", mock.MagicMock())

# Ensure tools/ is on the path.
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from parse_scorebook_pdf import (  # noqa: E402
    _metadata_from_filename,
    _norm,
    _slug_from_name,
    classify,
    compute_team_totals,
    stats_from_at_bats,
)

import pytest


# ---------------------------------------------------------------------------
# _norm
# ---------------------------------------------------------------------------

class TestNorm:
    def test_strips_leading_trailing_whitespace(self):
        assert _norm("  1B  ") == "1B"

    def test_uppercases(self):
        assert _norm("hr") == "HR"

    def test_removes_internal_spaces(self):
        assert _norm("1 B") == "1B"

    def test_removes_newlines(self):
        assert _norm("K\n") == "K"

    def test_collapses_e_plus_variant(self):
        assert _norm("E+E") == "E"

    def test_collapses_e_plus_anything(self):
        assert _norm("E+FC") == "E"

    def test_collapses_kd_variant(self):
        assert _norm("KD") == "K"

    def test_collapses_kd3(self):
        assert _norm("KD3") == "K"

    def test_collapses_kd1(self):
        assert _norm("KD1") == "K"

    def test_collapses_kd2(self):
        assert _norm("KD2") == "K"

    def test_plain_k_unchanged(self):
        assert _norm("K") == "K"

    def test_plain_1b_unchanged(self):
        assert _norm("1B") == "1B"

    def test_mixed_case_and_spaces_removed(self):
        assert _norm("  2b  ") == "2B"


# ---------------------------------------------------------------------------
# classify — parametrized over every documented input type
# ---------------------------------------------------------------------------

class TestClassify:
    # Hits
    @pytest.mark.parametrize("raw,expected_key", [
        ("1B", "singles"),
        ("2B", "doubles"),
        ("3B", "triples"),
        ("HR", "hr"),
    ])
    def test_hits_are_at_bats(self, raw, expected_key):
        key, is_ab = classify(raw)
        assert key == expected_key
        assert is_ab is True

    # Walks
    @pytest.mark.parametrize("raw", ["BB", "IBB"])
    def test_walks_not_at_bats(self, raw):
        key, is_ab = classify(raw)
        assert key == "bb"
        assert is_ab is False

    # HBP
    def test_hbp_not_at_bat(self):
        key, is_ab = classify("HBP")
        assert key == "hbp"
        assert is_ab is False

    # Strikeouts — all variants
    @pytest.mark.parametrize("raw", ["K", "KL", "KD", "KD3", "KD1", "KD2"])
    def test_strikeout_variants_are_at_bats(self, raw):
        key, is_ab = classify(raw)
        assert key == "so"
        assert is_ab is True

    # Outs
    @pytest.mark.parametrize("raw", ["G", "F", "L", "DP", "GDP", "TP", "E", "ROE", "FC"])
    def test_outs_are_at_bats(self, raw):
        key, is_ab = classify(raw)
        assert key == "out"
        assert is_ab is True

    # Sacrifice / SAC variants
    @pytest.mark.parametrize("raw", ["SAC", "SH", "SF"])
    def test_sac_variants_not_at_bats(self, raw):
        key, is_ab = classify(raw)
        assert key == "sac"
        assert is_ab is False

    # Noise — should return None
    @pytest.mark.parametrize("raw", ["SB", "PB", "WP", "3", "2", "UNKNOWN"])
    def test_noise_returns_none(self, raw):
        assert classify(raw) is None

    # Case-insensitive via _norm
    def test_lowercase_hit_classified(self):
        key, is_ab = classify("hr")
        assert key == "hr"
        assert is_ab is True

    # KD prefix collapses to strikeout
    def test_kd_prefix_is_strikeout(self):
        key, is_ab = classify("KD3")
        assert key == "so"
        assert is_ab is True

    # Error with "E+" prefix collapses to out
    def test_error_plus_variant_is_out(self):
        key, is_ab = classify("E+E")
        assert key == "out"
        assert is_ab is True


# ---------------------------------------------------------------------------
# stats_from_at_bats
# ---------------------------------------------------------------------------

class TestStatsFromAtBats:
    # ------------------------------------------------------------------
    # Empty input
    # ------------------------------------------------------------------

    def test_empty_list_all_zeros(self):
        s = stats_from_at_bats([])
        for key in ("pa", "ab", "h", "singles", "doubles", "triples", "hr",
                    "bb", "hbp", "so", "sac"):
            assert s[key] == 0, f"{key} should be 0 for empty input"

    def test_empty_list_derived_stats_none(self):
        s = stats_from_at_bats([])
        assert s["avg"] is None
        assert s["obp"] is None
        assert s["slg"] is None
        assert s["ops"] is None

    # ------------------------------------------------------------------
    # All strikeouts
    # ------------------------------------------------------------------

    def test_three_strikeouts_so_count(self):
        s = stats_from_at_bats(["K", "K", "K"])
        assert s["so"] == 3

    def test_three_strikeouts_ab(self):
        s = stats_from_at_bats(["K", "K", "K"])
        assert s["ab"] == 3

    def test_three_strikeouts_pa(self):
        s = stats_from_at_bats(["K", "K", "K"])
        assert s["pa"] == 3

    def test_three_strikeouts_no_hits(self):
        s = stats_from_at_bats(["K", "K", "K"])
        assert s["h"] == 0

    def test_three_strikeouts_avg_zero(self):
        # 0 hits / 3 AB → 0.0 (not None)
        s = stats_from_at_bats(["K", "K", "K"])
        assert s["avg"] == 0.0

    def test_three_strikeouts_slg_zero(self):
        s = stats_from_at_bats(["K", "K", "K"])
        assert s["slg"] == 0.0

    def test_three_strikeouts_obp_zero(self):
        # 0 numerator / 3 PA
        s = stats_from_at_bats(["K", "K", "K"])
        assert s["obp"] == 0.0

    # ------------------------------------------------------------------
    # Pure hits
    # ------------------------------------------------------------------

    def test_single_counted(self):
        s = stats_from_at_bats(["1B"])
        assert s["singles"] == 1
        assert s["h"] == 1
        assert s["ab"] == 1
        assert s["pa"] == 1

    def test_double_counted(self):
        s = stats_from_at_bats(["2B"])
        assert s["doubles"] == 1
        assert s["h"] == 1

    def test_triple_counted(self):
        s = stats_from_at_bats(["3B"])
        assert s["triples"] == 1
        assert s["h"] == 1

    def test_home_run_counted(self):
        s = stats_from_at_bats(["HR"])
        assert s["hr"] == 1
        assert s["h"] == 1

    def test_avg_computed_for_pure_hits(self):
        # 2 singles in 4 AB → avg = 0.500
        s = stats_from_at_bats(["1B", "1B", "K", "G"])
        assert s["avg"] == pytest.approx(0.5, abs=1e-3)

    # ------------------------------------------------------------------
    # Mixed: hits, walks, outs
    # ------------------------------------------------------------------

    def test_mixed_pa_count(self):
        # 1B, BB, K, G → 4 PA
        s = stats_from_at_bats(["1B", "BB", "K", "G"])
        assert s["pa"] == 4

    def test_mixed_ab_count(self):
        # BB does not count as AB → 3 AB
        s = stats_from_at_bats(["1B", "BB", "K", "G"])
        assert s["ab"] == 3

    def test_mixed_h_count(self):
        s = stats_from_at_bats(["1B", "BB", "K", "G"])
        assert s["h"] == 1

    def test_mixed_bb_count(self):
        s = stats_from_at_bats(["1B", "BB", "K", "G"])
        assert s["bb"] == 1

    def test_mixed_so_count(self):
        s = stats_from_at_bats(["1B", "BB", "K", "G"])
        assert s["so"] == 1

    def test_mixed_avg(self):
        # 1H / 3AB = 0.333
        s = stats_from_at_bats(["1B", "BB", "K", "G"])
        assert s["avg"] == pytest.approx(0.333, abs=1e-3)

    def test_mixed_obp(self):
        # (1H + 1BB + 0HBP) / 4PA = 0.500
        s = stats_from_at_bats(["1B", "BB", "K", "G"])
        assert s["obp"] == pytest.approx(0.5, abs=1e-3)

    def test_mixed_slg(self):
        # TB = 1 single = 1; 1/3AB = 0.333
        s = stats_from_at_bats(["1B", "BB", "K", "G"])
        assert s["slg"] == pytest.approx(0.333, abs=1e-3)

    def test_mixed_ops(self):
        s = stats_from_at_bats(["1B", "BB", "K", "G"])
        assert s["ops"] == pytest.approx(s["obp"] + s["slg"], abs=1e-3)

    # ------------------------------------------------------------------
    # SAC: counts as PA but not AB
    # ------------------------------------------------------------------

    def test_sac_increments_pa(self):
        s = stats_from_at_bats(["SAC"])
        assert s["pa"] == 1

    def test_sac_does_not_increment_ab(self):
        s = stats_from_at_bats(["SAC"])
        assert s["ab"] == 0

    def test_sac_counted_in_sac_field(self):
        s = stats_from_at_bats(["SAC"])
        assert s["sac"] == 1

    def test_sac_avg_none_when_no_ab(self):
        s = stats_from_at_bats(["SAC"])
        assert s["avg"] is None

    def test_sac_obp_computed_from_pa(self):
        # 0 hits, 0 BB, 0 HBP / 1 PA → 0.0
        s = stats_from_at_bats(["SAC"])
        assert s["obp"] == 0.0

    def test_sac_mixed_with_hit(self):
        # 1B + SAC → pa=2, ab=1, h=1, avg=1.0
        s = stats_from_at_bats(["1B", "SAC"])
        assert s["pa"] == 2
        assert s["ab"] == 1
        assert s["h"] == 1
        assert s["avg"] == pytest.approx(1.0)

    # ------------------------------------------------------------------
    # HBP: counts in OBP numerator, not in AB
    # ------------------------------------------------------------------

    def test_hbp_increments_pa(self):
        s = stats_from_at_bats(["HBP"])
        assert s["pa"] == 1

    def test_hbp_does_not_increment_ab(self):
        s = stats_from_at_bats(["HBP"])
        assert s["ab"] == 0

    def test_hbp_counted_in_hbp_field(self):
        s = stats_from_at_bats(["HBP"])
        assert s["hbp"] == 1

    def test_hbp_in_obp_numerator(self):
        # HBP alone: 0H + 0BB + 1HBP / 1PA = 1.0
        s = stats_from_at_bats(["HBP"])
        assert s["obp"] == pytest.approx(1.0)

    def test_hbp_mixed_obp(self):
        # 1B, HBP, G → pa=3, ab=2, h=1, bb=0, hbp=1
        # obp = (1+0+1)/3 = 0.667
        s = stats_from_at_bats(["1B", "HBP", "G"])
        assert s["obp"] == pytest.approx(0.667, abs=1e-3)

    # ------------------------------------------------------------------
    # SLG: total bases
    # ------------------------------------------------------------------

    def test_slg_double_gives_two_bases(self):
        # 2B only → TB=2, ab=1 → slg=2.0
        s = stats_from_at_bats(["2B"])
        assert s["slg"] == pytest.approx(2.0)

    def test_slg_triple_gives_three_bases(self):
        s = stats_from_at_bats(["3B"])
        assert s["slg"] == pytest.approx(3.0)

    def test_slg_hr_gives_four_bases(self):
        s = stats_from_at_bats(["HR"])
        assert s["slg"] == pytest.approx(4.0)

    def test_slg_mixed_total_bases(self):
        # 1B(1) + 2B(2) + HR(4) + K(0) → TB=7, ab=4 → 1.750
        s = stats_from_at_bats(["1B", "2B", "HR", "K"])
        assert s["slg"] == pytest.approx(7 / 4, abs=1e-3)

    # ------------------------------------------------------------------
    # Noise is silently ignored
    # ------------------------------------------------------------------

    def test_noise_ignored_in_pa(self):
        s = stats_from_at_bats(["SB", "WP", "PB"])
        assert s["pa"] == 0

    def test_noise_mixed_with_hit(self):
        s = stats_from_at_bats(["1B", "SB"])
        assert s["pa"] == 1
        assert s["h"] == 1

    # ------------------------------------------------------------------
    # KD variant normalised to strikeout
    # ------------------------------------------------------------------

    def test_kd_variant_counts_as_so(self):
        s = stats_from_at_bats(["KD3", "KD1"])
        assert s["so"] == 2
        assert s["ab"] == 2


# ---------------------------------------------------------------------------
# compute_team_totals
# ---------------------------------------------------------------------------

def _make_player(pa, ab, h, singles=0, doubles=0, triples=0, hr=0,
                 bb=0, hbp=0, so=0, sac=0):
    """Build a minimal player dict with a 'batting' sub-dict."""
    return {
        "name": "Test Player",
        "batting": {
            "pa": pa, "ab": ab, "h": h,
            "singles": singles, "doubles": doubles, "triples": triples, "hr": hr,
            "bb": bb, "hbp": hbp, "so": so, "sac": sac,
        },
    }


class TestComputeTeamTotals:
    def test_empty_players_list_all_zeros(self):
        t = compute_team_totals([])
        for key in ("pa", "ab", "h", "singles", "doubles", "triples",
                    "hr", "bb", "hbp", "so", "sac"):
            assert t[key] == 0

    def test_empty_players_avg_none(self):
        t = compute_team_totals([])
        assert t["avg"] is None

    def test_single_player_values_pass_through(self):
        p = _make_player(pa=4, ab=3, h=2, singles=1, doubles=1)
        t = compute_team_totals([p])
        assert t["pa"] == 4
        assert t["ab"] == 3
        assert t["h"] == 2
        assert t["singles"] == 1
        assert t["doubles"] == 1

    def test_single_player_avg_computed(self):
        p = _make_player(pa=4, ab=4, h=2)
        t = compute_team_totals([p])
        assert t["avg"] == pytest.approx(0.5)

    def test_two_players_counting_stats_summed(self):
        p1 = _make_player(pa=4, ab=4, h=2, singles=2, bb=0)
        p2 = _make_player(pa=5, ab=4, h=1, singles=1, bb=1)
        t = compute_team_totals([p1, p2])
        assert t["pa"] == 9
        assert t["ab"] == 8
        assert t["h"] == 3
        assert t["singles"] == 3
        assert t["bb"] == 1

    def test_two_players_avg_computed_from_totals(self):
        # 3H / 8AB = 0.375
        p1 = _make_player(pa=4, ab=4, h=2)
        p2 = _make_player(pa=4, ab=4, h=1)
        t = compute_team_totals([p1, p2])
        assert t["avg"] == pytest.approx(0.375)

    def test_multiple_players_all_stats_summed(self):
        players = [
            _make_player(pa=3, ab=3, h=1, singles=1, so=2),
            _make_player(pa=4, ab=3, h=0, so=3, bb=1),
            _make_player(pa=3, ab=2, h=2, doubles=1, hr=1, hbp=1),
        ]
        t = compute_team_totals(players)
        assert t["pa"] == 10
        assert t["ab"] == 8
        assert t["h"] == 3
        assert t["so"] == 5
        assert t["bb"] == 1
        assert t["hbp"] == 1
        assert t["doubles"] == 1
        assert t["hr"] == 1

    def test_missing_batting_key_treated_as_zero(self):
        # Player with partial batting dict — missing keys default to 0
        p = {"name": "Partial", "batting": {"pa": 3, "ab": 3, "h": 1}}
        t = compute_team_totals([p])
        assert t["pa"] == 3
        assert t["singles"] == 0

    def test_avg_none_when_ab_zero_across_all_players(self):
        p1 = _make_player(pa=1, ab=0, h=0, bb=1)
        p2 = _make_player(pa=1, ab=0, h=0, hbp=1)
        t = compute_team_totals([p1, p2])
        assert t["avg"] is None


# ---------------------------------------------------------------------------
# _slug_from_name
# ---------------------------------------------------------------------------

class TestSlugFromName:
    def test_lowercases(self):
        assert _slug_from_name("Sharks") == "sharks"

    def test_replaces_spaces_with_underscore(self):
        assert _slug_from_name("Red Sox") == "red_sox"

    def test_replaces_non_alphanumeric(self):
        assert _slug_from_name("Team #1!") == "team_1"

    def test_strips_leading_trailing_underscores(self):
        assert _slug_from_name("  Team  ") == "team"

    def test_truncates_to_30_chars(self):
        long_name = "a" * 50
        assert len(_slug_from_name(long_name)) == 30

    def test_collapses_multiple_non_alphanumeric_runs(self):
        # "a--b" → non-alpha chars replaced with single _ by re.sub
        result = _slug_from_name("a--b")
        assert result == "a_b"

    def test_empty_string(self):
        assert _slug_from_name("") == ""

    def test_alphanumeric_unchanged(self):
        assert _slug_from_name("team1") == "team1"

    def test_leading_special_chars_stripped(self):
        result = _slug_from_name("---Team")
        assert not result.startswith("_")

    def test_trailing_special_chars_stripped(self):
        result = _slug_from_name("Team---")
        assert not result.endswith("_")


# ---------------------------------------------------------------------------
# _metadata_from_filename
# ---------------------------------------------------------------------------

class TestMetadataFromFilename:
    def _path(self, stem: str) -> Path:
        return Path(f"/fake/{stem}.pdf")

    def test_feb_19_2026(self):
        meta = _metadata_from_filename(self._path("Feb_19_2026"))
        assert meta["date"] == "2026-02-19"

    def test_mar_3_2026_zero_padded(self):
        meta = _metadata_from_filename(self._path("Mar_3_2026"))
        assert meta["date"] == "2026-03-03"

    def test_mar_7_2026(self):
        meta = _metadata_from_filename(self._path("Mar_7_2026"))
        assert meta["date"] == "2026-03-07"

    def test_date_in_longer_filename(self):
        meta = _metadata_from_filename(self._path("Sharks_vs_Eagles_Apr_15_2026_game1"))
        assert meta["date"] == "2026-04-15"

    def test_no_date_returns_none(self):
        meta = _metadata_from_filename(self._path("no_date_here"))
        # The short numeric fallback may fire — but for a filename with no
        # recognisable month abbreviation and no 6-digit run, date is None.
        # Accept None only when there is genuinely no parseable date.
        # "no_date_here" has no month token and no 6-digit sequence → None.
        assert meta["date"] is None

    def test_returns_dict_with_date_key(self):
        meta = _metadata_from_filename(self._path("anything"))
        assert "date" in meta

    def test_case_insensitive_month(self):
        meta = _metadata_from_filename(self._path("feb_19_2026"))
        assert meta["date"] == "2026-02-19"

    def test_all_months_recognized(self):
        month_map = {
            "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
            "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
            "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
        }
        for abbr, num in month_map.items():
            meta = _metadata_from_filename(self._path(f"{abbr}_1_2025"))
            assert meta["date"] == f"2025-{num}-01", f"Failed for {abbr}"

    def test_day_zero_padded_in_output(self):
        meta = _metadata_from_filename(self._path("Jan_5_2025"))
        assert meta["date"] == "2025-01-05"

    def test_two_digit_day_not_double_padded(self):
        meta = _metadata_from_filename(self._path("Jun_25_2025"))
        assert meta["date"] == "2025-06-25"

    def test_iso_fallback_6digit_sequence(self):
        """Lines 203-204: fallback parses MMDDYY as 6-digit run."""
        meta = _metadata_from_filename(self._path("game_021926_final"))
        assert meta["date"] == "2026-02-19"


# ---------------------------------------------------------------------------
# _parse_players_from_page (lines 120-159) with fake PDF page
# ---------------------------------------------------------------------------

import parse_scorebook_pdf as psb


class FakePage:
    def __init__(self, tables=None, text=""):
        self._tables = tables or []
        self._text = text or ""

    def extract_tables(self):
        return self._tables

    def extract_text(self):
        return self._text


class TestParsePlayersFromPage:
    def test_no_tables_returns_empty(self):
        page = FakePage(tables=[])
        assert psb._parse_players_from_page(page) == []

    def test_valid_player_row_extracted(self):
        table = [["7", "Alice Smith", "SS", None, None, "1B", "K", "G"]]
        page = FakePage(tables=[table])
        players = psb._parse_players_from_page(page)
        assert len(players) == 1
        assert players[0]["number"] == "7"
        assert players[0]["name"] == "Alice Smith"

    def test_header_row_skipped(self):
        table = [["#", "Name", "Pos", None, None]]
        page = FakePage(tables=[table])
        assert psb._parse_players_from_page(page) == []

    def test_non_numeric_jersey_skipped(self):
        table = [["X7", "Alice Smith", "SS", None, None, "1B"]]
        page = FakePage(tables=[table])
        assert psb._parse_players_from_page(page) == []

    def test_empty_name_skipped(self):
        table = [["7", "", "SS", None, None, "1B"]]
        page = FakePage(tables=[table])
        assert psb._parse_players_from_page(page) == []

    def test_duplicate_jersey_skipped(self):
        table = [
            ["7", "Alice Smith", "SS", None, None, "1B"],
            ["7", "Alice Clone", "3B", None, None, "K"],
        ]
        page = FakePage(tables=[table])
        players = psb._parse_players_from_page(page)
        assert len(players) == 1

    def test_none_cells_skipped(self):
        table = [[None, None, None, None, None]]
        page = FakePage(tables=[table])
        assert psb._parse_players_from_page(page) == []

    def test_empty_row_skipped(self):
        table = [[]]
        page = FakePage(tables=[table])
        assert psb._parse_players_from_page(page) == []

    def test_at_bat_cells_extracted(self):
        table = [["7", "Alice Smith", "SS", None, None, "1B", "K", None, "HR"]]
        page = FakePage(tables=[table])
        players = psb._parse_players_from_page(page)
        assert "1B" in players[0]["at_bats_raw"]
        assert "K" in players[0]["at_bats_raw"]
        assert "HR" in players[0]["at_bats_raw"]

    def test_digit_only_cells_skipped_in_abs(self):
        table = [["7", "Alice Smith", "SS", None, None, "1B", "5", "#12"]]
        page = FakePage(tables=[table])
        players = psb._parse_players_from_page(page)
        assert "5" not in players[0]["at_bats_raw"]
        assert "#12" not in players[0]["at_bats_raw"]
        assert "1B" in players[0]["at_bats_raw"]


class TestPageTeamAndSide:
    def test_first_line_is_team_name(self):
        page = FakePage(text="Eagles\nAway Team")
        team, side, date_str = psb._page_team_and_side(page)
        assert team == "Eagles"

    def test_away_detected(self):
        page = FakePage(text="Eagles\nAway Team")
        _, side, _ = psb._page_team_and_side(page)
        assert side == "away"

    def test_home_detected(self):
        page = FakePage(text="Sharks\nHome Team 2026/04/15")
        _, side, _ = psb._page_team_and_side(page)
        assert side == "home"

    def test_date_extracted_from_side_line(self):
        page = FakePage(text="Sharks\nHome Team 2026/04/15")
        _, _, date_str = psb._page_team_and_side(page)
        assert date_str == "2026-04-15"

    def test_no_date_returns_none(self):
        page = FakePage(text="Eagles\nAway Team")
        _, _, date_str = psb._page_team_and_side(page)
        assert date_str is None

    def test_empty_text_returns_unknown(self):
        page = FakePage(text="")
        team, side, date_str = psb._page_team_and_side(page)
        assert team == "Unknown"
        assert side == "home"


# ---------------------------------------------------------------------------
# parse_pdf (lines 213-258) with mocked pdfplumber
# ---------------------------------------------------------------------------


class TestParsePdf:
    def test_returns_none_when_no_sharks_page(self, tmp_path):
        pdf_path = tmp_path / "May_15_2026.pdf"
        pdf_path.touch()
        eagles_page = FakePage(text="Eagles\nAway Team 2026/05/15", tables=[])
        ravens_page = FakePage(text="Ravens\nHome Team 2026/05/15", tables=[])
        mock_pdf = mock.MagicMock()
        mock_pdf.pages = [eagles_page, ravens_page]
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = mock.MagicMock(return_value=False)
        sys.modules["pdfplumber"].open.return_value = mock_pdf
        result = psb.parse_pdf(pdf_path)
        assert result is None

    def test_returns_game_dict_with_sharks_page(self, tmp_path):
        pdf_path = tmp_path / "May_15_2026.pdf"
        pdf_path.touch()
        sharks_table = [["7", "Alice Smith", "SS", None, None, "1B", "K"]]
        sharks_page = FakePage(text="Sharks\nHome Team 2026/05/15",
                               tables=[sharks_table])
        opp_page = FakePage(text="Eagles\nAway Team 2026/05/15", tables=[])
        mock_pdf = mock.MagicMock()
        mock_pdf.pages = [sharks_page, opp_page]
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = mock.MagicMock(return_value=False)
        sys.modules["pdfplumber"].open.return_value = mock_pdf
        result = psb.parse_pdf(pdf_path)
        assert result is not None
        assert result["sharks_side"] == "home"
        assert result["opponent"] == "Eagles"
        assert len(result["sharks_batting"]) == 1

    def test_date_from_pdf_used_when_filename_has_no_date(self, tmp_path):
        pdf_path = tmp_path / "no_date_game.pdf"
        pdf_path.touch()
        sharks_page = FakePage(text="Sharks\nHome Team 2026/05/20", tables=[])
        opp_page = FakePage(text="Eagles\nAway Team 2026/05/20", tables=[])
        mock_pdf = mock.MagicMock()
        mock_pdf.pages = [sharks_page, opp_page]
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = mock.MagicMock(return_value=False)
        sys.modules["pdfplumber"].open.return_value = mock_pdf
        result = psb.parse_pdf(pdf_path)
        assert result is not None
        assert result["date"] == "2026-05-20"

    def test_no_opponent_page_opponent_is_unknown(self, tmp_path):
        pdf_path = tmp_path / "May_15_2026.pdf"
        pdf_path.touch()
        sharks_page = FakePage(text="Sharks\nHome Team 2026/05/15", tables=[])
        mock_pdf = mock.MagicMock()
        mock_pdf.pages = [sharks_page]
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = mock.MagicMock(return_value=False)
        sys.modules["pdfplumber"].open.return_value = mock_pdf
        result = psb.parse_pdf(pdf_path)
        assert result is not None
        assert result["opponent"] == "Unknown"


# ---------------------------------------------------------------------------
# run() (lines 276-347)
# ---------------------------------------------------------------------------

import json as _json


class TestRun:
    def test_returns_empty_when_no_pdfs(self, tmp_path):
        scorebooks = tmp_path / "Scorebooks"
        scorebooks.mkdir()
        result = psb.run(scorebooks_dir=scorebooks, games_dir=tmp_path / "games")
        assert result == []

    def test_returns_results_and_writes_json(self, tmp_path, monkeypatch):
        scorebooks = tmp_path / "Scorebooks"
        scorebooks.mkdir()
        games = tmp_path / "games"
        (scorebooks / "May_15_2026.pdf").touch()

        fake_game = {
            "game_id": "2026-05-15_eagles",
            "date": "2026-05-15",
            "opponent": "Eagles",
            "sharks_side": "home",
            "source": "scorebook_pdf",
            "pdf_file": "May_15_2026.pdf",
            "sharks_batting": [{"number": "7", "name": "Alice",
                                "batting": {"h": 1, "ab": 3, "pa": 3,
                                            "singles": 1, "doubles": 0,
                                            "triples": 0, "hr": 0, "bb": 0,
                                            "hbp": 0, "so": 1, "sac": 0}}],
            "opponent_batting": [],
        }
        monkeypatch.setattr(psb, "parse_pdf", lambda p: fake_game)
        results = psb.run(scorebooks_dir=scorebooks, games_dir=games)
        assert len(results) == 1
        assert (games / "2026-05-15_eagles.json").exists()
        assert (games / "index.json").exists()

    def test_skips_pdf_that_returns_none(self, tmp_path, monkeypatch):
        scorebooks = tmp_path / "Scorebooks"
        scorebooks.mkdir()
        (scorebooks / "bad.pdf").touch()
        monkeypatch.setattr(psb, "parse_pdf", lambda p: None)
        result = psb.run(scorebooks_dir=scorebooks, games_dir=tmp_path / "games")
        assert result == []

    def test_run_enriches_with_known_results(self, tmp_path, monkeypatch):
        """Lines 317-322: game date matches known result → enriched with W/L and score."""
        scorebooks = tmp_path / "Scorebooks"
        scorebooks.mkdir()
        games = tmp_path / "games"
        (scorebooks / "Feb_19_2026.pdf").touch()

        fake_game = {
            "game_id": "2026-02-19_tbd",
            "date": "2026-02-19",
            "opponent": "TBD",
            "sharks_side": "away",
            "source": "scorebook_pdf",
            "pdf_file": "Feb_19_2026.pdf",
            "sharks_batting": [],
            "opponent_batting": [],
        }
        monkeypatch.setattr(psb, "parse_pdf", lambda p: fake_game)
        # Use the real known_game_results.json which has "2026-02-19" with score "13-20"
        results = psb.run(scorebooks_dir=scorebooks, games_dir=games)
        assert len(results) == 1
        # Result from real file: "L" with score "13-20"
        assert results[0].get("result") == "L"
        assert results[0].get("score") is not None

    def test_score_raw_used_when_non_numeric(self, tmp_path, monkeypatch):
        """Lines 323-324: score that can't be split as ints → score_raw."""
        scorebooks = tmp_path / "Scorebooks"
        scorebooks.mkdir()
        games = tmp_path / "games"
        (scorebooks / "Feb_19_2026.pdf").touch()

        fake_game = {
            "game_id": "2026-02-19_tbd",
            "date": "2026-02-19",
            "opponent": "TBD",
            "sharks_side": "away",
            "source": "scorebook_pdf",
            "pdf_file": "Feb_19_2026.pdf",
            "sharks_batting": [],
            "opponent_batting": [],
        }
        monkeypatch.setattr(psb, "parse_pdf", lambda p: fake_game)
        # Patch json.load to return a known result with non-numeric score
        known_data = {"results": [{"date": "2026-02-19", "result": "W", "score": "X-Y"}]}
        orig_json_load = _json.load
        call_count = [0]
        def fake_json_load(f):
            call_count[0] += 1
            if call_count[0] == 1:  # first call is for known_game_results.json
                return known_data
            return orig_json_load(f)
        monkeypatch.setattr(psb.json, "load", fake_json_load)
        results = psb.run(scorebooks_dir=scorebooks, games_dir=games)
        assert len(results) == 1
        assert results[0].get("score_raw") == "X-Y"

    def test_known_results_exception_swallowed(self, tmp_path, monkeypatch):
        """Lines 311-312: exception during known_results loading is swallowed."""
        scorebooks = tmp_path / "Scorebooks"
        scorebooks.mkdir()
        games = tmp_path / "games"
        (scorebooks / "May_15_2026.pdf").touch()

        fake_game = {
            "game_id": "2026-05-15_eagles",
            "date": "2026-05-15",
            "opponent": "Eagles",
            "sharks_side": "home",
            "source": "scorebook_pdf",
            "pdf_file": "May_15_2026.pdf",
            "sharks_batting": [],
            "opponent_batting": [],
        }
        monkeypatch.setattr(psb, "parse_pdf", lambda p: fake_game)
        # Make json.load raise to trigger the except block
        monkeypatch.setattr(psb.json, "load", lambda f: (_ for _ in ()).throw(
            RuntimeError("bad JSON")))
        # Should not raise despite the error
        results = psb.run(scorebooks_dir=scorebooks, games_dir=games)
        assert len(results) == 1
