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


# ---------------------------------------------------------------------------
# _player_name / _player_key helpers
# ---------------------------------------------------------------------------

def test_player_name_explicit():
    assert stats_db._player_name({"name": "Jane Doe"}) == "Jane Doe"


def test_player_name_from_first_last():
    assert stats_db._player_name({"first": "Jane", "last": "Doe"}) == "Jane Doe"


def test_player_name_unknown_fallback():
    assert stats_db._player_name({}) == "Unknown"


def test_player_key_with_number():
    key = stats_db._player_key({"number": "7", "first": "Jane", "last": "Doe"})
    assert key.startswith("sharks:7:")
    assert "jane_doe" in key


def test_player_key_without_number():
    key = stats_db._player_key({"first": "Jane", "last": "Doe"})
    assert "nonumber" in key


# ---------------------------------------------------------------------------
# get_db_status
# ---------------------------------------------------------------------------

def test_get_db_status_returns_dict(isolated_db):
    result = stats_db.get_db_status()
    assert isinstance(result, dict)
    assert "snapshot_count" in result
    assert "player_count" in result


def test_get_db_status_counts_snapshots(isolated_db):
    team = {"roster": [_player("7", "Smith",
                                batting={"pa": 5, "ab": 4, "h": 1},
                                pitching=None, fielding={"po": 1, "a": 0, "e": 0})]}
    stats_db.record_sharks_snapshot(team, source="test")
    status = stats_db.get_db_status()
    assert status["snapshot_count"] >= 1


def test_get_db_status_empty_db_has_no_latest(isolated_db):
    status = stats_db.get_db_status()
    assert status["latest"] is None


# ---------------------------------------------------------------------------
# insert_h2h_game / get_h2h_history / get_h2h_summary
# ---------------------------------------------------------------------------

def test_insert_h2h_game_returns_true_on_insert(isolated_db):
    result = stats_db.insert_h2h_game("game1", "peppers", "2026-04-01", 7, 3, "W")
    assert result is True


def test_insert_h2h_game_returns_false_on_duplicate(isolated_db):
    stats_db.insert_h2h_game("game1", "peppers", "2026-04-01", 7, 3, "W")
    result = stats_db.insert_h2h_game("game1", "peppers", "2026-04-01", 7, 3, "W")
    assert result is False


def test_get_h2h_history_returns_inserted_game(isolated_db):
    stats_db.insert_h2h_game("g1", "wildcats", "2026-03-15", 5, 2, "W")
    history = stats_db.get_h2h_history("wildcats")
    assert len(history) == 1
    assert history[0]["game_id"] == "g1"
    assert history[0]["runs_for"] == 5
    assert history[0]["result"] == "W"


def test_get_h2h_history_empty_opponent(isolated_db):
    stats_db.insert_h2h_game("g1", "wildcats", "2026-03-15", 5, 2, "W")
    history = stats_db.get_h2h_history("peppers")
    assert history == []


def test_get_h2h_history_sorted_newest_first(isolated_db):
    stats_db.insert_h2h_game("g1", "ravens", "2026-02-01", 4, 1, "W")
    stats_db.insert_h2h_game("g2", "ravens", "2026-04-01", 3, 5, "L")
    history = stats_db.get_h2h_history("ravens")
    assert history[0]["date"] > history[1]["date"]


def test_get_h2h_summary_win_loss(isolated_db):
    stats_db.insert_h2h_game("g1", "eagles", "2026-02-01", 5, 2, "W")
    stats_db.insert_h2h_game("g2", "eagles", "2026-03-01", 1, 4, "L")
    stats_db.insert_h2h_game("g3", "eagles", "2026-04-01", 3, 6, "L")
    summary = stats_db.get_h2h_summary("eagles")
    assert summary["wins"] == 1
    assert summary["losses"] == 2
    assert summary["ties"] == 0
    assert summary["games_played"] == 3


def test_get_h2h_summary_empty_opponent(isolated_db):
    summary = stats_db.get_h2h_summary("unknown_opponent")
    assert summary["games_played"] == 0
    assert summary["wins"] == 0


def test_get_h2h_summary_record_format(isolated_db):
    stats_db.insert_h2h_game("g1", "tigers", "2026-01-01", 5, 2, "W")
    stats_db.insert_h2h_game("g2", "tigers", "2026-02-01", 1, 3, "L")
    summary = stats_db.get_h2h_summary("tigers")
    assert summary["record"] == "1-1"


def test_get_h2h_summary_with_ties(isolated_db):
    stats_db.insert_h2h_game("g1", "bears", "2026-01-01", 4, 4, "T")
    stats_db.insert_h2h_game("g2", "bears", "2026-02-01", 3, 1, "W")
    summary = stats_db.get_h2h_summary("bears")
    assert summary["ties"] == 1
    assert summary["record"] == "1-0-1"


def test_get_h2h_summary_runs_totals(isolated_db):
    stats_db.insert_h2h_game("g1", "hawks", "2026-01-01", 5, 2, "W")
    stats_db.insert_h2h_game("g2", "hawks", "2026-02-01", 3, 6, "L")
    summary = stats_db.get_h2h_summary("hawks")
    assert summary["runs_for"] == 8
    assert summary["runs_against"] == 8


def test_get_h2h_summary_avg_runs(isolated_db):
    stats_db.insert_h2h_game("g1", "wolves", "2026-01-01", 6, 2, "W")
    stats_db.insert_h2h_game("g2", "wolves", "2026-02-01", 4, 4, "T")
    summary = stats_db.get_h2h_summary("wolves")
    assert summary["avg_runs_for"] == 5.0
    assert summary["avg_runs_against"] == 3.0


def test_get_h2h_summary_games_field_included(isolated_db):
    stats_db.insert_h2h_game("g1", "lions", "2026-01-01", 7, 3, "W")
    summary = stats_db.get_h2h_summary("lions")
    assert "games" in summary
    assert len(summary["games"]) == 1
    assert summary["games"][0]["game_id"] == "g1"


def test_get_h2h_summary_opponent_slug_in_result(isolated_db):
    summary = stats_db.get_h2h_summary("jaguars")
    assert summary["opponent_slug"] == "jaguars"


# ---------------------------------------------------------------------------
# _now_iso helper
# ---------------------------------------------------------------------------

def test_now_iso_returns_string(isolated_db):
    result = stats_db._now_iso()
    assert isinstance(result, str)
    assert "T" in result


def test_player_key_format(isolated_db):
    key = stats_db._player_key({"number": "42", "first": "John", "last": "Smith"})
    assert key == "sharks:42:john_smith"


def test_player_key_unknown_player(isolated_db):
    key = stats_db._player_key({})
    assert key == "sharks:nonumber:unknown"
