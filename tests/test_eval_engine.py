"""Tests for tools/eval_engine.py — drill library integrity, record
sanitization, scoring, and position-fit computation."""
from __future__ import annotations

import json

import pytest

from tools.eval_engine import (
    DRILL_WEIGHT,
    EVAL_DRILLS,
    POSITION_PROFILES,
    POSITIONS,
    STAT_WEIGHT,
    build_eval_payload,
    compute_position_fits,
    drill_score,
    is_returning,
    latest_drill_scores,
    run,
    sanitize_records,
)


def _player(first, last, **blocks):
    base = {"first": first, "last": last, "number": "1", "core": True, "borrowed": False}
    base.update(blocks)
    return base


RETURNING = _player(
    "Riley", "Vega",
    batting={"pa": 20, "avg": 0.350, "sb": 5, "sb_pct": 0.9, "sac": 1},
    fielding={"tc": 30, "po": 20, "a": 8, "fpct": 0.933, "e": 2, "dp": 1},
)
NEW_PLAYER = _player("Sam", "Ortiz")  # no stat blocks — brand new


class TestDrillLibrary:
    def test_ids_unique(self):
        ids = [d["id"] for d in EVAL_DRILLS]
        assert len(ids) == len(set(ids))

    def test_required_fields(self):
        for d in EVAL_DRILLS:
            assert d["unit"] in ("count", "seconds")
            assert d["name"] and d["how_to"] and d["scoring"]
            if d["unit"] == "seconds":
                best, worst = d["bounds"]
                assert best < worst
            else:
                assert d["default_attempts"] >= 1
            for pos in d["positions"]:
                assert pos in POSITIONS

    def test_profiles_reference_real_drills_and_cover_all_positions(self):
        drill_ids = {d["id"] for d in EVAL_DRILLS}
        assert set(POSITION_PROFILES) == set(POSITIONS)
        for profile in POSITION_PROFILES.values():
            assert profile["drills"], "every position needs at least one drill"
            for drill_id in profile["drills"]:
                assert drill_id in drill_ids


class TestSanitizeRecords:
    def test_valid_count_record(self):
        clean, errors = sanitize_records([
            {"player": "Riley Vega", "drill_id": "of_pop_flies", "made": 7, "attempts": 10},
        ])
        assert errors == []
        assert clean[0]["made"] == 7 and clean[0]["attempts"] == 10

    def test_valid_timed_record(self):
        clean, errors = sanitize_records([
            {"player": "Riley Vega", "drill_id": "home_to_first", "value": 4.25},
        ])
        assert errors == []
        assert clean[0]["value"] == 4.25 and clean[0]["made"] is None

    @pytest.mark.parametrize("bad", [
        {"player": "", "drill_id": "of_pop_flies", "made": 7, "attempts": 10},
        {"player": "A", "drill_id": "nope", "made": 7, "attempts": 10},
        {"player": "A", "drill_id": "of_pop_flies", "made": 11, "attempts": 10},
        {"player": "A", "drill_id": "of_pop_flies", "made": -1, "attempts": 10},
        {"player": "A", "drill_id": "of_pop_flies", "made": 5, "attempts": 0},
        {"player": "A", "drill_id": "home_to_first", "value": -2},
        {"player": "A", "drill_id": "home_to_first", "value": "fast"},
        "not-a-dict",
    ])
    def test_invalid_records_rejected(self, bad):
        clean, errors = sanitize_records([bad])
        assert clean == []
        assert errors

    def test_non_list_rejected(self):
        clean, errors = sanitize_records({"player": "x"})
        assert clean == [] and errors == ["records_must_be_list"]

    def test_truncates_long_strings(self):
        clean, _ = sanitize_records([
            {"player": "P" * 300, "drill_id": "of_pop_flies", "made": 1, "attempts": 10,
             "notes": "n" * 500, "date": "d" * 100},
        ])
        assert len(clean[0]["player"]) == 80
        assert len(clean[0]["notes"]) == 200
        assert len(clean[0]["date"]) == 32


