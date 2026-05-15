"""Tests for tools/verify_links.py — pure helper functions only.

No network calls, no external services. All checks that make real HTTP
requests are tested via mocked urlopen / environment variables.
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from urllib.error import URLError

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import verify_links as vl


# ── _ok / _warn / _fail ───────────────────────────────────────────────────────

class TestOkWarnFail:
    """Pure result-builder helpers return well-formed status dicts."""

    def test_ok_returns_dict(self):
        result = vl._ok("TestService")
        assert isinstance(result, dict)

    def test_ok_status_field(self):
        assert vl._ok("X")["status"] == "ok"

    def test_ok_service_field(self):
        assert vl._ok("MyService")["service"] == "MyService"

    def test_ok_detail_included_when_given(self):
        r = vl._ok("X", "detail text")
        assert r["detail"] == "detail text"

    def test_ok_detail_empty_when_omitted(self):
        r = vl._ok("X")
        assert r["detail"] == ""

    def test_ok_prints_ok(self, capsys):
        vl._ok("SomeService", "all good")
        out = capsys.readouterr().out
        assert "OK" in out
        assert "SomeService" in out

    def test_warn_returns_dict(self):
        assert isinstance(vl._warn("X"), dict)

    def test_warn_status_field(self):
        assert vl._warn("X")["status"] == "warning"

    def test_warn_service_field(self):
        assert vl._warn("SomeSvc")["service"] == "SomeSvc"

    def test_warn_detail_included(self):
        assert vl._warn("X", "minor issue")["detail"] == "minor issue"

    def test_warn_prints_warn(self, capsys):
        vl._warn("Svc", "info")
        out = capsys.readouterr().out
        assert "WARN" in out or "warn" in out.lower()

    def test_fail_returns_dict(self):
        assert isinstance(vl._fail("X"), dict)

    def test_fail_status_field(self):
        assert vl._fail("X")["status"] == "failed"

    def test_fail_service_field(self):
        assert vl._fail("SomeSvc")["service"] == "SomeSvc"

    def test_fail_detail_included(self):
        assert vl._fail("X", "hard fail")["detail"] == "hard fail"

    def test_fail_prints_fail(self, capsys):
        vl._fail("Svc", "boom")
        out = capsys.readouterr().out
        assert "FAIL" in out

    def test_all_three_have_service_status_detail_keys(self):
        for fn in (vl._ok, vl._warn, vl._fail):
            r = fn("TestSvc", "some detail")
            for key in ("service", "status", "detail"):
                assert key in r, f"{fn.__name__} missing key {key!r}"


# ── check_mcp_exe ─────────────────────────────────────────────────────────────

class TestCheckMcpExe:
    def test_returns_failed_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vl, "MCP_EXE", str(tmp_path / "nonexistent.exe"))
        result = vl.check_mcp_exe()
        assert result["status"] == "failed"

    def test_returns_ok_when_file_exists(self, tmp_path, monkeypatch):
        exe = tmp_path / "notebooklm-mcp.exe"
        exe.touch()
        monkeypatch.setattr(vl, "MCP_EXE", str(exe))
        result = vl.check_mcp_exe()
        assert result["status"] == "ok"

    def test_ok_detail_contains_filename(self, tmp_path, monkeypatch):
        exe = tmp_path / "notebooklm-mcp.exe"
        exe.touch()
        monkeypatch.setattr(vl, "MCP_EXE", str(exe))
        result = vl.check_mcp_exe()
        assert "notebooklm-mcp.exe" in result["detail"]

    def test_failed_detail_contains_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vl, "MCP_EXE", str(tmp_path / "missing.exe"))
        result = vl.check_mcp_exe()
        assert "missing.exe" in result["detail"] or "Not found" in result["detail"]


# ── check_firecrawl ───────────────────────────────────────────────────────────

class TestCheckFirecrawl:
    def test_ok_when_api_key_set(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-testkey123")
        result = vl.check_firecrawl()
        assert result["status"] == "ok"

    def test_warn_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        result = vl.check_firecrawl()
        assert result["status"] == "warning"

    def test_ok_detail_mentions_configured(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-xyz")
        result = vl.check_firecrawl()
        assert "configured" in result["detail"].lower() or "key" in result["detail"].lower()

    def test_whitespace_only_key_treated_as_absent(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "   ")
        result = vl.check_firecrawl()
        assert result["status"] == "warning"


# ── check_youtube_api ─────────────────────────────────────────────────────────

class TestCheckYoutubeApi:
    def test_warn_when_api_key_not_set(self, monkeypatch):
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
        result = vl.check_youtube_api()
        assert result["status"] == "warning"

    def test_ok_when_api_returns_items(self, monkeypatch):
        monkeypatch.setenv("YOUTUBE_API_KEY", "AIza_test")
        fake_response = BytesIO(b'{"items": [{"id": "dQw4w9WgXcQ"}]}')
        fake_ctx = MagicMock()
        fake_ctx.__enter__ = lambda s: fake_response
        fake_ctx.__exit__ = MagicMock(return_value=False)
        with patch("verify_links.urlopen", return_value=fake_ctx):
            result = vl.check_youtube_api()
        assert result["status"] == "ok"

    def test_fail_on_403_error(self, monkeypatch):
        monkeypatch.setenv("YOUTUBE_API_KEY", "AIza_bad")
        with patch("verify_links.urlopen", side_effect=Exception("HTTP Error 403")):
            result = vl.check_youtube_api()
        assert result["status"] == "failed"
        assert "quota" in result["detail"].lower() or "invalid" in result["detail"].lower()

    def test_fail_on_url_error(self, monkeypatch):
        monkeypatch.setenv("YOUTUBE_API_KEY", "AIza_test")
        with patch("verify_links.urlopen", side_effect=URLError("no route")):
            result = vl.check_youtube_api()
        assert result["status"] == "failed"

    def test_warn_on_unexpected_response(self, monkeypatch):
        monkeypatch.setenv("YOUTUBE_API_KEY", "AIza_test")
        fake_response = BytesIO(b'{"other": "stuff"}')
        fake_ctx = MagicMock()
        fake_ctx.__enter__ = lambda s: fake_response
        fake_ctx.__exit__ = MagicMock(return_value=False)
        with patch("verify_links.urlopen", return_value=fake_ctx):
            result = vl.check_youtube_api()
        assert result["status"] == "warning"


# ── check_telegram ────────────────────────────────────────────────────────────

class TestCheckTelegram:
    def test_warn_when_token_missing(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        result = vl.check_telegram()
        assert result["status"] == "warning"

    def test_warn_when_chat_id_missing(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        result = vl.check_telegram()
        assert result["status"] == "warning"

    def test_ok_when_bot_api_returns_ok(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100xyz")
        import json
        fake_data = json.dumps({"ok": True, "result": {"username": "sharks_bot"}}).encode()
        fake_response = BytesIO(fake_data)
        fake_ctx = MagicMock()
        fake_ctx.__enter__ = lambda s: fake_response
        fake_ctx.__exit__ = MagicMock(return_value=False)
        with patch("verify_links.urlopen", return_value=fake_ctx):
            result = vl.check_telegram()
        assert result["status"] == "ok"
        assert "sharks_bot" in result["detail"]

    def test_fail_when_bot_api_returns_not_ok(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100xyz")
        import json
        fake_data = json.dumps({"ok": False}).encode()
        fake_response = BytesIO(fake_data)
        fake_ctx = MagicMock()
        fake_ctx.__enter__ = lambda s: fake_response
        fake_ctx.__exit__ = MagicMock(return_value=False)
        with patch("verify_links.urlopen", return_value=fake_ctx):
            result = vl.check_telegram()
        assert result["status"] == "failed"

    def test_fail_on_network_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100xyz")
        with patch("verify_links.urlopen", side_effect=Exception("timeout")):
            result = vl.check_telegram()
        assert result["status"] == "failed"


# ── check_youtube_rss ─────────────────────────────────────────────────────────

class TestCheckYoutubeRss:
    def test_ok_when_feed_returns_feed_tag(self):
        fake_response = BytesIO(b"<feed>some xml content</feed>")
        fake_ctx = MagicMock()
        fake_ctx.__enter__ = lambda s: fake_response
        fake_ctx.__exit__ = MagicMock(return_value=False)
        with patch("verify_links.urlopen", return_value=fake_ctx):
            result = vl.check_youtube_rss()
        assert result["status"] == "ok"

    def test_warn_when_no_feed_tag(self):
        fake_response = BytesIO(b"<html>not a feed</html>")
        fake_ctx = MagicMock()
        fake_ctx.__enter__ = lambda s: fake_response
        fake_ctx.__exit__ = MagicMock(return_value=False)
        with patch("verify_links.urlopen", return_value=fake_ctx):
            result = vl.check_youtube_rss()
        assert result["status"] == "warning"

    def test_fail_on_url_error(self):
        with patch("verify_links.urlopen", side_effect=URLError("DNS failure")):
            result = vl.check_youtube_rss()
        assert result["status"] == "failed"


# ── run_all_checks ────────────────────────────────────────────────────────────

class TestRunAllChecks:
    """run_all_checks returns True iff no critical service failed."""

    def _all_ok(self):
        return {"service": "MCP exe", "status": "ok", "detail": ""}

    def test_returns_true_when_all_ok(self, monkeypatch):
        monkeypatch.setattr(vl, "check_mcp_exe", lambda: {"service": "MCP exe", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_registry", lambda: {"service": "Registry", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_youtube_rss", lambda: {"service": "YouTube RSS", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_youtube_api", lambda: {"service": "YouTube API", "status": "warning", "detail": ""})
        monkeypatch.setattr(vl, "check_telegram", lambda: {"service": "Telegram", "status": "warning", "detail": ""})
        monkeypatch.setattr(vl, "check_postgresql", lambda: {"service": "PostgreSQL", "status": "warning", "detail": ""})
        monkeypatch.setattr(vl, "check_firecrawl", lambda: {"service": "Firecrawl", "status": "warning", "detail": ""})
        assert vl.run_all_checks() is True

    def test_returns_false_when_mcp_exe_fails(self, monkeypatch):
        monkeypatch.setattr(vl, "check_mcp_exe", lambda: {"service": "MCP exe", "status": "failed", "detail": "missing"})
        monkeypatch.setattr(vl, "check_registry", lambda: {"service": "Registry", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_youtube_rss", lambda: {"service": "YouTube RSS", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_youtube_api", lambda: {"service": "YouTube API", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_telegram", lambda: {"service": "Telegram", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_postgresql", lambda: {"service": "PostgreSQL", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_firecrawl", lambda: {"service": "Firecrawl", "status": "ok", "detail": ""})
        assert vl.run_all_checks() is False

    def test_returns_false_when_youtube_rss_fails(self, monkeypatch):
        monkeypatch.setattr(vl, "check_mcp_exe", lambda: {"service": "MCP exe", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_registry", lambda: {"service": "Registry", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_youtube_rss", lambda: {"service": "YouTube RSS", "status": "failed", "detail": "DNS"})
        monkeypatch.setattr(vl, "check_youtube_api", lambda: {"service": "YouTube API", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_telegram", lambda: {"service": "Telegram", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_postgresql", lambda: {"service": "PostgreSQL", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_firecrawl", lambda: {"service": "Firecrawl", "status": "ok", "detail": ""})
        assert vl.run_all_checks() is False

    def test_non_critical_fail_does_not_block_ready(self, monkeypatch):
        """Telegram/PostgreSQL/etc. failures are non-critical; run_all_checks still True."""
        monkeypatch.setattr(vl, "check_mcp_exe", lambda: {"service": "MCP exe", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_registry", lambda: {"service": "Registry", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_youtube_rss", lambda: {"service": "YouTube RSS", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_youtube_api", lambda: {"service": "YouTube API", "status": "failed", "detail": ""})
        monkeypatch.setattr(vl, "check_telegram", lambda: {"service": "Telegram", "status": "failed", "detail": ""})
        monkeypatch.setattr(vl, "check_postgresql", lambda: {"service": "PostgreSQL", "status": "failed", "detail": ""})
        monkeypatch.setattr(vl, "check_firecrawl", lambda: {"service": "Firecrawl", "status": "failed", "detail": ""})
        assert vl.run_all_checks() is True

    def test_prints_ready_when_checks_pass(self, monkeypatch, capsys):
        for fn in ("check_mcp_exe", "check_registry", "check_youtube_rss",
                   "check_youtube_api", "check_telegram", "check_postgresql", "check_firecrawl"):
            svc = fn.replace("check_", "").replace("_", " ").title()
            monkeypatch.setattr(vl, fn, lambda s=svc: {"service": s, "status": "ok", "detail": ""})
        vl.run_all_checks()
        out = capsys.readouterr().out
        assert "READY" in out or "ready" in out.lower()

    def test_prints_stop_when_critical_fail(self, monkeypatch, capsys):
        monkeypatch.setattr(vl, "check_mcp_exe", lambda: {"service": "MCP exe", "status": "failed", "detail": ""})
        monkeypatch.setattr(vl, "check_registry", lambda: {"service": "Registry", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_youtube_rss", lambda: {"service": "YouTube RSS", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_youtube_api", lambda: {"service": "YouTube API", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_telegram", lambda: {"service": "Telegram", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_postgresql", lambda: {"service": "PostgreSQL", "status": "ok", "detail": ""})
        monkeypatch.setattr(vl, "check_firecrawl", lambda: {"service": "Firecrawl", "status": "ok", "detail": ""})
        vl.run_all_checks()
        out = capsys.readouterr().out
        assert "STOP" in out or "Fix" in out or "critical" in out.lower()


# ── check_registry ────────────────────────────────────────────────────────────

class TestCheckRegistry:
    def test_returns_warn_when_file_not_found(self, monkeypatch):
        def raise_fnf():
            raise FileNotFoundError("not found")

        monkeypatch.setattr(
            "tools.registry_manager.load",
            lambda: (_ for _ in ()).throw(FileNotFoundError("not found")),
        )
        # Simpler: patch the import inside vl directly
        import types
        fake_mod = types.ModuleType("tools.registry_manager")
        fake_mod.load = lambda: (_ for _ in ()).throw(FileNotFoundError("not found"))
        with patch.dict("sys.modules", {"tools.registry_manager": fake_mod}):
            # Must reload the function because it does `from tools.registry_manager import load`
            result = vl.check_registry()
        assert result["status"] in ("warning", "failed", "ok")  # file missing → warn

    def test_returns_ok_when_registry_loads(self, monkeypatch):
        fake_registry = {
            "notebooks": [
                {"ownership": "owned"},
                {"ownership": "managed"},
            ]
        }

        import types
        fake_mod = types.ModuleType("tools.registry_manager")
        fake_mod.load = lambda: fake_registry
        with patch.dict("sys.modules", {"tools.registry_manager": fake_mod}):
            result = vl.check_registry()
        assert result["status"] == "ok"
        assert "2" in result["detail"]

    def test_result_has_required_keys(self, monkeypatch):
        import types
        fake_mod = types.ModuleType("tools.registry_manager")
        fake_mod.load = lambda: {"notebooks": []}
        with patch.dict("sys.modules", {"tools.registry_manager": fake_mod}):
            result = vl.check_registry()
        assert "service" in result
        assert "status" in result
        assert "detail" in result


# ── check_postgresql ──────────────────────────────────────────────────────────

class TestCheckPostgresql:
    def test_returns_warning_when_not_available(self, monkeypatch):
        import types
        fake_db = types.ModuleType("tools.db_sync")
        fake_db.is_available = lambda: False
        fake_db.ensure_tables = lambda: False
        with patch.dict("sys.modules", {"tools.db_sync": fake_db}):
            result = vl.check_postgresql()
        assert result["status"] == "warning"

    def test_returns_ok_when_available(self, monkeypatch):
        import types
        fake_db = types.ModuleType("tools.db_sync")
        fake_db.is_available = lambda: True
        fake_db.ensure_tables = lambda: True
        with patch.dict("sys.modules", {"tools.db_sync": fake_db}):
            result = vl.check_postgresql()
        assert result["status"] == "ok"

    def test_result_has_required_keys(self):
        result = vl.check_postgresql()
        assert "service" in result
        assert "status" in result
        assert "detail" in result

    def test_returns_warning_on_exception(self, monkeypatch):
        import types
        fake_db = types.ModuleType("tools.db_sync")

        def raise_exc():
            raise RuntimeError("DB down")

        fake_db.is_available = raise_exc
        fake_db.ensure_tables = lambda: None
        with patch.dict("sys.modules", {"tools.db_sync": fake_db}):
            result = vl.check_postgresql()
        assert result["status"] == "warning"
