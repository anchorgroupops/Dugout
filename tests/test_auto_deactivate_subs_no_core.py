"""auto_deactivate_subs must no-op when no core players are configured.

Observed regression: on 2026-04-22 every player in production was flagged as
SUB OUT because team.json (CSV-export source) had no `core=True` players and
no roster_manifest.json existed.  _is_core_player() then returned False for
everyone, and auto_deactivate_subs deactivated the entire roster after every
game.
"""
from __future__ import annotations

import json

import sync_daemon


def _seed(sharks_dir, avail, past_games, manifest=None):
    sharks_dir.mkdir(parents=True, exist_ok=True)
    (sharks_dir / "schedule_manual.json").write_text(
        json.dumps({"past": past_games, "upcoming": []})
    )
    (sharks_dir / "availability.json").write_text(json.dumps(avail))
    if manifest is not None:
        (sharks_dir / "roster_manifest.json").write_text(json.dumps(manifest))


def test_noop_when_no_roster_manifest(tmp_path, monkeypatch):
    sharks = tmp_path / "sharks"
    _seed(
        sharks,
        avail={"Player A": True, "Player B": True},
        past_games=[{"date": "2000-01-01", "is_game": True}],  # way in the past
    )
    monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks)
    monkeypatch.setattr(sync_daemon, "_ROSTER_MANIFEST_CACHE", None)

    sync_daemon.auto_deactivate_subs()

    after = json.loads((sharks / "availability.json").read_text())
    assert after == {"Player A": True, "Player B": True}


def test_noop_when_roster_manifest_has_empty_core_players(tmp_path, monkeypatch):
    sharks = tmp_path / "sharks"
    _seed(
        sharks,
        avail={"Player A": True, "Player B": True},
        past_games=[{"date": "2000-01-01", "is_game": True}],
        manifest={"core_players": []},
    )
    monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks)
    monkeypatch.setattr(sync_daemon, "_ROSTER_MANIFEST_CACHE", None)

    sync_daemon.auto_deactivate_subs()

    after = json.loads((sharks / "availability.json").read_text())
    assert after == {"Player A": True, "Player B": True}


def test_deactivates_non_core_when_manifest_present(tmp_path, monkeypatch):
    sharks = tmp_path / "sharks"
    _seed(
        sharks,
        avail={"Core Player": True, "Sub Player": True},
        past_games=[{"date": "2000-01-01", "is_game": True}],
        manifest={"core_players": ["Core Player"]},
    )
    monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks)
    monkeypatch.setattr(sync_daemon, "_ROSTER_MANIFEST_CACHE", None)

    sync_daemon.auto_deactivate_subs()

    after = json.loads((sharks / "availability.json").read_text())
    assert after["Core Player"] is True
    assert after["Sub Player"] is False


def test_noop_when_schedule_file_missing(tmp_path, monkeypatch):
    sharks = tmp_path / "sharks"
    sharks.mkdir(parents=True)
    (sharks / "availability.json").write_text(json.dumps({"Player A": True}))
    # No schedule_manual.json created
    monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks)
    monkeypatch.setattr(sync_daemon, "_ROSTER_MANIFEST_CACHE", None)

    sync_daemon.auto_deactivate_subs()

    after = json.loads((sharks / "availability.json").read_text())
    assert after == {"Player A": True}


def test_noop_when_availability_file_missing(tmp_path, monkeypatch):
    sharks = tmp_path / "sharks"
    sharks.mkdir(parents=True)
    (sharks / "schedule_manual.json").write_text(
        json.dumps({"past": [{"date": "2000-01-01"}], "upcoming": []})
    )
    (sharks / "roster_manifest.json").write_text(json.dumps({"core_players": ["X"]}))
    # No availability.json created
    monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks)
    monkeypatch.setattr(sync_daemon, "_ROSTER_MANIFEST_CACHE", None)

    # Should not crash
    sync_daemon.auto_deactivate_subs()


def test_noop_when_no_past_games(tmp_path, monkeypatch):
    sharks = tmp_path / "sharks"
    _seed(
        sharks,
        avail={"Player A": True},
        past_games=[],  # empty
        manifest={"core_players": ["Core"]},
    )
    monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks)
    monkeypatch.setattr(sync_daemon, "_ROSTER_MANIFEST_CACHE", None)

    sync_daemon.auto_deactivate_subs()

    after = json.loads((sharks / "availability.json").read_text())
    assert after == {"Player A": True}


def test_noop_when_last_game_is_today(tmp_path, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")

    sharks = tmp_path / "sharks"
    _seed(
        sharks,
        avail={"Sub Player": True},
        past_games=[{"date": today, "is_game": True}],
        manifest={"core_players": ["Core"]},
    )
    monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks)
    monkeypatch.setattr(sync_daemon, "_ROSTER_MANIFEST_CACHE", None)

    sync_daemon.auto_deactivate_subs()

    after = json.loads((sharks / "availability.json").read_text())
    assert after["Sub Player"] is True  # no change — game is today


def test_already_inactive_sub_stays_inactive(tmp_path, monkeypatch):
    sharks = tmp_path / "sharks"
    _seed(
        sharks,
        avail={"Sub Player": False},
        past_games=[{"date": "2000-01-01", "is_game": True}],
        manifest={"core_players": ["Core"]},
    )
    monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks)
    monkeypatch.setattr(sync_daemon, "_ROSTER_MANIFEST_CACHE", None)

    sync_daemon.auto_deactivate_subs()

    after = json.loads((sharks / "availability.json").read_text())
    assert after["Sub Player"] is False


def test_multiple_subs_all_deactivated(tmp_path, monkeypatch):
    sharks = tmp_path / "sharks"
    _seed(
        sharks,
        avail={"Core": True, "Sub1": True, "Sub2": True, "Sub3": True},
        past_games=[{"date": "2000-01-01", "is_game": True}],
        manifest={"core_players": ["Core"]},
    )
    monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks)
    monkeypatch.setattr(sync_daemon, "_ROSTER_MANIFEST_CACHE", None)

    sync_daemon.auto_deactivate_subs()

    after = json.loads((sharks / "availability.json").read_text())
    assert after["Core"] is True
    assert after["Sub1"] is False
    assert after["Sub2"] is False
    assert after["Sub3"] is False


def test_already_deactivated_for_same_game_not_redeactivated(tmp_path, monkeypatch):
    """If sub_tracker already shows deactivated_after_game == last_game_date, skip."""
    sharks = tmp_path / "sharks"
    _seed(
        sharks,
        avail={"Sub Player": False},
        past_games=[{"date": "2000-01-01", "is_game": True}],
        manifest={"core_players": ["Core"]},
    )
    # pre-write sub_tracker showing already handled
    (sharks / "sub_tracker.json").write_text(json.dumps({
        "Sub Player": {"deactivated_after_game": "2000-01-01", "auto_deactivated": True}
    }))
    monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks)
    monkeypatch.setattr(sync_daemon, "_ROSTER_MANIFEST_CACHE", None)

    sync_daemon.auto_deactivate_subs()

    # Availability should remain unchanged
    after = json.loads((sharks / "availability.json").read_text())
    assert after["Sub Player"] is False
