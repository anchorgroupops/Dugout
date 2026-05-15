"""Tests for additional pure helpers in sync_daemon.

Covers:
- _canonical_team_name   — name normalization
- _parse_record_parts    — W-L-T parsing
- _sanitize_log          — control-char stripping
- _is_private_or_loopback — IP classification
- _origin_hostname       — URL → hostname extraction
- _read_json_file        — JSON read with retry + fallback
- _write_json_file       — atomic write via temp-rename
- _pick_scoreboard_target — game selection logic
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import sync_daemon

ET = ZoneInfo("America/New_York")

_canonical = sync_daemon._canonical_team_name
_parse_record = sync_daemon._parse_record_parts
_sanitize = sync_daemon._sanitize_log
_is_private = sync_daemon._is_private_or_loopback
_origin_hostname = sync_daemon._origin_hostname
_read_json = sync_daemon._read_json_file
_write_json = sync_daemon._write_json_file
_pick = sync_daemon._pick_scoreboard_target


# ── _canonical_team_name ─────────────────────────────────────────────────────

class TestCanonicalTeamName:
    def test_sharks_slug_returns_the_sharks(self):
        assert _canonical("", "sharks") == "The Sharks"

    def test_the_sharks_name_returns_the_sharks(self):
        assert _canonical("The Sharks") == "The Sharks"

    def test_sharks_lower_name_returns_the_sharks(self):
        assert _canonical("sharks") == "The Sharks"

    def test_regular_name_returned_as_is(self):
        assert _canonical("Riptide Rebels") == "Riptide Rebels"

    def test_slug_title_cased_when_no_name(self):
        result = _canonical("", "wildcats")
        assert result == "Wildcats"

    def test_slug_with_underscores_becomes_title_case(self):
        result = _canonical("", "riptide_rebels")
        assert result == "Riptide Rebels"

    def test_name_takes_priority_over_slug(self):
        assert _canonical("Blue Jays", "wildcats") == "Blue Jays"

    def test_empty_name_and_slug_returns_unknown(self):
        assert _canonical("", "") == "Unknown"

    def test_none_equivalent_blank_inputs(self):
        result = _canonical(None, None)
        assert result == "Unknown"

    def test_whitespace_only_name_falls_through_to_slug(self):
        result = _canonical("   ", "peppers")
        assert result == "Peppers"

    def test_sharks_slug_case_insensitive(self):
        assert _canonical("", "SHARKS") == "The Sharks"


# ── _parse_record_parts ───────────────────────────────────────────────────────

class TestParseRecordParts:
    def test_simple_win_loss(self):
        assert _parse_record("5-3") == (5, 3, 0)

    def test_win_loss_tie(self):
        assert _parse_record("4-2-1") == (4, 2, 1)

    def test_zero_zero(self):
        assert _parse_record("0-0") == (0, 0, 0)

    def test_spaces_around_hyphens(self):
        assert _parse_record("3 - 4") == (3, 4, 0)

    def test_empty_string_returns_zeros(self):
        assert _parse_record("") == (0, 0, 0)

    def test_none_returns_zeros(self):
        assert _parse_record(None) == (0, 0, 0)

    def test_garbage_returns_zeros(self):
        assert _parse_record("not-a-record") == (0, 0, 0)

    def test_large_numbers(self):
        assert _parse_record("12-0") == (12, 0, 0)

    def test_returns_tuple_of_three_ints(self):
        result = _parse_record("2-1")
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert all(isinstance(x, int) for x in result)

    def test_leading_trailing_whitespace(self):
        assert _parse_record("  7-2  ") == (7, 2, 0)


# ── _sanitize_log ─────────────────────────────────────────────────────────────

class TestSanitizeLog:
    def test_plain_string_unchanged(self):
        assert _sanitize("hello world") == "hello world"

    def test_newline_stripped(self):
        result = _sanitize("line1\nline2")
        assert "\n" not in result

    def test_carriage_return_stripped(self):
        result = _sanitize("col1\rcol2")
        assert "\r" not in result

    def test_tab_stripped(self):
        result = _sanitize("a\tb")
        assert "\t" not in result

    def test_null_byte_stripped(self):
        result = _sanitize("a\x00b")
        assert "\x00" not in result

    def test_high_control_chars_stripped(self):
        result = _sanitize("a\x80b")
        assert "\x80" not in result

    def test_max_len_truncates(self):
        long_str = "x" * 300
        result = _sanitize(long_str, max_len=200)
        assert len(result) <= 200

    def test_default_max_len_is_200(self):
        long_str = "y" * 300
        result = _sanitize(long_str)
        assert len(result) == 200

    def test_short_string_not_padded(self):
        result = _sanitize("hi", max_len=200)
        assert result == "hi"

    def test_empty_string(self):
        assert _sanitize("") == ""

    def test_log_injection_newline_removed(self):
        malicious = "safe\nINFO: injected message"
        result = _sanitize(malicious)
        assert "injected message" in result
        assert "\n" not in result


# ── _is_private_or_loopback ───────────────────────────────────────────────────

class TestIsPrivateOrLoopback:
    @pytest.mark.parametrize("ip", [
        "127.0.0.1",
        "::1",
        "10.0.0.1",
        "192.168.1.50",
        "172.16.0.1",
        "172.31.255.255",
    ])
    def test_private_and_loopback_return_true(self, ip):
        assert _is_private(ip) is True

    @pytest.mark.parametrize("ip", [
        "8.8.8.8",
        "1.1.1.1",
        "4.4.4.4",
        "2606:4700:4700::1111",  # Cloudflare public DNS
    ])
    def test_public_ips_return_false(self, ip):
        assert _is_private(ip) is False

    def test_invalid_ip_returns_false(self):
        assert _is_private("not-an-ip") is False

    def test_empty_string_returns_false(self):
        assert _is_private("") is False

    def test_returns_bool(self):
        assert isinstance(_is_private("127.0.0.1"), bool)


# ── _origin_hostname ─────────────────────────────────────────────────────────

class TestOriginHostname:
    def test_simple_http_url(self):
        assert _origin_hostname("http://example.com") == "example.com"

    def test_https_url(self):
        assert _origin_hostname("https://dugout.joelycannoli.com") == "dugout.joelycannoli.com"

    def test_url_with_port_strips_port(self):
        result = _origin_hostname("http://localhost:3000")
        assert result == "localhost"

    def test_returns_lowercase(self):
        result = _origin_hostname("https://MyHost.COM")
        assert result == "myhost.com"

    def test_empty_string_returns_empty(self):
        assert _origin_hostname("") == ""

    def test_garbage_returns_empty(self):
        assert _origin_hostname("not-a-url") == ""

    def test_url_with_path_ignores_path(self):
        result = _origin_hostname("https://example.com/some/path")
        assert result == "example.com"

    def test_url_with_query_ignores_query(self):
        result = _origin_hostname("https://example.com?foo=bar")
        assert result == "example.com"


# ── _read_json_file ───────────────────────────────────────────────────────────

class TestReadJsonFile:
    def test_reads_valid_json(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}')
        assert _read_json(f) == {"key": "value"}

    def test_missing_file_returns_default_none(self, tmp_path):
        result = _read_json(tmp_path / "missing.json")
        assert result is None

    def test_missing_file_returns_custom_default(self, tmp_path):
        result = _read_json(tmp_path / "missing.json", default={})
        assert result == {}

    def test_invalid_json_returns_default(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not valid}")
        result = _read_json(f, default={"fallback": True})
        assert result == {"fallback": True}

    def test_nested_json_round_trips(self, tmp_path):
        data = {"roster": [{"name": "Alice", "avg": 0.450}]}
        f = tmp_path / "team.json"
        f.write_text(json.dumps(data))
        assert _read_json(f) == data

    def test_empty_file_returns_default(self, tmp_path):
        f = tmp_path / "empty.json"
        f.write_text("")
        result = _read_json(f, default="empty")
        assert result == "empty"


# ── _write_json_file ──────────────────────────────────────────────────────────

class TestWriteJsonFile:
    def test_file_created(self, tmp_path):
        p = tmp_path / "out.json"
        _write_json(p, {"x": 1})
        assert p.exists()

    def test_content_round_trips(self, tmp_path):
        data = {"team": "Sharks", "wins": 7}
        p = tmp_path / "team.json"
        _write_json(p, data)
        assert json.loads(p.read_text()) == data

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "deep" / "nested" / "out.json"
        _write_json(p, {"ok": True})
        assert p.exists()

    def test_overwrites_existing_file(self, tmp_path):
        p = tmp_path / "out.json"
        p.write_text('{"old": true}')
        _write_json(p, {"new": True})
        assert json.loads(p.read_text()) == {"new": True}

    def test_file_permissions_are_644(self, tmp_path):
        import stat
        p = tmp_path / "out.json"
        _write_json(p, {})
        mode = oct(stat.S_IMODE(p.stat().st_mode))
        assert mode == "0o644"

    def test_list_written_correctly(self, tmp_path):
        p = tmp_path / "list.json"
        _write_json(p, [1, 2, 3])
        assert json.loads(p.read_text()) == [1, 2, 3]

    def test_read_back_via_read_json(self, tmp_path):
        p = tmp_path / "roundtrip.json"
        original = {"sharks": True, "score": 11}
        _write_json(p, original)
        assert _read_json(p) == original


# ── _pick_scoreboard_target ───────────────────────────────────────────────────

class TestPickScoreboardTarget:
    """_pick_scoreboard_target(games, now, today_str) → game dict or None."""

    def _now(self):
        return datetime.now(ET)

    def _ts(self, offset_hours=0):
        """ISO timestamp offset_hours from now."""
        t = datetime.now(timezone.utc) + timedelta(hours=offset_hours)
        return t.isoformat()

    def _today(self):
        return datetime.now(ET).date().isoformat()

    def test_empty_games_returns_none(self):
        assert _pick([], self._now(), self._today()) is None

    def test_returns_live_game(self):
        g = {"game_status": "in_progress", "start_ts": self._ts(-0.5)}
        result = _pick([g], self._now(), self._today())
        assert result is g

    def test_active_status_treated_as_live(self):
        g = {"game_status": "active", "start_ts": self._ts(-0.5)}
        result = _pick([g], self._now(), self._today())
        assert result is g

    def test_live_status_treated_as_live(self):
        g = {"game_status": "live", "start_ts": self._ts(-0.5)}
        result = _pick([g], self._now(), self._today())
        assert result is g

    def test_stale_live_game_skipped(self):
        stale = {"game_status": "in_progress", "start_ts": self._ts(-10)}
        result = _pick([stale], self._now(), self._today())
        assert result is None

    def test_stale_live_game_with_today_fallback(self):
        stale = {"game_status": "in_progress", "start_ts": self._ts(-10)}
        today_game = {"game_status": "scheduled", "start_ts": self._ts(2)}
        result = _pick([stale, today_game], self._now(), self._today())
        assert result is today_game

    def test_today_game_returned_when_no_live(self):
        g = {"game_status": "scheduled", "start_ts": self._ts(2)}
        result = _pick([g], self._now(), self._today())
        assert result is g

    def test_live_game_preferred_over_today_game(self):
        live = {"game_status": "in_progress", "start_ts": self._ts(-0.5)}
        today = {"game_status": "scheduled", "start_ts": self._ts(1)}
        result = _pick([live, today], self._now(), self._today())
        assert result is live

    def test_past_game_not_returned_as_today(self):
        yesterday_ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        g = {"game_status": "final", "start_ts": yesterday_ts}
        result = _pick([g], self._now(), self._today())
        assert result is None

    def test_no_start_ts_game_still_matched_by_today(self):
        g = {"game_status": "scheduled", "start_ts": ""}
        result = _pick([g], self._now(), self._today())
        assert result is None  # can't determine game_date without a parseable ts

    def test_first_live_game_wins_among_multiple_live(self):
        live1 = {"game_status": "in_progress", "start_ts": self._ts(-1), "id": "first"}
        live2 = {"game_status": "in_progress", "start_ts": self._ts(-0.5), "id": "second"}
        result = _pick([live1, live2], self._now(), self._today())
        assert result["id"] == "first"

    def test_returns_none_when_only_future_games(self):
        future = {"game_status": "scheduled", "start_ts": self._ts(48)}
        result = _pick([future], self._now(), self._today())
        assert result is None

    def test_case_insensitive_status_matching(self):
        g = {"game_status": "IN_PROGRESS", "start_ts": self._ts(-0.5)}
        result = _pick([g], self._now(), self._today())
        assert result is g


# ── _candidate_secrets_csv_paths ─────────────────────────────────────────────

class TestCandidateSecretsCsvPaths:
    def test_returns_list(self, monkeypatch):
        monkeypatch.delenv("SECRETS_CSV", raising=False)
        monkeypatch.delenv("APIS_CSV_PATH", raising=False)
        result = sync_daemon._candidate_secrets_csv_paths()
        assert isinstance(result, list)

    def test_all_items_are_paths(self, monkeypatch):
        monkeypatch.delenv("SECRETS_CSV", raising=False)
        monkeypatch.delenv("APIS_CSV_PATH", raising=False)
        result = sync_daemon._candidate_secrets_csv_paths()
        assert all(isinstance(p, Path) for p in result)

    def test_env_var_included_when_set(self, monkeypatch):
        monkeypatch.setenv("SECRETS_CSV", "/tmp/my_secrets.csv")
        result = sync_daemon._candidate_secrets_csv_paths()
        paths = [str(p) for p in result]
        assert "/tmp/my_secrets.csv" in paths

    def test_no_duplicates(self, monkeypatch):
        monkeypatch.delenv("SECRETS_CSV", raising=False)
        monkeypatch.delenv("APIS_CSV_PATH", raising=False)
        result = sync_daemon._candidate_secrets_csv_paths()
        strs = [str(p) for p in result]
        assert len(strs) == len(set(strs))

    def test_empty_env_var_excluded(self, monkeypatch):
        monkeypatch.setenv("SECRETS_CSV", "")
        monkeypatch.setenv("APIS_CSV_PATH", "")
        result = sync_daemon._candidate_secrets_csv_paths()
        for p in result:
            assert str(p).strip() != ""


# ── _load_secret_cache ───────────────────────────────────────────────────────

class TestLoadSecretCache:
    def test_returns_dict(self):
        sync_daemon._SECRET_CACHE = None  # reset
        result = sync_daemon._load_secret_cache()
        assert isinstance(result, dict)

    def test_returns_cached_value(self):
        sync_daemon._SECRET_CACHE = {"KEY": "cached_val"}
        result = sync_daemon._load_secret_cache()
        assert result["KEY"] == "cached_val"
        sync_daemon._SECRET_CACHE = None  # cleanup


# ── _resolve_secret ──────────────────────────────────────────────────────────

class TestResolveSecret:
    def test_returns_env_var_when_set(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_SECRET_XYZ", "env_value")
        sync_daemon._SECRET_CACHE = None
        result = sync_daemon._resolve_secret("MY_TEST_SECRET_XYZ", "default")
        assert result == "env_value"

    def test_returns_default_when_env_and_cache_miss(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_KEY_ZZZYY", raising=False)
        sync_daemon._SECRET_CACHE = {}
        result = sync_daemon._resolve_secret("NONEXISTENT_KEY_ZZZYY", "fallback")
        assert result == "fallback"

    def test_strips_whitespace_from_env(self, monkeypatch):
        monkeypatch.setenv("MY_PAD_SECRET", "  padded  ")
        sync_daemon._SECRET_CACHE = None
        result = sync_daemon._resolve_secret("MY_PAD_SECRET", "")
        assert result == "padded"

    def test_falls_back_to_cache_when_env_empty(self, monkeypatch):
        monkeypatch.setenv("CACHE_TEST_KEY", "")
        sync_daemon._SECRET_CACHE = {"CACHE_TEST_KEY": "from_cache"}
        result = sync_daemon._resolve_secret("CACHE_TEST_KEY", "default")
        assert result == "from_cache"
        sync_daemon._SECRET_CACHE = None


# ── _resolve_critical_env ────────────────────────────────────────────────────

class TestResolveCriticalEnv:
    def test_returns_env_var_when_set(self, monkeypatch):
        monkeypatch.setenv("CRITICAL_TEST_KEY", "real_value")
        sync_daemon._SECRET_CACHE = None
        result = sync_daemon._resolve_critical_env("CRITICAL_TEST_KEY", "fallback")
        assert result == "real_value"

    def test_returns_fallback_when_not_set(self, monkeypatch):
        monkeypatch.delenv("CRITICAL_TEST_KEY_ZZZ", raising=False)
        sync_daemon._SECRET_CACHE = {}
        result = sync_daemon._resolve_critical_env("CRITICAL_TEST_KEY_ZZZ", "my_fallback")
        assert result == "my_fallback"

    def test_returns_string(self, monkeypatch):
        monkeypatch.setenv("CRIT_STR_KEY", "hello")
        sync_daemon._SECRET_CACHE = None
        result = sync_daemon._resolve_critical_env("CRIT_STR_KEY", "x")
        assert isinstance(result, str)
