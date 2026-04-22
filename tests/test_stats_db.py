"""Tests for stats_db.record_sharks_snapshot — None-section handling.

Non-pitchers have `pitching: None` in team.json (set by gc_csv_ingest.py).
The snapshot recorder must tolerate that without crashing.
"""
from __future__ import annotations

import sqlite3

import pytest

import stats_db


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "stats_history.db"
    monkeypatch.setattr(stats_db, "DB_PATH", db_path)
    monkeypatch.setattr(stats_db, "SHARKS_DIR", tmp_path)
    monkeypatch.setattr(stats_db, "_schema_initialized", False)
    yield db_path


def _player(number, last, *, batting=..., pitching=..., fielding=...):
    p = {"number": number, "first": "X", "last": last}
    if batting is not ...:
        p["batting"] = batting
    if pitching is not ...:
        p["pitching"] = pitching
    if fielding is not ...:
        p["fielding"] = fielding
    return p


def test_records_snapshot_when_pitching_is_none(isolated_db):
    """Non-pitchers have pitching=None in team.json. Must not crash."""
    team = {
        "team_name": "The Sharks",
        "roster": [
            _player("1", "Pitcher",
                    batting={"pa": 10, "ab": 8, "h": 3},
                    pitching={"ip": "4.2", "er": 2, "bb": 1, "h": 5, "so": 6},
                    fielding={"po": 5, "a": 2, "e": 0}),
            _player("99", "Fielder",
                    batting={"pa": 12, "ab": 10, "h": 4},
                    pitching=None,
                    fielding={"po": 8, "a": 3, "e": 1}),
        ],
    }
    snapshot_id = stats_db.record_sharks_snapshot(team, source="test")
    assert snapshot_id > 0

    with sqlite3.connect(isolated_db) as conn:
        pcount = conn.execute(
            "SELECT COUNT(*) FROM pitching_snapshots WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchone()[0]
        bcount = conn.execute(
            "SELECT COUNT(*) FROM batting_snapshots WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchone()[0]
        fcount = conn.execute(
            "SELECT COUNT(*) FROM fielding_snapshots WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchone()[0]
    assert bcount == 2
    assert pcount == 2
    assert fcount == 2


def test_records_snapshot_when_fielding_is_none(isolated_db):
    team = {
        "roster": [_player("7", "NoField",
                           batting={"pa": 1, "ab": 1, "h": 0},
                           pitching=None,
                           fielding=None)],
    }
    snapshot_id = stats_db.record_sharks_snapshot(team, source="test")
    with sqlite3.connect(isolated_db) as conn:
        fpct = conn.execute(
            "SELECT fpct FROM fielding_snapshots WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchone()[0]
    assert fpct == 0.0


def test_records_snapshot_when_batting_is_none(isolated_db):
    team = {
        "roster": [_player("0", "Ghost",
                           batting=None, pitching=None, fielding=None)],
    }
    snapshot_id = stats_db.record_sharks_snapshot(team, source="test")
    with sqlite3.connect(isolated_db) as conn:
        row = conn.execute(
            "SELECT pa, ab, h, avg FROM batting_snapshots WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
    assert row == (0, 0, 0, 0.0)


def test_matches_real_sharks_team_json(isolated_db):
    """Regression for the 2026-04-22 production crash: 10/16 roster have pitching=None."""
    roster = [_player(str(i), f"P{i}",
                      batting={"pa": 5, "ab": 4, "h": 1},
                      pitching=None,
                      fielding={"po": 1, "a": 0, "e": 0}) for i in range(10)]
    roster.extend([_player(str(i), f"Pitch{i}",
                           batting={"pa": 3, "ab": 3, "h": 1},
                           pitching={"ip": "2.0", "er": 1, "bb": 0, "h": 2, "so": 2},
                           fielding={"po": 1, "a": 3, "e": 0}) for i in range(6)])
    team = {"team_name": "The Sharks", "roster": roster}
    snapshot_id = stats_db.record_sharks_snapshot(team, source="test", notes="repro")
    with sqlite3.connect(isolated_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM pitching_snapshots WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchone()[0]
    assert count == 16
