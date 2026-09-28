"""Regression tests for two live-scoring defects found in a hardening audit:

1. `_fetch_gc_live_events` overwrote `outs`/`runners` with every event it
   walked past, so when the stream had no `on_deck`/`next_batter` field (the
   common case) the loop walked all the way to the oldest event and returned
   *that* event's outs/runners as "current".
2. `/api/scoreboard` unconditionally overwrote a live game's score with
   whatever local `games/*.json` snapshot matched by date/gc_game_id — those
   files are CSV-import snapshots (final scores), so a live game could show a
   stale or wrong score as current.
"""
from unittest.mock import MagicMock

import sync_daemon as sd


# ---------------------------------------------------------------------------
# 1. _fetch_gc_live_events must not overwrite outs/runners with older events
# ---------------------------------------------------------------------------

def test_live_events_uses_most_recent_outs_and_runners(monkeypatch):
    events = [
        {
            "type": "at_bat",
            "data": {
                "outs": 0,
                "runners": [{"base": "1"}],
                "description": "Old at-bat, 0 outs, runner on first",
            },
        },
        {
            "type": "at_bat",
            "data": {
                "outs": 2,
                "runners": [{"base": "3"}],
                "description": "Current at-bat, 2 outs, runner on third",
                "batter": {"name": "Jane Doe", "number": "7"},
            },
        },
    ]
    resp = MagicMock(status_code=200)
    resp.json.return_value = events
    monkeypatch.setattr(sd.requests, "get", lambda *a, **k: resp)

    result = sd._fetch_gc_live_events("game-123")

    assert result["outs"] == 2
    assert result["runners"] == {"first": False, "second": False, "third": True}
    assert result["last_play"] == "Current at-bat, 2 outs, runner on third"


def test_live_events_single_event_still_works(monkeypatch):
    events = [
        {
            "type": "at_bat",
            "data": {
                "outs": 1,
                "runners": [{"base": "2"}],
                "description": "Solo event",
                "batter": {"name": "A", "number": "1"},
            },
        },
    ]
    resp = MagicMock(status_code=200)
    resp.json.return_value = events
    monkeypatch.setattr(sd.requests, "get", lambda *a, **k: resp)

    result = sd._fetch_gc_live_events("game-1")

    assert result["outs"] == 1
    assert result["runners"] == {"first": False, "second": True, "third": False}


# ---------------------------------------------------------------------------
# 2. /api/scoreboard must not let a local snapshot overwrite a live score
# ---------------------------------------------------------------------------

def _fake_live_game():
    return {
        "id": "game-live",
        "game_status": "in_progress",
        "start_ts": "2026-09-28T20:00:00.000Z",
        "opponent_team": {"name": "Riptide"},
        "home_away": "home",
        "score": {"team": 5, "opponent_team": 3},
        "current_inning": 4,
        "inning_half": "top",
    }


def test_local_game_file_does_not_overwrite_live_score(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
    monkeypatch.setattr(sd, "_fetch_gc_games", lambda *a, **k: [_fake_live_game()])
    monkeypatch.setattr(sd, "_cached_opponent_scouting", lambda *a, **k: {"has_data": False})
    monkeypatch.setattr(sd, "_cached_live_events", lambda *a, **k: None)

    games_dir = tmp_path / "games"
    games_dir.mkdir()
    (games_dir / "stale.json").write_text(
        '{"gc_game_id": "game-live", "score": {"sharks": 11, "opponent": 2}, '
        '"sharks_batting": [], "opponent_batting": []}'
    )

    with sd.app.test_client() as client:
        resp = client.get("/api/scoreboard")
        body = resp.get_json()

    assert body["status"] == "live"
    # Live score comes from the GC API (5-3), not the stale local file (11-2).
    assert body["sharks_score"] == 5
    assert body["opponent_score"] == 3


def test_local_game_file_still_enriches_final_score(tmp_path, monkeypatch):
    final_game = dict(_fake_live_game())
    final_game["game_status"] = "completed"
    monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
    monkeypatch.setattr(sd, "_fetch_gc_games", lambda *a, **k: [final_game])
    monkeypatch.setattr(sd, "_cached_opponent_scouting", lambda *a, **k: {"has_data": False})
    monkeypatch.setattr(sd, "_cached_live_events", lambda *a, **k: None)

    games_dir = tmp_path / "games"
    games_dir.mkdir()
    (games_dir / "final.json").write_text(
        '{"gc_game_id": "game-live", "score": {"sharks": 11, "opponent": 2}, '
        '"sharks_batting": [], "opponent_batting": []}'
    )

    with sd.app.test_client() as client:
        resp = client.get("/api/scoreboard")
        body = resp.get_json()

    assert body["status"] == "final"
    assert body["sharks_score"] == 11
    assert body["opponent_score"] == 2
