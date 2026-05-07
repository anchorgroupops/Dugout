"""Tests for sync_daemon._build_opponent_scouting — spray zones, danger, tags."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import sync_daemon

_build_scouting = sync_daemon._build_opponent_scouting


@pytest.fixture(autouse=True)
def _redirect_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(sync_daemon, "DATA_DIR", data_dir)
    pytest.data_dir = data_dir


def _opp_dir(slug):
    d = pytest.data_dir / "opponents" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_team(slug, roster=None, batting_stats=None):
    d = _opp_dir(slug)
    data = {}
    if roster is not None:
        data["roster"] = roster
    if batting_stats is not None:
        data["batting_stats"] = batting_stats
    (d / "team.json").write_text(json.dumps(data))


def _batter(name, number, ab, h, bb, so, hr=0, doubles=0, sb=0, avg=None):
    return {
        "name": name,
        "number": number,
        "ab": ab,
        "h": h,
        "bb": bb,
        "so": so,
        "hr": hr,
        "doubles": doubles,
        "sb": sb,
        "pa": ab + bb,
        "avg": avg or (round(h / ab, 3) if ab else 0),
    }


# ─── Basic structure ──────────────────────────────────────────────────────────

class TestBuildOpponentScoutingStructure:
    def test_returns_dict(self):
        result = _build_scouting("peppers", [])
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        result = _build_scouting("peppers", [])
        for key in ("opponent", "players", "has_data"):
            assert key in result

    def test_opponent_field_matches_slug(self):
        result = _build_scouting("wildcats", [])
        assert result["opponent"] == "wildcats"

    def test_no_data_has_data_false(self):
        result = _build_scouting("nobody", [])
        assert result["has_data"] is False

    def test_players_is_list(self):
        result = _build_scouting("peppers", [])
        assert isinstance(result["players"], list)

    def test_empty_when_no_team_file_and_no_live_batting(self):
        result = _build_scouting("peppers", [])
        assert result["players"] == []


# ─── Live batting input ───────────────────────────────────────────────────────

class TestLiveBattingInput:
    def test_live_batter_appears_in_output(self):
        live = [_batter("Alice", "7", ab=4, h=2, bb=1, so=1)]
        result = _build_scouting("peppers", live)
        assert len(result["players"]) == 1
        assert result["players"][0]["name"] == "Alice"

    def test_has_data_true_with_live_batting(self):
        live = [_batter("Bob", "9", ab=4, h=1, bb=0, so=2)]
        result = _build_scouting("peppers", live)
        assert result["has_data"] is True

    def test_player_card_has_required_fields(self):
        live = [_batter("Carol", "3", ab=4, h=2, bb=1, so=1)]
        result = _build_scouting("peppers", live)
        card = result["players"][0]
        for field in ("name", "number", "zones", "danger", "tags", "pa"):
            assert field in card

    def test_duplicate_players_deduplicated(self):
        live = [
            _batter("Dave", "11", ab=4, h=2, bb=1, so=1),
            _batter("Dave", "11", ab=4, h=3, bb=0, so=0),  # duplicate
        ]
        result = _build_scouting("peppers", live)
        assert len(result["players"]) == 1

    def test_multiple_players_all_appear(self):
        live = [
            _batter("Alice", "7", ab=4, h=2, bb=1, so=1),
            _batter("Bob", "9", ab=4, h=1, bb=0, so=2),
        ]
        result = _build_scouting("peppers", live)
        assert len(result["players"]) == 2


# ─── Zones ────────────────────────────────────────────────────────────────────

class TestZoneComputation:
    def test_zones_dict_has_all_eight_zones(self):
        live = [_batter("Alice", "7", ab=4, h=2, bb=1, so=0)]
        result = _build_scouting("peppers", live)
        zones = result["players"][0]["zones"]
        for zone in ("lf", "lc", "cf", "rc", "rf", "if3", "ifm", "if1"):
            assert zone in zones

    def test_zone_values_between_0_and_1(self):
        live = [_batter("Alice", "7", ab=8, h=4, bb=1, so=1, hr=1, doubles=2)]
        result = _build_scouting("peppers", live)
        zones = result["players"][0]["zones"]
        for k, v in zones.items():
            assert 0 <= v <= 1, f"Zone {k!r} = {v} out of [0, 1]"

    def test_max_zone_is_1_0(self):
        live = [_batter("Slugger", "5", ab=10, h=8, bb=2, so=0, hr=4, doubles=2)]
        result = _build_scouting("peppers", live)
        zones = result["players"][0]["zones"]
        assert max(zones.values()) == 1.0


# ─── Danger rating ────────────────────────────────────────────────────────────

class TestDangerRating:
    def test_danger_between_0_and_100(self):
        live = [_batter("Alice", "7", ab=4, h=2, bb=1, so=0)]
        card = _build_scouting("peppers", live)["players"][0]
        assert 0 <= card["danger"] <= 100

    def test_higher_avg_means_higher_danger(self):
        great = [_batter("Great", "7", ab=10, h=8, bb=2, so=0, hr=2)]
        poor = [_batter("Poor", "9", ab=10, h=1, bb=0, so=8)]
        d_great = _build_scouting("peppers", great)["players"][0]["danger"]
        d_poor = _build_scouting("peppers2", poor)["players"][0]["danger"]
        assert d_great > d_poor

    def test_home_run_hitter_has_high_danger(self):
        live = [_batter("Crusher", "1", ab=10, h=7, bb=2, so=0, hr=6)]
        card = _build_scouting("peppers", live)["players"][0]
        assert card["danger"] > 50

    def test_players_sorted_by_danger_descending(self):
        live = [
            _batter("Weak", "1", ab=10, h=1, bb=0, so=7),
            _batter("Strong", "2", ab=10, h=8, bb=3, so=0, hr=3),
        ]
        result = _build_scouting("peppers", live)
        dangers = [p["danger"] for p in result["players"]]
        assert dangers == sorted(dangers, reverse=True)


# ─── Threat tags ─────────────────────────────────────────────────────────────

class TestThreatTags:
    def test_contact_tag_for_high_avg(self):
        live = [_batter("Hitter", "7", ab=10, h=4, bb=1, so=1, avg=0.400)]
        card = _build_scouting("peppers", live)["players"][0]
        assert "Contact" in card["tags"]

    def test_power_tag_for_high_slg(self):
        # SLG = (4*4 + 0*other)/10 = 1.6 → well above 0.500
        live = [_batter("Slugger", "5", ab=10, h=5, bb=1, so=0, hr=4)]
        card = _build_scouting("peppers", live)["players"][0]
        assert "Power" in card["tags"]

    def test_patient_tag_when_bb_exceeds_so(self):
        live = [_batter("Patient", "3", ab=10, h=3, bb=5, so=2)]
        card = _build_scouting("peppers", live)["players"][0]
        assert "Patient" in card["tags"]

    def test_speed_tag_for_stolen_bases(self):
        live = [_batter("Speedy", "11", ab=10, h=4, bb=1, so=1, sb=3)]
        card = _build_scouting("peppers", live)["players"][0]
        assert "Speed" in card["tags"]

    def test_tags_is_list(self):
        live = [_batter("Normal", "7", ab=4, h=1, bb=0, so=2)]
        card = _build_scouting("peppers", live)["players"][0]
        assert isinstance(card["tags"], list)

    def test_no_spurious_tags_for_average_player(self):
        # avg=0.250, slg≈0.25, bb<so, sb=0 → no tags
        live = [_batter("Average", "7", ab=8, h=2, bb=1, so=3)]
        card = _build_scouting("peppers", live)["players"][0]
        assert "Power" not in card["tags"]
        assert "Speed" not in card["tags"]


# ─── Historical + live merge ──────────────────────────────────────────────────

class TestHistoricalMerge:
    def test_historical_batting_stats_loaded(self):
        _write_team("peppers", batting_stats=[
            {"name": "Emma", "number": "5", "ab": 8, "h": 3, "bb": 1, "so": 2},
        ])
        result = _build_scouting("peppers", [])
        assert len(result["players"]) == 1
        assert result["players"][0]["name"] == "Emma"

    def test_live_takes_priority_no_duplicate(self):
        _write_team("peppers", batting_stats=[
            {"name": "Emma", "number": "5", "ab": 4, "h": 1},
        ])
        live = [_batter("Emma", "5", ab=4, h=3, bb=1, so=0)]
        result = _build_scouting("peppers", live)
        assert len(result["players"]) == 1

    def test_historical_player_not_in_live_added(self):
        _write_team("peppers", batting_stats=[
            {"name": "Emma", "number": "5", "ab": 8, "h": 3},
        ])
        live = [_batter("Other", "9", ab=4, h=1, bb=0, so=1)]
        result = _build_scouting("peppers", live)
        assert len(result["players"]) == 2