class TestScoring:
    def test_count_ratio(self):
        assert drill_score({"drill_id": "of_pop_flies", "made": 7, "attempts": 10}) == 0.7

    def test_timed_bounds(self):
        # home_to_first bounds [3.5, 7.0]: at best → 1.0, at worst → 0.0
        assert drill_score({"drill_id": "home_to_first", "value": 3.5}) == 1.0
        assert drill_score({"drill_id": "home_to_first", "value": 7.0}) == 0.0
        assert drill_score({"drill_id": "home_to_first", "value": 2.0}) == 1.0  # clamped

    def test_latest_record_wins(self):
        scores = latest_drill_scores([
            {"player": "A", "drill_id": "of_pop_flies", "made": 3, "attempts": 10},
            {"player": "A", "drill_id": "of_pop_flies", "made": 9, "attempts": 10},
        ])
        assert scores["A"]["of_pop_flies"] == 0.9


class TestPositionFits:
    def test_returning_detection(self):
        assert is_returning(RETURNING) is True
        assert is_returning(NEW_PLAYER) is False

    def test_new_player_ranks_on_drills_alone(self):
        team = {"roster": [RETURNING, NEW_PLAYER]}
        records, _ = sanitize_records([
            {"player": "Sam Ortiz", "drill_id": "of_pop_flies", "made": 10, "attempts": 10},
            {"player": "Sam Ortiz", "drill_id": "long_toss", "made": 5, "attempts": 5},
        ])
        fits = compute_position_fits(team, records)
        cf = {e["name"]: e for e in fits["positions"]["CF"]}
        assert cf["Sam Ortiz"]["fit"] == 100.0
        assert cf["Sam Ortiz"]["stat_score"] is None
        assert cf["Sam Ortiz"]["returning"] is False

    def test_returning_player_blends_drills_and_stats(self):
        team = {"roster": [RETURNING, NEW_PLAYER]}
        records, _ = sanitize_records([
            {"player": "Riley Vega", "drill_id": "of_pop_flies", "made": 5, "attempts": 10},
        ])
        fits = compute_position_fits(team, records)
        entry = next(e for e in fits["positions"]["LF"] if e["name"] == "Riley Vega")
        assert entry["drill_score"] == 50.0
        assert entry["stat_score"] is not None
        expected = round(
            (DRILL_WEIGHT * 50.0 + STAT_WEIGHT * entry["stat_score"]) / (DRILL_WEIGHT + STAT_WEIGHT), 1
        )
        assert entry["fit"] == pytest.approx(expected, abs=0.11)

    def test_no_data_player_unranked_last(self):
        team = {"roster": [RETURNING, NEW_PLAYER]}
        fits = compute_position_fits(team, [])
        ss = fits["positions"]["SS"]
        assert ss[-1]["name"] == "Sam Ortiz" and ss[-1]["fit"] is None

    def test_unknown_logged_player_still_ranked(self):
        team = {"roster": [RETURNING]}
        records, _ = sanitize_records([
            {"player": "Walk-On Kid", "drill_id": "if_ground_balls", "made": 8, "attempts": 10},
        ])
        fits = compute_position_fits(team, records)
        assert "Walk-On Kid" in fits["players"]

    def test_borrowed_players_excluded(self):
        borrowed = _player("Bo", "Rrowed", borrowed=True,
                           fielding={"tc": 10, "po": 9, "a": 1, "fpct": 1.0, "e": 0, "dp": 0})
        fits = compute_position_fits({"roster": [RETURNING, borrowed]}, [])
        assert "Bo Rrowed" not in fits["players"]


class TestPayloadAndRun:
    def test_payload_shape(self):
        payload = build_eval_payload({"team_name": "The Sharks", "roster": [RETURNING]}, [])
        assert payload["team_name"] == "The Sharks"
        assert payload["drills"] == EVAL_DRILLS
        assert set(payload["position_stats"]) == set(POSITIONS)
        assert payload["roster"][0]["returning"] is True

    def test_run_writes_evals_json(self, tmp_path):
        (tmp_path / "team.json").write_text(json.dumps({"team_name": "Test Team", "roster": [RETURNING]}))
        (tmp_path / "eval_records.json").write_text(json.dumps([
            {"player": "Riley Vega", "drill_id": "of_pop_flies", "made": 7, "attempts": 10},
            {"player": "Riley Vega", "drill_id": "bogus_drill", "made": 7, "attempts": 10},
        ]))
        payload = run(tmp_path)
        written = json.loads((tmp_path / "evals.json").read_text())
        assert written["team_name"] == "Test Team"
        assert len(written["records"]) == 1  # invalid record dropped
        assert payload["fits"]["positions"]["LF"][0]["name"] == "Riley Vega"

    def test_run_survives_missing_files(self, tmp_path):
        payload = run(tmp_path)
        assert payload["records"] == []
        assert (tmp_path / "evals.json").exists()
