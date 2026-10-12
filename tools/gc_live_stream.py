"""Parse a GameChanger game-stream event log into live game state.

Input is the list returned by GET /game-streams/{stream_id}/events:
    [{"sequence_number": n, "event_data": "<json string>"}, ...]
Each event_data is one scoring event ({"code": ..., "attributes": {...}}) or a
{"code": "transaction", "events": [...]} bundle. "undo" removes the previous
top-level event, so the whole log is re-parsed on every poll rather than
applied incrementally.

GC never names the batter on an event. The batter is whoever sits at the
batting team's current lineup index: the index advances after each plate
appearance and the scorer can override it with goto_lineup_index.

ball_in_play locations are where the fielder made the play, in GC's field
frame (~320 wide, home plate at the bottom centre, smaller x = third-base
side). They are the spray-chart points.

Pure functions only: no network, no file I/O. tests/test_gc_live_stream.py
checks every plate appearance against GC's own play-by-play feed.
"""
from __future__ import annotations

import json

HIT_BASES = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
HIT_LABELS = {"single": "Single", "double": "Double", "triple": "Triple", "home_run": "Home Run"}
OUT_LABELS = {
    "ground_ball": "Ground Out", "hard_ground_ball": "Ground Out", "bunt": "Ground Out",
    "fly_ball": "Fly Out", "line_drive": "Line Out", "pop_fly": "Pop Out", "pop_up": "Pop Out",
}
REACH_LABELS = {"error": "Error", "fielders_choice": "Fielder's Choice"}
END_AT_BAT_LABELS = {
    "hit_by_pitch": "Hit By Pitch", "walk": "Walk", "intentional_walk": "Walk",
    "catcher_interference": "Catcher's Interference",
}
OUT_RUNNING_PLAYS = {"picked_off", "caught_stealing", "out_on_last_play", "runner_out"}


