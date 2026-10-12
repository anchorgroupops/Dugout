"""gc_live_stream parser vs GameChanger's own play-by-play feed.

The fixture is a real (anonymised) fall scrimmage: 273 scoring events with 7
undos, mid-game substitutions, lineup reorders and scorer jumps. plays_oracle
is GC's /plays feed for the same stream, so every plate appearance the parser
emits must match it 1:1.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from gc_live_stream import flatten_events, parse_stream  # noqa: E402

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "gc_game_stream_sample.json").read_text())
HOME, AWAY = FIXTURE["home_team_id"], FIXTURE["away_team_id"]


def _state():
    return parse_stream(FIXTURE["events"], HOME, AWAY)


def _ev(code, seq, **attrs):
    return {"sequence_number": seq, "event_data": json.dumps({"code": code, "attributes": attrs})}


def test_every_plate_appearance_matches_gc_play_feed():
    pas = _state()["plate_appearances"]
    oracle = [r for r in FIXTURE["plays_oracle"] if r["batter_id"]]
    got = [(p["inning"], p["half"], p["batter_id"], p["result"], p["outs"],
            p["score"][HOME], p["score"][AWAY]) for p in pas]
    want = [(r["inning"], r["half"], r["batter_id"], r["result"], r["outs"],
             r["home_score"], r["away_score"]) for r in oracle]
    assert got == want


def test_live_state_at_end_of_stream():
    s = _state()
    assert (s["inning"], s["half"], s["outs"]) == (3, "bottom", 2)
    assert (s["balls"], s["strikes"]) == (0, 0)
    assert s["score"] == {HOME: 13, AWAY: 7}
    assert s["batting_team"] == HOME
    # GC's feed ends on "${id038} at bat".
    assert s["batter_id"] == "id038"
    assert s["pitcher_id"] == "id002"


def test_spray_points_carry_batter_and_location():
    spray = _state()["spray"]
    assert len(spray) == 14
    first_opp = next(p for p in spray if p["team_id"] == HOME)
    assert first_opp["batter_id"] == "id036"
    assert first_opp["result"] == "Double"
    assert (first_opp["x"], first_opp["y"]) == (107, 139)
    assert all(0 <= p["x"] <= 320 and 0 <= p["y"] <= 320 for p in spray)


def test_undo_removes_whole_transaction():
    bip = {"sequence_number": 2, "event_data": json.dumps({"code": "transaction", "events": [
        {"code": "pitch", "attributes": {"result": "ball_in_play"}},
        {"code": "ball_in_play", "attributes": {"playResult": "single", "playType": "line_drive",
                                                "defenders": [{"location": {"x": 1, "y": 2}}]}},
    ]})}
    events = [_ev("fill_lineup_index", 1, teamId="a", playerId="p1", index=0), bip,
              {"sequence_number": 3, "event_data": json.dumps({"code": "undo"})}]
    assert [e["code"] for e in flatten_events(events)] == ["fill_lineup_index"]
    s = parse_stream(events, "h", "a")
    assert s["plate_appearances"] == [] and s["spray"] == [] and s["bases"] == {}


def test_count_and_events_order_by_sequence_number():
    events = [_ev("pitch", 3, result="ball"), _ev("pitch", 2, result="foul"),
              _ev("pitch", 4, result="foul"), _ev("pitch", 5, result="foul"),
              _ev("fill_lineup_index", 1, teamId="a", playerId="p1", index=0)]
    s = parse_stream(events, "h", "a")
    assert (s["balls"], s["strikes"], s["batter_id"]) == (1, 2, "p1")


def test_hbp_ball_does_not_count_and_forces_runner():
    events = [_ev("fill_lineup_index", 1, teamId="a", playerId="p1", index=0),
              _ev("fill_lineup_index", 2, teamId="a", playerId="p2", index=1),
              _ev("end_at_bat", 3, reason="hit_by_pitch"),
              _ev("pitch", 4, result="ball", advancesCount=False),
              _ev("end_at_bat", 5, reason="hit_by_pitch")]
    s = parse_stream(events, "h", "a")
    assert s["balls"] == 0
    assert s["bases"] == {"1": "p2", "2": "p1"}
    assert [p["result"] for p in s["plate_appearances"]] == ["Hit By Pitch", "Hit By Pitch"]


def test_garbage_rows_are_ignored():
    s = parse_stream([{"sequence_number": 1, "event_data": "not json"}, {"x": 1}, None], "h", "a")
    assert s["plate_appearances"] == [] and s["inning"] == 1
