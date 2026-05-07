"""Tests for tools/db_sync.py — PostgreSQL logging wrapper.

All functions silently return False when psycopg2 is absent or the DB is
unreachable. That's the guaranteed fallback path for CI.
"""
from __future__ import annotations

import os

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import db_sync


class TestDbUrl:
    def test_returns_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("LIBRARIAN_DB_URL", raising=False)
        url = db_sync._db_url()
        assert "postgresql" in url
        assert "192.168.7.222" in url

    def test_returns_custom_url_from_env(self, monkeypatch):
        monkeypatch.setenv("LIBRARIAN_DB_URL", "postgresql://user:pass@localhost/testdb")
        url = db_sync._db_url()
        assert url == "postgresql://user:pass@localhost/testdb"


class TestIsAvailable:
    def test_returns_bool(self):
        result = db_sync.is_available()
        assert isinstance(result, bool)

    def test_returns_false_when_no_db(self, monkeypatch):
        monkeypatch.setenv("LIBRARIAN_DB_URL", "postgresql://bad:bad@127.0.0.1:1/noexist")
        result = db_sync.is_available()
        assert result is False


class TestEnsureTables:
    def test_returns_false_when_no_db(self, monkeypatch):
        monkeypatch.setenv("LIBRARIAN_DB_URL", "postgresql://bad:bad@127.0.0.1:1/noexist")
        result = db_sync.ensure_tables()
        assert result is False

    def test_returns_bool(self):
        result = db_sync.ensure_tables()
        assert isinstance(result, bool)


class TestLogSyncRun:
    def test_returns_false_when_no_db(self, monkeypatch):
        monkeypatch.setenv("LIBRARIAN_DB_URL", "postgresql://bad:bad@127.0.0.1:1/noexist")
        result = db_sync.log_sync_run("nb-1", "My Notebook", 5, 0, 1200)
        assert result is False

    def test_returns_bool(self):
        result = db_sync.log_sync_run("nb-1", "Test NB", 0, 0, 500, dry_run=True)
        assert isinstance(result, bool)

    def test_dry_run_flag_accepted(self):
        result = db_sync.log_sync_run("nb-2", "NB", 1, 0, 300, dry_run=True)
        assert isinstance(result, bool)

    def test_error_string_accepted(self):
        result = db_sync.log_sync_run("nb-3", "NB", 0, 1, 100, error="some error")
        assert isinstance(result, bool)


class TestLogSource:
    def test_returns_false_when_no_db(self, monkeypatch):
        monkeypatch.setenv("LIBRARIAN_DB_URL", "postgresql://bad:bad@127.0.0.1:1/noexist")
        result = db_sync.log_source("nb-1", "https://example.com/vid", "Title")
        assert result is False

    def test_returns_bool(self):
        result = db_sync.log_source("nb-1", "https://example.com/vid", "Title")
        assert isinstance(result, bool)

    def test_optional_params_accepted(self):
        result = db_sync.log_source(
            "nb-1", "https://example.com/vid",
            title="Title", source_type="youtube",
            status="success", source_id="abc123",
            error=None,
        )
        assert isinstance(result, bool)

    def test_failed_status_accepted(self):
        result = db_sync.log_source("nb-1", "https://example.com/vid", status="failed", error="timeout")
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Tests using mock connection to exercise the "success path" branches
# ---------------------------------------------------------------------------

def _make_mock_conn():
    """Build a minimal mock psycopg2 connection."""
    from unittest.mock import MagicMock
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


class TestWithMockConnection:
    def test_ensure_tables_success_path(self, monkeypatch):
        conn, cursor = _make_mock_conn()
        monkeypatch.setattr(db_sync, "_get_conn", lambda: conn)
        result = db_sync.ensure_tables()
        assert result is True
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_ensure_tables_exception_returns_false(self, monkeypatch):
        conn, cursor = _make_mock_conn()
        conn.cursor.return_value.__enter__.side_effect = RuntimeError("bad")
        monkeypatch.setattr(db_sync, "_get_conn", lambda: conn)
        result = db_sync.ensure_tables()
        assert result is False
        conn.close.assert_called_once()

    def test_log_sync_run_success_path(self, monkeypatch):
        conn, cursor = _make_mock_conn()
        monkeypatch.setattr(db_sync, "_get_conn", lambda: conn)
        result = db_sync.log_sync_run("nb-1", "NB", 3, 0, 1000)
        assert result is True
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_log_sync_run_exception_returns_false(self, monkeypatch):
        conn, cursor = _make_mock_conn()
        conn.cursor.return_value.__enter__.side_effect = RuntimeError("write fail")
        monkeypatch.setattr(db_sync, "_get_conn", lambda: conn)
        result = db_sync.log_sync_run("nb-1", "NB", 0, 1, 100)
        assert result is False
        conn.close.assert_called_once()

    def test_log_source_success_path(self, monkeypatch):
        conn, cursor = _make_mock_conn()
        monkeypatch.setattr(db_sync, "_get_conn", lambda: conn)
        result = db_sync.log_source("nb-1", "https://x.com/v", "Title")
        assert result is True
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_log_source_exception_returns_false(self, monkeypatch):
        conn, cursor = _make_mock_conn()
        conn.cursor.return_value.__enter__.side_effect = RuntimeError("insert fail")
        monkeypatch.setattr(db_sync, "_get_conn", lambda: conn)
        result = db_sync.log_source("nb-1", "https://x.com/v")
        assert result is False
        conn.close.assert_called_once()

    def test_is_available_with_good_conn(self, monkeypatch):
        conn, _ = _make_mock_conn()
        monkeypatch.setattr(db_sync, "_get_conn", lambda: conn)
        result = db_sync.is_available()
        assert result is True
        conn.close.assert_called_once()

    def test_get_conn_import_error_returns_none(self, monkeypatch):
        import sys
        # Temporarily remove psycopg2 if present
        original = sys.modules.get("psycopg2")
        sys.modules["psycopg2"] = None  # type: ignore[assignment]
        try:
            result = db_sync._get_conn()
            assert result is None
        finally:
            if original is None:
                sys.modules.pop("psycopg2", None)
            else:
                sys.modules["psycopg2"] = original
