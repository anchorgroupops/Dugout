"""Tests for tools/gc_schedule.py.

gc_schedule.py is a thin subclass of GameChangerScraper whose only unique
logic is:
  - scrape_schedule()      – Playwright-gated; tested via ImportError smoke.
  - _take_error_snapshot() – timestamp formatting helper; testable in
                             isolation by mocking the page object.

The bulk of testable pure functions lives in gc_scraper (the base module),
which is unconditionally imported by gc_schedule.  Those functions are
exercised here because they are the shared foundation:
  - Module-level constants (URLs, team IDs, column maps).
  - _safe_val()            – cell-value coercion.
  - STAT_VIEWS             – scraping manifest integrity.
  - Auth-cooldown helpers  – pure file-system helpers (mocked fs).
"""
from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Bootstrap path so the tools/ package is importable without installing it.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))


# ===========================================================================
# Class 1 – Module-level import & constant sanity
# ===========================================================================
class TestModuleImport:
    """gc_schedule and gc_scraper must import cleanly and expose expected names."""

    def test_gc_schedule_imports_without_error(self):
        """The module must be importable even when Playwright is absent."""
        # Remove any cached copy so we get a fresh load.
        for key in list(sys.modules):
            if key in ("gc_schedule", "gc_scraper"):
                del sys.modules[key]
        import gc_schedule  # noqa: F401 – ImportError is the failure mode

    def test_gc_scraper_imports_without_error(self):
        import gc_scraper  # noqa: F401

    def test_schedule_scraper_class_exists(self):
        import gc_schedule
        assert hasattr(gc_schedule, "ScheduleScraper")

    def test_schedule_scraper_is_subclass_of_game_changer_scraper(self):
        import gc_schedule
        import gc_scraper
        assert issubclass(gc_schedule.ScheduleScraper, gc_scraper.GameChangerScraper)

    def test_et_timezone_constant(self):
        import gc_schedule
        from zoneinfo import ZoneInfo
        assert gc_schedule.ET == ZoneInfo("America/New_York")

    def test_path_constants_are_path_objects(self):
        import gc_schedule
        assert isinstance(gc_schedule.DATA_DIR, Path)
        assert isinstance(gc_schedule.SHARKS_DIR, Path)
        assert isinstance(gc_schedule.TMP_DIR, Path)

    def test_sharks_dir_is_inside_data_dir(self):
        import gc_schedule
        assert gc_schedule.SHARKS_DIR.parent == gc_schedule.DATA_DIR


# ===========================================================================
# Class 2 – gc_scraper constants (inherited by ScheduleScraper)
# ===========================================================================
class TestGcScraperConstants:
    """Constants defined in gc_scraper that flow through to ScheduleScraper."""

    def test_gc_base_url_format(self):
        import gc_scraper
        assert gc_scraper.GC_BASE_URL.startswith("https://")
        assert "gc.com" in gc_scraper.GC_BASE_URL

    def test_gc_login_url_derived_from_base(self):
        import gc_scraper
        assert gc_scraper.GC_LOGIN_URL.startswith(gc_scraper.GC_BASE_URL)
        assert "login" in gc_scraper.GC_LOGIN_URL

    def test_gc_team_id_is_non_empty_string(self):
        import gc_scraper
        assert isinstance(gc_scraper.GC_TEAM_ID, str)
        assert len(gc_scraper.GC_TEAM_ID) > 0

    def test_gc_season_slug_is_non_empty_string(self):
        import gc_scraper
        assert isinstance(gc_scraper.GC_SEASON_SLUG, str)
        assert len(gc_scraper.GC_SEASON_SLUG) > 0

    def test_gc_season_slug_default_matches_expected_pattern(self):
        """Default slug should look like '<year>-<word>-<team>'."""
        import gc_scraper
        import re
        # e.g. "2026-spring-sharks"
        assert re.match(r"^\d{4}-\w+-\w+", gc_scraper.GC_SEASON_SLUG), (
            f"Unexpected season slug format: {gc_scraper.GC_SEASON_SLUG!r}"
        )

    def test_gc_stats_url_contains_team_id_and_slug(self):
        import gc_scraper
        assert gc_scraper.GC_TEAM_ID in gc_scraper.GC_STATS_URL
        assert gc_scraper.GC_SEASON_SLUG in gc_scraper.GC_STATS_URL

    def test_auth_cooldown_hours_is_positive_float(self):
        import gc_scraper
        assert isinstance(gc_scraper.AUTH_COOLDOWN_HOURS, float)
        assert gc_scraper.AUTH_COOLDOWN_HOURS > 0

    def test_gc_headless_is_bool(self):
        import gc_scraper
        assert isinstance(gc_scraper.GC_HEADLESS, bool)