def flatten_events(raw_events: list) -> list:
    """Raw API rows -> effective top-level events, with every undo applied."""
    rows = sorted((r for r in raw_events or [] if isinstance(r, dict)),
                  key=lambda r: r.get("sequence_number") or 0)
    stack: list = []
    for row in rows:
        data = row.get("event_data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                continue
        if not isinstance(data, dict):
            continue
        if data.get("code") == "undo":
            if stack:
                stack.pop()
            continue
        stack.append(data)
    out = []
    for ev in stack:
        if ev.get("code") == "transaction":
            out.extend(e for e in ev.get("events") or [] if isinstance(e, dict))
        else:
            out.append(ev)
    return out


class _Game:
    def __init__(self, home_id, away_id):
        self.home_id = home_id
        self.away_id = away_id
        self.inning = 1
        self.half = "top"
        self.outs = 0
        self.balls = 0
        self.strikes = 0
        self.bases: dict[int, str] = {}
        self.score = {}
        self.lineups: dict[str, list] = {}
        self.lineup_idx: dict[str, int] = {}
        self.lineup_closed: set = set()
        self.positions: dict[str, dict] = {}
        self.plate_appearances: list = []
        self.spray: list = []
        self.last_scored: list = []
        self.last_play = ""

    # -- helpers -------------------------------------------------------
    @property
    def batting_team(self):
        return self.away_id if self.half == "top" else self.home_id

    @property
    def fielding_team(self):
        return self.home_id if self.half == "top" else self.away_id

    def _lineup(self, team):
        return self.lineups.setdefault(team, [])

    def current_batter(self, team=None):
        team = team or self.batting_team
        lineup = self._lineup(team)
        idx = self.lineup_idx.get(team, 0)
        return lineup[idx] if 0 <= idx < len(lineup) else None

    def on_deck(self):
        team = self.batting_team
        lineup = self._lineup(team)
        nxt = self._next_index(team)
        return lineup[nxt] if 0 <= nxt < len(lineup) else None

    def _next_index(self, team):
        nxt = self.lineup_idx.get(team, 0) + 1
        if team in self.lineup_closed and nxt >= len(self._lineup(team)):
            nxt = 0
        return nxt

    def pitcher(self):
        for pid, pos in self.positions.get(self.fielding_team, {}).items():
            if pos == "P":
                return pid
        return None

    def score_dict(self):
        return {self.home_id: self.score.get(self.home_id, 0),
                self.away_id: self.score.get(self.away_id, 0)}

    def _run(self, runner):
        team = self.batting_team
        self.score[team] = self.score.get(team, 0) + 1
        self.last_scored.append(runner)

    def _place(self, runner, base):
        for b, pid in list(self.bases.items()):
            if pid == runner:
                del self.bases[b]
        if runner in self.last_scored and base < 4:
            # A scorer correction after the default advance sent him home.
            self.last_scored.remove(runner)
            team = self.batting_team
            self.score[team] = self.score.get(team, 0) - 1
        if base >= 4:
            self._run(runner)
        elif base >= 1:
            self.bases[base] = runner

    def _advance_all(self, n):
        for base in sorted(self.bases, reverse=True):
            runner = self.bases.pop(base)
            if base + n >= 4:
                self._run(runner)
            else:
                self.bases[base + n] = runner

    def _force_to_first(self, batter):
        if 1 in self.bases:
            if 2 in self.bases:
                if 3 in self.bases:
                    self._run(self.bases.pop(3))
                self.bases[3] = self.bases.pop(2)
            self.bases[2] = self.bases.pop(1)
        if batter:
            self.bases[1] = batter

    def _end_pa(self, result, batter=None):
        team = self.batting_team
        batter = batter or self.current_batter(team)
        self.plate_appearances.append({
            "inning": self.inning, "half": self.half, "team_id": team,
            "batter_id": batter, "result": result, "outs": self.outs,
            "score": self.score_dict(),
        })
        self.last_play = result
        self.balls = self.strikes = 0
        self.lineup_idx[team] = self._next_index(team)
        if self.outs >= 3:
            self._end_half()

    def _end_half(self):
        if self.half == "top":
            self.half = "bottom"
        else:
            self.half = "top"
            self.inning += 1
        self.outs = self.balls = self.strikes = 0
        self.bases = {}
        self.last_scored = []

    def _out(self):
        self.outs += 1

    # -- event handlers --------------------------------------------------
    def apply(self, ev):
        code = ev.get("code")
        a = ev.get("attributes") or {}
        handler = getattr(self, "_on_" + str(code), None)
        if handler:
            handler(a)

    def _on_set_teams(self, a):
        self.home_id = a.get("homeId") or self.home_id
        self.away_id = a.get("awayId") or self.away_id

    def _on_fill_lineup_index(self, a):
        lineup = self._lineup(a.get("teamId"))
        idx = int(a.get("index", 0))
        while len(lineup) <= idx:
            lineup.append(None)
        lineup[idx] = a.get("playerId")

    def _on_fill_position(self, a):
        team_pos = self.positions.setdefault(a.get("teamId"), {})
        pos = a.get("position")
        if pos == "P":
            for pid, p in list(team_pos.items()):
                if p == "P":
                    del team_pos[pid]
        team_pos[a.get("playerId")] = pos

    def _on_goto_lineup_index(self, a):
        self.lineup_idx[a.get("teamId")] = int(a.get("index", 0))

    def _on_confirm_end_of_lineup(self, a):
        self.lineup_closed.add(a.get("teamId"))

    def _on_reorder_lineup(self, a):
        lineup = self._lineup(a.get("teamId"))
        src, dst = int(a.get("fromIndex", -1)), int(a.get("toIndex", -1))
        if 0 <= src < len(lineup) and 0 <= dst < len(lineup):
            lineup.insert(dst, lineup.pop(src))

    def _on_sub_players(self, a):
        team, inc, out = a.get("teamId"), a.get("incomingPlayerId"), a.get("outgoingPlayerId")
        lineup = self._lineup(team)
        for i, pid in enumerate(lineup):
            if pid == out:
                lineup[i] = inc
        team_pos = self.positions.get(team, {})
        if out in team_pos:
            team_pos[inc] = team_pos.pop(out)
        if a.get("applyToBaserunners"):
            self._on_replace_runner(a)

    def _on_replace_runner(self, a):
        inc, out = a.get("incomingPlayerId"), a.get("outgoingPlayerId")
        for b, pid in list(self.bases.items()):
            if pid == out:
                self.bases[b] = inc

    def _on_pitch(self, a):
        self.last_scored = []
        result = a.get("result")
        counts = a.get("advancesCount", True)
        if result == "ball":
            if counts:
                self.balls += 1
                if self.balls >= 4:
                    self._force_to_first(self.current_batter())
                    self._end_pa("Walk")
        elif result in ("strike_looking", "strike_swinging"):
            if counts:
                self.strikes += 1
                if self.strikes >= 3:
                    self._out()
                    self._end_pa("Strikeout")
        elif result == "foul":
            if counts and self.strikes < 2:
                self.strikes += 1
        # ball_in_play pitches are resolved by the ball_in_play event.

    def _on_ball_in_play(self, a):
        batter = self.current_batter()
        play_result = str(a.get("playResult") or "")
        play_type = str(a.get("playType") or "")
        defenders = a.get("defenders") or []
        if play_result in HIT_BASES:
            label = HIT_LABELS[play_result]
            n = HIT_BASES[play_result]
            self._advance_all(n)
            self._place(batter, n)
        elif "out" in play_result:
            label = OUT_LABELS.get(play_type, "Out")
            self._out()
            if play_result == "batter_out_advance_runners" and self.outs < 3:
                self._advance_all(1)
        else:
            label = REACH_LABELS.get(play_result, play_result.replace("_", " ").title() or "In Play")
            self._force_to_first(batter)
        for d in defenders[:1]:
            loc = d.get("location") or {}
            if "x" in loc and "y" in loc:
                self.spray.append({
                    "batter_id": batter, "team_id": self.batting_team,
                    "inning": self.inning, "half": self.half,
                    "x": loc["x"], "y": loc["y"], "position": d.get("position"),
                    "play_type": play_type, "play_result": play_result, "result": label,
                    "hit": play_result in HIT_BASES, "error": bool(d.get("error")),
                })
        self._end_pa(label, batter)

    def _on_end_at_bat(self, a):
        reason = str(a.get("reason") or "")
        label = END_AT_BAT_LABELS.get(reason, reason.replace("_", " ").title() or "End At Bat")
        if reason in END_AT_BAT_LABELS:
            self._force_to_first(self.current_batter())
        self._end_pa(label)

    def _on_base_running(self, a):
        runner, base = a.get("runnerId"), int(a.get("base") or 0)
        if a.get("playType") in OUT_RUNNING_PLAYS:
            for b, pid in list(self.bases.items()):
                if pid == runner:
                    del self.bases[b]
            self._out()
            if self.outs >= 3:
                self._end_half()
            return
        self._place(runner, base)

    def _on_end_half(self, a):
        self._end_half()

    # -- output ------------------------------------------------------------
    def snapshot(self):
        return {
            "home_id": self.home_id, "away_id": self.away_id,
            "inning": self.inning, "half": self.half,
            "outs": self.outs, "balls": self.balls, "strikes": self.strikes,
            "bases": {str(b): pid for b, pid in sorted(self.bases.items())},
            "score": self.score_dict(),
            "batting_team": self.batting_team,
            "batter_id": self.current_batter(),
            "on_deck_id": self.on_deck(),
            "pitcher_id": self.pitcher(),
            "last_play": self.last_play,
            "plate_appearances": self.plate_appearances,
            "spray": self.spray,
        }


def parse_stream(raw_events: list, home_id: str | None = None, away_id: str | None = None) -> dict:
    """Full re-parse of a game stream into a JSON-serialisable state dict."""
    game = _Game(home_id, away_id)
    for ev in flatten_events(raw_events):
        game.apply(ev)
    return game.snapshot()
