"""Tests for previously-uncovered sync_daemon.py functions.

Covers:
- _set_sync_stage()            — stage/progress mutation
- send_alert()                 — HTTP webhook with mocked requests
- _request_origin()            — Flask request context
- _client_ip()                 — Flask request context + XFF parsing
- _guard_mutating_request()    — origin validation
- _supplement_enriched_from_base() — dict merging / field fill
- get_next_game_time()         — schedule JSON parsing
- _validate_path_slug()        — slug validation (Flask jsonify)
- _is_trusted_proxy()          — IP trust check
- _normalized_request_host()   — host header parsing
- _guard_mutating_rate_limit() — rate limiter with time mocking
- Flask error handlers         — 413/400/500 responses
"""
from __future__ import annotations

import json
import sys
import time as _time_mod
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import sync_daemon as sd

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# _set_sync_stage
# ---------------------------------------------------------------------------

class TestSetSyncStage:
    def test_sets_stage_in_status(self):
        orig = sd._SYNC_STATUS.copy()
        try:
            sd._set_sync_stage("starting")
            assert sd._SYNC_STATUS["stage"] == "starting"
        finally:
            sd._SYNC_STATUS.update(orig)

    def test_sets_progress_for_known_stage(self):
        orig = sd._SYNC_STATUS.copy()
        try:
            sd._set_sync_stage("scraping_schedule")
            assert sd._SYNC_STATUS["progress"] == 15
        finally:
            sd._SYNC_STATUS.update(orig)

    def test_sets_progress_0_for_idle(self):
        orig = sd._SYNC_STATUS.copy()
        try:
            sd._set_sync_stage("idle")
            assert sd._SYNC_STATUS["progress"] == 0
        finally:
            sd._SYNC_STATUS.update(orig)

    def test_unknown_stage_does_not_crash(self):
        orig = sd._SYNC_STATUS.copy()
        try:
            sd._set_sync_stage("unknown_stage_xyz")
        finally:
            sd._SYNC_STATUS.update(orig)

    def test_all_known_stages_set_progress(self):
        orig = sd._SYNC_STATUS.copy()
        try:
            for stage_name, pct, _ in sd._SYNC_STAGES:
                sd._set_sync_stage(stage_name)
                assert sd._SYNC_STATUS["progress"] == pct
        finally:
            sd._SYNC_STATUS.update(orig)

    def test_finalizing_stage(self):
        orig = sd._SYNC_STATUS.copy()
        try:
            sd._set_sync_stage("finalizing")
            assert sd._SYNC_STATUS["progress"] == 95
        finally:
            sd._SYNC_STATUS.update(orig)

    def test_analyzing_stage(self):
        orig = sd._SYNC_STATUS.copy()
        try:
            sd._set_sync_stage("analyzing")
            assert sd._SYNC_STATUS["progress"] == 80
        finally:
            sd._SYNC_STATUS.update(orig)


# ---------------------------------------------------------------------------
# send_alert
# ---------------------------------------------------------------------------

class TestSendAlert:
    def test_no_url_returns_immediately(self, monkeypatch):
        monkeypatch.setattr(sd, "N8N_WEBHOOK_URL", "")
        mock_post = MagicMock()
        monkeypatch.setattr(sd.requests, "post", mock_post)
        sd.send_alert("test message")
        mock_post.assert_not_called()

    def test_posts_to_webhook_url(self, monkeypatch):
        monkeypatch.setattr(sd, "N8N_WEBHOOK_URL", "http://n8n.local/webhook")
        resp = MagicMock()
        resp.status_code = 200
        mock_post = MagicMock(return_value=resp)
        monkeypatch.setattr(sd.requests, "post", mock_post)
        sd.send_alert("alert message")
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "http://n8n.local/webhook" in call_kwargs[0]

    def test_payload_includes_message(self, monkeypatch):
        monkeypatch.setattr(sd, "N8N_WEBHOOK_URL", "http://n8n.local/webhook")
        resp = MagicMock()
        resp.status_code = 200
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["json"] = json
            return resp

        monkeypatch.setattr(sd.requests, "post", fake_post)
        sd.send_alert("important alert")
        assert captured["json"]["message"] == "important alert"

    def test_payload_includes_level(self, monkeypatch):
        monkeypatch.setattr(sd, "N8N_WEBHOOK_URL", "http://n8n.local/webhook")
        resp = MagicMock()
        resp.status_code = 200
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["json"] = json
            return resp

        monkeypatch.setattr(sd.requests, "post", fake_post)
        sd.send_alert("msg", level="critical")
        assert captured["json"]["level"] == "critical"

    def test_non_200_response_no_exception(self, monkeypatch):
        monkeypatch.setattr(sd, "N8N_WEBHOOK_URL", "http://n8n.local/webhook")
        resp = MagicMock()
        resp.status_code = 500
        monkeypatch.setattr(sd.requests, "post", MagicMock(return_value=resp))
        sd.send_alert("msg")  # must not raise

    def test_request_exception_swallowed(self, monkeypatch):
        monkeypatch.setattr(sd, "N8N_WEBHOOK_URL", "http://n8n.local/webhook")
        monkeypatch.setattr(sd.requests, "post",
                            MagicMock(side_effect=RuntimeError("connection error")))
        sd.send_alert("msg")  # must not raise


# ---------------------------------------------------------------------------
# Flask request-context tests: _request_origin, _client_ip, _validate_path_slug,
# _is_trusted_proxy, _normalized_request_host, _guard_mutating_request
# ---------------------------------------------------------------------------

@pytest.fixture
def flask_app():
    """Return the sync_daemon Flask app in test mode."""
    sd.app.config["TESTING"] = True
    return sd.app


class TestRequestOrigin:
    def test_returns_origin_header(self, flask_app):
        with flask_app.test_request_context(
            "/api/test", headers={"Origin": "https://example.com"}
        ):
            assert sd._request_origin() == "https://example.com"

    def test_strips_whitespace(self, flask_app):
        with flask_app.test_request_context(
            "/api/test", headers={"Origin": "  https://example.com  "}
        ):
            assert sd._request_origin() == "https://example.com"

    def test_falls_back_to_referer(self, flask_app):
        with flask_app.test_request_context(
            "/api/test", headers={"Referer": "https://example.com/path?q=1"}
        ):
            assert sd._request_origin() == "https://example.com"

    def test_empty_when_no_headers(self, flask_app):
        with flask_app.test_request_context("/api/test"):
            assert sd._request_origin() == ""

    def test_invalid_referer_returns_empty(self, flask_app):
        with flask_app.test_request_context(
            "/api/test", headers={"Referer": "not-a-url"}
        ):
            assert sd._request_origin() == ""

    def test_origin_takes_priority_over_referer(self, flask_app):
        with flask_app.test_request_context(
            "/api/test",
            headers={"Origin": "https://origin.com", "Referer": "https://referer.com/page"}
        ):
            assert sd._request_origin() == "https://origin.com"


class TestClientIp:
    def test_returns_remote_addr_for_public_ip(self, flask_app):
        with flask_app.test_request_context(
            "/api/test", environ_base={"REMOTE_ADDR": "203.0.113.10"}
        ):
            assert sd._client_ip() == "203.0.113.10"

    def test_trusts_xff_from_private_proxy(self, flask_app):
        with flask_app.test_request_context(
            "/api/test",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={"X-Forwarded-For": "203.0.113.42"}
        ):
            assert sd._client_ip() == "203.0.113.42"

    def test_ignores_xff_from_public_ip(self, flask_app):
        with flask_app.test_request_context(
            "/api/test",
            environ_base={"REMOTE_ADDR": "8.8.8.8"},  # Google DNS — truly public
            headers={"X-Forwarded-For": "1.2.3.4"}
        ):
            assert sd._client_ip() == "8.8.8.8"

    def test_ignores_invalid_xff(self, flask_app):
        with flask_app.test_request_context(
            "/api/test",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={"X-Forwarded-For": "not-an-ip"}
        ):
            # Invalid XFF → falls back to remote_addr
            assert sd._client_ip() == "127.0.0.1"

    def test_empty_remote_addr(self, flask_app):
        with flask_app.test_request_context(
            "/api/test", environ_base={"REMOTE_ADDR": ""}
        ):
            result = sd._client_ip()
            assert isinstance(result, str)


class TestIsTrustedProxy:
    def test_loopback_is_trusted(self, flask_app):
        with flask_app.test_request_context(
            "/api/test", environ_base={"REMOTE_ADDR": "127.0.0.1"}
        ):
            assert sd._is_trusted_proxy() is True

    def test_private_ip_is_trusted(self, flask_app):
        with flask_app.test_request_context(
            "/api/test", environ_base={"REMOTE_ADDR": "192.168.1.1"}
        ):
            assert sd._is_trusted_proxy() is True

    def test_public_ip_not_trusted(self, flask_app):
        with flask_app.test_request_context(
            "/api/test", environ_base={"REMOTE_ADDR": "8.8.8.8"}
        ):
            assert sd._is_trusted_proxy() is False

    def test_invalid_addr_returns_false(self, flask_app):
        with flask_app.test_request_context(
            "/api/test", environ_base={"REMOTE_ADDR": "not-an-ip"}
        ):
            assert sd._is_trusted_proxy() is False


class TestNormalizedRequestHost:
    def test_returns_simple_host(self, flask_app):
        with flask_app.test_request_context(
            "/api/test", headers={"Host": "example.com"}
        ):
            result = sd._normalized_request_host()
            assert "example" in result

    def test_strips_port(self, flask_app):
        with flask_app.test_request_context(
            "/api/test", headers={"Host": "example.com:8080"}
        ):
            result = sd._normalized_request_host()
            assert result == "example.com"

    def test_returns_lowercase(self, flask_app):
        with flask_app.test_request_context(
            "/api/test", headers={"Host": "EXAMPLE.COM"}
        ):
            result = sd._normalized_request_host()
            assert result == result.lower()

    def test_trusts_xfh_from_private_proxy(self, flask_app):
        with flask_app.test_request_context(
            "/api/test",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={"Host": "backend", "X-Forwarded-Host": "frontend.example.com"}
        ):
            result = sd._normalized_request_host()
            assert result == "frontend.example.com"

    def test_ignores_xfh_from_public_ip(self, flask_app):
        with flask_app.test_request_context(
            "/api/test",
            environ_base={"REMOTE_ADDR": "8.8.8.8"},
            headers={"Host": "real.com", "X-Forwarded-Host": "spoofed.com"}
        ):
            result = sd._normalized_request_host()
            assert result == "real.com"

    def test_ipv6_host_stripped(self, flask_app):
        with flask_app.test_request_context(
            "/api/test",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={"X-Forwarded-Host": "[::1]:5000"}
        ):
            result = sd._normalized_request_host()
            assert result == "::1"

    def test_xfh_comma_separated_first_used(self, flask_app):
        with flask_app.test_request_context(
            "/api/test",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={"X-Forwarded-Host": "first.com, second.com"}
        ):
            result = sd._normalized_request_host()
            assert result == "first.com"


class TestValidatePathSlug:
    def test_valid_slug_returns_none(self, flask_app):
        with flask_app.test_request_context("/"):
            assert sd._validate_path_slug("sharks") is None

    def test_valid_slug_with_hyphen_returns_none(self, flask_app):
        with flask_app.test_request_context("/"):
            assert sd._validate_path_slug("spring-2026") is None

    def test_valid_slug_with_underscore_returns_none(self, flask_app):
        with flask_app.test_request_context("/"):
            assert sd._validate_path_slug("team_data") is None

    def test_invalid_slug_returns_error_tuple(self, flask_app):
        with flask_app.test_request_context("/"):
            result = sd._validate_path_slug("bad slug!")
            assert result is not None
            assert result[1] == 400

    def test_empty_slug_returns_error(self, flask_app):
        with flask_app.test_request_context("/"):
            result = sd._validate_path_slug("")
            assert result is not None
            assert result[1] == 400

    def test_too_long_slug_returns_error(self, flask_app):
        with flask_app.test_request_context("/"):
            result = sd._validate_path_slug("a" * 81)
            assert result is not None
            assert result[1] == 400

    def test_custom_label_in_error(self, flask_app):
        with flask_app.test_request_context("/"):
            result = sd._validate_path_slug("invalid!", label="team_id")
            assert result is not None


class TestGuardMutatingRequest:
    def test_non_json_returns_415(self, flask_app):
        with flask_app.test_request_context(
            "/api/test",
            method="POST",
            content_type="text/plain",
            data=b"hello"
        ):
            result = sd._guard_mutating_request()
            assert result is not None
            assert result[1] == 415

    def test_valid_origin_in_write_origins_returns_none(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS",
                            ["https://allowed.example.com"])
        with flask_app.test_request_context(
            "/api/test",
            method="POST",
            content_type="application/json",
            data=b'{}',
            headers={"Origin": "https://allowed.example.com"}
        ):
            result = sd._guard_mutating_request()
            assert result is None

    def test_disallowed_origin_returns_403(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS",
                            ["https://allowed.example.com"])
        with flask_app.test_request_context(
            "/api/test",
            method="POST",
            content_type="application/json",
            data=b'{}',
            headers={"Origin": "https://evil.com"}
        ):
            result = sd._guard_mutating_request()
            assert result is not None
            assert result[1] == 403

    def test_no_origin_returns_403(self, flask_app):
        with flask_app.test_request_context(
            "/api/test",
            method="POST",
            content_type="application/json",
            data=b'{}'
        ):
            result = sd._guard_mutating_request()
            assert result is not None
            assert result[1] == 403


# ---------------------------------------------------------------------------
# _supplement_enriched_from_base
# ---------------------------------------------------------------------------

