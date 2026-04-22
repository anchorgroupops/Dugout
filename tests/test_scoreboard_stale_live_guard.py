"""Guard against GC's public API leaving old games stuck at game_status=in_progress.

Observed regression: 2026-04-14 game vs NWVLL Stihlers was still reported as
game_status="in_progress" by GC's API at 2026-04-22 (8 days later).  The
scoreboard greedily picked it, pinning status="live" with auto-refresh firing
every 15s against a dead game.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import sync_daemon

ET = ZoneInfo("America/New_York")


def test_stale_live_game_is_rejected():
    now = datetime(2026, 4, 22, 17, 0, tzinfo=ET)
    today = now.date().isoformat()

    stale = {
        "id": "stale-live",
        "game_status": "in_progress",
        "start_ts": "2026-04-14T22:30:00+00:00",  # 8 days ago
    }

    out = sync_daemon._pick_scoreboard_target([stale], now, today)
    assert out is None, "stale-live game must not pin the scoreboard"


def test_fresh_live_game_is_accepted():
    # now = 20:00 ET = 00:00 UTC next day
    now = datetime(2026, 4, 22, 20, 0, tzinfo=ET)
    today = now.date().isoformat()

    # start = 2026-04-22 19:30 ET = 2026-04-22 23:30 UTC → 30 min before now
    fresh = {
        "id": "fresh-live",
        "game_status": "in_progress",
        "start_ts": "2026-04-22T23:30:00+00:00",
    }

    out = sync_daemon._pick_scoreboard_target([fresh], now, today)
    assert out is fresh


def test_falls_through_to_today_game_when_live_is_stale():
    now = datetime(2026, 4, 22, 12, 0, tzinfo=ET)
    today = now.date().isoformat()

    stale = {
        "id": "stale-live",
        "game_status": "in_progress",
        "start_ts": "2026-04-14T22:30:00+00:00",
    }
    today_game = {
        "id": "today",
        "game_status": "scheduled",
        "start_ts": "2026-04-22T22:30:00+00:00",
    }

    out = sync_daemon._pick_scoreboard_target([stale, today_game], now, today)
    assert out is today_game


def test_returns_none_when_nothing_relevant():
    now = datetime(2026, 4, 22, 12, 0, tzinfo=ET)
    today = now.date().isoformat()

    old_completed = {
        "id": "old",
        "game_status": "completed",
        "start_ts": "2026-04-10T22:30:00+00:00",
    }

    assert sync_daemon._pick_scoreboard_target([old_completed], now, today) is None


def test_handles_unparseable_start_ts_gracefully():
    now = datetime(2026, 4, 22, 12, 0, tzinfo=ET)
    today = now.date().isoformat()

    weird_live = {
        "id": "weird",
        "game_status": "in_progress",
        "start_ts": "not-a-timestamp",
    }

    # Without a parseable start, we can't apply the freshness guard — fall back
    # to the original behaviour and accept it as live rather than silently drop.
    out = sync_daemon._pick_scoreboard_target([weird_live], now, today)
    assert out is weird_live