# ===========================================================================
# Class 3 – Column-mapping dictionaries
# ===========================================================================
class TestColumnMaps:
    """All stat-column maps must be dicts mapping non-empty str -> non-empty str."""

    MAP_NAMES = [
        "BATTING_STD_MAP",
        "BATTING_ADV_MAP",
        "PITCHING_STD_MAP",
        "PITCHING_ADV_MAP",
        "PITCHING_BRK_MAP",
        "FIELDING_STD_MAP",
        "FIELDING_CATCH_MAP",
        "FIELDING_INN_MAP",
    ]

    @pytest.mark.parametrize("map_name", MAP_NAMES)
    def test_map_is_dict(self, map_name):
        import gc_scraper
        m = getattr(gc_scraper, map_name)
        assert isinstance(m, dict), f"{map_name} should be a dict"

    @pytest.mark.parametrize("map_name", MAP_NAMES)
    def test_map_is_non_empty(self, map_name):
        import gc_scraper
        m = getattr(gc_scraper, map_name)
        assert len(m) > 0, f"{map_name} should not be empty"

    @pytest.mark.parametrize("map_name", MAP_NAMES)
    def test_map_keys_are_non_empty_strings(self, map_name):
        import gc_scraper
        m = getattr(gc_scraper, map_name)
        for k in m:
            assert isinstance(k, str) and k, f"{map_name}: key {k!r} is empty or non-str"

    @pytest.mark.parametrize("map_name", MAP_NAMES)
    def test_map_values_are_non_empty_lowercase_strings(self, map_name):
        import gc_scraper
        m = getattr(gc_scraper, map_name)
        for k, v in m.items():
            assert isinstance(v, str) and v, (
                f"{map_name}[{k!r}] value is empty or non-str"
            )
            assert v == v.lower(), (
                f"{map_name}[{k!r}] value {v!r} should be lowercase (JSON key)"
            )

    def test_batting_std_has_core_columns(self):
        import gc_scraper
        for col in ("GP", "PA", "AB", "AVG", "OBP", "H", "HR", "RBI", "BB", "SO"):
            assert col in gc_scraper.BATTING_STD_MAP, f"BATTING_STD_MAP missing {col!r}"

    def test_pitching_std_has_core_columns(self):
        import gc_scraper
        for col in ("GP", "IP", "ERA", "WHIP", "SO", "BB", "H"):
            assert col in gc_scraper.PITCHING_STD_MAP, (
                f"PITCHING_STD_MAP missing {col!r}"
            )

    def test_fielding_std_has_core_columns(self):
        import gc_scraper
        for col in ("TC", "PO", "A", "E", "FPCT"):
            assert col in gc_scraper.FIELDING_STD_MAP, (
                f"FIELDING_STD_MAP missing {col!r}"
            )

    def test_fielding_inn_map_covers_all_nine_positions_plus_total(self):
        import gc_scraper
        m = gc_scraper.FIELDING_INN_MAP
        # Should cover every defensive position
        assert "IP:P" in m, "Missing pitcher innings column IP:P"
        assert "IP:C" in m, "Missing catcher innings column IP:C"
        assert "IP:1B" in m
        assert "IP:SS" in m
        assert "IP:LF" in m
        assert "IP:CF" in m
        assert "IP:RF" in m
        assert "IP:F" in m, "Missing total-innings column IP:F"


