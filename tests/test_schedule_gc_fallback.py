"""/api/schedule must fall back to GameChanger's public games list when
schedule_manual.json is absent (the Pi has never had one), so Scout,
Practice and Lineups agree with /api/scoreboard about the next game."""
from datetime import datetime, timedelta

import pytest

import sync_daemon as sd


_FAKE_GAMES = [
    {
        "id": "future-1",
        "opponent_team": {"name": "Riptide Rebels"},
        "start_ts": (datetime.now(sd.ET) + timedelta(days=1)).replace(hour=18, minute=30).astimezone(
            __import__("datetime").timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "home_away": "away",
    },
    {
        "id": "past-1",
        "opponent_team": {"name": "Peppers"},
        "start_ts": (datetime.now(sd.ET) - timedelta(days=10)).astimezone(
            __import__("datetime").timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "home_away": "home",
    },
    {"id": "junk", "opponent_team": {}, "start_ts": "not-a-date"},
]


@pytest.fixture
def no_manual_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
    monkeypatch.setattr(sd, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(sd, "_fetch_gc_games", lambda *a, **k: _FAKE_GAMES)


def test_schedule_falls_back_to_gc_when_manual_file_missing(no_manual_schedule):
    with sd.app.test_client() as client:
        body = client.get("/api/schedule").get_json()
    assert [g["opponent"] for g in body["upcoming"]] == ["Riptide Rebels"]
    assert body["upcoming"][0]["is_game"] is True
    assert body["upcoming"][0]["source"] == "gamechanger"
    assert body["upcoming"][0]["home_away"] == "away"
    assert [g["opponent"] for g in body["past"]] == ["Peppers"]


def test_schedule_prefers_manual_file_when_it_has_games(no_manual_schedule, tmp_path):
    (tmp_path / "schedule_manual.json").write_text(
        '{"upcoming": [{"date": "2099-01-01", "opponent": "Manual FC", "is_game": true}], "past": []}'
    )
    with sd.app.test_client() as client:
        body = client.get("/api/schedule").get_json()
    assert [g["opponent"] for g in body["upcoming"]] == ["Manual FC"]


def test_schedule_from_gc_games_shapes_time_and_skips_junk():
    out = sd._schedule_from_gc_games(_FAKE_GAMES, datetime.now(sd.ET).strftime("%Y-%m-%d"))
    assert len(out["upcoming"]) + len(out["past"]) == 2
    assert out["upcoming"][0]["time"] == "6:30 PM"


def test_fetch_gc_games_returns_empty_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(sd.requests, "get", boom)
    assert sd._fetch_gc_games("team") == []
