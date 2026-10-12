"""Regression tests for two live-scoring defects found in a hardening audit:

1. (Retired) `_fetch_gc_live_events` called an unauthenticated GC endpoint
   that never answered; live play-by-play now comes from the dugout-tablet
   worker and is covered by tests/test_live_tablet_routes.py.
2. `/api/scoreboard` unconditionally overwrote a live game's score with
   whatever local `games/*.json` snapshot matched by date/gc_game_id — those
   files are CSV-import snapshots (final scores), so a live game could show a
   stale or wrong score as current.
"""
from datetime import datetime, timedelta, timezone

import sync_daemon as sd


# ---------------------------------------------------------------------------
# 2. /api/scoreboard must not let a local snapshot overwrite a live score
# ---------------------------------------------------------------------------

def _fake_live_game():
    return {
        "id": "game-live",
        "game_status": "in_progress",
        # 30 minutes ago, so the game is "live" whenever the test runs
        # (a pinned date went stale the next evening).
        "start_ts": (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),
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