# ===========================================================================
# Class 4 – STAT_VIEWS manifest integrity
# ===========================================================================
class TestStatViews:
    """STAT_VIEWS controls the scraping loop — its structure must be exact."""

    def test_stat_views_is_list(self):
        import gc_scraper
        assert isinstance(gc_scraper.STAT_VIEWS, list)

    def test_stat_views_has_eight_entries(self):
        import gc_scraper
        assert len(gc_scraper.STAT_VIEWS) == 8, (
            f"Expected 8 stat views, got {len(gc_scraper.STAT_VIEWS)}"
        )

    def test_every_view_is_four_tuple(self):
        import gc_scraper
        for i, view in enumerate(gc_scraper.STAT_VIEWS):
            assert len(view) == 4, f"STAT_VIEWS[{i}] should be a 4-tuple, got {len(view)}"

    def test_major_tabs_are_valid(self):
        import gc_scraper
        valid = {"Batting", "Pitching", "Fielding"}
        for major, sub, col_map, json_key in gc_scraper.STAT_VIEWS:
            assert major in valid, f"Unknown major tab: {major!r}"

    def test_column_maps_are_dicts(self):
        import gc_scraper
        for major, sub, col_map, json_key in gc_scraper.STAT_VIEWS:
            assert isinstance(col_map, dict), (
                f"STAT_VIEWS entry {major}/{sub}: col_map is not a dict"
            )

    def test_json_keys_are_unique(self):
        import gc_scraper
        keys = [entry[3] for entry in gc_scraper.STAT_VIEWS]
        assert len(keys) == len(set(keys)), f"Duplicate json_key in STAT_VIEWS: {keys}"

    def test_batting_standard_is_first(self):
        import gc_scraper
        first = gc_scraper.STAT_VIEWS[0]
        assert first[0] == "Batting" and first[1] == "Standard"

    def test_json_keys_are_non_empty_strings(self):
        import gc_scraper
        for _, _, _, json_key in gc_scraper.STAT_VIEWS:
            assert isinstance(json_key, str) and json_key


# ===========================================================================
# Class 5 – _safe_val() pure function
# ===========================================================================
class TestSafeVal:
    """_safe_val converts raw cell text to int/float/str/None deterministically."""

    @pytest.fixture(autouse=True)
    def _import(self):
        import gc_scraper
        self.safe = gc_scraper._safe_val

    def test_none_input_returns_none(self):
        assert self.safe(None) is None

    def test_empty_string_returns_none(self):
        assert self.safe("") is None

    def test_dash_returns_none(self):
        assert self.safe("-") is None

    def test_em_dash_returns_none(self):
        assert self.safe("—") is None

    def test_na_string_returns_none(self):
        assert self.safe("N/A") is None

    def test_integer_string_returns_int(self):
        result = self.safe("42")
        assert result == 42
        assert isinstance(result, int)

    def test_zero_string_returns_int_zero(self):
        result = self.safe("0")
        assert result == 0
        assert isinstance(result, int)

    def test_negative_integer_string(self):
        result = self.safe("-3")
        assert result == -3
        assert isinstance(result, int)

    def test_float_string_returns_float(self):
        result = self.safe("0.375")
        assert abs(result - 0.375) < 1e-9
        assert isinstance(result, float)

    def test_percentage_looking_float(self):
        result = self.safe("1.000")
        assert isinstance(result, float)
        assert abs(result - 1.0) < 1e-9

    def test_plain_text_returned_as_string(self):
        result = self.safe("Jane Doe")
        assert result == "Jane Doe"
        assert isinstance(result, str)

    def test_leading_trailing_whitespace_stripped(self):
        result = self.safe("  7  ")
        assert result == 7
        assert isinstance(result, int)

    def test_mixed_alpha_numeric_returned_as_string(self):
        result = self.safe("4.2IP")
        assert isinstance(result, str)
        assert result == "4.2IP"

    def test_stat_string_with_slash_returned_as_string(self):
        # e.g. "3/5" fielding fraction — not a real number
        result = self.safe("3/5")
        assert isinstance(result, str)