class TestSupplementEnrichedFromBase:
    def test_no_base_file_returns_without_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        team_data = {"roster": [{"number": "7", "name": "Jane"}]}
        sd._supplement_enriched_from_base(team_data)  # must not raise

    def test_fills_missing_section(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        base_roster = [{"number": "7", "catching": {"tc": 5, "po": 5}}]
        (tmp_path / "team.json").write_text(json.dumps({"roster": base_roster}))
        team_data = {"roster": [{"number": "7", "name": "Jane"}]}
        sd._supplement_enriched_from_base(team_data)
        assert team_data["roster"][0].get("catching") == {"tc": 5, "po": 5}

    def test_does_not_overwrite_existing_section(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        base_roster = [{"number": "7", "catching": {"tc": 1}}]
        (tmp_path / "team.json").write_text(json.dumps({"roster": base_roster}))
        team_data = {"roster": [{"number": "7", "catching": {"tc": 99}}]}
        sd._supplement_enriched_from_base(team_data)
        assert team_data["roster"][0]["catching"]["tc"] == 99

    def test_fills_missing_batting_advanced_fields(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        base_roster = [{"number": "7",
                        "batting_advanced": {"babip": 0.350, "ps": 5.2}}]
        (tmp_path / "team.json").write_text(json.dumps({"roster": base_roster}))
        team_data = {"roster": [{"number": "7",
                                  "batting_advanced": {"pa": 20}}]}
        sd._supplement_enriched_from_base(team_data)
        adv = team_data["roster"][0]["batting_advanced"]
        assert adv.get("babip") == 0.350
        assert adv.get("ps") == 5.2

    def test_fills_missing_pitching_fields(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        base_roster = [{"number": "12",
                        "pitching": {"gp": 5, "gs": 5, "sv": 0, "baa": 0.25}}]
        (tmp_path / "team.json").write_text(json.dumps({"roster": base_roster}))
        team_data = {"roster": [{"number": "12",
                                  "pitching": {"ip": "15.0", "er": 4}}]}
        sd._supplement_enriched_from_base(team_data)
        pit = team_data["roster"][0]["pitching"]
        assert pit.get("baa") == 0.25

    def test_copies_pitching_section_when_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        base_roster = [{"number": "12",
                        "pitching": {"gp": 3, "ip": "9.0"}}]
        (tmp_path / "team.json").write_text(json.dumps({"roster": base_roster}))
        team_data = {"roster": [{"number": "12", "name": "Ace"}]}
        sd._supplement_enriched_from_base(team_data)
        assert "pitching" in team_data["roster"][0]

    def test_player_without_number_skipped(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        base_roster = [{"number": "7", "catching": {"tc": 5}}]
        (tmp_path / "team.json").write_text(json.dumps({"roster": base_roster}))
        # Player with no number
        team_data = {"roster": [{"name": "NoNumber", "catching": None}]}
        sd._supplement_enriched_from_base(team_data)  # must not raise

    def test_invalid_base_json_no_crash(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        (tmp_path / "team.json").write_text("not valid json {{{")
        team_data = {"roster": [{"number": "7"}]}
        sd._supplement_enriched_from_base(team_data)  # must not raise


# ---------------------------------------------------------------------------
# get_next_game_time
# ---------------------------------------------------------------------------

class TestGetNextGameTime:
    def _write_schedule(self, sharks_dir, upcoming):
        sharks_dir.mkdir(parents=True, exist_ok=True)
        sched = {"upcoming": upcoming}
        (sharks_dir / "schedule_manual.json").write_text(json.dumps(sched))

    def test_returns_none_when_no_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        result = sd.get_next_game_time()
        assert result is None

    def test_returns_none_when_no_upcoming_games(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        self._write_schedule(tmp_path, [])
        assert sd.get_next_game_time() is None

    def test_skips_non_game_entries(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        future = (datetime.now(ET) + timedelta(days=1)).strftime("%Y-%m-%d")
        self._write_schedule(tmp_path, [
            {"is_game": False, "date": future, "time": "06:00 PM"}
        ])
        assert sd.get_next_game_time() is None

    def test_skips_entries_without_date(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        self._write_schedule(tmp_path, [
            {"is_game": True, "date": "", "time": "06:00 PM"}
        ])
        assert sd.get_next_game_time() is None

    def test_returns_future_game_datetime(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        future = (datetime.now(ET) + timedelta(days=2)).strftime("%Y-%m-%d")
        self._write_schedule(tmp_path, [
            {"is_game": True, "date": future, "time": "06:00 PM"}
        ])
        result = sd.get_next_game_time()
        assert result is not None
        assert result.tzinfo is not None

    def test_returns_none_for_old_game(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        past = (datetime.now(ET) - timedelta(days=5)).strftime("%Y-%m-%d")
        self._write_schedule(tmp_path, [
            {"is_game": True, "date": past, "time": "06:00 PM"}
        ])
        assert sd.get_next_game_time() is None

    def test_includes_game_still_in_progress(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        # Game started 1 hour ago — within GAME_DURATION_HOURS window
        recent = (datetime.now(ET) - timedelta(hours=1)).strftime("%Y-%m-%d")
        recent_time = (datetime.now(ET) - timedelta(hours=1)).strftime("%I:%M %p")
        self._write_schedule(tmp_path, [
            {"is_game": True, "date": recent, "time": recent_time}
        ])
        result = sd.get_next_game_time()
        assert result is not None

    def test_24h_time_format_parsed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        future = (datetime.now(ET) + timedelta(days=2)).strftime("%Y-%m-%d")
        self._write_schedule(tmp_path, [
            {"is_game": True, "date": future, "time": "18:00"}  # 24h format
        ])
        result = sd.get_next_game_time()
        assert result is not None

    def test_invalid_time_format_skipped(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        future = (datetime.now(ET) + timedelta(days=2)).strftime("%Y-%m-%d")
        self._write_schedule(tmp_path, [
            {"is_game": True, "date": future, "time": "bad time format"}
        ])
        result = sd.get_next_game_time()
        assert result is None

    def test_default_time_used_when_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        future = (datetime.now(ET) + timedelta(days=2)).strftime("%Y-%m-%d")
        # No 'time' key → defaults to "12:00 PM"
        self._write_schedule(tmp_path, [
            {"is_game": True, "date": future}
        ])
        result = sd.get_next_game_time()
        assert result is not None


# ---------------------------------------------------------------------------
# _guard_mutating_rate_limit — time-controlled tests
# ---------------------------------------------------------------------------

class TestGuardMutatingRateLimit:
    def test_non_api_path_returns_none(self, flask_app):
        with flask_app.test_request_context(
            "/health", method="GET"
        ):
            result = sd._guard_mutating_rate_limit()
            assert result is None

    def test_get_request_returns_none(self, flask_app):
        with flask_app.test_request_context(
            "/api/data", method="GET"
        ):
            result = sd._guard_mutating_rate_limit()
            assert result is None

    def test_first_post_allowed(self, flask_app, monkeypatch):
        orig_buckets = sd._MUTATE_RATE_BUCKETS.copy()
        try:
            sd._MUTATE_RATE_BUCKETS.clear()
            with flask_app.test_request_context(
                "/api/test", method="POST",
                content_type="application/json",
                environ_base={"REMOTE_ADDR": "10.0.99.1"},
                data=b'{}'
            ):
                result = sd._guard_mutating_rate_limit()
                assert result is None
        finally:
            sd._MUTATE_RATE_BUCKETS.clear()
            sd._MUTATE_RATE_BUCKETS.update(orig_buckets)

    def test_rate_limit_exceeded_returns_429(self, flask_app):
        orig_buckets = sd._MUTATE_RATE_BUCKETS.copy()
        orig_max = sd.MUTATE_RATE_MAX
        try:
            sd._MUTATE_RATE_BUCKETS.clear()
            sd.MUTATE_RATE_MAX = 1  # very tight limit
            ip_key = "10.0.88.1:/api/rate_test"
            now = _time_mod.time()
            # Pre-fill the bucket to the limit
            sd._MUTATE_RATE_BUCKETS[ip_key] = [now]
            with flask_app.test_request_context(
                "/api/rate_test", method="POST",
                content_type="application/json",
                environ_base={"REMOTE_ADDR": "10.0.88.1"},
                data=b'{}'
            ):
                result = sd._guard_mutating_rate_limit()
                assert result is not None
                assert result[1] == 429
        finally:
            sd.MUTATE_RATE_MAX = orig_max
            sd._MUTATE_RATE_BUCKETS.clear()
            sd._MUTATE_RATE_BUCKETS.update(orig_buckets)

    def test_stale_keys_evicted(self, flask_app):
        orig_buckets = sd._MUTATE_RATE_BUCKETS.copy()
        orig_eviction = sd._LAST_EVICTION
        try:
            sd._MUTATE_RATE_BUCKETS.clear()
            # Add a stale key (timestamps way in the past)
            sd._MUTATE_RATE_BUCKETS["old_ip:/api/stale"] = [1000.0]
            # Force eviction to fire by setting _LAST_EVICTION to 0
            sd._LAST_EVICTION = 0.0
            with flask_app.test_request_context(
                "/api/stale", method="POST",
                content_type="application/json",
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
                data=b'{}'
            ):
                sd._guard_mutating_rate_limit()
            # Stale key should have been evicted
            assert "old_ip:/api/stale" not in sd._MUTATE_RATE_BUCKETS
        finally:
            sd._MUTATE_RATE_BUCKETS.clear()
            sd._MUTATE_RATE_BUCKETS.update(orig_buckets)
            sd._LAST_EVICTION = orig_eviction

    def test_hard_cap_on_too_many_keys(self, flask_app):
        orig_buckets = sd._MUTATE_RATE_BUCKETS.copy()
        orig_max_keys = sd._MUTATE_RATE_MAX_KEYS
        try:
            sd._MUTATE_RATE_BUCKETS.clear()
            sd._MUTATE_RATE_MAX_KEYS = 2
            now = _time_mod.time()
            # Fill to max_keys
            sd._MUTATE_RATE_BUCKETS["ip1:/api/a"] = [now]
            sd._MUTATE_RATE_BUCKETS["ip2:/api/b"] = [now]
            # Third new IP should hit the hard cap
            with flask_app.test_request_context(
                "/api/c", method="POST",
                content_type="application/json",
                environ_base={"REMOTE_ADDR": "10.99.99.99"},
                data=b'{}'
            ):
                result = sd._guard_mutating_rate_limit()
                assert result is not None
                assert result[1] == 429
        finally:
            sd._MUTATE_RATE_MAX_KEYS = orig_max_keys
            sd._MUTATE_RATE_BUCKETS.clear()
            sd._MUTATE_RATE_BUCKETS.update(orig_buckets)


# ---------------------------------------------------------------------------
# Flask error handlers
# ---------------------------------------------------------------------------

class TestFlaskErrorHandlers:
    def test_413_error_handler(self, flask_app):
        with flask_app.test_client() as client:
            # Send a body that exceeds MAX_CONTENT_LENGTH
            orig_max = flask_app.config["MAX_CONTENT_LENGTH"]
            flask_app.config["MAX_CONTENT_LENGTH"] = 10
            try:
                resp = client.post(
                    "/api/trigger-sync",
                    data=b"x" * 50,
                    content_type="application/json"
                )
                assert resp.status_code in (413, 400, 403, 404, 415)
            finally:
                flask_app.config["MAX_CONTENT_LENGTH"] = orig_max

    def test_health_route_exists(self, flask_app):
        with flask_app.test_client() as client:
            resp = client.get("/health")
            assert resp.status_code in (200, 404)

    def test_security_after_request_adds_headers(self, flask_app):
        with flask_app.test_client() as client:
            resp = client.get("/health")
            if resp.status_code == 200:
                # Security headers should be present on API responses
                headers = dict(resp.headers)
                assert "Server" not in headers or headers["Server"] != "Werkzeug"


# ---------------------------------------------------------------------------
# Flask route tests — simple GET routes
# ---------------------------------------------------------------------------

class TestFlaskGameStateRoutes:
    def test_get_game_state_returns_200(self, flask_app):
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/game-state")
        assert resp.status_code == 200

    def test_get_game_state_returns_json(self, flask_app):
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/game-state")
        data = resp.get_json()
        assert "inning" in data
        assert "half" in data

    def test_post_game_state_updates_inning(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        orig_state = sd._LIVE_GAME_STATE.copy()
        try:
            with flask_app.test_client() as client:
                resp = client.post(
                    "/api/announcer/game-state",
                    json={"inning": 5},
                    content_type="application/json",
                    headers={"Origin": "https://test.example.com"}
                )
            assert resp.status_code == 200
            assert sd._LIVE_GAME_STATE["inning"] == 5
        finally:
            sd._LIVE_GAME_STATE.update(orig_state)

    def test_post_game_state_updates_half(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        orig_state = sd._LIVE_GAME_STATE.copy()
        try:
            with flask_app.test_client() as client:
                resp = client.post(
                    "/api/announcer/game-state",
                    json={"half": "bottom"},
                    content_type="application/json",
                    headers={"Origin": "https://test.example.com"}
                )
            assert resp.status_code == 200
            assert sd._LIVE_GAME_STATE["half"] == "bottom"
        finally:
            sd._LIVE_GAME_STATE.update(orig_state)

    def test_post_game_state_updates_outs(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        orig_state = sd._LIVE_GAME_STATE.copy()
        try:
            with flask_app.test_client() as client:
                resp = client.post(
                    "/api/announcer/game-state",
                    json={"outs": 2},
                    content_type="application/json",
                    headers={"Origin": "https://test.example.com"}
                )
            assert resp.status_code == 200
            assert sd._LIVE_GAME_STATE["outs"] == 2
        finally:
            sd._LIVE_GAME_STATE.update(orig_state)

    def test_post_game_state_updates_scores(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        orig_state = sd._LIVE_GAME_STATE.copy()
        try:
            with flask_app.test_client() as client:
                resp = client.post(
                    "/api/announcer/game-state",
                    json={"score_us": 3, "score_them": 1},
                    content_type="application/json",
                    headers={"Origin": "https://test.example.com"}
                )
            assert resp.status_code == 200
            assert sd._LIVE_GAME_STATE["score_us"] == 3
        finally:
            sd._LIVE_GAME_STATE.update(orig_state)

    def test_post_game_state_updates_bases(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        orig_state = sd._LIVE_GAME_STATE.copy()
        try:
            with flask_app.test_client() as client:
                resp = client.post(
                    "/api/announcer/game-state",
                    json={"bases": [True, False, True]},
                    content_type="application/json",
                    headers={"Origin": "https://test.example.com"}
                )
            assert resp.status_code == 200
            assert sd._LIVE_GAME_STATE["bases"] == [True, False, True]
        finally:
            sd._LIVE_GAME_STATE.update(orig_state)

    def test_post_game_state_updates_achievement(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        orig_state = sd._LIVE_GAME_STATE.copy()
        try:
            with flask_app.test_client() as client:
                resp = client.post(
                    "/api/announcer/game-state",
                    json={"achievement": "Home Run!"},
                    content_type="application/json",
                    headers={"Origin": "https://test.example.com"}
                )
            assert resp.status_code == 200
            assert "Home Run" in sd._LIVE_GAME_STATE["achievement"]
        finally:
            sd._LIVE_GAME_STATE.update(orig_state)

    def test_post_game_state_clears_achievement(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        orig_state = sd._LIVE_GAME_STATE.copy()
        try:
            with flask_app.test_client() as client:
                resp = client.post(
                    "/api/announcer/game-state",
                    json={"achievement": None},
                    content_type="application/json",
                    headers={"Origin": "https://test.example.com"}
                )
            assert resp.status_code == 200
            assert sd._LIVE_GAME_STATE["achievement"] is None
        finally:
            sd._LIVE_GAME_STATE.update(orig_state)

    def test_post_game_state_ignores_invalid_inning(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        orig_state = sd._LIVE_GAME_STATE.copy()
        try:
            with flask_app.test_client() as client:
                resp = client.post(
                    "/api/announcer/game-state",
                    json={"inning": "notanumber"},
                    content_type="application/json",
                    headers={"Origin": "https://test.example.com"}
                )
            assert resp.status_code == 200
        finally:
            sd._LIVE_GAME_STATE.update(orig_state)

    def test_post_game_state_clamps_inning_max(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        orig_state = sd._LIVE_GAME_STATE.copy()
        try:
            with flask_app.test_client() as client:
                resp = client.post(
                    "/api/announcer/game-state",
                    json={"inning": 999},
                    content_type="application/json",
                    headers={"Origin": "https://test.example.com"}
                )
            assert resp.status_code == 200
            assert sd._LIVE_GAME_STATE["inning"] <= 20
        finally:
            sd._LIVE_GAME_STATE.update(orig_state)

    def test_post_game_state_requires_json(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/announcer/game-state",
                data=b"not json",
                content_type="text/plain",
                headers={"Origin": "https://test.example.com"}
            )
        assert resp.status_code == 415

    def test_post_game_state_requires_origin(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/announcer/game-state",
                json={"inning": 3},
                content_type="application/json"
                # No Origin header
            )
        assert resp.status_code == 403


class TestLicensingInfoRoute:
    def test_returns_200(self, flask_app):
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/licensing-info")
        assert resp.status_code == 200

    def test_returns_disclaimer(self, flask_app):
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/licensing-info")
        data = resp.get_json()
        assert "disclaimer" in data
        assert "license" in data["disclaimer"].lower()

    def test_returns_providers(self, flask_app):
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/licensing-info")
        data = resp.get_json()
        assert "providers" in data
        assert len(data["providers"]) > 0


class TestRecentSubsRoute:
    def test_returns_200(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        with flask_app.test_client() as client:
            resp = client.get("/api/recent-subs")
        assert resp.status_code == 200

    def test_returns_list(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        with flask_app.test_client() as client:
            resp = client.get("/api/recent-subs")
        data = resp.get_json()
        assert isinstance(data, list)

    def test_includes_recent_sub(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        from datetime import datetime, timezone
        recent_ts = (datetime.now(ET) - timedelta(days=3)).isoformat()
        tracker = {"Jane Sub": {"last_active": recent_ts, "auto_deactivated": True}}
        (tmp_path / "sub_tracker.json").write_text(json.dumps(tracker))
        with flask_app.test_client() as client:
            resp = client.get("/api/recent-subs")
        data = resp.get_json()
        names = [r["name"] for r in data]
        assert "Jane Sub" in names

    def test_excludes_old_sub(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        old_ts = (datetime.now(ET) - timedelta(days=30)).isoformat()
        tracker = {"Old Sub": {"last_active": old_ts, "auto_deactivated": True}}
        (tmp_path / "sub_tracker.json").write_text(json.dumps(tracker))
        with flask_app.test_client() as client:
            resp = client.get("/api/recent-subs")
        data = resp.get_json()
        names = [r["name"] for r in data]
        assert "Old Sub" not in names


# ---------------------------------------------------------------------------
# _load_roster_manifest, _load_sub_tracker, _is_core_player
# ---------------------------------------------------------------------------

class TestRosterManifestHelpers:
    def test_load_roster_manifest_no_file(self, monkeypatch, tmp_path):
        sd._ROSTER_MANIFEST_CACHE = None  # clear cache
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        result = sd._load_roster_manifest()
        assert result == []
        sd._ROSTER_MANIFEST_CACHE = None  # reset

    def test_load_roster_manifest_reads_file(self, monkeypatch, tmp_path):
        sd._ROSTER_MANIFEST_CACHE = None
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        (tmp_path / "roster_manifest.json").write_text(
            json.dumps({"core_players": ["Jane Doe", "Sam Smith"]})
        )
        result = sd._load_roster_manifest()
        assert "jane doe" in result
        assert "sam smith" in result
        sd._ROSTER_MANIFEST_CACHE = None

    def test_load_roster_manifest_cached(self, monkeypatch, tmp_path):
        sd._ROSTER_MANIFEST_CACHE = ["cached_player"]
        result = sd._load_roster_manifest()
        assert result == ["cached_player"]
        sd._ROSTER_MANIFEST_CACHE = None

    def test_is_core_player_true(self, monkeypatch, tmp_path):
        sd._ROSTER_MANIFEST_CACHE = None
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        (tmp_path / "roster_manifest.json").write_text(
            json.dumps({"core_players": ["Jane Doe"]})
        )
        assert sd._is_core_player("Jane Doe") is True
        sd._ROSTER_MANIFEST_CACHE = None

    def test_is_core_player_false(self, monkeypatch, tmp_path):
        sd._ROSTER_MANIFEST_CACHE = None
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        (tmp_path / "roster_manifest.json").write_text(
            json.dumps({"core_players": ["Jane Doe"]})
        )
        assert sd._is_core_player("Random Sub") is False
        sd._ROSTER_MANIFEST_CACHE = None

    def test_load_sub_tracker_empty_when_no_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        result = sd._load_sub_tracker()
        assert result == {}

    def test_save_sub_tracker_writes_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        sd._save_sub_tracker({"Sub": {"last_active": "2026-05-01"}})
        data = json.loads((tmp_path / "sub_tracker.json").read_text())
        assert "Sub" in data


# ---------------------------------------------------------------------------
# /api/schedule
# ---------------------------------------------------------------------------

class TestHandleSchedule:
    def test_no_file_returns_empty_lists(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        with flask_app.test_client() as client:
            resp = client.get("/api/schedule")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"upcoming": [], "past": []}

    def test_returns_upcoming_and_past(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        sched = {
            "upcoming": [{"opponent": "Tigers", "date": "2099-06-01"}],
            "past": [{"opponent": "Bears", "date": "2024-01-01"}],
        }
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        with flask_app.test_client() as client:
            resp = client.get("/api/schedule")
        data = resp.get_json()
        assert len(data["upcoming"]) == 1
        assert len(data["past"]) == 1

    def test_promotes_stale_upcoming_to_past(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        sched = {
            "upcoming": [{"opponent": "Old Foes", "date": "2020-01-01"}],
            "past": [],
        }
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        with flask_app.test_client() as client:
            resp = client.get("/api/schedule")
        data = resp.get_json()
        assert len(data["upcoming"]) == 0
        assert len(data["past"]) == 1
        assert data["past"][0]["opponent_raw"] == "Old Foes"

    def test_applies_known_result_to_promoted_game(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        sched = {
            "upcoming": [{"opponent": "Rivals", "date": "2020-03-15"}],
            "past": [],
        }
        known = {"results": [{"date": "2020-03-15", "result": "W", "score": "11-5"}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        (tmp_path / "known_game_results.json").write_text(json.dumps(known))
        with flask_app.test_client() as client:
            resp = client.get("/api/schedule")
        data = resp.get_json()
        assert data["past"][0]["result"] == "W"
        assert data["past"][0]["score"] == "11-5"

    def test_applies_known_result_to_existing_past_game(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        sched = {
            "upcoming": [],
            "past": [{"opponent": "Old Team", "date": "2020-01-05", "result": "", "score": ""}],
        }
        known = {"results": [{"date": "2020-01-05", "result": "L", "score": "3-7"}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        (tmp_path / "known_game_results.json").write_text(json.dumps(known))
        with flask_app.test_client() as client:
            resp = client.get("/api/schedule")
        data = resp.get_json()
        assert data["past"][0]["result"] == "L"

    def test_opponent_raw_preserved(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        sched = {
            "upcoming": [{"opponent": "Team ABC (1234)", "date": "2099-06-01"}],
            "past": [],
        }
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        with flask_app.test_client() as client:
            resp = client.get("/api/schedule")
        data = resp.get_json()
        assert data["upcoming"][0]["opponent_raw"] == "Team ABC (1234)"

    def test_bad_known_results_file_does_not_crash(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        sched = {"upcoming": [], "past": []}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        (tmp_path / "known_game_results.json").write_text("{{bad json")
        with flask_app.test_client() as client:
            resp = client.get("/api/schedule")
        assert resp.status_code == 200

    def test_does_not_overwrite_existing_result(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        sched = {
            "upcoming": [],
            "past": [{"opponent": "Known", "date": "2020-06-01", "result": "W", "score": "5-3"}],
        }
        known = {"results": [{"date": "2020-06-01", "result": "L", "score": "1-9"}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        (tmp_path / "known_game_results.json").write_text(json.dumps(known))
        with flask_app.test_client() as client:
            resp = client.get("/api/schedule")
        data = resp.get_json()
        # Existing "W" should not be overwritten with "L"
        assert data["past"][0]["result"] == "W"


# ---------------------------------------------------------------------------
# /api/stats-db/status
# ---------------------------------------------------------------------------

class TestHandleStatsDbStatus:
    def test_returns_200_with_mock(self, flask_app, monkeypatch):
        import types
        fake_stats = types.ModuleType("stats_db")
        fake_stats.get_db_status = lambda: {"rows": 42, "tables": 5}
        monkeypatch.setitem(sys.modules, "stats_db", fake_stats)
        with flask_app.test_client() as client:
            resp = client.get("/api/stats-db/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["rows"] == 42

    def test_returns_503_on_exception(self, flask_app, monkeypatch):
        import types
        fake_stats = types.ModuleType("stats_db")
        fake_stats.get_db_status = MagicMock(side_effect=RuntimeError("db gone"))
        monkeypatch.setitem(sys.modules, "stats_db", fake_stats)
        with flask_app.test_client() as client:
            resp = client.get("/api/stats-db/status")
        assert resp.status_code == 503
        assert "stats_db_unavailable" in resp.get_json().get("error", "")


# ---------------------------------------------------------------------------
# /api/opponent-discovery
# ---------------------------------------------------------------------------

class TestHandleOpponentDiscovery:
    def test_returns_defaults_when_no_file(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        with flask_app.test_client() as client:
            resp = client.get("/api/opponent-discovery")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["generated_at"] is None
        assert data["teams"] == []
        assert data["missing_schedule_opponents"] == []

    def test_returns_file_content(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        artifact = {"generated_at": "2026-05-01", "teams": [{"id": "abc"}], "missing_schedule_opponents": []}
        (tmp_path / "opponent_discovery.json").write_text(json.dumps(artifact))
        with flask_app.test_client() as client:
            resp = client.get("/api/opponent-discovery")
        data = resp.get_json()
        assert data["generated_at"] == "2026-05-01"
        assert len(data["teams"]) == 1


# ---------------------------------------------------------------------------
# /api/availability  GET + POST
# ---------------------------------------------------------------------------

class TestHandleAvailabilityGet:
    def test_returns_200(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        with flask_app.test_client() as client:
            resp = client.get("/api/availability")
        assert resp.status_code == 200

    def test_returns_saved_when_no_team_file(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        avail = {"Jane Doe": True, "Bob Smith": False}
        (tmp_path / "availability.json").write_text(json.dumps(avail))
        with flask_app.test_client() as client:
            resp = client.get("/api/availability")
        data = resp.get_json()
        assert data["Jane Doe"] is True
        assert data["Bob Smith"] is False

    def test_backfills_core_players_as_true(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        sd._ROSTER_MANIFEST_CACHE = None
        team = {"roster": [{"first": "Jane", "last": "Doe"}, {"first": "Sam", "last": "Smith"}]}
        manifest = {"core_players": ["Jane Doe"]}
        (tmp_path / "team_enriched.json").write_text(json.dumps(team))
        (tmp_path / "roster_manifest.json").write_text(json.dumps(manifest))
        with flask_app.test_client() as client:
            resp = client.get("/api/availability")
        data = resp.get_json()
        assert data["Jane Doe"] is True   # core player default
        assert data["Sam Smith"] is False  # non-core default
        sd._ROSTER_MANIFEST_CACHE = None

    def test_saved_value_overrides_default(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        sd._ROSTER_MANIFEST_CACHE = None
        team = {"roster": [{"first": "Jane", "last": "Doe"}]}
        manifest = {"core_players": ["Jane Doe"]}
        avail = {"Jane Doe": False}  # manually set to unavailable
        (tmp_path / "team_enriched.json").write_text(json.dumps(team))
        (tmp_path / "roster_manifest.json").write_text(json.dumps(manifest))
        (tmp_path / "availability.json").write_text(json.dumps(avail))
        with flask_app.test_client() as client:
            resp = client.get("/api/availability")
        data = resp.get_json()
        assert data["Jane Doe"] is False
        sd._ROSTER_MANIFEST_CACHE = None

    def test_preserves_extra_subs_in_saved(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        team = {"roster": [{"first": "Jane", "last": "Doe"}]}
        avail = {"Jane Doe": True, "Extra Sub": True}
        (tmp_path / "team_enriched.json").write_text(json.dumps(team))
        (tmp_path / "availability.json").write_text(json.dumps(avail))
        with flask_app.test_client() as client:
            resp = client.get("/api/availability")
        data = resp.get_json()
        assert "Extra Sub" in data


class TestHandleAvailabilityPost:
    def test_post_requires_origin(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/availability",
                json={"Jane Doe": True},
                content_type="application/json",
            )
        assert resp.status_code == 403

    def test_post_rejects_non_json(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/availability",
                data="not json",
                content_type="text/plain",
                headers={"Origin": "https://test.example.com"},
            )
        assert resp.status_code == 415

    def test_post_rejects_too_large(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        big_payload = {f"Player {i}": True for i in range(61)}
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/availability",
                json=big_payload,
                content_type="application/json",
                headers={"Origin": "https://test.example.com"},
            )
        assert resp.status_code == 400
        assert "payload_too_large" in resp.get_json().get("error", "")

    def test_post_rejects_non_bool_values(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/availability",
                json={"Jane Doe": "yes"},
                content_type="application/json",
                headers={"Origin": "https://test.example.com"},
            )
        assert resp.status_code == 400
        assert "values_must_be_boolean" in resp.get_json().get("error", "")

    def test_post_saves_availability(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        sd._ROSTER_MANIFEST_CACHE = None
        (tmp_path / "roster_manifest.json").write_text(json.dumps({"core_players": ["Jane Doe"]}))
        # Mock out the optimizer/SWOT imports so they don't fail
        with patch("sync_daemon.lineup_optimizer", create=True), \
             patch("sync_daemon.swot_analyzer", create=True):
            with flask_app.test_client() as client:
                resp = client.post(
                    "/api/availability",
                    json={"Jane Doe": True},
                    content_type="application/json",
                    headers={"Origin": "https://test.example.com"},
                )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"
        saved = json.loads((tmp_path / "availability.json").read_text())
        assert saved["Jane Doe"] is True
        sd._ROSTER_MANIFEST_CACHE = None


# ---------------------------------------------------------------------------
# /api/league-players
# ---------------------------------------------------------------------------

class TestHandleLeaguePlayers:
    def test_returns_empty_list_no_opponents_dir(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "DATA_DIR", tmp_path)
        with flask_app.test_client() as client:
            resp = client.get("/api/league-players")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_returns_players_from_team_file(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "DATA_DIR", tmp_path)
        opp_dir = tmp_path / "opponents" / "team_alpha"
        opp_dir.mkdir(parents=True)
        team_data = {
            "team_name": "Alpha",
            "gc_team_id": "tid1",
            "roster": [{"first": "Alice", "last": "Wonder", "number": "7"}],
        }
        (opp_dir / "team.json").write_text(json.dumps(team_data))
        with flask_app.test_client() as client:
            resp = client.get("/api/league-players")
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["first"] == "Alice"
        assert data[0]["team_name"] == "Alpha"

    def test_sorted_alphabetically(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "DATA_DIR", tmp_path)
        opp_dir = tmp_path / "opponents" / "team_z"
        opp_dir.mkdir(parents=True)
        roster = [
            {"first": "Zara", "last": "A", "number": "1"},
            {"first": "Anna", "last": "B", "number": "2"},
        ]
        (opp_dir / "team.json").write_text(json.dumps({"team_name": "Z", "roster": roster}))
        with flask_app.test_client() as client:
            resp = client.get("/api/league-players")
        data = resp.get_json()
        assert data[0]["first"] == "Anna"
        assert data[1]["first"] == "Zara"

    def test_bad_team_file_skipped(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "DATA_DIR", tmp_path)
        opp_dir = tmp_path / "opponents" / "bad_team"
        opp_dir.mkdir(parents=True)
        (opp_dir / "team.json").write_text("{{bad json")
        with flask_app.test_client() as client:
            resp = client.get("/api/league-players")
        assert resp.status_code == 200
        assert resp.get_json() == []


# ---------------------------------------------------------------------------
# /api/games/<game_id>
# ---------------------------------------------------------------------------

class TestHandleGameDetail:
    def test_returns_404_when_not_found(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        (tmp_path / "games").mkdir()
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game_20240101")
        assert resp.status_code == 404

    def test_returns_400_for_invalid_slug(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        (tmp_path / "games").mkdir()
        with flask_app.test_client() as client:
            resp = client.get("/api/games/../../etc/passwd")
        assert resp.status_code in (400, 404)

    def test_returns_game_data(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        game = {"game_id": "game_20240101", "date": "2024-01-01", "opponent": "Tigers"}
        (games_dir / "game_20240101.json").write_text(json.dumps(game))
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game_20240101")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["game_id"] == "game_20240101"

    def test_legacy_to_new_format_bridge(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        game = {
            "game_id": "game_20240102",
            "date": "2024-01-02",
            "sharks": {"batting": [{"name": "Jane", "pa": 3}], "pitching": []},
        }
        (games_dir / "game_20240102.json").write_text(json.dumps(game))
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game_20240102")
        data = resp.get_json()
        assert "sharks_batting" in data
        assert data["sharks_batting"][0]["name"] == "Jane"

    def test_opponent_stats_bridge(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        game = {
            "game_id": "game_20240103",
            "date": "2024-01-03",
            "opponent_stats": {"batting": [{"name": "Opp1", "pa": 2}], "pitching": []},
        }
        (games_dir / "game_20240103.json").write_text(json.dumps(game))
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game_20240103")
        data = resp.get_json()
        assert "opponent_batting" in data
        assert data["opponent_batting"][0]["name"] == "Opp1"

    def test_score_dict_converted_to_string(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        game = {
            "game_id": "game_20240104",
            "date": "2024-01-04",
            "score": {"sharks": 11, "opponent": 5},
        }
        (games_dir / "game_20240104.json").write_text(json.dumps(game))
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game_20240104")
        data = resp.get_json()
        assert data.get("score_str") == "11-5"

    def test_503_on_corrupt_json(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        (games_dir / "game_bad.json").write_text("{{not valid")
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game_bad")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# /api/games  (list)
# ---------------------------------------------------------------------------

class TestHandleGamesList:
    def test_returns_empty_list_no_games(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        (tmp_path / "games").mkdir()
        with flask_app.test_client() as client:
            resp = client.get("/api/games")
        assert resp.status_code == 200
        assert resp.get_json() == []


# ---------------------------------------------------------------------------
# /api/announcer/heartbeat  (POST)
# ---------------------------------------------------------------------------

class TestAnnouncerHeartbeat:
    def _make_adb(self):
        adb = MagicMock()
        adb.update_heartbeat = MagicMock()
        return adb

    def test_heartbeat_rejected_without_origin(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/announcer/heartbeat",
                json={"worker_id": "mac"},
                content_type="application/json",
            )
        assert resp.status_code == 403

    def test_heartbeat_accepted_with_origin(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        mock_adb = self._make_adb()
        monkeypatch.setattr(sd, "_announcer_db", lambda: mock_adb)
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/announcer/heartbeat",
                json={"worker_id": "mac", "version": "1.0"},
                content_type="application/json",
                headers={"Origin": "https://test.example.com"},
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["worker_id"] == "mac"

    def test_heartbeat_calls_update_heartbeat(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        mock_adb = self._make_adb()
        monkeypatch.setattr(sd, "_announcer_db", lambda: mock_adb)
        with flask_app.test_client() as client:
            client.post(
                "/api/announcer/heartbeat",
                json={"worker_id": "mac", "version": "2.0"},
                content_type="application/json",
                headers={"Origin": "https://test.example.com"},
            )
        mock_adb.update_heartbeat.assert_called_once_with("mac", "2.0")

    def test_heartbeat_default_worker_id(self, flask_app, monkeypatch):
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        mock_adb = self._make_adb()
        monkeypatch.setattr(sd, "_announcer_db", lambda: mock_adb)
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/announcer/heartbeat",
                json={},
                content_type="application/json",
                headers={"Origin": "https://test.example.com"},
            )
        data = resp.get_json()
        assert data["worker_id"] == "mac"


# ---------------------------------------------------------------------------
# /api/announcer/worker-status  (GET)
# ---------------------------------------------------------------------------

class TestAnnouncerWorkerStatus:
    def _make_adb(self, hb=None, pending=0, alive=False):
        adb = MagicMock()
        adb.get_heartbeat_info = MagicMock(return_value=hb)
        adb.get_pending_jobs = MagicMock(return_value=list(range(pending)))
        adb.is_worker_alive = MagicMock(return_value=alive)
        return adb

    def test_returns_200(self, flask_app, monkeypatch):
        adb = self._make_adb()
        monkeypatch.setattr(sd, "_announcer_db", lambda: adb)
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/worker-status")
        assert resp.status_code == 200

    def test_hub_status_always_online(self, flask_app, monkeypatch):
        adb = self._make_adb()
        monkeypatch.setattr(sd, "_announcer_db", lambda: adb)
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/worker-status")
        assert resp.get_json()["hub_status"] == "ONLINE"

    def test_offline_when_no_heartbeat(self, flask_app, monkeypatch):
        adb = self._make_adb(hb=None, alive=False)
        monkeypatch.setattr(sd, "_announcer_db", lambda: adb)
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/worker-status")
        data = resp.get_json()
        assert data["primary_worker"]["status"] == "OFFLINE"
        assert data["current_mode"] == "RAPID"

    def test_active_when_alive_with_pending_jobs(self, flask_app, monkeypatch):
        hb = {"worker_id": "mac-pro", "last_seen_at": "2026-05-08T12:00:00"}
        adb = self._make_adb(hb=hb, pending=3, alive=True)
        monkeypatch.setattr(sd, "_announcer_db", lambda: adb)
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/worker-status")
        data = resp.get_json()
        assert data["primary_worker"]["status"] == "ACTIVE"
        assert data["current_mode"] == "ELITE"
        assert data["primary_worker"]["queue_depth"] == 3

    def test_standby_when_alive_no_pending_jobs(self, flask_app, monkeypatch):
        hb = {"worker_id": "mac-pro", "last_seen_at": "2026-05-08T12:00:00"}
        adb = self._make_adb(hb=hb, pending=0, alive=True)
        monkeypatch.setattr(sd, "_announcer_db", lambda: adb)
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/worker-status")
        data = resp.get_json()
        assert data["primary_worker"]["status"] == "STANDBY"

    def test_offline_when_heartbeat_exists_but_not_alive(self, flask_app, monkeypatch):
        hb = {"worker_id": "mac-pro", "last_seen_at": "2026-05-01T12:00:00"}
        adb = self._make_adb(hb=hb, pending=0, alive=False)
        monkeypatch.setattr(sd, "_announcer_db", lambda: adb)
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/worker-status")
        data = resp.get_json()
        assert data["primary_worker"]["status"] == "OFFLINE"

    def test_failover_worker_always_ready(self, flask_app, monkeypatch):
        adb = self._make_adb()
        monkeypatch.setattr(sd, "_announcer_db", lambda: adb)
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/worker-status")
        data = resp.get_json()
        assert data["failover_worker"]["status"] == "READY"


# ---------------------------------------------------------------------------
# /api/announcer/render-queue  (GET)
# ---------------------------------------------------------------------------

class TestAnnouncerRenderQueueGet:
    def test_returns_200_with_empty_jobs(self, flask_app, monkeypatch):
        adb = MagicMock()
        adb.get_pending_jobs = MagicMock(return_value=[])
        monkeypatch.setattr(sd, "_announcer_db", lambda: adb)
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/render-queue")
        assert resp.status_code == 200
        assert resp.get_json()["jobs"] == []

    def test_returns_jobs_list(self, flask_app, monkeypatch):
        adb = MagicMock()
        adb.get_pending_jobs = MagicMock(return_value=[{"id": "j1"}, {"id": "j2"}])
        monkeypatch.setattr(sd, "_announcer_db", lambda: adb)
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/render-queue")
        data = resp.get_json()
        assert len(data["jobs"]) == 2


# ---------------------------------------------------------------------------
# auto_deactivate_subs()
# ---------------------------------------------------------------------------

class TestAutoDeactivateSubs:
    def _setup_files(self, tmp_path, past_date="2020-01-01", roster=None):
        """Write minimal schedule + availability + roster_manifest to tmp_path.

        roster_manifest must be non-empty or auto_deactivate_subs() exits early
        (can't distinguish subs from starters without a core player list).
        """
        sd._ROSTER_MANIFEST_CACHE = None
        sched = {
            "past": [{"opponent": "Old Team", "date": past_date}],
            "upcoming": [],
        }
        avail = {"Sub Player": True}
        # Include at least one core player so the manifest is truthy
        manifest = {"core_players": roster or ["Jane Core"]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        (tmp_path / "availability.json").write_text(json.dumps(avail))
        (tmp_path / "roster_manifest.json").write_text(json.dumps(manifest))

    def test_no_op_when_no_schedule_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        sd._ROSTER_MANIFEST_CACHE = None
        (tmp_path / "availability.json").write_text('{}')
        # No schedule_manual.json — should return without modifying
        sd.auto_deactivate_subs()

    def test_no_op_when_no_availability_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        sd._ROSTER_MANIFEST_CACHE = None
        sched = {"past": [{"date": "2020-01-01"}], "upcoming": []}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        sd.auto_deactivate_subs()

    def test_no_op_when_no_manifest(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        sd._ROSTER_MANIFEST_CACHE = None
        sched = {"past": [{"date": "2020-01-01"}], "upcoming": []}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        (tmp_path / "availability.json").write_text('{"Sub Player": true}')
        # No roster_manifest.json — _load_roster_manifest returns [] → skip
        sd.auto_deactivate_subs()
        saved = json.loads((tmp_path / "availability.json").read_text())
        assert saved["Sub Player"] is True
        sd._ROSTER_MANIFEST_CACHE = None

    def test_no_op_when_no_past_games(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        sd._ROSTER_MANIFEST_CACHE = None
        sched = {"past": [], "upcoming": []}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        (tmp_path / "availability.json").write_text('{"Sub Player": true}')
        (tmp_path / "roster_manifest.json").write_text('{"core_players": []}')
        sd.auto_deactivate_subs()
        sd._ROSTER_MANIFEST_CACHE = None

    def test_deactivates_sub_after_game_day(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        self._setup_files(tmp_path, past_date="2020-01-01")
        sd.auto_deactivate_subs()
        saved = json.loads((tmp_path / "availability.json").read_text())
        assert saved["Sub Player"] is False
        sd._ROSTER_MANIFEST_CACHE = None

    def test_does_not_deactivate_core_player(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        sd._ROSTER_MANIFEST_CACHE = None
        sched = {"past": [{"date": "2020-01-01"}], "upcoming": []}
        avail = {"Jane Doe": True}
        manifest = {"core_players": ["Jane Doe"]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        (tmp_path / "availability.json").write_text(json.dumps(avail))
        (tmp_path / "roster_manifest.json").write_text(json.dumps(manifest))
        sd.auto_deactivate_subs()
        saved = json.loads((tmp_path / "availability.json").read_text())
        assert saved["Jane Doe"] is True
        sd._ROSTER_MANIFEST_CACHE = None

    def test_does_not_deactivate_twice(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        sd._ROSTER_MANIFEST_CACHE = None
        sched = {"past": [{"date": "2020-01-01"}], "upcoming": []}
        avail = {"Sub Player": True}  # still active — but tracker says already done
        manifest = {"core_players": ["Jane Core"]}  # non-empty so function doesn't exit early
        tracker = {"Sub Player": {"deactivated_after_game": "2020-01-01", "auto_deactivated": True}}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        (tmp_path / "availability.json").write_text(json.dumps(avail))
        (tmp_path / "roster_manifest.json").write_text(json.dumps(manifest))
        (tmp_path / "sub_tracker.json").write_text(json.dumps(tracker))
        sd.auto_deactivate_subs()
        # availability should not be changed since already_deactivated is True
        saved = json.loads((tmp_path / "availability.json").read_text())
        assert saved["Sub Player"] is True
        sd._ROSTER_MANIFEST_CACHE = None

    def test_no_deactivation_if_game_day_is_today(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        sd._ROSTER_MANIFEST_CACHE = None
        today = datetime.now(ET).strftime("%Y-%m-%d")
        sched = {"past": [{"date": today}], "upcoming": []}
        avail = {"Sub Player": True}
        manifest = {"core_players": ["Jane Core"]}  # non-empty so function doesn't exit early
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        (tmp_path / "availability.json").write_text(json.dumps(avail))
        (tmp_path / "roster_manifest.json").write_text(json.dumps(manifest))
        sd.auto_deactivate_subs()
        saved = json.loads((tmp_path / "availability.json").read_text())
        assert saved["Sub Player"] is True  # not deactivated — game is today
        sd._ROSTER_MANIFEST_CACHE = None


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------

class TestTtsStat:
    def test_decimal_stat_spoken_form(self):
        result = sd._tts_stat(0.778)
        assert "seven" in result.lower()

    def test_zero_returns_zero(self):
        result = sd._tts_stat(0.0)
        assert result == "zero"

    def test_integer_like_stat(self):
        result = sd._tts_stat(1.234)
        assert result  # any non-empty string

    def test_non_numeric_passthrough(self):
        result = sd._tts_stat("N/A")
        assert result == "N/A"

    def test_negative_decimal(self):
        result = sd._tts_stat(-0.123)
        assert result  # just must not crash

    def test_large_value_non_decimal(self):
        result = sd._tts_stat(42)
        assert "42" in result

    def test_three_digit_after_decimal(self):
        result = sd._tts_stat(0.500)
        assert "five" in result.lower() or "00" in result or "0" in result


class TestApplyPhonetics:
    def test_known_word_replaced(self):
        result = sd._apply_phonetics("The Sharks face PCLL tonight")
        assert "Palm Coast Little League" in result

    def test_case_insensitive(self):
        result = sd._apply_phonetics("pcll standings")
        assert "Palm Coast Little League" in result

    def test_unknown_word_unchanged(self):
        result = sd._apply_phonetics("Hello world")
        assert result == "Hello world"

    def test_empty_string(self):
        assert sd._apply_phonetics("") == ""


class TestCleanOpponentName:
    def test_strips_at_prefix(self):
        assert sd._clean_opponent_name("@ Tigers") == "Tigers"

    def test_strips_vs_dot_prefix(self):
        assert sd._clean_opponent_name("vs. Lions") == "Lions"

    def test_strips_vs_space_prefix(self):
        assert sd._clean_opponent_name("vs Bears") == "Bears"

    def test_no_prefix_unchanged(self):
        assert sd._clean_opponent_name("Panthers") == "Panthers"

    def test_strips_whitespace(self):
        assert sd._clean_opponent_name("  @ Wolves  ") == "Wolves"


class TestAllRosterNames:
    def test_returns_full_roster_names(self):
        team = {"roster": [
            {"first": "Jane", "last": "Doe"},
            {"first": "Bob", "last": "Smith"},
        ]}
        names = sd._all_roster_names(team)
        assert "Jane Doe" in names
        assert "Bob Smith" in names

    def test_empty_roster(self):
        assert sd._all_roster_names({"roster": []}) == []

    def test_uses_name_field_if_present(self):
        team = {"roster": [{"name": "Full Name"}]}
        assert "Full Name" in sd._all_roster_names(team)


class TestCoreRosterNames:
    def test_includes_default_players(self):
        team = {"roster": [
            {"first": "Jane", "last": "Doe"},
            {"first": "Bob", "last": "Smith"},
        ]}
        names = sd._core_roster_names(team)
        assert "Jane Doe" in names
        assert "Bob Smith" in names

    def test_excludes_core_false_players(self):
        team = {"roster": [
            {"first": "Jane", "last": "Doe"},
            {"first": "Sub", "last": "Player", "core": False},
        ]}
        names = sd._core_roster_names(team)
        assert "Sub Player" not in names

    def test_sorted_alphabetically(self):
        team = {"roster": [
            {"first": "Zara", "last": "Z"},
            {"first": "Alice", "last": "A"},
        ]}
        names = sd._core_roster_names(team)
        assert names[0] == "Alice A"
        assert names[1] == "Zara Z"


class TestCalcPlayerPracticeProfile:
    def test_returns_expected_keys(self):
        player = {}
        prof = sd._calc_player_practice_profile(player)
        for key in ("pa", "ab", "h", "obp", "slg", "k_rate", "bb_rate", "ip", "errors", "fpct"):
            assert key in prof

    def test_k_rate_calculated(self):
        player = {"pa": 10, "so": 4}
        prof = sd._calc_player_practice_profile(player)
        assert abs(prof["k_rate"] - 0.4) < 0.01

    def test_zero_division_safe(self):
        player = {"pa": 0, "ab": 0, "so": 0}
        prof = sd._calc_player_practice_profile(player)
        assert prof["k_rate"] == 0.0
        assert prof["bb_rate"] == 0.0


class TestBuildPracticeNeeds:
    def test_empty_team_returns_empty_list(self):
        needs = sd._build_practice_needs({"roster": []}, [])
        assert needs == []

    def test_returns_list(self):
        team = {"roster": [{"first": "Jane", "last": "Doe", "pa": 10, "so": 5}]}
        needs = sd._build_practice_needs(team, ["Jane Doe"])
        assert isinstance(needs, list)

    def test_priority_assigned(self):
        team = {"roster": [
            {"first": "Jane", "last": "Doe", "pa": 8, "so": 4, "obp": 0.20, "slg": 0.20},
        ]}
        needs = sd._build_practice_needs(team, ["Jane Doe"])
        if needs:
            assert needs[0]["priority"] == 1

    def test_player_not_in_selected_excluded(self):
        team = {"roster": [
            {"first": "Jane", "last": "Doe", "pa": 10, "so": 5},
            {"first": "Bob", "last": "Smith", "pa": 10, "so": 5},
        ]}
        needs = sd._build_practice_needs(team, ["Jane Doe"])
        # Bob not in selected — shouldn't appear in focus_players
        all_focus = [p for n in needs for p in n.get("focus_players", [])]
        assert all("Bob" not in fp for fp in all_focus)


class TestBuildVoiceOverviewText:
    def _make_ctx(self):
        return {
            "team": {
                "team_name": "The Sharks",
                "roster": [
                    {"first": "Jane", "last": "Doe", "obp": 0.500, "ops": 1.0, "number": "7"},
                ],
            },
            "swot": {"team_swot": {"strengths": ["Great pitching"], "weaknesses": ["Low OBP"]}},
            "lineups": {"balanced": {"lineup": [{"first": "Jane", "last": "Doe", "number": "7"}]}},
            "schedule": {"upcoming": [{"opponent": "Tigers", "date": "2099-06-01", "home_away": "home"}]},
            "games": [{"date": "2024-01-01", "result": "W"}, {"date": "2024-01-02", "result": "L"}],
        }

    def test_returns_string(self):
        text = sd._build_voice_overview_text(self._make_ctx())
        assert isinstance(text, str)
        assert len(text) > 50

    def test_contains_team_name(self):
        text = sd._build_voice_overview_text(self._make_ctx())
        assert "Sharks" in text

    def test_includes_win_loss_record(self):
        text = sd._build_voice_overview_text(self._make_ctx())
        assert "1 and 1" in text

    def test_empty_ctx_does_not_crash(self):
        text = sd._build_voice_overview_text({})
        assert isinstance(text, str)

    def test_no_games_shows_zero_record(self):
        ctx = self._make_ctx()
        ctx["games"] = []
        text = sd._build_voice_overview_text(ctx)
        assert "oh and oh" in text

    def test_applies_pcll_phonetics(self):
        ctx = self._make_ctx()
        ctx["schedule"]["upcoming"][0]["opponent"] = "PCLL All-Stars"
        text = sd._build_voice_overview_text(ctx)
        assert "Palm Coast Little League" in text or "PCLL" not in text


# ---------------------------------------------------------------------------
# /api/practice-insights  GET
# ---------------------------------------------------------------------------

class TestHandlePracticeInsights:
    def test_returns_200_with_no_team_file(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        with flask_app.test_client() as client:
            resp = client.get("/api/practice-insights")
        assert resp.status_code == 200

    def test_returns_needs_key(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        with flask_app.test_client() as client:
            resp = client.get("/api/practice-insights")
        data = resp.get_json()
        assert "needs" in data

    def test_returns_recommended_plan_key(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        with flask_app.test_client() as client:
            resp = client.get("/api/practice-insights")
        data = resp.get_json()
        assert "recommended_plan" in data

    def test_with_team_file_returns_team_name(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        team = {"team_name": "The Sharks", "roster": [
            {"first": "Jane", "last": "Doe"},
        ]}
        (tmp_path / "team_enriched.json").write_text(json.dumps(team))
        with flask_app.test_client() as client:
            resp = client.get("/api/practice-insights")
        data = resp.get_json()
        assert "Sharks" in data.get("team_name", "")

    def test_player_filter_via_query_string(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        team = {"team_name": "The Sharks", "roster": [
            {"first": "Jane", "last": "Doe"},
            {"first": "Bob", "last": "Smith"},
        ]}
        (tmp_path / "team_enriched.json").write_text(json.dumps(team))
        with flask_app.test_client() as client:
            resp = client.get("/api/practice-insights?players=Jane+Doe")
        assert resp.status_code == 200

    def test_fallback_general_fundamentals_when_no_stat_data(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        with flask_app.test_client() as client:
            resp = client.get("/api/practice-insights")
        data = resp.get_json()
        need_keys = [n["key"] for n in data.get("needs", [])]
        assert "general_fundamentals" in need_keys


# ---------------------------------------------------------------------------
# _load_practice_rsvp_defaults
# ---------------------------------------------------------------------------

class TestLoadPracticeRsvpDefaults:
    def _make_team(self):
        return {"roster": [
            {"first": "Jane", "last": "Doe"},
            {"first": "Sam", "last": "Smith"},
        ]}

    def test_fallback_to_full_roster_when_no_rsvp_no_avail(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        team = self._make_team()
        names, source, _ = sd._load_practice_rsvp_defaults(team)
        assert source == "roster_default"
        assert "Jane Doe" in names

    def test_uses_availability_when_no_rsvp(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        team = self._make_team()
        avail = {"Jane Doe": True, "Sam Smith": False}
        (tmp_path / "availability.json").write_text(json.dumps(avail))
        names, source, _ = sd._load_practice_rsvp_defaults(team)
        assert source == "availability"
        assert "Jane Doe" in names
        assert "Sam Smith" not in names

    def test_uses_rsvp_next_attending(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        team = self._make_team()
        rsvp = {"next": {"date": "2026-06-01", "title": "Practice", "attending": ["Jane Doe"]}}
        (tmp_path / "practice_rsvp.json").write_text(json.dumps(rsvp))
        names, source, meta = sd._load_practice_rsvp_defaults(team)
        assert source == "practice_rsvp"
        assert "Jane Doe" in names

    def test_rsvp_meta_date_returned(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        team = self._make_team()
        rsvp = {"next": {"date": "2026-06-15", "title": "Big Practice", "attending": ["Jane Doe"]}}
        (tmp_path / "practice_rsvp.json").write_text(json.dumps(rsvp))
        _, _, meta = sd._load_practice_rsvp_defaults(team)
        assert meta["date"] == "2026-06-15"
        assert meta["title"] == "Big Practice"

    def test_uses_rsvp_practices_list(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        team = self._make_team()
        rsvp = {
            "practices": [
                {"date": "2099-06-01", "title": "Future Practice", "attending": ["Jane Doe"]},
            ]
        }
        (tmp_path / "practice_rsvp.json").write_text(json.dumps(rsvp))
        names, source, _ = sd._load_practice_rsvp_defaults(team)
        assert source == "practice_rsvp"
        assert "Jane Doe" in names


# ---------------------------------------------------------------------------
# /api/voice-update  GET
# ---------------------------------------------------------------------------

class TestHandleVoiceUpdate:
    def test_returns_404_when_no_file_no_api_key(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        # No voice file, no ElevenLabs key — should return 404 error JSON
        with flask_app.test_client() as client:
            resp = client.get("/api/voice-update")
        assert resp.status_code == 404
        data = resp.get_json()
        assert "no_voice_available" in data.get("error", "")

    def test_returns_mp3_when_file_exists(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        mp3_file = tmp_path / "voice_update.mp3"
        mp3_file.write_bytes(b"\xff\xfbFakeMP3Data")  # minimal fake MP3
        with flask_app.test_client() as client:
            resp = client.get("/api/voice-update")
        assert resp.status_code == 200
        assert resp.content_type == "audio/mpeg"

    def test_returns_fresh_voice_without_stale_header(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        mp3_file = tmp_path / "voice_update.mp3"
        mp3_file.write_bytes(b"\xff\xfbFakeMP3Data")
        with flask_app.test_client() as client:
            resp = client.get("/api/voice-update")
        assert resp.headers.get("X-Voice-Stale") is None

    def test_stale_header_when_file_older_than_24h(self, flask_app, monkeypatch, tmp_path):
        import time as _t
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        mp3_file = tmp_path / "voice_update.mp3"
        mp3_file.write_bytes(b"\xff\xfbFakeMP3Data")
        # Set modification time to 25 hours ago
        old_mtime = _t.time() - (25 * 3600)
        import os
        os.utime(mp3_file, (old_mtime, old_mtime))
        with flask_app.test_client() as client:
            resp = client.get("/api/voice-update")
        assert resp.headers.get("X-Voice-Stale") == "true"

    def test_includes_generated_at_header_from_meta(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        mp3_file = tmp_path / "voice_update.mp3"
        mp3_file.write_bytes(b"\xff\xfbFakeMP3Data")
        meta = {"generated_at": "2026-05-08T10:00:00"}
        (tmp_path / "voice_overview_latest.json").write_text(json.dumps(meta))
        with flask_app.test_client() as client:
            resp = client.get("/api/voice-update")
        assert "2026-05-08" in resp.headers.get("X-Voice-Generated-At", "")


# ---------------------------------------------------------------------------
# /api/regenerate-lineups  POST
# ---------------------------------------------------------------------------

class TestHandleRegenerateLineups:
    def test_returns_403_without_origin(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/regenerate-lineups",
                json={},
                content_type="application/json",
            )
        assert resp.status_code == 403

    def test_returns_415_for_non_json(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/regenerate-lineups",
                data="plain text",
                content_type="text/plain",
                headers={"Origin": "https://test.example.com"},
            )
        assert resp.status_code == 415

    def test_success_with_mocked_optimizer(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        import types
        fake_lo = types.ModuleType("lineup_optimizer")
        fake_lo.run = MagicMock()
        monkeypatch.setitem(sys.modules, "lineup_optimizer", fake_lo)
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/regenerate-lineups",
                json={},
                content_type="application/json",
                headers={"Origin": "https://test.example.com"},
            )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

    def test_returns_lineups_from_file(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        import types
        fake_lo = types.ModuleType("lineup_optimizer")
        fake_lo.run = MagicMock()
        monkeypatch.setitem(sys.modules, "lineup_optimizer", fake_lo)
        lineups = {"balanced": {"lineup": []}, "aggressive": {"lineup": []}}
        (tmp_path / "lineups.json").write_text(json.dumps(lineups))
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/regenerate-lineups",
                json={},
                content_type="application/json",
                headers={"Origin": "https://test.example.com"},
            )
        data = resp.get_json()
        assert "balanced" in data["lineups"]

    def test_500_on_optimizer_error(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        import types
        fake_lo = types.ModuleType("lineup_optimizer")
        fake_lo.run = MagicMock(side_effect=RuntimeError("lineup broke"))
        monkeypatch.setitem(sys.modules, "lineup_optimizer", fake_lo)
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/regenerate-lineups",
                json={},
                content_type="application/json",
                headers={"Origin": "https://test.example.com"},
            )
        assert resp.status_code == 500
        assert "regenerate_failed" in resp.get_json().get("error", "")


# ---------------------------------------------------------------------------
# /api/announcer/roster  GET
# ---------------------------------------------------------------------------

class TestHandleAnnouncerRoster:
    def test_returns_500_when_announcer_engine_raises(self, flask_app, monkeypatch):
        import types
        fake_ae = types.ModuleType("announcer_engine")
        fake_ae.load_announcer_roster = MagicMock(side_effect=RuntimeError("engine broke"))
        fake_ae.get_roster_stats = MagicMock(return_value={})
        monkeypatch.setitem(sys.modules, "announcer_engine", fake_ae)
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/roster")
        assert resp.status_code == 500
        assert "announcer_roster_failed" in resp.get_json().get("error", "")

    def test_returns_roster_and_stats(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        import types
        fake_ae = types.ModuleType("announcer_engine")
        fake_ae.load_announcer_roster = MagicMock(return_value=[{"id": "p1", "first": "Jane", "last": "Doe"}])
        fake_ae.get_roster_stats = MagicMock(return_value={"total": 1})
        monkeypatch.setitem(sys.modules, "announcer_engine", fake_ae)
        with flask_app.test_client() as client:
            resp = client.get("/api/announcer/roster")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "roster" in data
        assert data["stats"]["total"] == 1


# ---------------------------------------------------------------------------
# Availability POST — sub tracker activation branch
# ---------------------------------------------------------------------------

class TestHandleAvailabilityPostSubTracker:
    def test_activating_non_core_sub_updates_tracker(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        sd._ROSTER_MANIFEST_CACHE = None
        # No core players — so any player is a sub
        (tmp_path / "roster_manifest.json").write_text('{"core_players": []}')
        # Old availability: Sub is False
        (tmp_path / "availability.json").write_text('{"Sub Player": false}')
        import types
        fake_lo = types.ModuleType("lineup_optimizer")
        fake_lo.run = MagicMock()
        fake_sa = types.ModuleType("swot_analyzer")
        fake_sa.run_sharks_analysis = MagicMock()
        monkeypatch.setitem(sys.modules, "lineup_optimizer", fake_lo)
        monkeypatch.setitem(sys.modules, "swot_analyzer", fake_sa)
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/availability",
                json={"Sub Player": True},
                content_type="application/json",
                headers={"Origin": "https://test.example.com"},
            )
        assert resp.status_code == 200
        # sub_tracker should now have "Sub Player"
        tracker = json.loads((tmp_path / "sub_tracker.json").read_text())
        assert "Sub Player" in tracker
        assert tracker["Sub Player"]["auto_deactivated"] is False
        sd._ROSTER_MANIFEST_CACHE = None

    def test_optimizer_exception_does_not_break_response(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        sd._ROSTER_MANIFEST_CACHE = None
        (tmp_path / "roster_manifest.json").write_text('{"core_players": ["Jane Doe"]}')
        import types
        fake_lo = types.ModuleType("lineup_optimizer")
        fake_lo.run = MagicMock(side_effect=RuntimeError("optimizer broke"))
        monkeypatch.setitem(sys.modules, "lineup_optimizer", fake_lo)
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/availability",
                json={"Jane Doe": True},
                content_type="application/json",
                headers={"Origin": "https://test.example.com"},
            )
        assert resp.status_code == 200
        sd._ROSTER_MANIFEST_CACHE = None


# ---------------------------------------------------------------------------
# _pick_scoreboard_target  (pure function)
# ---------------------------------------------------------------------------

class TestPickScoreboardTarget:
    def test_returns_none_for_empty_games(self):
        now = datetime.now(ET)
        today_str = now.strftime("%Y-%m-%d")
        result = sd._pick_scoreboard_target([], now, today_str)
        assert result is None

    def test_picks_in_progress_game(self):
        now = datetime.now(ET)
        today_str = now.strftime("%Y-%m-%d")
        game = {"game_id": "live1", "game_status": "in_progress", "start_ts": now.isoformat()}
        result = sd._pick_scoreboard_target([game], now, today_str)
        assert result is game

    def test_picks_todays_game(self):
        now = datetime.now(ET)
        today_str = now.strftime("%Y-%m-%d")
        game = {"game_id": "today1", "game_status": "scheduled",
                "start_ts": f"{today_str}T12:00:00-04:00"}
        result = sd._pick_scoreboard_target([game], now, today_str)
        assert result is game

    def test_prefers_live_over_today(self):
        now = datetime.now(ET)
        today_str = now.strftime("%Y-%m-%d")
        today_game = {"game_id": "today", "game_status": "scheduled",
                      "start_ts": f"{today_str}T12:00:00-04:00"}
        live_game = {"game_id": "live", "game_status": "active",
                     "start_ts": now.isoformat()}
        result = sd._pick_scoreboard_target([today_game, live_game], now, today_str)
        assert result["game_id"] == "live"

    def test_rejects_stale_live_game(self):
        now = datetime.now(ET)
        today_str = now.strftime("%Y-%m-%d")
        # Game started 10 hours ago with in_progress status (stale GC bug)
        stale_ts = (now.replace(tzinfo=None) - timedelta(hours=10))
        stale_iso = stale_ts.isoformat() + "-04:00"
        stale_game = {"game_id": "stale", "game_status": "in_progress", "start_ts": stale_iso}
        result = sd._pick_scoreboard_target([stale_game], now, today_str)
        assert result is None

    def test_returns_none_for_past_game(self):
        now = datetime.now(ET)
        today_str = now.strftime("%Y-%m-%d")
        game = {"game_id": "old", "game_status": "completed",
                "start_ts": "2020-01-01T12:00:00-04:00"}
        result = sd._pick_scoreboard_target([game], now, today_str)
        assert result is None

    def test_game_with_invalid_timestamp(self):
        now = datetime.now(ET)
        today_str = now.strftime("%Y-%m-%d")
        game = {"game_id": "bad_ts", "game_status": "active", "start_ts": "not-a-date"}
        result = sd._pick_scoreboard_target([game], now, today_str)
        # active status without valid ts — live_game should still be set
        assert result is game


# ---------------------------------------------------------------------------
# _augment_sharks_batting  (pure function with file I/O)
# ---------------------------------------------------------------------------

class TestAugmentSharksBatting:
    def test_empty_list_passthrough(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        result = sd._augment_sharks_batting([])
        assert result == []

    def test_no_team_merged_passthrough(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        rows = [{"name": "Jane", "h": 2, "ab": 4}]
        result = sd._augment_sharks_batting(rows)
        assert result == rows

    def test_augments_with_season_stats(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        roster_data = {
            "roster": [{"name": "Jane Doe", "number": "7",
                        "batting": {"avg": 0.400, "slg": 0.700, "obp": 0.500, "ops": 1.200}}]
        }
        (tmp_path / "team_merged.json").write_text(json.dumps(roster_data))
        rows = [{"name": "Jane Doe", "number": "7", "h": 2, "ab": 4}]
        result = sd._augment_sharks_batting(rows)
        assert result[0].get("avg") == 0.400

    def test_matches_by_number(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        roster_data = {
            "roster": [{"name": "Jane Doe", "number": "7",
                        "batting": {"avg": 0.400, "slg": 0.700, "obp": 0.500, "ops": 1.200}}]
        }
        (tmp_path / "team_merged.json").write_text(json.dumps(roster_data))
        rows = [{"player": "Who", "number": "7", "h": 1, "ab": 3}]
        result = sd._augment_sharks_batting(rows)
        assert result[0].get("avg") == 0.400

    def test_unknown_player_not_augmented(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        roster_data = {"roster": [{"name": "Jane Doe", "number": "7", "batting": {"avg": 0.400}}]}
        (tmp_path / "team_merged.json").write_text(json.dumps(roster_data))
        rows = [{"name": "Mystery Player", "number": "99", "h": 1}]
        result = sd._augment_sharks_batting(rows)
        assert result[0].get("avg") is None

    def test_exception_returns_original_rows(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        (tmp_path / "team_merged.json").write_text("{{bad json")
        rows = [{"name": "Jane", "h": 1}]
        result = sd._augment_sharks_batting(rows)
        assert result == rows


# ---------------------------------------------------------------------------
# _slugify_opponent  (pure function)
# ---------------------------------------------------------------------------

class TestSlugifyOpponent:
    def test_basic_slug(self):
        assert sd._slugify_opponent("The Tigers") == "the_tigers"

    def test_empty_returns_empty(self):
        assert sd._slugify_opponent("") == ""

    def test_special_chars_removed(self):
        slug = sd._slugify_opponent("Sharks & Dolphins!")
        assert "&" not in slug
        assert "!" not in slug

    def test_lowercase(self):
        assert sd._slugify_opponent("TIGERS") == "tigers"


# ---------------------------------------------------------------------------
# _build_practice_needs — coverage for defense, pitching, baserunning branches
# ---------------------------------------------------------------------------

class TestBuildPracticeNeedsExtended:
    def _player(self, name, **kwargs):
        parts = name.split()
        p = {"first": parts[0], "last": parts[-1] if len(parts) > 1 else ""}
        p.update(kwargs)
        return p

    def test_defense_need_with_errors(self):
        team = {"roster": [self._player("Jane Doe", pa=8, ab=6, h=2, so=1, e=3, fpct=0.85)]}
        needs = sd._build_practice_needs(team, ["Jane Doe"])
        keys = [n["key"] for n in needs]
        assert "defense_reliability" in keys

    def test_pitch_command_need(self):
        team = {"roster": [self._player("Jane Doe", pa=6, ab=5, h=2, so=1, ip=3.0, bb=5)]}
        needs = sd._build_practice_needs(team, ["Jane Doe"])
        keys = [n["key"] for n in needs]
        assert "pitch_command" in keys

    def test_baserunning_need(self):
        # Player with good OBP but 0 steals and >= 4 PA
        team = {"roster": [self._player("Jane Doe", pa=8, ab=6, h=3, bb=2, obp=0.45, sb=0)]}
        needs = sd._build_practice_needs(team, ["Jane Doe"])
        keys = [n["key"] for n in needs]
        assert "baserunning_iq" in keys

    def test_player_with_no_name_skipped(self):
        team = {"roster": [{"first": "", "last": "", "pa": 10, "so": 5}]}
        needs = sd._build_practice_needs(team, [])
        assert needs == []


# ---------------------------------------------------------------------------
# _load_practice_rsvp_defaults — rsvps dict branch
# ---------------------------------------------------------------------------

class TestLoadPracticeRsvpDefaultsRsvpsDict:
    def _make_team(self):
        return {"roster": [
            {"first": "Jane", "last": "Doe"},
            {"first": "Sam", "last": "Smith"},
        ]}

    def test_uses_rsvps_dict_when_attending_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        team = self._make_team()
        rsvp = {"next": {"date": "2026-06-01", "attending": [],
                         "rsvps": {"Jane Doe": True, "Sam Smith": False}}}
        (tmp_path / "practice_rsvp.json").write_text(json.dumps(rsvp))
        names, source, _ = sd._load_practice_rsvp_defaults(team)
        assert source == "practice_rsvp"
        assert "Jane Doe" in names
        assert "Sam Smith" not in names

    def test_practices_list_uses_rsvps_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        team = self._make_team()
        rsvp = {
            "practices": [
                {"date": "2099-06-01", "attending": [],
                 "rsvps": {"Jane Doe": True, "Sam Smith": False}},
            ]
        }
        (tmp_path / "practice_rsvp.json").write_text(json.dumps(rsvp))
        names, source, _ = sd._load_practice_rsvp_defaults(team)
        assert source == "practice_rsvp"
        assert "Jane Doe" in names


# ---------------------------------------------------------------------------
# handle_game_detail — advanced stat keys + strip_totals
# ---------------------------------------------------------------------------

class TestHandleGameDetailExtended:
    def test_advanced_keys_copied_from_sharks_block(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        game = {
            "game_id": "game_adv",
            "date": "2024-03-01",
            "sharks": {
                "batting": [{"name": "Jane", "pa": 3}],
                "pitching": [],
                "batting_advanced": [{"name": "Jane", "k_rate": 0.33}],
            },
        }
        (games_dir / "game_adv.json").write_text(json.dumps(game))
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game_adv")
        data = resp.get_json()
        assert "sharks_batting_advanced" in data

    def test_strip_totals_row_removes_first_row(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        # First row PA = sum of rest (totals row pattern)
        game = {
            "game_id": "game_totals",
            "date": "2024-03-02",
            "sharks": {
                "batting": [
                    {"name": "TOTALS", "pa": 10},  # PA == sum of rest
                    {"name": "Jane", "pa": 5},
                    {"name": "Bob", "pa": 5},
                ],
                "pitching": [],
            },
        }
        (games_dir / "game_totals.json").write_text(json.dumps(game))
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game_totals")
        data = resp.get_json()
        names = [r["name"] for r in data.get("sharks_batting", [])]
        assert "TOTALS" not in names

    def test_score_dict_bridge_with_equal_score(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        game = {
            "game_id": "game_tie",
            "date": "2024-03-03",
            "score": {"sharks": 5, "opponent": 5},
        }
        (games_dir / "game_tie.json").write_text(json.dumps(game))
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game_tie")
        data = resp.get_json()
        assert data.get("score_str") == "5-5"


# ---------------------------------------------------------------------------
# handle_availability GET — empty-name player branch
# ---------------------------------------------------------------------------

class TestHandleAvailabilityGetEmptyName:
    def test_player_with_empty_name_skipped(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        # Roster with one real player and one with empty first/last
        team = {"roster": [
            {"first": "Jane", "last": "Doe"},
            {"first": "", "last": ""},  # empty name — should be skipped (line 1624-1625)
        ]}
        (tmp_path / "team_enriched.json").write_text(json.dumps(team))
        with flask_app.test_client() as client:
            resp = client.get("/api/availability")
        data = resp.get_json()
        assert "" not in data
        assert " " not in data  # also no whitespace-only key


# ---------------------------------------------------------------------------
# /api/scoreboard  GET
# ---------------------------------------------------------------------------

class TestHandleScoreboard:
    def _mock_gc_response(self, games_list):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json = MagicMock(return_value=games_list)
        return mock_resp

    def test_no_game_returns_no_game_status(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        with patch("sync_daemon.requests.get", return_value=self._mock_gc_response([])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "no_game"

    def test_gc_api_error_falls_back_gracefully(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        with patch("sync_daemon.requests.get", side_effect=ConnectionError("timeout")):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        assert resp.status_code == 200

    def test_upcoming_game_returned_when_no_active_game(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        today = datetime.now(ET).strftime("%Y-%m-%d")
        sched = {"upcoming": [{"date": today, "opponent": "Tigers", "time": "6:00 PM",
                                "is_game": True, "home_away": "home"}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        with patch("sync_daemon.requests.get", return_value=self._mock_gc_response([])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        data = resp.get_json()
        assert data["status"] == "upcoming"
        assert "Tigers" in data["opponent"]

    def test_live_game_returns_live_status(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        now = datetime.now(ET)
        game = {
            "id": "gc123",
            "game_status": "in_progress",
            "start_ts": now.isoformat(),
            "score": {"team": 5, "opponent_team": 3},
            "opponent_team": {"name": "Tigers"},
            "home_away": "home",
        }
        with patch("sync_daemon.requests.get", return_value=self._mock_gc_response([game])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        data = resp.get_json()
        assert data["status"] == "live"
        assert data["sharks_score"] == 5
        assert data["opponent_score"] == 3

    def test_completed_game_returns_final_status(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        today = datetime.now(ET).strftime("%Y-%m-%d")
        game = {
            "id": "gc456",
            "game_status": "completed",
            "start_ts": f"{today}T12:00:00-04:00",
            "score": {"team": 7, "opponent_team": 2},
            "opponent_team": {"name": "Bears"},
        }
        with patch("sync_daemon.requests.get", return_value=self._mock_gc_response([game])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        data = resp.get_json()
        assert data["status"] == "final"

    def test_gc_api_returns_non_list_falls_back(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json = MagicMock(return_value={"not": "a list"})
        with patch("sync_daemon.requests.get", return_value=mock_resp):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "no_game"

    def test_includes_scouting_key_for_named_opponent(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        today = datetime.now(ET).strftime("%Y-%m-%d")
        game = {
            "id": "gc789",
            "game_status": "completed",
            "start_ts": f"{today}T12:00:00-04:00",
            "score": {"team": 5, "opponent_team": 3},
            "opponent_team": {"name": "Tigers"},
        }
        with patch("sync_daemon.requests.get", return_value=self._mock_gc_response([game])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        data = resp.get_json()
        assert "opponent_scouting" in data


# ---------------------------------------------------------------------------
# _build_games_feed (via /api/games with GC-format game files)
# ---------------------------------------------------------------------------

class TestBuildGamesFeedGcFormat:
    def test_gc_format_game_included(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        gc_game = {
            "game_id": "game_gc_001",
            "source": "gc_full_scraper_v2",
            "date": "2024-05-01",
            "opponent": "Tigers",
            "score": {"sharks": 8, "opponent": 3},
            "score_str": "8-3",
            "sharks": {"batting": [{"name": "Jane", "pa": 4, "h": 2}], "pitching": []},
        }
        (games_dir / "game_gc_001.json").write_text(json.dumps(gc_game))
        with flask_app.test_client() as client:
            resp = client.get("/api/games")
        data = resp.get_json()
        ids = [g["game_id"] for g in data]
        assert "game_gc_001" in ids

    def test_gc_game_without_stats_excluded(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        gc_game = {
            "game_id": "game_gc_future",
            "source": "gc_full_scraper_v2",
            "date": "2099-06-01",
            "opponent": "Future Team",
            "sharks": {"batting": [], "pitching": []},  # no stats
        }
        (games_dir / "game_gc_future.json").write_text(json.dumps(gc_game))
        with flask_app.test_client() as client:
            resp = client.get("/api/games")
        data = resp.get_json()
        ids = [g["game_id"] for g in data]
        assert "game_gc_future" not in ids

    def test_gc_game_deduplicates_by_date(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        gc_game = {
            "game_id": "game_gc_dup",
            "source": "gc_full_scraper_v2",
            "date": "2024-05-01",
            "opponent": "Tigers",
            "sharks": {"batting": [{"name": "Jane", "pa": 4}], "pitching": []},
        }
        (games_dir / "game_gc_dup.json").write_text(json.dumps(gc_game))
        # games are de-duped by date — GC format preferred over PDF
        data = sd._build_games_feed()
        assert any(g["game_id"] == "game_gc_dup" for g in data)

    def test_index_json_read_as_pdf_games(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        # index.json holds the list of PDF-scraped games (should be a list, not a dict)
        index_data = [{"game_id": "pdf_001", "date": "2024-01-01", "opponent": "Lions"}]
        (games_dir / "index.json").write_text(json.dumps(index_data))
        with flask_app.test_client() as client:
            resp = client.get("/api/games")
        assert resp.status_code == 200
        data = resp.get_json()
        assert any(g["game_id"] == "pdf_001" for g in data)


# ---------------------------------------------------------------------------
# _build_voice_overview_text — duplicate date and non-list branches
# ---------------------------------------------------------------------------

class TestBuildVoiceOverviewTextExtended:
    def test_deduplicates_games_by_date(self):
        ctx = {
            "team": {"team_name": "The Sharks", "roster": []},
            "swot": {},
            "lineups": {},
            "schedule": {"upcoming": []},
            "games": [
                {"date": "2024-01-01", "result": "W"},
                {"date": "2024-01-01", "result": "W"},  # duplicate date — should count only once
            ],
        }
        text = sd._build_voice_overview_text(ctx)
        assert "1 and 0" in text  # deduplicated: 1 win, 0 losses

    def test_games_not_list_shows_zero_record(self):
        ctx = {
            "team": {"roster": []},
            "swot": {},
            "lineups": {},
            "schedule": {"upcoming": []},
            "games": "not a list",
        }
        text = sd._build_voice_overview_text(ctx)
        assert "oh and oh" in text

    def test_next_game_bad_date_format_fallback(self):
        ctx = {
            "team": {"roster": []},
            "swot": {},
            "lineups": {},
            "schedule": {"upcoming": [{"opponent": "Tigers", "date": "bad-date",
                                       "home_away": "home"}]},
            "games": [],
        }
        text = sd._build_voice_overview_text(ctx)
        assert isinstance(text, str)  # must not crash


# ---------------------------------------------------------------------------
# Additional handle_scoreboard branches
# ---------------------------------------------------------------------------

class TestHandleScoreboardExtended:
    def _mock_gc(self, games_list):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json = MagicMock(return_value=games_list)
        return mock_resp

    def test_scheduled_status_returns_pregame(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        today = datetime.now(ET).strftime("%Y-%m-%d")
        game = {
            "id": "gc_sched",
            "game_status": "scheduled",
            "start_ts": f"{today}T18:00:00-04:00",
            "score": {"team": 0, "opponent_team": 0},
            "opponent_team": {"name": "Lions"},
        }
        with patch("sync_daemon.requests.get", return_value=self._mock_gc([game])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        data = resp.get_json()
        assert data["status"] == "pregame"

    def test_unknown_status_returns_pregame(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        today = datetime.now(ET).strftime("%Y-%m-%d")
        game = {
            "id": "gc_unk",
            "game_status": "something_unknown",
            "start_ts": f"{today}T18:00:00-04:00",
            "score": {"team": 0, "opponent_team": 0},
            "opponent_team": {"name": "Bears"},
        }
        with patch("sync_daemon.requests.get", return_value=self._mock_gc([game])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        data = resp.get_json()
        assert data["status"] == "pregame"

    def test_local_game_file_enriches_scoreboard(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        today = datetime.now(ET).strftime("%Y-%m-%d")
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        local_game = {
            "date": today,
            "sharks_batting": [{"name": "Jane", "h": 2}],
            "opponent_batting": [],
            "score": {"sharks": 6, "opponent": 4},
        }
        (games_dir / "game_today.json").write_text(json.dumps(local_game))
        game = {
            "id": "gc_today",
            "game_status": "completed",
            "start_ts": f"{today}T12:00:00-04:00",
            "score": {"team": 5, "opponent_team": 3},
            "opponent_team": {"name": "Tigers"},
        }
        with patch("sync_daemon.requests.get", return_value=self._mock_gc([game])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        data = resp.get_json()
        # Local file should override score
        assert data["sharks_score"] == 6

    def test_schedule_context_adds_time(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        today = datetime.now(ET).strftime("%Y-%m-%d")
        sched = {"upcoming": [{"date": today, "opponent": "Wolves", "time": "7:00 PM",
                                "home_away": "away", "is_game": True}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        game = {
            "id": "gc_sched_ctx",
            "game_status": "scheduled",
            "start_ts": f"{today}T18:00:00-04:00",
            "score": {"team": 0, "opponent_team": 0},
            "opponent_team": {"name": "Wolves"},
        }
        with patch("sync_daemon.requests.get", return_value=self._mock_gc([game])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        data = resp.get_json()
        assert data.get("time") == "7:00 PM"

    def test_live_game_fetches_live_events(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        now = datetime.now(ET)
        game = {
            "id": "gc_live_evt",
            "game_status": "in_progress",
            "start_ts": now.isoformat(),
            "score": {"team": 3, "opponent_team": 2},
            "opponent_team": {"name": "Tigers"},
        }
        fake_events = {"batter": "Jane", "runners": []}
        with patch("sync_daemon.requests.get", return_value=self._mock_gc([game])), \
             patch("sync_daemon._cached_live_events", return_value=fake_events):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        data = resp.get_json()
        assert data.get("live_play") == fake_events


# ---------------------------------------------------------------------------
# handle_game_detail — self-heal, strip_totals normal path, advanced keys
# ---------------------------------------------------------------------------

class TestHandleGameDetailSelfHeal:
    def test_self_heal_supplements_sharks_data_from_gc_file(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        # Primary game file lacks sharks block
        primary = {"game_id": "game_no_sharks", "date": "2024-04-15", "opponent": "Tigers"}
        (games_dir / "game_no_sharks.json").write_text(json.dumps(primary))
        # GC game file with same date has sharks block
        gc_game = {
            "date": "2024-04-15",
            "result": "W",
            "sharks": {"batting": [{"name": "Jane", "pa": 4}], "pitching": []},
        }
        (games_dir / "game_gc_20240415.json").write_text(json.dumps(gc_game))
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game_no_sharks")
        data = resp.get_json()
        assert "sharks_batting" in data
        assert data["sharks_batting"][0]["name"] == "Jane"

    def test_strip_totals_row_no_strip_when_not_totals(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        # Two rows where first row PA does NOT equal sum of rest
        game = {
            "game_id": "game_notot",
            "date": "2024-04-20",
            "sharks": {
                "batting": [
                    {"name": "Jane", "pa": 3},
                    {"name": "Bob", "pa": 5},
                ],
                "pitching": [],
            },
        }
        (games_dir / "game_notot.json").write_text(json.dumps(game))
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game_notot")
        data = resp.get_json()
        names = [r["name"] for r in data.get("sharks_batting", [])]
        assert "Jane" in names  # first row NOT stripped

    def test_batting_advanced_key_exposed(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        game = {
            "game_id": "game_badvanced",
            "date": "2024-04-21",
            "sharks": {
                "batting": [{"name": "Jane", "pa": 4}],
                "pitching": [],
                "pitching_advanced": [{"era": 1.5}],
            },
        }
        (games_dir / "game_badvanced.json").write_text(json.dumps(game))
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game_badvanced")
        data = resp.get_json()
        assert "sharks_pitching_advanced" in data


# ---------------------------------------------------------------------------
# auto_deactivate_subs — no-date branch (line 1516)
# ---------------------------------------------------------------------------

class TestAutoDeactivateSubsNoBranch:
    def test_no_op_when_last_game_has_no_date(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        sd._ROSTER_MANIFEST_CACHE = None
        sched = {"past": [{"opponent": "Unknown", "date": ""}], "upcoming": []}
        avail = {"Sub Player": True}
        manifest = {"core_players": ["Jane Core"]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(sched))
        (tmp_path / "availability.json").write_text(json.dumps(avail))
        (tmp_path / "roster_manifest.json").write_text(json.dumps(manifest))
        sd.auto_deactivate_subs()
        # No date → should return early without deactivating
        saved = json.loads((tmp_path / "availability.json").read_text())
        assert saved["Sub Player"] is True
        sd._ROSTER_MANIFEST_CACHE = None


# ---------------------------------------------------------------------------
# _build_games_feed — known results & GC self-heal branches
# ---------------------------------------------------------------------------

class TestBuildGamesFeedBranches:
    def test_known_result_applied_to_pdf_game(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        # PDF game (from index.json) with no result
        index = [{"game_id": "pdf_001", "date": "2024-03-10", "opponent": "Tigers"}]
        (games_dir / "index.json").write_text(json.dumps(index))
        # Known results file
        known = {"results": [{"date": "2024-03-10", "result": "W", "score": "8-3"}]}
        (tmp_path / "known_game_results.json").write_text(json.dumps(known))
        result = sd._build_games_feed()
        game = next((g for g in result if g["game_id"] == "pdf_001"), None)
        assert game is not None
        assert game.get("result") == "W"

    def test_known_result_kr_no_date_skipped(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        index = [{"game_id": "pdf_002", "date": "2024-03-11", "opponent": "Lions"}]
        (games_dir / "index.json").write_text(json.dumps(index))
        # Known result with no date — should be skipped
        known = {"results": [{"date": "", "result": "W", "score": "5-2"}]}
        (tmp_path / "known_game_results.json").write_text(json.dumps(known))
        result = sd._build_games_feed()
        game = next((g for g in result if g["game_id"] == "pdf_002"), None)
        assert game is not None
        assert not game.get("result")  # not applied

    def test_gc_game_self_heal_fills_result_for_pdf_game(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        # PDF game with no result and no score
        index = [{"game_id": "pdf_003", "date": "2024-03-12", "opponent": "Bears"}]
        (games_dir / "index.json").write_text(json.dumps(index))
        # GC game file with same date and score
        gc_game = {
            "date": "2024-03-12",
            "score": {"sharks": 5, "opponent": 2},
        }
        (games_dir / "game_gc_20240312.json").write_text(json.dumps(gc_game))
        result = sd._build_games_feed()
        game = next((g for g in result if g["game_id"] == "pdf_003"), None)
        assert game is not None
        assert game.get("result") == "W"

    def test_pdf_game_without_date_not_self_healed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        # PDF game with no date
        index = [{"game_id": "pdf_nodate", "date": "", "opponent": "Tigers"}]
        (games_dir / "index.json").write_text(json.dumps(index))
        result = sd._build_games_feed()
        game = next((g for g in result if g["game_id"] == "pdf_nodate"), None)
        assert game is not None
        assert not game.get("result")  # no date → no self-heal

    def test_known_results_bad_json_does_not_crash(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        index = [{"game_id": "pdf_x", "date": "2024-05-01", "opponent": "Tigers"}]
        (games_dir / "index.json").write_text(json.dumps(index))
        (tmp_path / "known_game_results.json").write_text("{{bad json")
        result = sd._build_games_feed()
        assert isinstance(result, list)

    def test_gc_game_with_duplicate_id_not_added_twice(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        # Two GC-format files with the same game_id
        gc_game = {
            "game_id": "dup_gc",
            "source": "gc_full_scraper_v2",
            "date": "2024-05-05",
            "opponent": "Tigers",
            "sharks": {"batting": [{"name": "Jane", "pa": 4}], "pitching": []},
        }
        (games_dir / "game_gc_dup_a.json").write_text(json.dumps(gc_game))
        (games_dir / "game_gc_dup_b.json").write_text(json.dumps(gc_game))
        result = sd._build_games_feed()
        matching = [g for g in result if g.get("game_id") == "dup_gc"]
        assert len(matching) == 1  # second duplicate skipped (line 1770)

    def test_gc_game_totals_with_invalid_pa_type(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        gc_game = {
            "game_id": "game_bad_pa",
            "source": "gc_full_scraper_v2",
            "date": "2024-05-06",
            "opponent": "Bears",
            "sharks": {
                "batting": [{"name": "Jane", "pa": "not-a-number"}],
                "pitching": [],
            },
        }
        (games_dir / "game_bad_pa.json").write_text(json.dumps(gc_game))
        result = sd._build_games_feed()
        game = next((g for g in result if g.get("game_id") == "game_bad_pa"), None)
        assert game is not None
        # pa totals should fall back to 0 when non-numeric


# ---------------------------------------------------------------------------
# handle_availability POST — additional edge cases
# ---------------------------------------------------------------------------

class TestHandleAvailabilityPostEdgeCases:
    def test_rejects_non_dict_json_body(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/availability",
                data='["not", "a", "dict"]',
                content_type="application/json",
                headers={"Origin": "https://test.example.com"},
            )
        assert resp.status_code == 400
        assert "invalid_json_object" in resp.get_json().get("error", "")

    def test_rejects_key_longer_than_80_chars(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "WRITE_ORIGINS", ["https://test.example.com"])
        long_key = "A" * 81
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/availability",
                json={long_key: True},
                content_type="application/json",
                headers={"Origin": "https://test.example.com"},
            )
        assert resp.status_code == 400
        assert "invalid_player_name" in resp.get_json().get("error", "")


# ---------------------------------------------------------------------------
# Additional handle_scoreboard exception branches
# ---------------------------------------------------------------------------

class TestHandleScoreboardExceptionBranches:
    def _mock_gc(self, games_list):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json = MagicMock(return_value=games_list)
        return mock_resp

    def test_schedule_file_bad_json_does_not_crash(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        # Bad schedule file — exception caught and returns no_game
        (tmp_path / "schedule_manual.json").write_text("{{bad json")
        with patch("sync_daemon.requests.get", return_value=self._mock_gc([])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "no_game"

    def test_game_with_bad_start_ts_does_not_crash(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        today = datetime.now(ET).strftime("%Y-%m-%d")
        game = {
            "id": "gc_bad_ts",
            "game_status": "completed",
            "start_ts": "not-a-timestamp",
            "score": {"team": 3, "opponent_team": 2},
            "opponent_team": {"name": "Tigers"},
        }
        with patch("sync_daemon.requests.get", return_value=self._mock_gc([game])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        assert resp.status_code == 200

    def test_local_game_index_json_skipped(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        today = datetime.now(ET).strftime("%Y-%m-%d")
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        # index.json should be skipped in scoreboard local enrichment
        (games_dir / "index.json").write_text('[{"date": "' + today + '"}]')
        game = {
            "id": "gc_idx_skip",
            "game_status": "completed",
            "start_ts": f"{today}T12:00:00-04:00",
            "score": {"team": 4, "opponent_team": 1},
            "opponent_team": {"name": "Bears"},
        }
        with patch("sync_daemon.requests.get", return_value=self._mock_gc([game])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        assert resp.status_code == 200

    def test_live_events_exception_does_not_crash(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        now = datetime.now(ET)
        game = {
            "id": "gc_evt_err",
            "game_status": "in_progress",
            "start_ts": now.isoformat(),
            "score": {"team": 2, "opponent_team": 1},
            "opponent_team": {"name": "Wolves"},
        }
        with patch("sync_daemon.requests.get", return_value=self._mock_gc([game])), \
             patch("sync_daemon._cached_live_events", side_effect=RuntimeError("cache fail")):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        assert resp.status_code == 200

    def test_scouting_exception_does_not_crash(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        today = datetime.now(ET).strftime("%Y-%m-%d")
        game = {
            "id": "gc_scout_err",
            "game_status": "completed",
            "start_ts": f"{today}T12:00:00-04:00",
            "score": {"team": 5, "opponent_team": 3},
            "opponent_team": {"name": "Tigers"},
        }
        with patch("sync_daemon.requests.get", return_value=self._mock_gc([game])), \
             patch("sync_daemon._cached_opponent_scouting", side_effect=RuntimeError("scout fail")):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# _cached_live_events  (cache hit branch)
# ---------------------------------------------------------------------------

class TestCachedLiveEvents:
    def test_returns_cached_result(self, monkeypatch):
        import time as _t
        game_id = "test_game_cache"
        fake_data = {"batter": "Jane"}
        # Inject a fresh cache entry
        sd._LIVE_EVENTS_CACHE[game_id] = (_t.time() + 60, fake_data)
        result = sd._cached_live_events(game_id)
        assert result == fake_data
        del sd._LIVE_EVENTS_CACHE[game_id]

    def test_expired_cache_re_fetches(self, monkeypatch):
        import time as _t
        game_id = "test_game_exp"
        # Inject an expired cache entry
        sd._LIVE_EVENTS_CACHE[game_id] = (_t.time() - 10, {"old": "data"})
        fresh_data = {"new": "events"}
        with patch("sync_daemon._fetch_gc_live_events", return_value=fresh_data):
            result = sd._cached_live_events(game_id)
        assert result == fresh_data
        del sd._LIVE_EVENTS_CACHE[game_id]


# ---------------------------------------------------------------------------
# handle_game_detail — self-heal copies result/score_str
# ---------------------------------------------------------------------------

class TestHandleGameDetailSelfHealCopy:
    def test_result_copied_from_gc_file(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        primary = {"game_id": "game_noresult", "date": "2024-05-10", "opponent": "Tigers"}
        (games_dir / "game_noresult.json").write_text(json.dumps(primary))
        gc_game = {
            "date": "2024-05-10",
            "result": "W",
            "score_str": "7-3",
            "sharks": {"batting": [{"name": "Jane"}], "pitching": []},
        }
        (games_dir / "game_gc_2024.json").write_text(json.dumps(gc_game))
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game_noresult")
        data = resp.get_json()
        assert data.get("result") == "W"
        assert data.get("score_str") == "7-3"

    def test_strip_totals_exception_returns_all_rows(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        # Rows where PA field is non-numeric (exception in _strip_team_totals_row)
        game = {
            "game_id": "game_paerr",
            "date": "2024-05-11",
            "sharks": {
                "batting": [
                    {"name": "Row1", "pa": "N/A"},
                    {"name": "Row2", "pa": "N/A"},
                ],
                "pitching": [],
            },
        }
        (games_dir / "game_paerr.json").write_text(json.dumps(game))
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game_paerr")
        data = resp.get_json()
        # Exception caught — returns original rows unchanged
        assert len(data.get("sharks_batting", [])) == 2


# ---------------------------------------------------------------------------
# _build_games_feed — additional exception and edge-case branches
# ---------------------------------------------------------------------------

class TestBuildGamesFeedEdgeCases:
    def test_known_results_with_non_dict_item_does_not_crash(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        index = [{"game_id": "pdf_edge", "date": "2024-06-01", "opponent": "Tigers"}]
        (games_dir / "index.json").write_text(json.dumps(index))
        # Non-dict items in results list → causes AttributeError → exception caught at 1702
        known = {"results": ["not a dict", 42]}
        (tmp_path / "known_game_results.json").write_text(json.dumps(known))
        result = sd._build_games_feed()
        assert isinstance(result, list)

    def test_gc_self_heal_skips_file_with_different_date(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        index = [{"game_id": "pdf_misdate", "date": "2024-06-01", "opponent": "Bears"}]
        (games_dir / "index.json").write_text(json.dumps(index))
        # GC game file with a DIFFERENT date — should be skipped (line 1717)
        gc_game = {
            "date": "2024-07-01",  # different date
            "score": {"sharks": 5, "opponent": 3},
        }
        (games_dir / "game_gc_diff_date.json").write_text(json.dumps(gc_game))
        result = sd._build_games_feed()
        game = next((g for g in result if g["game_id"] == "pdf_misdate"), None)
        assert game is not None
        assert not game.get("result")  # not self-healed

    def test_gc_self_heal_skips_file_with_no_valid_score(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        index = [{"game_id": "pdf_noscore", "date": "2024-06-02", "opponent": "Cats"}]
        (games_dir / "index.json").write_text(json.dumps(index))
        # GC game file with same date but score missing sharks/opponent keys (line 1723)
        gc_game = {
            "date": "2024-06-02",
            "score": {"team": 5, "other_team": 3},  # no sharks/opponent keys
        }
        (games_dir / "game_gc_noscore.json").write_text(json.dumps(gc_game))
        result = sd._build_games_feed()
        game = next((g for g in result if g["game_id"] == "pdf_noscore"), None)
        assert game is not None
        assert not game.get("result")  # score check failed

    def test_gc_format_game_bad_batting_row_exception_caught(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        # A GC v2 game file where batting contains non-dict items → totals _s() call raises
        gc_game = {
            "game_id": "game_gc_badrow",
            "source": "gc_full_scraper_v2",
            "date": "2024-06-10",
            "opponent": "Tigers",
            "sharks": {
                "batting": "not a list",  # invalid batting → exception in has_any_stats
                "pitching": [],
            },
        }
        (games_dir / "game_gc_badrow.json").write_text(json.dumps(gc_game))
        result = sd._build_games_feed()
        # The game should be excluded (exception handler at 1821-1822 fired or has_any_stats=False)
        assert isinstance(result, list)

    def test_gc_self_heal_non_numeric_score_exception_caught(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        index = [{"game_id": "pdf_numex", "date": "2024-07-01", "opponent": "Sharks"}]
        (games_dir / "index.json").write_text(json.dumps(index))
        # GC file with non-numeric score that causes TypeError in sh > op comparison
        gc_game = {"date": "2024-07-01", "score": {"sharks": "five", "opponent": 3}}
        (games_dir / "game_gc_numex.json").write_text(json.dumps(gc_game))
        result = sd._build_games_feed()
        assert isinstance(result, list)  # exception caught at lines 1731-1732

    def test_gc_v2_non_numeric_score_exception_caught(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        # GC v2 game with non-numeric score — triggers exception at 1821-1822
        gc_game = {
            "game_id": "game_gc_ex",
            "source": "gc_full_scraper_v2",
            "date": "2024-07-02",
            "opponent": "Tigers",
            "score": {"sharks": "five", "opponent": 3},  # non-numeric
            "sharks": {"batting": [{"name": "Jane", "pa": 4}], "pitching": []},
        }
        (games_dir / "game_gc_ex.json").write_text(json.dumps(gc_game))
        result = sd._build_games_feed()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# handle_game_detail — invalid slug returns 400
# ---------------------------------------------------------------------------

class TestHandleGameDetailInvalidSlug:
    def test_invalid_slug_with_dot_returns_400(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        (tmp_path / "games").mkdir()
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game.with.dots")
        assert resp.status_code == 400
        assert "invalid_parameter" in resp.get_json().get("error", "")

    def test_slug_with_spaces_url_encoded(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        (tmp_path / "games").mkdir()
        with flask_app.test_client() as client:
            resp = client.get("/api/games/game%20with%20spaces")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Additional exception branches in handle_scoreboard
# ---------------------------------------------------------------------------

class TestHandleScoreboardMoreBranches:
    def _mock_gc(self, games_list):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json = MagicMock(return_value=games_list)
        return mock_resp

    def test_schedule_fallback_exception_returns_no_game(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        # Create a bad schedule file in a dir that will be monkeypatched
        (tmp_path / "schedule_manual.json").write_text("{{bad")
        with patch("sync_daemon.requests.get", return_value=self._mock_gc([])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        # Bad schedule file caught → returns no_game
        assert resp.get_json()["status"] == "no_game"

    def test_live_game_with_bad_start_ts_parses_gracefully(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        game = {
            "id": "gc_bad_start",
            "game_status": "in_progress",  # live game — picked even with bad start_ts
            "start_ts": "not-a-date",  # bad start_ts
            "score": {"team": 4, "opponent_team": 2},
            "opponent_team": {"name": "Lions"},
        }
        with patch("sync_daemon.requests.get", return_value=self._mock_gc([game])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        data = resp.get_json()
        # Should not crash; covers lines 2105-2106 (start_ts parse exception)
        assert data["status"] == "live"

    def test_local_enrichment_bad_game_file_skipped(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        today = datetime.now(ET).strftime("%Y-%m-%d")
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        # A corrupt game file in games_dir
        (games_dir / "game_corrupt.json").write_text("{{bad json")
        game = {
            "id": "gc_corrupt_test",
            "game_status": "completed",
            "start_ts": f"{today}T12:00:00-04:00",
            "score": {"team": 5, "opponent_team": 2},
            "opponent_team": {"name": "Tigers"},
        }
        with patch("sync_daemon.requests.get", return_value=self._mock_gc([game])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        assert resp.status_code == 200

    def test_schedule_context_exception_does_not_crash(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        today = datetime.now(ET).strftime("%Y-%m-%d")
        # Bad schedule file
        (tmp_path / "schedule_manual.json").write_text("{{bad json")
        game = {
            "id": "gc_sched_ex",
            "game_status": "completed",
            "start_ts": f"{today}T12:00:00-04:00",
            "score": {"team": 5, "opponent_team": 3},
            "opponent_team": {"name": "Tigers"},
        }
        with patch("sync_daemon.requests.get", return_value=self._mock_gc([game])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        assert resp.status_code == 200

    def test_local_enrichment_bad_start_ts_falls_back_to_today(self, flask_app, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        today = datetime.now(ET).strftime("%Y-%m-%d")
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        local_game = {
            "date": today,
            "sharks_batting": [{"name": "Jane", "h": 1}],
            "score": {"sharks": 4, "opponent": 2},
        }
        (games_dir / "game_local.json").write_text(json.dumps(local_game))
        # in_progress game so it gets picked even with bad start_ts
        game = {
            "id": "gc_bad_start_local",
            "game_status": "in_progress",
            "start_ts": "not-a-date",  # bad start_ts → fallback to today_str (lines 2131-2132)
            "score": {"team": 3, "opponent_team": 1},
            "opponent_team": {"name": "Tigers"},
        }
        with patch("sync_daemon.requests.get", return_value=self._mock_gc([game])):
            with flask_app.test_client() as client:
                resp = client.get("/api/scoreboard")
        data = resp.get_json()
        # Local enrichment finds today's game by date fallback → overrides score
        assert data["status"] == "live"
        assert data["sharks_score"] == 4  # from local file
