"""Tests for tools/notify.py — Telegram notification wrapper."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tools import notify


@pytest.fixture
def clean_telegram_env(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    yield


class TestSendTelegram:
    def test_unconfigured_returns_false(self, clean_telegram_env):
        assert notify.send_telegram("hi") is False

    def test_only_token_unconfigured(self, clean_telegram_env, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
        assert notify.send_telegram("hi") is False

    def test_only_chat_id_unconfigured(self, clean_telegram_env, monkeypatch):
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
        assert notify.send_telegram("hi") is False

    def test_success_returns_true(self, clean_telegram_env, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "CHAT")

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.object(notify, "urlopen", return_value=mock_resp) as uo:
            assert notify.send_telegram("hi") is True

        # Validate URL contains token + payload has chat_id
        call_args = uo.call_args
        req = call_args.args[0]
        assert "TOKEN" in req.full_url
        body = json.loads(req.data)
        assert body["chat_id"] == "CHAT"
        assert body["text"] == "hi"

    def test_non_ok_response_returns_false(self, clean_telegram_env, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "CHAT")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": False, "error": "bad chat"}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch.object(notify, "urlopen", return_value=mock_resp):
            assert notify.send_telegram("hi") is False

    def test_url_error_returns_false(self, clean_telegram_env, monkeypatch, capsys):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "CHAT")
        with patch.object(notify, "urlopen", side_effect=notify.URLError("unreachable")):
            assert notify.send_telegram("hi") is False
        assert "Telegram send failed" in capsys.readouterr().out

    def test_explicit_token_and_chat_id_bypass_env(self, clean_telegram_env):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch.object(notify, "urlopen", return_value=mock_resp):
            assert notify.send_telegram("hi", token="T", chat_id="C") is True


class TestNotifySyncComplete:
    def test_calls_send_telegram_with_ok_status(self, clean_telegram_env):
        with patch.object(notify, "send_telegram", return_value=True) as st:
            result = notify.notify_sync_complete(total_added=10, total_failed=0, notebooks_synced=3, duration_secs=12.4)
        assert result is True
        msg = st.call_args.args[0]
        assert "OK" in msg
        assert "10" in msg
        assert "3" in msg

    def test_partial_failure_message(self, clean_telegram_env):
        with patch.object(notify, "send_telegram", return_value=True) as st:
            notify.notify_sync_complete(total_added=2, total_failed=1, notebooks_synced=1, duration_secs=5)
        msg = st.call_args.args[0]
        assert "PARTIAL" in msg
        assert "1 failed" in msg

    def test_dry_run_prefix(self, clean_telegram_env):
        with patch.object(notify, "send_telegram", return_value=True) as st:
            notify.notify_sync_complete(
                total_added=0, total_failed=0, notebooks_synced=0, duration_secs=1, dry_run=True,
            )
        assert "DRY RUN" in st.call_args.args[0]


class TestNotifyError:
    def test_sends_context_and_error(self, clean_telegram_env):
        with patch.object(notify, "send_telegram", return_value=True) as st:
            notify.notify_error("batch_sync", "database locked")
        msg = st.call_args.args[0]
        assert "batch_sync" in msg
        assert "database locked" in msg

    def test_truncates_long_errors_to_300(self, clean_telegram_env):
        with patch.object(notify, "send_telegram", return_value=True) as st:
            notify.notify_error("x", "E" * 500)
        msg = st.call_args.args[0]
        # Only the first 300 chars of the error should be in the message
        assert "E" * 300 in msg
        assert "E" * 301 not in msg


class TestNotifyCircuitOpen:
    def test_includes_notebook_and_count(self, clean_telegram_env):
        with patch.object(notify, "send_telegram", return_value=True) as st:
            notify.notify_circuit_open("My Notebook", 7)
        msg = st.call_args.args[0]
        assert "My Notebook" in msg
        assert "7" in msg
        assert "Circuit Breaker" in msg