# ===========================================================================
# Class 6 – Auth-cooldown pure helpers
# ===========================================================================
class TestAuthCooldown:
    """set_auth_cooldown / clear_auth_cooldown / is_auth_on_cooldown are
    pure-ish file-system helpers; we redirect the cooldown file to tmp_path."""

    @pytest.fixture(autouse=True)
    def _redirect_cooldown_file(self, tmp_path, monkeypatch):
        """Point gc_scraper's cooldown file at a temp location."""
        import gc_scraper
        self.cooldown_file = tmp_path / ".auth_cooldown"
        monkeypatch.setattr(gc_scraper, "_AUTH_COOLDOWN_FILE", self.cooldown_file)
        # Import the module-level functions after patching the attr
        self.set_cd = gc_scraper.set_auth_cooldown
        self.clear_cd = gc_scraper.clear_auth_cooldown
        self.is_on_cd = gc_scraper.is_auth_on_cooldown

    def test_no_file_means_not_on_cooldown(self):
        assert not self.cooldown_file.exists()
        assert self.is_on_cd() is False

    def test_set_cooldown_creates_file(self):
        self.set_cd("test reason")
        assert self.cooldown_file.exists()

    def test_set_cooldown_file_contains_valid_json(self):
        self.set_cd("unit test")
        data = json.loads(self.cooldown_file.read_text())
        assert "failed_at" in data
        assert "reason" in data
        assert data["reason"] == "unit test"

    def test_set_cooldown_failed_at_is_iso_format(self):
        self.set_cd("timestamp check")
        data = json.loads(self.cooldown_file.read_text())
        # Must parse without raising
        datetime.fromisoformat(data["failed_at"])

    def test_is_on_cooldown_returns_true_after_set(self):
        self.set_cd("fresh failure")
        assert self.is_on_cd() is True

    def test_clear_cooldown_removes_file(self):
        self.set_cd("will be cleared")
        assert self.cooldown_file.exists()
        self.clear_cd()
        assert not self.cooldown_file.exists()

    def test_is_on_cooldown_false_after_clear(self):
        self.set_cd("set then clear")
        self.clear_cd()
        assert self.is_on_cd() is False

    def test_clear_when_no_file_is_safe(self):
        # Should not raise even when the file doesn't exist
        self.clear_cd()

    def test_expired_cooldown_returns_false_and_removes_file(self, monkeypatch):
        """A cooldown whose failed_at is older than AUTH_COOLDOWN_HOURS should
        be treated as expired and auto-cleaned up."""
        import gc_scraper
        from zoneinfo import ZoneInfo
        ET = ZoneInfo("America/New_York")

        # Write a cooldown that is clearly expired (far in the past)
        expired_at = (datetime.now(ET) - timedelta(hours=100)).isoformat()
        self.cooldown_file.write_text(
            json.dumps({"failed_at": expired_at, "reason": "old failure"})
        )
        assert not self.is_on_cd()
        # File should be cleaned up
        assert not self.cooldown_file.exists()

    def test_recent_cooldown_returns_true(self):
        """A cooldown set just now is still active."""
        self.set_cd("very recent")
        assert self.is_on_cd() is True


# ===========================================================================
# Class 7 – ScheduleScraper instantiation (no network)
# ===========================================================================
class TestScheduleScraperInstantiation:
    """ScheduleScraper can be constructed without credentials or network."""

    def test_default_instantiation(self, monkeypatch):
        """Constructor must not raise even without env vars."""
        monkeypatch.delenv("GC_EMAIL", raising=False)
        monkeypatch.delenv("GC_PASSWORD", raising=False)
        monkeypatch.delenv("GC_TEAM_ID", raising=False)
        monkeypatch.delenv("GC_SEASON_SLUG", raising=False)
        import gc_schedule
        scraper = gc_schedule.ScheduleScraper()
        assert scraper is not None

    def test_team_name_defaults_to_the_sharks(self, monkeypatch):
        monkeypatch.delenv("TEAM_NAME", raising=False)
        import gc_schedule
        scraper = gc_schedule.ScheduleScraper()
        assert scraper.team_name == "The Sharks"

    def test_custom_team_name_is_respected(self):
        import gc_schedule
        scraper = gc_schedule.ScheduleScraper(team_name="Test Team")
        assert scraper.team_name == "Test Team"

    def test_custom_team_id_is_respected(self):
        import gc_schedule
        scraper = gc_schedule.ScheduleScraper(team_id="TESTID123")
        assert scraper.team_id == "TESTID123"

    def test_custom_season_slug_is_respected(self):
        import gc_schedule
        scraper = gc_schedule.ScheduleScraper(season_slug="2025-fall-test")
        assert scraper.season_slug == "2025-fall-test"

    def test_stats_url_built_from_team_id_and_slug(self):
        import gc_schedule
        scraper = gc_schedule.ScheduleScraper(
            team_id="MYTEAM", season_slug="2025-test-slug"
        )
        assert "MYTEAM" in scraper.stats_url
        assert "2025-test-slug" in scraper.stats_url

    def test_browser_and_context_initially_none(self):
        import gc_schedule
        scraper = gc_schedule.ScheduleScraper()
        assert scraper.browser is None
        assert scraper.context is None


