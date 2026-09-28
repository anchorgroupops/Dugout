"""Regression tests for tools/gc_web_mobile_scraper.py hardening:
  - _fetch_public_games must retry transient HTTP failures (429/5xx/timeout)
    with backoff instead of raising on the first hiccup.
  - Box-score JSON must be written atomically so a crash mid-write can't
    leave a half-written game file for the API/dashboard to read.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import gc_web_mobile_scraper as gwm


class _FakeResp:
    def __init__(self, status_code, body=None, headers=None):
        self.status_code = status_code
        self._body = body if body is not None else []
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._body


def test_fetch_public_games_retries_429_then_succeeds(monkeypatch):
    calls = []

    def fake_get(url, timeout=30):
        calls.append(url)
        if len(calls) == 1:
            return _FakeResp(429, headers={"Retry-After": "0"})
        return _FakeResp(200, body=[{"id": "1"}])

    monkeypatch.setattr(gwm.requests, "get", fake_get)
    monkeypatch.setattr(gwm.time, "sleep", lambda s: None)
    result = gwm._fetch_public_games("team")
    assert len(calls) == 2
    assert result == [{"id": "1"}]


def test_fetch_public_games_retries_timeout_then_raises_after_exhaustion(monkeypatch):
    calls = []

    def fake_get(url, timeout=30):
        calls.append(url)
        raise requests.exceptions.Timeout("slow")

    monkeypatch.setattr(gwm.requests, "get", fake_get)
    monkeypatch.setattr(gwm.time, "sleep", lambda s: None)
    with pytest.raises(requests.exceptions.Timeout):
        gwm._fetch_public_games("team")
    assert len(calls) == 3


def test_fetch_public_games_does_not_retry_client_error(monkeypatch):
    calls = []

    def fake_get(url, timeout=30):
        calls.append(url)
        return _FakeResp(404)

    monkeypatch.setattr(gwm.requests, "get", fake_get)
    monkeypatch.setattr(gwm.time, "sleep", lambda s: None)
    with pytest.raises(requests.exceptions.HTTPError):
        gwm._fetch_public_games("team")
    assert len(calls) == 1


def test_atomic_write_json_leaves_no_partial_file_on_crash(tmp_path, monkeypatch):
    target = tmp_path / "game.json"

    def boom_dump(*a, **k):
        raise RuntimeError("simulated crash mid-write")

    monkeypatch.setattr(gwm.json, "dump", boom_dump)
    with pytest.raises(RuntimeError):
        gwm._atomic_write_json(target, {"a": 1})

    assert not target.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_json_writes_full_valid_json(tmp_path):
    target = tmp_path / "game.json"
    gwm._atomic_write_json(target, {"a": 1, "b": [1, 2, 3]})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1, "b": [1, 2, 3]}


def test_fetch_public_games_http_date_retry_after_does_not_crash(monkeypatch):
    calls, sleeps = [], []

    def fake_get(url, timeout=30):
        calls.append(url)
        if len(calls) == 1:
            return _FakeResp(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
        return _FakeResp(200, body=[{"id": "1"}])

    monkeypatch.setattr(gwm.requests, "get", fake_get)
    monkeypatch.setattr(gwm.time, "sleep", sleeps.append)
    assert gwm._fetch_public_games("team") == [{"id": "1"}]
    assert sleeps == [1]


def test_fetch_public_games_retry_after_is_capped(monkeypatch):
    calls, sleeps = [], []

    def fake_get(url, timeout=30):
        calls.append(url)
        if len(calls) == 1:
            return _FakeResp(429, headers={"Retry-After": "86400"})
        return _FakeResp(200, body=[])

    monkeypatch.setattr(gwm.requests, "get", fake_get)
    monkeypatch.setattr(gwm.time, "sleep", sleeps.append)
    gwm._fetch_public_games("team")
    assert max(sleeps) <= 60.0
