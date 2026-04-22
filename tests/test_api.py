"""Tests for api.py — Flask REST API endpoints.

Conventions:
- Use the Flask test client, not the running gunicorn server.
- Authenticated endpoints require X-API-Key: matches LIBRARIAN_API_KEY (set per-test).
- Filesystem paths (REGISTRY_PATH, SUGGESTIONS_PATH, LOGS_DIR, PID_FILE, BATCH_SYNC_STATE_PATH,
  app.config["ARCHIVE_PATH"]) are monkeypatched to tmp_path to avoid touching real repo state.
- Network calls (requests.get, MCPClient) are mocked.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


TEST_KEY = "test-api-key-12345"


@pytest.fixture
def api_module(monkeypatch, tmp_path):
    """Import api with isolated filesystem roots and a test API key.

    Reloading on each test keeps module-level path constants tied to the tmp dir
    and prevents cross-test pollution of suggestions.json / PID file / logs.
    """
    monkeypatch.setenv("LIBRARIAN_API_KEY", TEST_KEY)
    monkeypatch.setenv("LIBRARIAN_ARCHIVE_PATH", str(tmp_path))
    monkeypatch.setenv("LIBRARIAN_MIN_FREE_GB", "0.001")

    # Force re-import so module-level ROOT / LOGS_DIR / PID_FILE / paths are rebuilt
    import importlib
    import sys
    if "api" in sys.modules:
        del sys.modules["api"]
    import api

    # Retarget filesystem constants to tmp_path
    api.ROOT = tmp_path
    api.LOGS_DIR = tmp_path / "logs"
    api.REGISTRY_PATH = tmp_path / "notebooks.json"
    api.SUGGESTIONS_PATH = tmp_path / "suggestions.json"
    api.PID_FILE = tmp_path / ".sync_pid"
    api.BATCH_SYNC_STATE_PATH = api.LOGS_DIR / "batch_sync_state.json"
    api.app.config["ARCHIVE_PATH"] = tmp_path

    yield api

    # Clean up module cache so another test can re-import
    if "api" in sys.modules:
        del sys.modules["api"]


@pytest.fixture
def client(api_module):
    api_module.app.testing = True
    return api_module.app.test_client()


@pytest.fixture
def auth_headers():
    return {"X-API-Key": TEST_KEY}


# ====================================================================
# Helpers / decorators
# ====================================================================
class TestToBool:
    def test_none_uses_default(self, api_module):
        assert api_module._to_bool(None) is False
        assert api_module._to_bool(None, default=True) is True

    @pytest.mark.parametrize("val,expected", [
        ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
        ("0", False), ("false", False), ("no", False), ("", False), ("maybe", False),
    ])
    def test_various_strings(self, api_module, val, expected):
        assert api_module._to_bool(val) is expected

    def test_whitespace_stripped(self, api_module):
        assert api_module._to_bool("  true  ") is True


# ====================================================================
# JSON I/O helpers
# ====================================================================
class TestReadJson:
    def test_missing_file_returns_fallback(self, api_module, tmp_path):
        result = api_module._read_json(tmp_path / "missing.json", fallback={"ok": True})
        assert result == {"ok": True}

    def test_valid_json(self, api_module, tmp_path):
        p = tmp_path / "data.json"
        p.write_text(json.dumps({"foo": "bar"}))
        assert api_module._read_json(p) == {"foo": "bar"}

    def test_invalid_json_returns_fallback(self, api_module, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json{")
        # Needs a Flask request context for _logger() to work
        with api_module.app.app_context():
            result = api_module._read_json(p, fallback=[])
        assert result == []


class TestAtomicWriteJson:
    def test_writes_json_atomically(self, api_module, tmp_path):
        target = tmp_path / "sub" / "out.json"  # nested subdir to force mkdir
        api_module._atomic_write_json(target, {"a": 1})
        assert json.loads(target.read_text()) == {"a": 1}

    def test_overwrites_existing(self, api_module, tmp_path):
        target = tmp_path / "out.json"
        target.write_text("stale")
        api_module._atomic_write_json(target, {"new": True})
        assert json.loads(target.read_text()) == {"new": True}


# ====================================================================
# Auth
# ====================================================================
class TestRequireApiKey:
    def test_no_auth_returns_401(self, client):
        resp = client.get("/notebooks")
        assert resp.status_code == 401
        assert resp.json["error"] == "Unauthorized"

    def test_wrong_key_returns_401(self, client):
        resp = client.get("/notebooks", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_bearer_token_works(self, client, api_module, tmp_path):
        # Need a registry file for /notebooks to 200
        api_module.REGISTRY_PATH.write_text(json.dumps({"notebooks": []}))
        resp = client.get("/notebooks", headers={"Authorization": f"Bearer {TEST_KEY}"})
        assert resp.status_code == 200

    def test_x_api_key_header_works(self, client, api_module, auth_headers):
        api_module.REGISTRY_PATH.write_text(json.dumps({"notebooks": []}))
        resp = client.get("/notebooks", headers=auth_headers)
        assert resp.status_code == 200

    def test_unconfigured_server_returns_503(self, client, api_module):
        api_module.app.config["LIBRARIAN_API_KEY"] = ""
        resp = client.get("/notebooks", headers={"X-API-Key": TEST_KEY})
        assert resp.status_code == 503
        assert "not configured" in resp.json["error"].lower()


# ====================================================================
# Public endpoints
# ====================================================================
class TestFavicon:
    def test_returns_204(self, client):
        resp = client.get("/favicon.ico")
        assert resp.status_code == 204


class TestOptionsHandler:
    def test_options_returns_204(self, client):
        resp = client.options("/anything")
        assert resp.status_code == 204

    def test_options_root_returns_204(self, client):
        resp = client.options("/")
        assert resp.status_code == 204


class TestHealth:
    def test_health_returns_200_with_structure(self, client, api_module):
        with patch.object(api_module, "_youtube_connectivity", return_value={"status": "degraded"}):
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json["status"] == "ok"
        assert "disk" in resp.json
        assert "youtube_api" in resp.json
        assert "last_batch_sync" in resp.json

    def test_health_reports_missing_archive(self, client, api_module, tmp_path):
        api_module.app.config["ARCHIVE_PATH"] = tmp_path / "does-not-exist"
        with patch.object(api_module, "_youtube_connectivity", return_value={"status": "degraded"}):
            resp = client.get("/health")
        assert resp.json["disk"]["status"] == "error"


# ====================================================================
# Status endpoints
# ====================================================================
class TestGetStatus:
    def test_no_logs_dir(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200
        assert resp.json["status"] == "no_logs"

    def test_no_run_logs_in_dir(self, client, api_module):
        api_module.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        resp = client.get("/status")
        assert resp.json["status"] == "no_logs"

    def test_returns_latest_run_log(self, client, api_module):
        api_module.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        old = api_module.LOGS_DIR / "run_2020-01-01.json"
        new = api_module.LOGS_DIR / "run_2026-01-01.json"
        old.write_text(json.dumps({"stage": "old", "progress": 50}))
        new.write_text(json.dumps({"stage": "done", "progress": 100}))
        resp = client.get("/status")
        assert resp.json["stage"] == "done"
        assert resp.json["progress"] == 100

    def test_sync_status_alias(self, client):
        # /sync/status is aliased to the same handler
        resp = client.get("/sync/status")
        assert resp.status_code == 200


class TestRunStatus:
    def test_returns_not_running_without_pid_file(self, client, auth_headers):
        resp = client.get("/run/status", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json["running"] is False

    def test_returns_running_when_pid_exists(self, client, auth_headers, api_module):
        api_module.PID_FILE.write_text(str(os.getpid()))
        resp = client.get("/run/status", headers=auth_headers)
        assert resp.json["running"] is True
        assert resp.json["pid"] == os.getpid()


# ====================================================================
# /run — trigger sync
# ====================================================================
class TestTriggerRun:
    def test_requires_auth(self, client):
        resp = client.post("/run")
        assert resp.status_code == 401

    def test_triggers_new_sync(self, client, auth_headers, api_module):
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        with patch.object(api_module.subprocess, "Popen", return_value=mock_proc) as popen:
            resp = client.post("/run", headers=auth_headers, json={"dry_run": True})
        assert resp.status_code == 200
        assert resp.json["status"] == "triggered"
        assert "--dry-run" in popen.call_args.args[0]
        # PID file should have been written
        assert api_module.PID_FILE.exists()

    def test_passes_notebook_and_limit_args(self, client, auth_headers, api_module):
        mock_proc = MagicMock(pid=42)
        with patch.object(api_module.subprocess, "Popen", return_value=mock_proc) as popen:
            resp = client.post("/run", headers=auth_headers, json={"notebook": "nb123", "limit": 5})
        assert resp.status_code == 200
        called_args = popen.call_args.args[0]
        assert "--notebook" in called_args
        assert "nb123" in called_args
        assert "--limit" in called_args
        assert "5" in called_args

    def test_already_running_returns_status(self, client, auth_headers, api_module):
        api_module.PID_FILE.write_text(str(os.getpid()))  # current process = "running"
        resp = client.post("/run", headers=auth_headers, json={})
        assert resp.status_code == 200
        assert resp.json["status"] == "already_running"


# ====================================================================
# /notebooks
# ====================================================================
class TestNotebooks:
    def test_registry_missing_returns_404(self, client, auth_headers):
        resp = client.get("/notebooks", headers=auth_headers)
        assert resp.status_code == 404

    def test_returns_registry_content(self, client, auth_headers, api_module):
        api_module.REGISTRY_PATH.write_text(json.dumps({"notebooks": [{"id": "a"}]}))
        resp = client.get("/notebooks", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json["notebooks"] == [{"id": "a"}]


class TestDiscoverNotebooks:
    def test_merges_registered_flag(self, client, auth_headers, api_module):
        api_module.REGISTRY_PATH.write_text(json.dumps({"notebooks": [{"id": "nb1"}]}))

        class FakeClient:
            def list_notebooks(self):
                return {"notebooks": [
                    {"id": "nb1", "title": "One"},
                    {"id": "nb2", "title": "Two"},
                ]}
            def close(self):
                pass

        with patch.dict("sys.modules", {"mcp_client": MagicMock(MCPClient=lambda: FakeClient())}):
            resp = client.get("/notebooks/discover", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json
        assert body["total"] == 2
        registered_map = {nb["id"]: nb["registered"] for nb in body["notebooks"]}
        assert registered_map["nb1"] is True
        assert registered_map["nb2"] is False

    def test_mcp_failure_returns_500(self, client, auth_headers):
        class BrokenClient:
            def list_notebooks(self):
                raise RuntimeError("mcp dead")
            def close(self):
                pass

        with patch.dict("sys.modules", {"mcp_client": MagicMock(MCPClient=lambda: BrokenClient())}):
            resp = client.get("/notebooks/discover", headers=auth_headers)
        assert resp.status_code == 500
        assert "mcp dead" in resp.json["error"].lower()


# ====================================================================
# /suggestions
# ====================================================================
class TestSuggestionsGet:
    def test_default_empty(self, client, auth_headers):
        resp = client.get("/suggestions", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json["total"] == 0
        assert resp.json["suggestions"] == []

    def test_returns_file_content(self, client, auth_headers, api_module):
        api_module.SUGGESTIONS_PATH.write_text(json.dumps({
            "generated_at": None, "total": 1, "pending": 1,
            "suggestions": [{"id": "s1", "status": "pending"}],
        }))
        resp = client.get("/suggestions", headers=auth_headers)
        assert resp.json["total"] == 1
        assert resp.json["suggestions"][0]["id"] == "s1"


class TestSuggestionsGenerate:
    def test_adds_empty_notebook_suggestion(self, client, auth_headers, api_module):
        api_module.REGISTRY_PATH.write_text(json.dumps({
            "notebooks": [{"id": "nb1", "title": "Empty", "sources": []}]
        }))
        resp = client.post("/suggestions/generate", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json["added"] >= 1
        data = json.loads(api_module.SUGGESTIONS_PATH.read_text())
        assert any(s["type"] == "add_source" for s in data["suggestions"])

    def test_skips_fresh_notebooks(self, client, auth_headers, api_module):
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        api_module.REGISTRY_PATH.write_text(json.dumps({
            "notebooks": [{
                "id": "nb1", "title": "Fresh", "sources": [{"s": 1}],
                "last_synced": now_iso, "config": {"refresh_interval_days": 7},
            }]
        }))
        resp = client.post("/suggestions/generate", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json["added"] == 0

    def test_flags_stale_notebooks(self, client, auth_headers, api_module):
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        api_module.REGISTRY_PATH.write_text(json.dumps({
            "notebooks": [{
                "id": "nb1", "title": "Stale", "sources": [{"s": 1}],
                "last_synced": old, "config": {"refresh_interval_days": 7},
            }]
        }))
        resp = client.post("/suggestions/generate", headers=auth_headers)
        assert resp.json["added"] == 1
        data = json.loads(api_module.SUGGESTIONS_PATH.read_text())
        assert any("stale" in s["id"] for s in data["suggestions"])

    def test_does_not_duplicate_existing(self, client, auth_headers, api_module):
        api_module.REGISTRY_PATH.write_text(json.dumps({
            "notebooks": [{"id": "nb1", "title": "Empty", "sources": []}]
        }))
        # Prime with an existing identical suggestion
        api_module.SUGGESTIONS_PATH.write_text(json.dumps({
            "suggestions": [{"id": "auto-empty-nb1", "status": "pending"}]
        }))
        resp = client.post("/suggestions/generate", headers=auth_headers)
        assert resp.json["added"] == 0  # nothing new


class TestSuggestionsUpdate:
    def test_rejects_invalid_status(self, client, auth_headers, api_module):
        api_module.SUGGESTIONS_PATH.write_text(json.dumps({
            "suggestions": [{"id": "s1", "status": "pending"}]
        }))
        resp = client.patch("/suggestions/s1", headers=auth_headers, json={"status": "bogus"})
        assert resp.status_code == 400

    def test_404_when_file_missing(self, client, auth_headers):
        resp = client.patch("/suggestions/s1", headers=auth_headers, json={"status": "approved"})
        assert resp.status_code == 404

    def test_404_when_id_not_present(self, client, auth_headers, api_module):
        api_module.SUGGESTIONS_PATH.write_text(json.dumps({
            "suggestions": [{"id": "s1", "status": "pending"}]
        }))
        resp = client.patch("/suggestions/does-not-exist", headers=auth_headers, json={"status": "approved"})
        assert resp.status_code == 404

    def test_approves_and_recomputes_pending_count(self, client, auth_headers, api_module):
        api_module.SUGGESTIONS_PATH.write_text(json.dumps({
            "suggestions": [
                {"id": "s1", "status": "pending"},
                {"id": "s2", "status": "pending"},
            ],
            "pending": 2,
        }))
        resp = client.patch("/suggestions/s1", headers=auth_headers, json={"status": "approved"})
        assert resp.status_code == 200
        data = json.loads(api_module.SUGGESTIONS_PATH.read_text())
        assert data["pending"] == 1
        s1 = next(s for s in data["suggestions"] if s["id"] == "s1")
        assert s1["status"] == "approved"


# ====================================================================
# Error handler
# ====================================================================
class TestErrorHandler:
    def test_unhandled_exception_returns_500(self, client, api_module):
        @api_module.app.route("/_test_boom", methods=["GET"])
        def _boom():
            raise RuntimeError("kaboom")

        # In Flask testing mode with PROPAGATE_EXCEPTIONS=True, the exception
        # bubbles. Turn that off so our handler runs.
        api_module.app.config["PROPAGATE_EXCEPTIONS"] = False
        resp = client.get("/_test_boom")
        assert resp.status_code == 500
        assert resp.json["error"] == "Internal server error"

    def test_http_exception_preserves_code(self, client, api_module):
        from werkzeug.exceptions import NotFound

        @api_module.app.route("/_test_nf", methods=["GET"])
        def _nf():
            raise NotFound(description="custom not found")

        api_module.app.config["PROPAGATE_EXCEPTIONS"] = False
        resp = client.get("/_test_nf")
        assert resp.status_code == 404
        assert resp.json["error"] == "custom not found"


# ====================================================================
# Response hardening headers
# ====================================================================
class TestResponseHardening:
    def test_security_headers_set(self, client):
        resp = client.get("/status")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "SAMEORIGIN"
        assert "Content-Security-Policy" in resp.headers

    def test_correlation_id_echoed(self, client):
        resp = client.get("/status", headers={"X-Correlation-ID": "abc-123"})
        assert resp.headers["X-Correlation-ID"] == "abc-123"

    def test_correlation_id_generated_when_missing(self, client):
        resp = client.get("/status")
        assert resp.headers["X-Correlation-ID"]  # non-empty UUID

    def test_hsts_toggleable(self, client, api_module):
        api_module.app.config["ENABLE_HSTS"] = False
        resp = client.get("/status")
        assert "Strict-Transport-Security" not in resp.headers


# ====================================================================
# Connectivity helpers
# ====================================================================
class TestYoutubeConnectivity:
    def test_missing_key_returns_degraded(self, api_module, monkeypatch):
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
        with api_module.app.app_context():
            result = api_module._youtube_connectivity()
        assert result["status"] == "degraded"

    def test_http_200_is_ok(self, api_module, monkeypatch):
        monkeypatch.setenv("YOUTUBE_API_KEY", "fake")
        mock_resp = MagicMock(status_code=200)
        with patch.object(api_module.requests, "get", return_value=mock_resp):
            with api_module.app.app_context():
                result = api_module._youtube_connectivity()
        assert result["status"] == "ok"

    def test_http_403_is_rate_limited(self, api_module, monkeypatch):
        monkeypatch.setenv("YOUTUBE_API_KEY", "fake")
        mock_resp = MagicMock(status_code=403)
        with patch.object(api_module.requests, "get", return_value=mock_resp):
            with api_module.app.app_context():
                result = api_module._youtube_connectivity()
        assert result["status"] == "rate_limited"

    def test_request_exception_is_error(self, api_module, monkeypatch):
        monkeypatch.setenv("YOUTUBE_API_KEY", "fake")
        with patch.object(api_module.requests, "get", side_effect=api_module.requests.RequestException("timeout")):
            with api_module.app.app_context():
                result = api_module._youtube_connectivity()
        assert result["status"] == "error"
        assert "timeout" in result["detail"]


class TestLastBatchSyncStatus:
    def test_reads_state_file_when_present(self, api_module):
        api_module.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        api_module.BATCH_SYNC_STATE_PATH.write_text(json.dumps({
            "status": "ok", "stage": "done", "updated_at": "2026-04-22T00:00:00Z",
            "summary": {"added": 3},
        }))
        with api_module.app.app_context():
            result = api_module._last_batch_sync_status()
        assert result["status"] == "ok"
        assert result["summary"]["added"] == 3

    def test_falls_back_to_run_log(self, api_module):
        api_module.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        (api_module.LOGS_DIR / "run_2026-04-22.json").write_text(json.dumps({
            "run_at": "2026-04-22T00:00:00Z", "added": 5, "failed": 1,
        }))
        with api_module.app.app_context():
            result = api_module._last_batch_sync_status()
        assert result["summary"]["added"] == 5

    def test_no_logs_dir_returns_unknown(self, api_module):
        # LOGS_DIR doesn't exist — function should handle gracefully
        with api_module.app.app_context():
            result = api_module._last_batch_sync_status()
        assert result["status"] == "unknown"