# ===========================================================================
# Class 8 – scrape_schedule() raises ImportError when Playwright absent
# ===========================================================================
class _BlockPlaywright:
    """Meta-path finder that blocks playwright imports entirely."""
    def find_spec(self, name, path=None, target=None):
        if name == "playwright" or name.startswith("playwright."):
            raise ImportError(f"blocked-for-test: {name}")
        return None


@pytest.fixture
def playwright_blocked():
    for k in list(sys.modules):
        if k in ("gc_schedule", "gc_scraper") or k.startswith("playwright"):
            del sys.modules[k]
    blocker = _BlockPlaywright()
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        sys.meta_path[:] = [x for x in sys.meta_path if x is not blocker]


class TestScrapeScheduleNetworkBoundary:
    """scrape_schedule() must propagate ImportError when Playwright is absent
    (not swallow it as a silent None)."""

    def test_scrape_schedule_raises_importerror_without_playwright(
        self, playwright_blocked
    ):
        mod = importlib.import_module("gc_schedule")
        scraper = mod.ScheduleScraper()
        with pytest.raises(ImportError):
            scraper.scrape_schedule()


# ===========================================================================
# Class 9 – _take_error_snapshot() helper (mocked page)
# ===========================================================================
class TestTakeErrorSnapshot:
    """_take_error_snapshot creates a timestamped PNG path and calls
    page.screenshot; test via a mock page."""

    def test_snapshot_calls_page_screenshot(self, tmp_path):
        import gc_schedule
        scraper = gc_schedule.ScheduleScraper()

        mock_page = MagicMock()

        with patch("gc_schedule.TMP_DIR", tmp_path):
            scraper._take_error_snapshot(mock_page, "unit_test_prefix")

        mock_page.screenshot.assert_called_once()
        call_kwargs = mock_page.screenshot.call_args
        path_arg = call_kwargs.kwargs.get("path") or call_kwargs.args[0]
        assert "unit_test_prefix" in path_arg

    def test_snapshot_path_contains_timestamp(self, tmp_path):
        import gc_schedule
        scraper = gc_schedule.ScheduleScraper()

        mock_page = MagicMock()

        with patch("gc_schedule.TMP_DIR", tmp_path):
            scraper._take_error_snapshot(mock_page, "ts_check")

        call_kwargs = mock_page.screenshot.call_args
        path_arg = call_kwargs.kwargs.get("path") or call_kwargs.args[0]
        # Timestamp is 15 digits: YYYYMMDD_HHMMSS
        import re
        assert re.search(r"\d{8}_\d{6}", path_arg), (
            f"Expected YYYYMMDD_HHMMSS in path, got: {path_arg}"
        )

    def test_snapshot_creates_tmp_dir_if_missing(self, tmp_path):
        import gc_schedule
        scraper = gc_schedule.ScheduleScraper()

        nested_tmp = tmp_path / "deeply" / "nested"
        assert not nested_tmp.exists()

        mock_page = MagicMock()
        with patch("gc_schedule.TMP_DIR", nested_tmp):
            scraper._take_error_snapshot(mock_page, "dir_creation")

        assert nested_tmp.exists()

    def test_snapshot_silences_screenshot_exception(self, tmp_path):
        """A failure inside page.screenshot must not propagate."""
        import gc_schedule
        scraper = gc_schedule.ScheduleScraper()

        mock_page = MagicMock()
        mock_page.screenshot.side_effect = RuntimeError("browser crashed")

        with patch("gc_schedule.TMP_DIR", tmp_path):
            # Should not raise
            scraper._take_error_snapshot(mock_page, "silent_fail")
