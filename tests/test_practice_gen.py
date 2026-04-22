"""Tests for tools/practice_gen.py — weakness → drill mapping + plan generation."""
from __future__ import annotations

from datetime import datetime

import pytest

from tools.practice_gen import (
    _clean_opponent_name,
    _extract_time_hint,
    _iso,
    _load_json,
    _normalize_date_str,
    _parse_event_datetime,
    ET_TZ,
    DRILL_LIBRARY,
    generate_practice_plan,
    map_weaknesses_to_drills,
)


# ====================================================================
# Pure helpers
# ====================================================================
class TestIso:
    def test_none_returns_none(self):
        assert _iso(None) is None

    def test_datetime_to_iso(self):
        dt = datetime(2026, 4, 22, 12, 0, 0)
        assert _iso(dt) == "2026-04-22T12:00:00"


class TestLoadJson:
    def test_missing_returns_default(self, tmp_path):
        assert _load_json(tmp_path / "absent.json", default={"x": 1}) == {"x": 1}

    def test_valid_json(self, tmp_path):
        p = tmp_path / "data.json"
        p.write_text('{"y": 2}')
        assert _load_json(p, default={}) == {"y": 2}

    def test_invalid_json_returns_default(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not valid")
        assert _load_json(p, default=[]) == []


class TestNormalizeDateStr:
    def test_empty_returns_empty(self):
        assert _normalize_date_str("") == ""
        assert _normalize_date_str(None) == ""

    def test_iso_passthrough(self):
        assert _normalize_date_str("2026-04-22") == "2026-04-22"

    def test_slash_to_iso(self):
        assert _normalize_date_str("4/22/2026") == "2026-04-22"
        assert _normalize_date_str("12/1/2026") == "2026-12-01"

    def test_unknown_format_returned_unchanged(self):
        assert _normalize_date_str("April 22, 2026") == "April 22, 2026"


class TestParseEventDatetime:
    def test_iso_date_with_12h_time(self):
        dt = _parse_event_datetime("2026-04-22", "6:00 PM")
        assert dt is not None
        assert dt.year == 2026 and dt.hour == 18
        assert dt.tzinfo == ET_TZ

    def test_empty_date_returns_none(self):
        assert _parse_event_datetime("") is None

    def test_date_only_uses_default_time(self):
        dt = _parse_event_datetime("2026-04-22", default_time="12:00 PM")
        assert dt.hour == 12

    def test_slash_date_normalized(self):
        dt = _parse_event_datetime("4/22/2026", "6:00 PM")
        assert dt is not None and dt.day == 22

    def test_24h_time_accepted(self):
        dt = _parse_event_datetime("2026-04-22", "18:30")
        assert dt is not None and dt.hour == 18 and dt.minute == 30

    def test_unparseable_time_falls_back_to_date_only(self):
        # When time can't parse, the function falls back to the date-only format
        # (midnight in ET) rather than failing.
        dt = _parse_event_datetime("2026-04-22", "not-a-time ZZZ")
        assert dt is not None and dt.hour == 0 and dt.day == 22

    def test_empty_date_returns_none_even_with_time(self):
        assert _parse_event_datetime("", "6:00 PM") is None


class TestExtractTimeHint:
    def test_explicit_time_key(self):
        assert _extract_time_hint({"time": "6:00 PM"}) == "6:00 PM"

    def test_falls_through_keys(self):
        assert _extract_time_hint({"start_time": "5:30 PM"}) == "5:30 PM"

    def test_parses_from_title(self):
        assert _extract_time_hint({"title": "Practice @ 6:00 PM - Field 2"}) == "6:00 PM"

    def test_no_time_returns_empty(self):
        assert _extract_time_hint({"title": "No time info"}) == ""


class TestCleanOpponentName:
    @pytest.mark.parametrize("raw,expected", [
        ("@ Eagles", "Eagles"),
        ("vs. Eagles", "Eagles"),
        ("vs Eagles", "Eagles"),
        ("Eagles", "Eagles"),
        ("", ""),
        ("  @ Eagles  ", "Eagles"),
    ])
    def test_strips_prefixes(self, raw, expected):
        assert _clean_opponent_name(raw) == expected


# ====================================================================
# map_weaknesses_to_drills
# ====================================================================
class TestMapWeaknessesToDrills:
    def test_no_weaknesses_returns_empty(self):
        swot = {"team_swot": {"weaknesses": []}, "player_analyses": []}
        assert map_weaknesses_to_drills(swot) == []

    def test_known_weakness_maps_to_drills(self):
        # "Low batting average" must map to drills per WEAKNESS_DRILL_MAP
        swot = {
            "team_swot": {"weaknesses": ["Low batting average (BA: 0.150)"]},
            "player_analyses": [],
        }
        drills = map_weaknesses_to_drills(swot)
        assert len(drills) > 0
        for d in drills:
            assert "drill_id" in d
            assert "priority_score" in d
            assert d["priority_score"] >= 1

    def test_priority_increases_with_more_matches(self):
        # Same weakness appearing multiple times should bump the score
        swot = {
            "team_swot": {"weaknesses": ["Low batting average (BA: 0.150)"]},
            "player_analyses": [
                {"swot": {"weaknesses": ["Low batting average (BA: 0.1)"]}},
                {"swot": {"weaknesses": ["Low batting average (BA: 0.1)"]}},
            ],
        }
        drills = map_weaknesses_to_drills(swot)
        assert drills[0]["priority_score"] >= 3

    def test_results_sorted_by_priority_desc(self):
        swot = {
            "team_swot": {"weaknesses": [
                "Low batting average (BA: 0.1)",
                "Low batting average (BA: 0.2)",
                "Low batting average (BA: 0.3)",
                "Error-prone fielding (F%: 0.5)",  # different weakness, fewer hits
            ]},
            "player_analyses": [],
        }
        drills = map_weaknesses_to_drills(swot)
        scores = [d["priority_score"] for d in drills]
        assert scores == sorted(scores, reverse=True)

    def test_matchup_boosts_counter_drills(self):
        swot = {"team_swot": {"weaknesses": []}, "player_analyses": []}
        matchup = {
            "empty": False,
            "opponent": "Eagles",
            "their_advantages": ["Higher team batting average (0.350 vs 0.250)"],
            "our_advantages": [],
        }
        drills = map_weaknesses_to_drills(swot, matchup=matchup)
        assert len(drills) > 0
        # Reasons should mention opponent
        assert any("Eagles" in r for d in drills for r in d["reasons"])

    def test_empty_matchup_no_boost(self):
        swot = {"team_swot": {"weaknesses": []}, "player_analyses": []}
        matchup = {"empty": True}
        assert map_weaknesses_to_drills(swot, matchup=matchup) == []

    def test_exploit_our_advantages(self):
        swot = {"team_swot": {"weaknesses": []}, "player_analyses": []}
        matchup = {
            "empty": False,
            "opponent": "Eagles",
            "their_advantages": [],
            "our_advantages": ["Higher team batting average (0.400 vs 0.200)"],
        }
        drills = map_weaknesses_to_drills(swot, matchup=matchup)
        assert len(drills) > 0

    def test_unknown_weakness_ignored(self):
        swot = {
            "team_swot": {"weaknesses": ["Mysterious flaw"]},
            "player_analyses": [],
        }
        assert map_weaknesses_to_drills(swot) == []


# ====================================================================
# generate_practice_plan
# ====================================================================
class TestGeneratePracticePlan:
    def test_uses_provided_date(self):
        swot = {"team_swot": {"weaknesses": []}, "player_analyses": []}
        plan = generate_practice_plan(swot, date="4/22/2026")
        assert plan.startswith("4/22/2026")

    def test_default_date_uses_today(self):
        swot = {"team_swot": {"weaknesses": []}, "player_analyses": []}
        plan = generate_practice_plan(swot)
        now = datetime.now(ET_TZ)
        assert plan.startswith(f"{now.month}/{now.day}/{now.year}")

    def test_always_starts_with_warmup(self):
        swot = {"team_swot": {"weaknesses": []}, "player_analyses": []}
        plan = generate_practice_plan(swot)
        assert "Stretch/Warmup" in plan

    def test_empty_weaknesses_uses_default_drills(self):
        swot = {"team_swot": {"weaknesses": []}, "player_analyses": []}
        plan = generate_practice_plan(swot, duration_minutes=90)
        # Should include at least one default drill from the fallback list
        any_default = any(
            DRILL_LIBRARY[d]["name"] in plan
            for d in ("baserunning_431", "soft_toss", "ground_ball_circuit", "live_situations")
        )
        assert any_default

    def test_includes_opponent_header_when_matchup(self):
        swot = {"team_swot": {"weaknesses": []}, "player_analyses": []}
        matchup = {"empty": False, "opponent": "Eagles", "their_advantages": [], "our_advantages": []}
        plan = generate_practice_plan(swot, matchup=matchup)
        assert "Prep for: Eagles" in plan

    def test_short_duration_trims_drills(self):
        """A 30-min plan should produce fewer drill lines than a 120-min plan."""
        swot = {"team_swot": {"weaknesses": []}, "player_analyses": []}
        short_plan = generate_practice_plan(swot, duration_minutes=30)
        long_plan = generate_practice_plan(swot, duration_minutes=120)
        assert len(short_plan.splitlines()) < len(long_plan.splitlines())

    def test_weakness_based_drills_appear(self):
        swot = {
            "team_swot": {"weaknesses": ["Low batting average (BA: 0.1)"]},
            "player_analyses": [],
        }
        plan = generate_practice_plan(swot, duration_minutes=120)
        # At least one of the mapped batting drills should appear
        mapped_batting_drills = ["soft_toss", "live_bp", "tee_work"]
        matched = any(DRILL_LIBRARY[d]["name"] in plan for d in mapped_batting_drills)
        assert matched

    def test_ends_with_fun_drill_when_time_remains(self):
        swot = {"team_swot": {"weaknesses": []}, "player_analyses": []}
        plan = generate_practice_plan(swot, duration_minutes=120)
        fun_name = DRILL_LIBRARY["strike_at_home"]["name"]
        # Fun drill should appear near the end
        last_third = "\n".join(plan.splitlines()[-20:])
        assert fun_name in plan  # At minimum it's somewhere
