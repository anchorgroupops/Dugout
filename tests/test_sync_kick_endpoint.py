"""Tests for POST /api/sync/kick — the manual sync-cycle trigger."""
from __future__ import annotations

import time

import pytest

import sync_daemon


TOKEN = "test-kick-token-123"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DEPLOY_WEBHOOK_TOKEN", TOKEN)
    # Reset the kick state between tests.
    sync_daemon._KICK_STATUS.update(
        {"status": "idle", "last_started": "", "last_completed": "", "last_success": None, "error": ""}
    )
    sync_daemon.app.config["TESTING"] = True
    return sync_daemon.app.test_client()


def test_kick_rejects_without_token(client):
    r = client.post("/api/sync/kick")
    assert r.status_code == 401


def test_kick_rejects_with_bad_token(client):
    r = client.post("/api/sync/kick", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_kick_503_when_token_unconfigured(monkeypatch):
    monkeypatch.delenv("DEPLOY_WEBHOOK_TOKEN", raising=False)
    c = sync_daemon.app.test_client()
    r = c.post("/api/sync/kick", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503


def test_kick_starts_and_marks_status(client, monkeypatch):
    calls = []

    def fake_cycle():
        calls.append(1)
        return True

    monkeypatch.setattr(sync_daemon, "run_sync_cycle", fake_cycle)

    r = client.post("/api/sync/kick", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 202
    body = r.get_json()
    assert body["status"] == "started"
    assert body["since"]

    # Give the background thread a moment to run
    for _ in range(50):
        if calls:
            break
        time.sleep(0.02)

    assert calls == [1]

    # Status should settle back to idle with last_success=True
    for _ in range(50):
        if sync_daemon._KICK_STATUS["status"] == "idle" and sync_daemon._KICK_STATUS["last_completed"]:
            break
        time.sleep(0.02)

    assert sync_daemon._KICK_STATUS["status"] == "idle"
    assert sync_daemon._KICK_STATUS["last_success"] is True
    assert sync_daemon._KICK_STATUS["error"] == ""


def test_kick_second_request_returns_409_while_running(client, monkeypatch):
    # Simulate "already running" by pre-setting the lock-protected state
    with sync_daemon._KICK_LOCK:
        sync_daemon._KICK_STATUS["status"] = "running"
        sync_daemon._KICK_STATUS["last_started"] = "2026-04-23T00:00:00-04:00"

    r = client.post("/api/sync/kick", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 409
    body = r.get_json()
    assert body["status"] == "already_running"

    # Cleanup
    with sync_daemon._KICK_LOCK:
        sync_daemon._KICK_STATUS["status"] = "idle"


def test_kick_status_endpoint_requires_token(client):
    r = client.get("/api/sync/kick/status")
    assert r.status_code == 401

    r = client.get("/api/sync/kick/status", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    body = r.get_json()
    assert "status" in body
    assert "last_started" in body


def test_kick_captures_exception_in_status(client, monkeypatch):
    def boom():
        raise RuntimeError("oh no")

    monkeypatch.setattr(sync_daemon, "run_sync_cycle", boom)

    r = client.post("/api/sync/kick", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 202

    # Wait for thread to finish
    for _ in range(50):
        if sync_daemon._KICK_STATUS["status"] == "idle" and sync_daemon._KICK_STATUS["last_completed"]:
            break
        time.sleep(0.02)

    assert sync_daemon._KICK_STATUS["status"] == "idle"
    assert sync_daemon._KICK_STATUS["last_success"] is False
    assert "oh no" in sync_daemon._KICK_STATUS["error"]
