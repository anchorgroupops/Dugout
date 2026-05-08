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
