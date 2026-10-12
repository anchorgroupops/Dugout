"""gc_live_worker with a fake GC: arm gating, polling, backfill, fail-closed."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import gc_live_worker as w  # noqa: E402
import live_tablet  # noqa: E402

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "gc_game_stream_sample.json").read_text())
NOW = datetime(2026, 10, 11, 23, 0, tzinfo=timezone.utc)
SHARKS = "team-sharks"


def _schedule(start):
    return [{"event": {"id": "ev-today", "event_type": "game", "status": "scheduled",
                       "start": {"datetime": start.isoformat().replace("+00:00", "Z")}},
             "pregame_data": {"opponent_name": "Rivals", "opponent_id": "team-opp",
                              "home_away": "away"}}]


def _plays():
    return {"team_players": FIXTURE["players"]}


class FakeGC:
    """Stands in for GCClient; answers by path, or raises a scripted status."""

    def __init__(self, routes, fail_events_with=None):
        self.team_uuid = SHARKS
        self.routes = routes
        self.fail_events_with = fail_events_with
        self.calls = []
        self.refreshes = 0

    def refresh(self):
        self.refreshes += 1

    def get(self, path):
        self.calls.append(path)
        if "/game-streams/" in path and self.fail_events_with:
            raise w.GCHttpError(self.fail_events_with)
        for prefix, value in self.routes.items():
            if path.startswith(prefix):
                return value
        raise w.GCHttpError(404)


def _routes(summaries=()):
    return {
        f"/teams/{SHARKS}/schedule": _schedule(NOW - timedelta(minutes=30)),
        f"/teams/{SHARKS}/game-summaries": list(summaries),
        "/events/ev-today/best-game-stream-id": {"game_stream_id": "gs-today"},
        "/game-stream-processing/": _plays(),
        "/game-streams/": FIXTURE["events"],
    }


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _worker(tmp_path, polls_before_disarm=2):
    """A worker whose sleep() disarms after a few polls so loops terminate."""
    clock = Clock(NOW)
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        clock.t += timedelta(seconds=s)
        if sleeps.count(w.POLL_S) >= polls_before_disarm:
            live_tablet.disarm(tmp_path)

    worker = w.LiveWorker(tmp_path, clock=clock, sleep=sleep)
    return worker, sleeps


def _status(tmp_path):
    return json.loads((live_tablet.live_dir(tmp_path) / "status.json").read_text())


def test_pick_game_window():
    sched = _schedule(NOW - timedelta(hours=1))
    assert w.pick_game(sched, NOW)["event"]["id"] == "ev-today"
    assert w.pick_game(_schedule(NOW + timedelta(hours=3)), NOW) is None
    assert w.pick_game(_schedule(NOW - timedelta(hours=5)), NOW) is None
    sched[0]["event"]["status"] = "canceled"
    assert w.pick_game(sched, NOW) is None


def test_tick_does_nothing_unarmed(tmp_path):
    called = []
    worker = w.LiveWorker(tmp_path, session_factory=lambda: called.append(1), clock=Clock(NOW))
    worker.tick()
    assert called == []


def test_polls_parses_and_writes_state(tmp_path):
    live_tablet.arm(tmp_path, NOW)
    worker, sleeps = _worker(tmp_path)
    gc = FakeGC(_routes())
    worker._poll_game(gc)

    state = json.loads((live_tablet.live_dir(tmp_path) / "state.json").read_text())
    assert state["meta"]["event_id"] == "ev-today"
    assert state["meta"]["home_id"] == "team-opp" and state["meta"]["away_id"] == SHARKS
    assert state["parsed"]["plate_appearances"], "fixture should parse into PAs"
    assert (live_tablet.live_dir(tmp_path) / "games" / "ev-today.json").exists()
    st = _status(tmp_path)
    assert st["phase"] == "disarmed" and st["last_http"] == 200
    assert st["events_seen"] == len(FIXTURE["events"])
    assert sleeps.count(w.POLL_S) == 2

    # The payload the tablet reads is live and names the opponent.
    live_tablet.arm(tmp_path, worker.clock())
    payload = live_tablet.build_tablet_payload(tmp_path, worker.clock())
    assert payload["game"]["opponent"] == "Rivals"


@pytest.mark.parametrize("code", [403, 429])
def test_forbidden_or_rate_limit_stops_immediately(tmp_path, code):
    live_tablet.arm(tmp_path, NOW)
    worker, _ = _worker(tmp_path, polls_before_disarm=99)
    gc = FakeGC(_routes(), fail_events_with=code)
    worker._poll_game(gc)
    st = _status(tmp_path)
    assert st["phase"] == "stopped" and st["last_http"] == code
    assert sum("/game-streams/" in c for c in gc.calls) == 1
    assert gc.refreshes == 0


def test_401_refreshes_headers_once_then_stops(tmp_path):
    live_tablet.arm(tmp_path, NOW)
    worker, _ = _worker(tmp_path, polls_before_disarm=99)
    gc = FakeGC(_routes(), fail_events_with=401)
    worker._poll_game(gc)
    assert _status(tmp_path)["phase"] == "stopped"
    assert gc.refreshes == 1
    assert sum("/game-streams/" in c for c in gc.calls) == 2


def test_401_recovers_after_refresh(tmp_path):
    live_tablet.arm(tmp_path, NOW)
    worker, _ = _worker(tmp_path)
    gc = FakeGC(_routes(), fail_events_with=401)
    real_refresh = gc.refresh

    def refresh():
        real_refresh()
        gc.fail_events_with = None
    gc.refresh = refresh
    worker._poll_game(gc)
    st = _status(tmp_path)
    assert st["phase"] == "disarmed" and st["last_http"] == 200 and gc.refreshes == 1


def test_other_errors_stop_after_max_fails(tmp_path):
    live_tablet.arm(tmp_path, NOW)
    worker, _ = _worker(tmp_path, polls_before_disarm=99)
    gc = FakeGC(_routes(), fail_events_with=500)
    worker._poll_game(gc)
    assert _status(tmp_path)["phase"] == "stopped"
    assert sum("/game-streams/" in c for c in gc.calls) == w.MAX_FAILS


def test_failed_session_is_not_retried_until_rearmed(tmp_path):
    live_tablet.arm(tmp_path, NOW)
    starts = []

    def factory():
        starts.append(1)
        raise RuntimeError("login failed")

    worker = w.LiveWorker(tmp_path, session_factory=factory, clock=Clock(NOW))
    worker.tick()
    worker.tick()
    assert len(starts) == 1
    assert _status(tmp_path)["phase"] == "stopped"

    live_tablet.arm(tmp_path, NOW + timedelta(minutes=1))
    worker.tick()
    assert len(starts) == 2


def test_backfill_writes_completed_games_once(tmp_path):
    live_tablet.arm(tmp_path, NOW)
    summaries = [
        {"event_id": "ev-old", "game_status": "completed", "home_away": "away",
         "game_stream": {"id": "gs-old", "opponent_id": "team-opp"}},
        {"event_id": "ev-today", "game_status": "in_progress",
         "game_stream": {"id": "gs-today"}},
    ]
    worker, sleeps = _worker(tmp_path)
    gc = FakeGC(_routes(summaries))
    worker._backfill(gc)
    games = live_tablet.live_dir(tmp_path) / "games"
    assert sorted(p.name for p in games.glob("*.json")) == ["ev-old.json"]
    assert all(s >= w.BACKFILL_GAP_S for s in sleeps)

    gc.calls.clear()
    worker._backfill(gc)
    assert not any("/game-streams/" in c for c in gc.calls)


def test_status_never_holds_headers_or_names(tmp_path):
    live_tablet.arm(tmp_path, NOW)
    worker, _ = _worker(tmp_path)
    worker._poll_game(FakeGC(_routes()))
    raw = (live_tablet.live_dir(tmp_path) / "status.json").read_text()
    assert set(json.loads(raw)) <= {"phase", "error", "last_http", "events_seen", "last_poll_at"}
    assert "Shark" not in raw and "Rival" not in raw
