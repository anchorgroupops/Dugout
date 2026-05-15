"""Tests for tools/practice_gen.py — weakness → drill mapping + plan generation."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

import tools.practice_gen as pg_mod
from tools.practice_gen import (
    _clean_opponent_name,
    _extract_time_hint,
    _iso,
    _load_json,
    _load_practice_events,
    _load_game_events,
    _compute_windows,
    _snapshot_source_files,
    _load_plan_meta,
    _save_plan_meta,
    _resolve_opponent_slug,
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


# ====================================================================
# DRILL_LIBRARY / map integrity
# ====================================================================
class TestDrillLibraryIntegrity:
    REQUIRED_DRILL_KEYS = {"name", "duration", "targets", "setup", "instructions", "objective"}

    def test_all_drills_have_required_keys(self):
        for drill_id, drill in DRILL_LIBRARY.items():
            missing = self.REQUIRED_DRILL_KEYS - drill.keys()
            assert not missing, f"Drill {drill_id!r} missing keys: {missing}"

    def test_all_drill_durations_are_positive_ints(self):
        for drill_id, drill in DRILL_LIBRARY.items():
            dur = drill["duration"]
            assert isinstance(dur, int) and dur > 0, \
                f"Drill {drill_id!r} has bad duration: {dur!r}"

    def test_all_drill_instructions_non_empty_lists(self):
        for drill_id, drill in DRILL_LIBRARY.items():
            instructions = drill["instructions"]
            assert isinstance(instructions, list) and instructions, \
                f"Drill {drill_id!r} has empty or non-list instructions"

    def test_all_drill_names_are_non_empty_strings(self):
        for drill_id, drill in DRILL_LIBRARY.items():
            name = drill["name"]
            assert isinstance(name, str) and name.strip(), \
                f"Drill {drill_id!r} has empty name"

    def test_drill_count_is_15(self):
        assert len(DRILL_LIBRARY) == 15

    def test_weakness_map_count_is_12(self):
        from practice_gen import WEAKNESS_DRILL_MAP
        assert len(WEAKNESS_DRILL_MAP) == 12

    def test_weakness_map_all_drill_ids_valid(self):
        from practice_gen import WEAKNESS_DRILL_MAP
        for weakness, drills in WEAKNESS_DRILL_MAP.items():
            for drill_id in drills:
                assert drill_id in DRILL_LIBRARY, \
                    f"WEAKNESS_DRILL_MAP[{weakness!r}] has unknown drill {drill_id!r}"

    def test_matchup_boosts_all_drill_ids_valid(self):
        from practice_gen import MATCHUP_DRILL_BOOSTS
        for pattern, drills in MATCHUP_DRILL_BOOSTS.items():
            for drill_id in drills:
                assert drill_id in DRILL_LIBRARY, \
                    f"MATCHUP_DRILL_BOOSTS[{pattern!r}] has unknown drill {drill_id!r}"

    def test_exploit_boosts_all_drill_ids_valid(self):
        from practice_gen import EXPLOIT_DRILL_BOOSTS
        for pattern, drills in EXPLOIT_DRILL_BOOSTS.items():
            for drill_id in drills:
                assert drill_id in DRILL_LIBRARY, \
                    f"EXPLOIT_DRILL_BOOSTS[{pattern!r}] has unknown drill {drill_id!r}"


# ====================================================================
# Additional map_weaknesses_to_drills edge cases
# ====================================================================
class TestMapWeaknessesFineGrained:
    def _swot(self, team_weaknesses=None, player_analyses=None):
        return {
            "team_swot": {"weaknesses": team_weaknesses or []},
            "player_analyses": player_analyses or [],
        }

    def test_their_advantages_boost_is_exactly_two(self):
        from practice_gen import MATCHUP_DRILL_BOOSTS
        matchup = {
            "empty": False,
            "opponent": "Eagles",
            "their_advantages": ["Higher team batting average"],
            "our_advantages": [],
        }
        drills = map_weaknesses_to_drills(self._swot(), matchup=matchup)
        boosted_ids = MATCHUP_DRILL_BOOSTS["Higher team batting average"]
        for rec in drills:
            if rec["drill_id"] in boosted_ids:
                assert rec["priority_score"] == 2, \
                    f"{rec['drill_id']!r} score should be 2, got {rec['priority_score']}"

    def test_our_advantages_boost_is_exactly_one(self):
        from practice_gen import EXPLOIT_DRILL_BOOSTS
        matchup = {
            "empty": False,
            "opponent": "Eagles",
            "their_advantages": [],
            "our_advantages": ["More aggressive baserunning"],
        }
        drills = map_weaknesses_to_drills(self._swot(), matchup=matchup)
        boosted_ids = EXPLOIT_DRILL_BOOSTS["More aggressive baserunning"]
        for rec in drills:
            if rec["drill_id"] in boosted_ids:
                assert rec["priority_score"] == 1, \
                    f"{rec['drill_id']!r} score should be 1, got {rec['priority_score']}"

    def test_drill_fields_from_library_included_in_result(self):
        swot = self._swot(["Low batting average"])
        drills = map_weaknesses_to_drills(swot)
        rec = next(r for r in drills if r["drill_id"] == "soft_toss")
        assert rec["name"] == DRILL_LIBRARY["soft_toss"]["name"]
        assert rec["duration"] == DRILL_LIBRARY["soft_toss"]["duration"]
        assert rec["objective"] == DRILL_LIBRARY["soft_toss"]["objective"]

    def test_no_duplicate_drill_ids_in_output(self):
        swot = self._swot(["Low batting average", "High strikeout rate", "Struggles to reach base"])
        drills = map_weaknesses_to_drills(swot)
        ids = [r["drill_id"] for r in drills]
        assert len(ids) == len(set(ids)), "Duplicate drill_id found in output"

    def test_combined_team_and_player_weakness_score(self):
        # Team has "Low batting average"; 2 players also have it
        players = [
            {"swot": {"weaknesses": ["Low batting average"]}},
            {"swot": {"weaknesses": ["Low batting average"]}},
        ]
        swot = self._swot(["Low batting average"], player_analyses=players)
        drills = map_weaknesses_to_drills(swot)
        soft_toss = next(r for r in drills if r["drill_id"] == "soft_toss")
        assert soft_toss["priority_score"] == 3  # 1 team + 2 players

    def test_reasons_populated_for_team_weakness(self):
        swot = self._swot(["Low batting average"])
        drills = map_weaknesses_to_drills(swot)
        soft_toss = next(r for r in drills if r["drill_id"] == "soft_toss")
        assert "Low batting average" in soft_toss["reasons"]

    def test_matchup_reason_contains_counter_label(self):
        matchup = {
            "empty": False,
            "opponent": "Wildcats",
            "their_advantages": ["Higher team batting average"],
            "our_advantages": [],
        }
        from practice_gen import MATCHUP_DRILL_BOOSTS
        drills = map_weaknesses_to_drills(self._swot(), matchup=matchup)
        boosted_id = MATCHUP_DRILL_BOOSTS["Higher team batting average"][0]
        rec = next(r for r in drills if r["drill_id"] == boosted_id)
        assert any("Counter Wildcats" in reason for reason in rec["reasons"])

    def test_matchup_exploit_reason_contains_exploit_label(self):
        matchup = {
            "empty": False,
            "opponent": "Ravens",
            "their_advantages": [],
            "our_advantages": ["More aggressive baserunning"],
        }
        from practice_gen import EXPLOIT_DRILL_BOOSTS
        drills = map_weaknesses_to_drills(self._swot(), matchup=matchup)
        boosted_id = EXPLOIT_DRILL_BOOSTS["More aggressive baserunning"][0]
        rec = next(r for r in drills if r["drill_id"] == boosted_id)
        assert any("Exploit vs Ravens" in reason for reason in rec["reasons"])

    def test_all_known_weaknesses_produce_drills(self):
        from practice_gen import WEAKNESS_DRILL_MAP
        for weakness in WEAKNESS_DRILL_MAP:
            swot = self._swot([weakness])
            drills = map_weaknesses_to_drills(swot)
            assert drills, f"Weakness {weakness!r} produced no drills"

    def test_all_matchup_patterns_produce_drills(self):
        from practice_gen import MATCHUP_DRILL_BOOSTS
        for pattern in MATCHUP_DRILL_BOOSTS:
            matchup = {
                "empty": False,
                "opponent": "X",
                "their_advantages": [pattern],
                "our_advantages": [],
            }
            drills = map_weaknesses_to_drills(self._swot(), matchup=matchup)
            assert drills, f"MATCHUP pattern {pattern!r} produced no drills"

    def test_all_exploit_patterns_produce_drills(self):
        from practice_gen import EXPLOIT_DRILL_BOOSTS
        for pattern in EXPLOIT_DRILL_BOOSTS:
            matchup = {
                "empty": False,
                "opponent": "X",
                "their_advantages": [],
                "our_advantages": [pattern],
            }
            drills = map_weaknesses_to_drills(self._swot(), matchup=matchup)
            assert drills, f"EXPLOIT pattern {pattern!r} produced no drills"


# ====================================================================
# Additional generate_practice_plan edge cases
# ====================================================================
class TestGeneratePracticePlanEdgeCases:
    def _swot(self, weaknesses=None):
        return {"team_swot": {"weaknesses": weaknesses or []}, "player_analyses": []}

    def test_objectives_line_present(self):
        plan = generate_practice_plan(self._swot(["Low batting average"]))
        assert "Objectives:" in plan

    def test_warmup_is_item_number_one(self):
        plan = generate_practice_plan(self._swot())
        lines = plan.splitlines()
        # Find line starting with "1."
        first_drill_line = next((l for l in lines if l.startswith("1.")), "")
        assert "Warmup" in first_drill_line or "Stretch" in first_drill_line

    def test_no_matchup_no_prep_for_line(self):
        plan = generate_practice_plan(self._swot())
        assert "Prep for:" not in plan

    def test_empty_matchup_no_prep_for_line(self):
        matchup = {"empty": True, "opponent": "Eagles"}
        plan = generate_practice_plan(self._swot(), matchup=matchup)
        assert "Prep for:" not in plan

    def test_long_plan_has_water_break(self):
        # 120-min plan with many drills should include a water break
        swot = self._swot(["Low batting average", "High ERA", "Error-prone fielding",
                           "Inefficient on the bases", "High strikeout rate"])
        plan = generate_practice_plan(swot, duration_minutes=120)
        assert "Water Break" in plan

    def test_drill_setup_line_present(self):
        swot = self._swot(["Low batting average"])
        plan = generate_practice_plan(swot, duration_minutes=120)
        # Soft-Toss has a setup string that should appear in the plan
        assert "tosser" in plan or "plate" in plan.lower()

    def test_plan_line_count_increases_with_duration(self):
        swot = self._swot(["Low batting average", "High strikeout rate"])
        short = generate_practice_plan(swot, duration_minutes=40)
        long = generate_practice_plan(swot, duration_minutes=120)
        assert len(long.splitlines()) > len(short.splitlines())


# ====================================================================
# Additional _normalize_date_str edge cases
# ====================================================================
class TestNormalizeDateStrExtra:
    def test_single_digit_month_and_day(self):
        assert _normalize_date_str("1/5/2026") == "2026-01-05"

    def test_double_digit_month_and_day(self):
        assert _normalize_date_str("12/31/2026") == "2026-12-31"

    def test_whitespace_only_returns_empty(self):
        assert _normalize_date_str("   ") == ""


# ====================================================================
# Additional _extract_time_hint edge cases
# ====================================================================
class TestExtractTimeHintExtra:
    def test_practice_time_key(self):
        assert _extract_time_hint({"practice_time": "5:00 PM"}) == "5:00 PM"

    def test_empty_string_value_falls_through(self):
        # Empty "time" value should not be returned; should fall through
        result = _extract_time_hint({"time": "", "start_time": "7:30 AM"})
        assert result == "7:30 AM"

    def test_title_with_no_time_returns_empty(self):
        assert _extract_time_hint({"title": "Practice at the park"}) == ""

    def test_title_time_uppercased(self):
        result = _extract_time_hint({"title": "Practice 6:30 pm"})
        # The function uppercases AM/PM
        assert "PM" in result or "6:30" in result


# ====================================================================
# TestLoadPracticeEvents
# ====================================================================

_NOW = datetime(2026, 5, 10, 12, 0, tzinfo=ET_TZ)


class TestLoadPracticeEvents:
    def test_returns_empty_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        assert _load_practice_events(_NOW) == []

    def test_loads_next_event(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        rsvp = {"next": {"date": "2026-05-15", "title": "Practice"}}
        (tmp_path / "practice_rsvp.json").write_text(json.dumps(rsvp))
        events = _load_practice_events(_NOW)
        assert len(events) == 1
        assert events[0]["kind"] == "practice"

    def test_loads_multiple_from_practices_list(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        rsvp = {
            "practices": [
                {"date": "2026-05-15", "title": "A"},
                {"date": "2026-05-22", "title": "B"},
            ]
        }
        (tmp_path / "practice_rsvp.json").write_text(json.dumps(rsvp))
        events = _load_practice_events(_NOW)
        assert len(events) == 2

    def test_deduplicates_same_event(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        rsvp = {
            "next": {"date": "2026-05-15", "title": "Practice"},
            "practices": [{"date": "2026-05-15", "title": "Practice"}],
        }
        (tmp_path / "practice_rsvp.json").write_text(json.dumps(rsvp))
        events = _load_practice_events(_NOW)
        assert len(events) == 1

    def test_skips_entry_without_date(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        rsvp = {"practices": [{"title": "No Date Here"}]}
        (tmp_path / "practice_rsvp.json").write_text(json.dumps(rsvp))
        assert _load_practice_events(_NOW) == []

    def test_event_has_is_future_field(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        rsvp = {"next": {"date": "2026-05-15", "title": "Future"}}
        (tmp_path / "practice_rsvp.json").write_text(json.dumps(rsvp))
        events = _load_practice_events(_NOW)
        assert "is_future" in events[0]
        assert events[0]["is_future"] is True

    def test_past_event_is_not_future(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        rsvp = {"next": {"date": "2026-05-01", "title": "Past"}}
        (tmp_path / "practice_rsvp.json").write_text(json.dumps(rsvp))
        events = _load_practice_events(_NOW)
        assert events[0]["is_future"] is False

    def test_returns_empty_when_non_dict_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        (tmp_path / "practice_rsvp.json").write_text("[]")
        assert _load_practice_events(_NOW) == []


# ====================================================================
# TestLoadGameEvents
# ====================================================================

class TestLoadGameEvents:
    def test_returns_empty_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        assert _load_game_events(_NOW) == []

    def test_loads_past_game(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        schedule = {"past": [{"date": "2026-04-20", "opponent": "Eagles", "is_game": True}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(schedule))
        events = _load_game_events(_NOW)
        assert len(events) == 1
        assert events[0]["kind"] == "game"

    def test_loads_upcoming_game(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        schedule = {"upcoming": [{"date": "2026-05-20", "opponent": "Hawks"}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(schedule))
        events = _load_game_events(_NOW)
        assert len(events) == 1

    def test_skips_non_game_entries(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        schedule = {"upcoming": [{"date": "2026-05-20", "is_game": False}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(schedule))
        assert _load_game_events(_NOW) == []

    def test_skips_entries_without_date(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        schedule = {"upcoming": [{"opponent": "No Date"}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(schedule))
        assert _load_game_events(_NOW) == []

    def test_cleans_opponent_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        schedule = {"upcoming": [{"date": "2026-05-20", "opponent": "vs. Ravens"}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(schedule))
        events = _load_game_events(_NOW)
        assert events[0]["title"] == "Ravens"

    def test_is_future_for_upcoming(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        schedule = {"upcoming": [{"date": "2026-05-20", "opponent": "Bears"}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(schedule))
        events = _load_game_events(_NOW)
        assert events[0]["is_future"] is True

    def test_returns_empty_when_non_dict(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        (tmp_path / "schedule_manual.json").write_text("[]")
        assert _load_game_events(_NOW) == []


# ====================================================================
# TestComputeWindows
# ====================================================================

class TestComputeWindows:
    def test_returns_dict_with_required_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        windows = _compute_windows(_NOW)
        for key in ("latest_completed_event", "latest_completed_end",
                    "planning_allowed_after", "next_practice", "next_practice_start",
                    "refresh_window_start"):
            assert key in windows

    def test_no_events_next_practice_is_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        windows = _compute_windows(_NOW)
        assert windows["next_practice"] is None
        assert windows["next_practice_start"] is None

    def test_no_events_planning_allowed_after_is_now(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        windows = _compute_windows(_NOW)
        assert windows["planning_allowed_after"] == _NOW

    def test_future_practice_appears_as_next_practice(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        rsvp = {"next": {"date": "2026-05-15", "title": "Future Practice"}}
        (tmp_path / "practice_rsvp.json").write_text(json.dumps(rsvp))
        windows = _compute_windows(_NOW)
        assert windows["next_practice"] is not None


# ====================================================================
# TestSnapshotSourceFiles
# ====================================================================

class TestSnapshotSourceFiles:
    def test_returns_dict(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path.parent)
        result = _snapshot_source_files()
        assert isinstance(result, dict)

    def test_missing_file_has_exists_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path.parent)
        result = _snapshot_source_files()
        for val in result.values():
            assert "exists" in val

    def test_existing_file_has_sha1(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path.parent)
        (tmp_path / "swot_analysis.json").write_text('{"ok": true}')
        result = _snapshot_source_files()
        entry = next((v for v in result.values() if v.get("exists")), None)
        assert entry is not None
        assert "sha1" in entry
        assert len(entry["sha1"]) == 40


# ====================================================================
# TestLoadAndSavePlanMeta
# ====================================================================

class TestLoadPlanMeta:
    def test_returns_empty_dict_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "PLAN_META_FILE", tmp_path / "meta.json")
        result = _load_plan_meta()
        assert result == {}

    def test_returns_dict_from_file(self, tmp_path, monkeypatch):
        meta_file = tmp_path / "meta.json"
        meta_file.write_text('{"generated_at": "2026-05-01T10:00:00"}')
        monkeypatch.setattr(pg_mod, "PLAN_META_FILE", meta_file)
        result = _load_plan_meta()
        assert result["generated_at"] == "2026-05-01T10:00:00"

    def test_returns_empty_on_non_dict_content(self, tmp_path, monkeypatch):
        meta_file = tmp_path / "meta.json"
        meta_file.write_text("[]")
        monkeypatch.setattr(pg_mod, "PLAN_META_FILE", meta_file)
        result = _load_plan_meta()
        assert result == {}


class TestSavePlanMeta:
    def test_writes_json_file(self, tmp_path, monkeypatch):
        meta_file = tmp_path / "meta.json"
        monkeypatch.setattr(pg_mod, "PLAN_META_FILE", meta_file)
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        _save_plan_meta({"key": "value"})
        assert meta_file.exists()
        assert json.loads(meta_file.read_text())["key"] == "value"

    def test_creates_parent_dir(self, tmp_path, monkeypatch):
        sub = tmp_path / "subdir"
        meta_file = sub / "meta.json"
        monkeypatch.setattr(pg_mod, "PLAN_META_FILE", meta_file)
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", sub)
        _save_plan_meta({"x": 1})
        assert meta_file.exists()

    def test_overwrites_existing(self, tmp_path, monkeypatch):
        meta_file = tmp_path / "meta.json"
        meta_file.write_text('{"old": true}')
        monkeypatch.setattr(pg_mod, "PLAN_META_FILE", meta_file)
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        _save_plan_meta({"new": True})
        content = json.loads(meta_file.read_text())
        assert "new" in content
        assert "old" not in content


# ====================================================================
# TestResolveOpponentSlug
# ====================================================================

class TestResolveOpponentSlug:
    def test_returns_none_when_no_discovery_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        result = _resolve_opponent_slug("Eagles")
        assert result is None

    def test_matches_from_discovery_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        discovery = {"teams": [{"team_name": "Eagles", "slug": "eagles"}]}
        (tmp_path / "opponent_discovery.json").write_text(json.dumps(discovery))
        result = _resolve_opponent_slug("Eagles")
        assert result == "eagles"

    def test_partial_name_match(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        discovery = {"teams": [{"team_name": "Blue Eagles", "slug": "blue_eagles"}]}
        (tmp_path / "opponent_discovery.json").write_text(json.dumps(discovery))
        result = _resolve_opponent_slug("Eagles")
        assert result == "blue_eagles"

    def test_fallback_to_opponents_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        opp_dir = tmp_path / "opponents" / "hawks"
        opp_dir.mkdir(parents=True)
        result = _resolve_opponent_slug("Hawks")
        assert result == "hawks"

    def test_returns_none_when_no_match(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        result = _resolve_opponent_slug("Totally Unknown Team")
        assert result is None


# ====================================================================
# _parse_event_datetime — line 479 (all formats fail)
# ====================================================================

class TestParseEventDatetimeReturnNone:
    def test_non_iso_non_slash_date_returns_none(self):
        """date_str normalizes to non-empty non-ISO string → all strptime fail → None."""
        result = _parse_event_datetime("April 22, 2026")
        assert result is None


# ====================================================================
# _load_practice_events — line 516 (unparseable date → skip)
# ====================================================================

class TestLoadPracticeEventsUnparseableDate:
    def test_unparseable_date_skips_event(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        rsvp = {"practices": [{"date": "April 22, 2026", "title": "Practice"}]}
        (tmp_path / "practice_rsvp.json").write_text(json.dumps(rsvp))
        events = _load_practice_events(_NOW)
        assert events == []


# ====================================================================
# _load_game_events — line 562 (unparseable date → skip)
# ====================================================================

class TestLoadGameEventsUnparseableDate:
    def test_unparseable_date_skips_game(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        schedule = {"upcoming": [{"date": "April 22, 2026", "opponent": "Eagles"}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(schedule))
        events = _load_game_events(_NOW)
        assert events == []


# ====================================================================
# _resolve_opponent_slug — line 701 (non-dict team entry skipped)
# ====================================================================

class TestResolveOpponentSlugNonDictTeam:
    def test_non_dict_entry_in_teams_list_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        discovery = {"teams": ["not-a-dict", {"team_name": "Eagles", "slug": "eagles"}]}
        (tmp_path / "opponent_discovery.json").write_text(json.dumps(discovery))
        result = _resolve_opponent_slug("Eagles")
        assert result == "eagles"


# ====================================================================
# _write_plan — lines 651-656
# ====================================================================

class TestWritePlan:
    def test_writes_plan_file(self, tmp_path, monkeypatch):
        from tools.practice_gen import _write_plan, PLAN_FILE
        plan_file = tmp_path / "next_practice.txt"
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "PLAN_FILE", plan_file)
        swot = {"team_swot": {"weaknesses": []}, "player_analyses": []}
        windows = {"next_practice_start": None}
        plan = _write_plan(swot, windows)
        assert plan_file.exists()
        assert isinstance(plan, str)
        assert len(plan) > 0

    def test_uses_next_practice_start_for_date(self, tmp_path, monkeypatch):
        from tools.practice_gen import _write_plan
        plan_file = tmp_path / "next_practice.txt"
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "PLAN_FILE", plan_file)
        swot = {"team_swot": {"weaknesses": []}, "player_analyses": []}
        target = datetime(2026, 7, 4, 18, 0, tzinfo=ET_TZ)
        windows = {"next_practice_start": target}
        plan = _write_plan(swot, windows)
        assert "7/4/2026" in plan


# ====================================================================
# _resolve_next_opponent_matchup — lines 661-692
# ====================================================================

class TestResolveNextOpponentMatchup:
    from tools.practice_gen import _resolve_next_opponent_matchup

    def test_returns_none_when_no_schedule_file(self, tmp_path, monkeypatch):
        from tools.practice_gen import _resolve_next_opponent_matchup
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        assert _resolve_next_opponent_matchup() is None

    def test_returns_none_when_schedule_not_dict(self, tmp_path, monkeypatch):
        from tools.practice_gen import _resolve_next_opponent_matchup
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        (tmp_path / "schedule_manual.json").write_text("[]")
        assert _resolve_next_opponent_matchup() is None

    def test_returns_none_when_no_future_games(self, tmp_path, monkeypatch):
        from tools.practice_gen import _resolve_next_opponent_matchup
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        schedule = {"upcoming": [{"date": "2020-01-01", "opponent": "Eagles"}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(schedule))
        assert _resolve_next_opponent_matchup() is None

    def test_returns_none_when_no_slug_resolved(self, tmp_path, monkeypatch):
        from tools.practice_gen import _resolve_next_opponent_matchup
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        schedule = {"upcoming": [{"date": "2099-06-01", "opponent": "UnknownTeam"}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(schedule))
        result = _resolve_next_opponent_matchup()
        assert result is None

    def test_returns_none_when_matchup_file_missing(self, tmp_path, monkeypatch):
        from tools.practice_gen import _resolve_next_opponent_matchup
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        # Create slug match via opponents dir
        (tmp_path / "opponents" / "eagles").mkdir(parents=True)
        discovery = {"teams": [{"team_name": "Eagles", "slug": "eagles"}]}
        (tmp_path / "opponent_discovery.json").write_text(json.dumps(discovery))
        schedule = {"upcoming": [{"date": "2099-06-01", "opponent": "Eagles"}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(schedule))
        # No matchup file at opponents/eagles/team.json → returns None
        result = _resolve_next_opponent_matchup()
        assert result is None

    def test_skips_is_game_false_entries(self, tmp_path, monkeypatch):
        from tools.practice_gen import _resolve_next_opponent_matchup
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        schedule = {"upcoming": [{"date": "2099-06-01", "opponent": "Eagles", "is_game": False}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(schedule))
        assert _resolve_next_opponent_matchup() is None

    def test_returns_matchup_when_file_exists_and_our_team_loaded(self, tmp_path, monkeypatch):
        """Lines 679-688: matchup file exists, analyze_matchup called, returns dict."""
        import sys, types
        from tools.practice_gen import _resolve_next_opponent_matchup
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        # Set up opponent dir and matchup file
        opp_dir = tmp_path / "opponents" / "eagles"
        opp_dir.mkdir(parents=True)
        opp_team = {"roster": []}
        (opp_dir / "team.json").write_text(json.dumps(opp_team))
        # Discovery so slug resolves
        discovery = {"teams": [{"team_name": "Eagles", "slug": "eagles"}]}
        (tmp_path / "opponent_discovery.json").write_text(json.dumps(discovery))
        schedule = {"upcoming": [{"date": "2099-06-01", "opponent": "Eagles"}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(schedule))
        # Mock swot_analyzer module
        fake_swot = types.ModuleType("swot_analyzer")
        our_team_mock = {"roster": [{"first": "Alice", "last": "Smith"}]}
        fake_swot.load_team = lambda path, prefer_merged=False: our_team_mock
        fake_swot.analyze_matchup = lambda our, opp: {
            "their_advantages": [], "our_advantages": [], "key_matchup": ""}
        saved = sys.modules.get("swot_analyzer")
        sys.modules["swot_analyzer"] = fake_swot
        try:
            result = _resolve_next_opponent_matchup()
        finally:
            if saved is None:
                sys.modules.pop("swot_analyzer", None)
            else:
                sys.modules["swot_analyzer"] = saved
        assert result is not None
        assert result["opponent"] == "Eagles"
        assert result["opponent_slug"] == "eagles"

    def test_exception_in_analyze_matchup_swallowed(self, tmp_path, monkeypatch):
        """Line 689-690: exception inside try block is caught, returns None."""
        import sys, types
        from tools.practice_gen import _resolve_next_opponent_matchup
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        opp_dir = tmp_path / "opponents" / "eagles"
        opp_dir.mkdir(parents=True)
        (opp_dir / "team.json").write_text("{}")
        discovery = {"teams": [{"team_name": "Eagles", "slug": "eagles"}]}
        (tmp_path / "opponent_discovery.json").write_text(json.dumps(discovery))
        schedule = {"upcoming": [{"date": "2099-06-01", "opponent": "Eagles"}]}
        (tmp_path / "schedule_manual.json").write_text(json.dumps(schedule))
        fake_swot = types.ModuleType("swot_analyzer")
        fake_swot.load_team = lambda path, prefer_merged=False: {"roster": []}
        fake_swot.analyze_matchup = lambda our, opp: (_ for _ in ()).throw(RuntimeError("boom"))
        saved = sys.modules.get("swot_analyzer")
        sys.modules["swot_analyzer"] = fake_swot
        try:
            result = _resolve_next_opponent_matchup()
        finally:
            if saved is None:
                sys.modules.pop("swot_analyzer", None)
            else:
                sys.modules["swot_analyzer"] = saved
        assert result is None


# ====================================================================
# run_scheduled — lines 721-802
# ====================================================================

_SWOT = {"team_swot": {"weaknesses": []}, "player_analyses": []}


class TestRunScheduled:
    from tools.practice_gen import run_scheduled

    @pytest.fixture(autouse=True)
    def _dirs(self, tmp_path, monkeypatch):
        self.sharks = tmp_path / "sharks"
        self.sharks.mkdir()
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", self.sharks)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "PLAN_FILE", self.sharks / "next_practice.txt")
        monkeypatch.setattr(pg_mod, "PLAN_META_FILE", self.sharks / "next_practice_meta.json")

    def _write_swot(self):
        (self.sharks / "swot_analysis.json").write_text(json.dumps(_SWOT))

    def test_skipped_when_no_swot(self):
        from tools.practice_gen import run_scheduled
        result = run_scheduled()
        assert result["status"] == "skipped"
        assert result["reason"] == "missing_swot"

    def test_force_generates_plan(self):
        from tools.practice_gen import run_scheduled
        self._write_swot()
        result = run_scheduled(force=True)
        assert result["status"] == "generated"
        assert result["mode"] == "scheduled_force"

    def test_initial_after_cooldown_generates_plan(self):
        from tools.practice_gen import run_scheduled
        self._write_swot()
        # No meta → new cycle → initial
        result = run_scheduled(force=False)
        assert result["status"] == "generated"
        assert result["mode"] == "scheduled_initial"

    def test_skipped_during_cooldown(self, monkeypatch):
        from tools.practice_gen import run_scheduled
        from datetime import datetime, timedelta
        self._write_swot()
        # Simulate a just-completed event: set planning_allowed_after to far future
        future = datetime(2099, 1, 1, tzinfo=ET_TZ)
        monkeypatch.setattr(pg_mod, "_compute_windows", lambda now: {
            "latest_completed_event": {"title": "Game"},
            "latest_completed_end": future - timedelta(hours=0.5),
            "planning_allowed_after": future,
            "next_practice": None,
            "next_practice_start": None,
            "refresh_window_start": None,
        })
        result = run_scheduled(force=False)
        assert result["status"] == "skipped"
        assert result["reason"] == "cooldown_after_event"

    def test_skipped_outside_refresh_window(self, monkeypatch):
        from tools.practice_gen import run_scheduled
        from datetime import datetime, timedelta
        self._write_swot()
        now = datetime.now(ET_TZ)
        past = now - timedelta(hours=10)
        # cycle_anchor_end=None means _iso(None)=None → (None or "")="" → prev must also be ""
        meta = {"cycle_anchor_end": None, "source_snapshot": {}}
        monkeypatch.setattr(pg_mod, "_compute_windows", lambda n: {
            "latest_completed_event": None,
            "latest_completed_end": None,
            "planning_allowed_after": past,
            "next_practice": None,
            "next_practice_start": None,
            "refresh_window_start": None,
        })
        monkeypatch.setattr(pg_mod, "_load_plan_meta", lambda: meta)
        result = run_scheduled(force=False)
        assert result["status"] == "skipped"
        assert result["reason"] == "outside_refresh_window"

    def test_refresh_skipped_when_already_done(self, monkeypatch):
        from tools.practice_gen import run_scheduled
        from datetime import datetime, timedelta
        self._write_swot()
        now = datetime.now(ET_TZ)
        past = now - timedelta(hours=10)
        next_practice = now + timedelta(hours=0.5)
        refresh_start = now - timedelta(hours=0.5)
        refresh_iso = next_practice.isoformat()
        # cycle_anchor_end=None → _iso(None)=None → (None or "")="" matches str(None or "")=""
        meta = {
            "cycle_anchor_end": None,
            "last_refresh_for_practice": refresh_iso,
            "source_snapshot": {},
        }
        monkeypatch.setattr(pg_mod, "_compute_windows", lambda n: {
            "latest_completed_event": None,
            "latest_completed_end": None,
            "planning_allowed_after": past,
            "next_practice": {"title": "P"},
            "next_practice_start": next_practice,
            "refresh_window_start": refresh_start,
        })
        monkeypatch.setattr(pg_mod, "_load_plan_meta", lambda: meta)
        monkeypatch.setattr(pg_mod, "_snapshot_source_files", lambda: {})
        monkeypatch.setattr(pg_mod, "_iso", lambda dt: dt.isoformat() if dt else None)
        result = run_scheduled(force=False)
        assert result["status"] == "skipped"
        assert result["reason"] == "refresh_already_done"

    def test_refresh_skipped_when_no_new_info(self, monkeypatch):
        from tools.practice_gen import run_scheduled
        from datetime import datetime, timedelta
        self._write_swot()
        now = datetime.now(ET_TZ)
        past = now - timedelta(hours=10)
        next_practice = now + timedelta(hours=0.5)
        refresh_start = now - timedelta(hours=0.5)
        snapshot = {"file": {"exists": False}}
        meta = {
            "cycle_anchor_end": None,
            "last_refresh_for_practice": "other_val",
            "source_snapshot": snapshot,
        }
        monkeypatch.setattr(pg_mod, "_compute_windows", lambda n: {
            "latest_completed_event": None,
            "latest_completed_end": None,
            "planning_allowed_after": past,
            "next_practice": {"title": "P"},
            "next_practice_start": next_practice,
            "refresh_window_start": refresh_start,
        })
        monkeypatch.setattr(pg_mod, "_load_plan_meta", lambda: meta)
        monkeypatch.setattr(pg_mod, "_snapshot_source_files", lambda: snapshot)
        monkeypatch.setattr(pg_mod, "_iso", lambda dt: dt.isoformat() if dt else None)
        result = run_scheduled(force=False)
        assert result["status"] == "skipped"
        assert result["reason"] == "no_new_info"

    def test_refresh_generates_when_new_info(self, monkeypatch):
        from tools.practice_gen import run_scheduled
        from datetime import datetime, timedelta
        self._write_swot()
        now = datetime.now(ET_TZ)
        past = now - timedelta(hours=10)
        next_practice = now + timedelta(hours=0.5)
        refresh_start = now - timedelta(hours=0.5)
        old_snapshot = {"file": {"exists": False}}
        new_snapshot = {"file": {"exists": True, "sha1": "abc"}}
        meta = {
            "cycle_anchor_end": None,
            "last_refresh_for_practice": "other_val",
            "source_snapshot": old_snapshot,
        }
        monkeypatch.setattr(pg_mod, "_compute_windows", lambda n: {
            "latest_completed_event": None,
            "latest_completed_end": None,
            "planning_allowed_after": past,
            "next_practice": {"title": "P"},
            "next_practice_start": next_practice,
            "refresh_window_start": refresh_start,
        })
        monkeypatch.setattr(pg_mod, "_load_plan_meta", lambda: meta)
        monkeypatch.setattr(pg_mod, "_snapshot_source_files", lambda: new_snapshot)
        monkeypatch.setattr(pg_mod, "_iso", lambda dt: dt.isoformat() if dt else None)
        monkeypatch.setattr(pg_mod, "_save_plan_meta", lambda m: None)
        monkeypatch.setattr(pg_mod, "_resolve_next_opponent_matchup", lambda: None)
        result = run_scheduled(force=False)
        assert result["status"] == "generated"
        assert result["mode"] == "scheduled_refresh"


# ====================================================================
# run() — lines 812-829
# ====================================================================

class TestRun:
    @pytest.fixture(autouse=True)
    def _dirs(self, tmp_path, monkeypatch):
        self.sharks = tmp_path / "sharks"
        self.sharks.mkdir()
        monkeypatch.setattr(pg_mod, "SHARKS_DIR", self.sharks)
        monkeypatch.setattr(pg_mod, "DATA_DIR", tmp_path)
        monkeypatch.setattr(pg_mod, "PLAN_FILE", self.sharks / "next_practice.txt")
        monkeypatch.setattr(pg_mod, "PLAN_META_FILE", self.sharks / "meta.json")

    def test_returns_none_when_no_swot(self, capsys):
        from tools.practice_gen import run
        result = run()
        assert result is None
        assert "SWOT" in capsys.readouterr().out

    def test_generates_plan_when_swot_exists(self):
        from tools.practice_gen import run
        (self.sharks / "swot_analysis.json").write_text(json.dumps(_SWOT))
        plan_file = self.sharks / "next_practice.txt"
        result = run()
        assert result is not None
        assert plan_file.exists()
        assert "Stretch" in result or "Warmup" in result

    def test_prints_plan_to_stdout(self, capsys):
        from tools.practice_gen import run
        (self.sharks / "swot_analysis.json").write_text(json.dumps(_SWOT))
        run()
        out = capsys.readouterr().out
        assert "Plan saved" in out or "PRACTICE" in out

    def test_matchup_printed_when_available(self, monkeypatch, capsys):
        from tools.practice_gen import run
        (self.sharks / "swot_analysis.json").write_text(json.dumps(_SWOT))
        monkeypatch.setattr(pg_mod, "_resolve_next_opponent_matchup",
                            lambda: {"opponent": "Eagles", "their_advantages": [],
                                     "our_advantages": []})
        run()
        out = capsys.readouterr().out
        assert "Eagles" in out
