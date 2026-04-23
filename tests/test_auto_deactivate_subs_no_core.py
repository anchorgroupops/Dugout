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
