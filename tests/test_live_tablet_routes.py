"""Routes for the dugout tablet: /api/live/{tablet,status,arm,disarm}, and the
scoreboard's live play-by-play now read from the tablet worker's state."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import live_tablet  # noqa: E402
import sync_daemon as sd  # noqa: E402

TOKEN = "t3st-write-token"
ORIGIN = "https://dugout.joelycannoli.com"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "DATA_DIR", tmp_path)
    monkeypatch.delenv("DUGOUT_APP_PASSWORD", raising=False)
    monkeypatch.delenv("DUGOUT_WRITE_TOKEN", raising=False)
    with sd._MUTATE_RATE_LOCK:
        sd._MUTATE_RATE_BUCKETS.clear()
    sd.app.config["TESTING"] = True
    yield sd.app.test_client()
    with sd._MUTATE_RATE_LOCK:
        sd._MUTATE_RATE_BUCKETS.clear()


def _write_state(data_dir, fetched_at, parsed_overrides=None):
    parsed = {
        "home_id": "team-opp", "away_id": "team-sharks", "inning": 2, "half": "top",
        "outs": 1, "balls": 2, "strikes": 1, "bases": {"3": "p2"},
        "score": {"team-opp": 4, "team-sharks": 3}, "batting_team": "team-sharks",
        "batter_id": "p1", "on_deck_id": "p3", "pitcher_id": "o9", "last_play": "Single",
        "plate_appearances": [], "spray": [],
    }
    parsed.update(parsed_overrides or {})
    doc = {
        "meta": {"event_id": "ev1", "date": "2026-10-11", "opponent_name": "Rivals",
                 "sharks_team_id": "team-sharks"},
        "players": {"p1": {"name": "Shark One", "number": "1", "team_id": "team-sharks"},
                    "p3": {"name": "Shark Three", "number": "3", "team_id": "team-sharks"}},
        "parsed": parsed,
        "fetched_at": live_tablet._iso(fetched_at),
    }
    live_tablet.write_json_atomic(live_tablet.live_dir(data_dir) / "state.json", doc)


# -- read endpoints ------------------------------------------------------------

def test_tablet_idle_when_nothing_on_disk(client):
    r = client.get("/api/live/tablet")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "idle" and body["game"] is None
    assert r.headers["Cache-Control"] == "no-store"


def test_status_is_exempt_from_team_password_but_tablet_is_not(client, monkeypatch):
    monkeypatch.setenv("DUGOUT_APP_PASSWORD", "team-pass")
    assert client.get("/api/live/tablet").status_code == 401
    r = client.get("/api/live/status")
    assert r.status_code == 200
    assert set(r.get_json()) == {"armed", "armed_until", "last_poll_at", "last_poll_age_s",
                                 "last_http", "events_seen", "phase", "error"}


def test_status_carries_no_names_or_ids(client, tmp_path):
    now = datetime.now(timezone.utc)
    live_tablet.arm(tmp_path, now)
    _write_state(tmp_path, now)
    live_tablet.write_json_atomic(live_tablet.live_dir(tmp_path) / "status.json",
                                  {"phase": "polling", "last_http": 200, "events_seen": 12,
                                   "last_poll_at": live_tablet._iso(now)})
    text = client.get("/api/live/status").get_data(as_text=True)
    for leak in ("Shark", "Rivals", "team-sharks", "ev1", "p1"):
        assert leak not in text


# -- write endpoints -------------------------------------------------------------

def test_arm_needs_origin(client):
    assert client.post("/api/live/arm", json={"hours": 2}).status_code == 403


def test_arm_needs_write_token_when_configured(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DUGOUT_WRITE_TOKEN", TOKEN)
    r = client.post("/api/live/arm", json={"hours": 2}, headers={"Origin": ORIGIN})
    assert r.status_code == 401
    assert not (live_tablet.live_dir(tmp_path) / "armed.json").exists()
    r = client.post("/api/live/arm", json={"hours": 2},
                    headers={"Origin": ORIGIN, "X-Dugout-Token": TOKEN})
    assert r.status_code == 200 and r.get_json()["armed"] is True


def test_arm_clamps_hours_and_disarm_clears(client, tmp_path):
    r = client.post("/api/live/arm", json={"hours": 99}, headers={"Origin": ORIGIN})
    until = datetime.fromisoformat(r.get_json()["armed_until"])
    assert until - datetime.now(timezone.utc) <= timedelta(hours=live_tablet.ARM_MAX_HOURS)
    assert client.get("/api/live/status").get_json()["armed"] is True

    r = client.post("/api/live/disarm", json={}, headers={"Origin": ORIGIN})
    assert r.status_code == 200 and r.get_json() == {"armed": False}
    assert client.get("/api/live/status").get_json()["armed"] is False


@pytest.mark.parametrize("hours", ["lots", None, [], "nan"])
def test_arm_rejects_non_numeric_hours(client, hours):
    r = client.post("/api/live/arm", json={"hours": hours}, headers={"Origin": ORIGIN})
    assert r.status_code == 400


def test_arm_is_rate_limited(client):
    codes = [client.post("/api/live/arm", json={}, headers={"Origin": ORIGIN}).status_code
             for _ in range(sd.MUTATE_RATE_MAX + 1)]
    assert codes[-1] == 429


# -- scoreboard live play-by-play ----------------------------------------------------

def test_scoreboard_live_play_from_fresh_worker_state(client, tmp_path):
    now = datetime.now(timezone.utc)
    live_tablet.arm(tmp_path, now - timedelta(minutes=5))
    _write_state(tmp_path, now)
    play = sd._live_play_from_worker("ignored")
    assert play["outs"] == 1 and play["balls"] == 2 and play["strikes"] == 1
    assert play["runners"] == {"first": False, "second": False, "third": True}
    assert play["current_batter"] == {"name": "Shark One", "number": "1"}
    assert play["next_batter"] == {"name": "Shark Three", "number": "3"}


def test_scoreboard_live_play_none_when_stale_or_unarmed(client, tmp_path):
    now = datetime.now(timezone.utc)
    _write_state(tmp_path, now)
    assert sd._live_play_from_worker("x") is None          # not armed
    live_tablet.arm(tmp_path, now - timedelta(minutes=10))
    _write_state(tmp_path, now - timedelta(minutes=5))
    assert sd._live_play_from_worker("x") is None          # stale
