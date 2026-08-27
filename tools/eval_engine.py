"""
Player Evaluation Engine — preseason tryout/eval drills and position-fit scoring.

Coaches log drill results ("pop flies caught 7/10", "home-to-first in 4.2s")
during preseason evals. This engine combines those results with last season's
GameChanger stats (when a player is returning) to rank every player's fit for
each defensive position.

Team-agnostic: all functions operate on a team dict + records list; the CLI
resolves the data directory through tools/team_registry.py so a second team is
a YAML append, not a code branch (data/<data_slug>/, per SIGN-006 the Sharks
dir is never shared with opponent data).

Files (per team data dir):
  eval_records.json  — the coach-entered log (list of record dicts), source of truth
  evals.json         — computed payload (drills + records + fits), static fallback
                       served by nginx and synced into the PWA bundle
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

_ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = _ROOT_DIR / "data"

MAX_RECORDS = 2000
MAX_NAME_LEN = 80
MAX_NOTES_LEN = 200
MAX_ATTEMPTS = 500
MAX_TIMED_VALUE = 1000.0

POSITIONS = ["P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]

# ── Eval Drill Library ────────────────────────────────────────────────────
# Two scoring units:
#   "count"   — made out of attempts (log e.g. 7/10); score = made/attempts
#   "seconds" — stopwatch time, lower is better; score normalized between
#               bounds [best, worst]
# `positions` = which defensive spots the drill informs (empty = batting/
# lineup gauge). `stat_keys` = last-season GameChanger stats that measure the
# same skill, shown alongside the drill so the coach sees which stats map to it.
EVAL_DRILLS = [
    {
        "id": "if_ground_balls",
        "name": "Ground Balls (Infield)",
        "category": "Fielding",
        "unit": "count",
        "default_attempts": 10,
        "how_to": "Player at their infield spot. Coach hits 10 game-speed grounders, mixing straight-on, glove side, and backhand. Player fields and makes the throw to 1B.",
        "scoring": "Clean field + accurate throw = 1. Log made/attempts (e.g. 7/10).",
        "positions": ["1B", "2B", "3B", "SS"],
        "stat_keys": ["fielding.fpct", "fielding.a", "fielding.e"],
    },
    {
        "id": "of_pop_flies",
        "name": "Pop Flies / Fly Balls",
        "category": "Fielding",
        "unit": "count",
        "default_attempts": 10,
        "how_to": "Player in the outfield. Coach hits or throws 10 catchable fly balls: 4 straight-on, 3 requiring a drop step left, 3 right. Player calls the ball and catches.",
        "scoring": "Clean catch = 1. Log made/attempts (e.g. 7/10).",
        "positions": ["LF", "CF", "RF"],
        "stat_keys": ["fielding.po", "fielding.fpct"],
    },
    {
        "id": "arm_accuracy",
        "name": "Throwing Accuracy",
        "category": "Throwing",
        "unit": "count",
        "default_attempts": 10,
        "how_to": "Player at SS depth, target (net or receiver) at 1B. 10 throws at game intensity after a shuffle step. Chest-high window counts.",
        "scoring": "On-target throw = 1. Log made/attempts.",
        "positions": ["2B", "3B", "SS", "C", "P"],
        "stat_keys": ["fielding.a", "fielding.e"],
    },
    {
        "id": "long_toss",
        "name": "Arm Strength (OF Long Throw)",
        "category": "Throwing",
        "unit": "count",
        "default_attempts": 5,
        "how_to": "Player in medium outfield. Coach rolls a ball out; player charges, crow-hops, and throws to a cutoff/base target. 5 reps.",
        "scoring": "Strong, on-line throw reaching the target on ≤1 hop = 1. Log made/attempts.",
        "positions": ["LF", "CF", "RF", "3B"],
        "stat_keys": ["fielding.a"],
    },
    {
        "id": "if_transfer",
        "name": "Quick Hands / DP Transfer",
        "category": "Fielding",
        "unit": "count",
        "default_attempts": 10,
        "how_to": "Player at 2B bag. Coach feeds 10 short tosses; player receives, transfers, and simulates the double-play pivot throw.",
        "scoring": "Clean catch-transfer-throw under control = 1. Log made/attempts.",
        "positions": ["2B", "SS"],
        "stat_keys": ["fielding.dp", "fielding.fpct"],
    },
    {
        "id": "first_base_scoops",
        "name": "1B Scoops & Stretches",
        "category": "Fielding",
        "unit": "count",
        "default_attempts": 10,
        "how_to": "Player at 1B with a foot on the bag. Coach throws 10 mixed feeds: short hops, wide, and high. Player stretches or scoops while keeping contact when possible.",
        "scoring": "Ball secured = 1. Log made/attempts.",
        "positions": ["1B"],
        "stat_keys": ["fielding.po", "fielding.e"],
    },
    {
        "id": "catcher_blocking",
        "name": "Catcher Blocking",
        "category": "Catching",
        "unit": "count",
        "default_attempts": 10,
        "how_to": "Player in full gear behind the plate. Coach throws 10 balls in the dirt: middle, glove side, arm side. Player drops, blocks, and keeps the ball in front.",
        "scoring": "Ball kept within reach in front = 1. Log made/attempts.",
        "positions": ["C"],
        "stat_keys": ["catching.pb", "catching.cs_pct"],
    },
    {
        "id": "catcher_pop_time",
        "name": "Catcher Pop Time",
        "category": "Catching",
        "unit": "seconds",
        "bounds": [2.0, 4.5],
        "how_to": "Player in full gear. Coach pitches from the mound; on the catch, player throws down to 2B. Stopwatch from glove pop to glove pop at 2B. Best of 3 throws.",
        "scoring": "Log the best time in seconds (lower is better).",
        "positions": ["C"],
        "stat_keys": ["catching.cs_pct", "catching.sb"],
    },
    {
        "id": "pitch_strikes",
        "name": "Pitching Strike Challenge",
        "category": "Pitching",
        "unit": "count",
        "default_attempts": 15,
        "how_to": "Player pitches from the rubber to a catcher or strike-zone net at game distance. 15 pitches at game effort.",
        "scoring": "Strike = 1. Log strikes/15.",
        "positions": ["P"],
        "stat_keys": ["pitching_advanced.s_pct", "pitching.whip", "pitching_advanced.k_bb"],
    },
    {
        "id": "home_to_first",
        "name": "Home-to-First Sprint",
        "category": "Speed",
        "unit": "seconds",
        "bounds": [3.5, 7.0],
        "how_to": "Player takes a full swing at the plate (no ball needed) and sprints through 1B. Stopwatch from contact motion to the bag. Best of 2 runs.",
        "scoring": "Log the best time in seconds (lower is better).",
        "positions": ["2B", "SS", "CF"],
        "stat_keys": ["batting.sb", "batting.sb_pct"],
    },
    {
        "id": "tee_line_drives",
        "name": "Tee / Front-Toss Contact",
        "category": "Hitting",
        "unit": "count",
        "default_attempts": 10,
        "how_to": "Player takes 10 swings off the tee or front toss. Coach judges contact quality: hard line drive or hard ground ball counts.",
        "scoring": "Hard contact = 1. Log made/attempts.",
        "positions": [],
        "stat_keys": ["batting.avg", "batting_advanced.qab_pct", "batting_advanced.ld_pct"],
    },
    {
        "id": "bunt_placement",
        "name": "Bunt Placement",
        "category": "Hitting",
        "unit": "count",
        "default_attempts": 10,
        "how_to": "Live or machine pitches. Player squares and bunts: 5 toward 3B line, 5 toward 1B line. Fair and inside the grass line counts.",
        "scoring": "Fair, well-placed bunt = 1. Log made/attempts.",
        "positions": [],
        "stat_keys": ["batting.sac", "batting_advanced.c_pct"],
    },
]

_DRILLS_BY_ID = {d["id"]: d for d in EVAL_DRILLS}

# ── Position Profiles ─────────────────────────────────────────────────────
# Per position: which drills gauge it (weighted) and which last-season stats
# back it up (weighted; "dir" -1 means lower is better). Stats are min-max
# normalized across the roster, so weights only express relative importance.
POSITION_PROFILES = {
    "P": {
        "drills": {"pitch_strikes": 1.5, "arm_accuracy": 0.5},
        "stats": {
            "pitching_advanced.s_pct": {"weight": 1.2, "dir": 1},
            "pitching.whip": {"weight": 1.0, "dir": -1},
            "pitching_advanced.k_bb": {"weight": 0.8, "dir": 1},
            "pitching.baa": {"weight": 0.6, "dir": -1},
        },
    },
    "C": {
        "drills": {"catcher_pop_time": 1.2, "catcher_blocking": 1.2, "arm_accuracy": 0.6},
        "stats": {
            "catching.cs_pct": {"weight": 1.2, "dir": 1},
            "catching.pb": {"weight": 1.0, "dir": -1},
            "fielding.fpct": {"weight": 0.6, "dir": 1},
        },
    },
    "1B": {
        "drills": {"first_base_scoops": 1.3, "if_ground_balls": 1.0},
        "stats": {
            "fielding.po": {"weight": 1.0, "dir": 1},
            "fielding.fpct": {"weight": 1.0, "dir": 1},
            "fielding.e": {"weight": 0.6, "dir": -1},
        },
    },
    "2B": {
        "drills": {"if_ground_balls": 1.2, "if_transfer": 1.0, "arm_accuracy": 0.8, "home_to_first": 0.5},
        "stats": {
            "fielding.fpct": {"weight": 1.1, "dir": 1},
            "fielding.a": {"weight": 0.9, "dir": 1},
            "fielding.dp": {"weight": 0.6, "dir": 1},
        },
    },
    "3B": {
        "drills": {"if_ground_balls": 1.2, "arm_accuracy": 1.2, "long_toss": 0.6},
        "stats": {
            "fielding.a": {"weight": 1.1, "dir": 1},
            "fielding.fpct": {"weight": 1.0, "dir": 1},
            "fielding.e": {"weight": 0.6, "dir": -1},
        },
    },
    "SS": {
        "drills": {"if_ground_balls": 1.3, "arm_accuracy": 1.1, "if_transfer": 1.0, "home_to_first": 0.6},
        "stats": {
            "fielding.a": {"weight": 1.2, "dir": 1},
            "fielding.fpct": {"weight": 1.0, "dir": 1},
            "fielding.dp": {"weight": 0.6, "dir": 1},
            "fielding.e": {"weight": 0.6, "dir": -1},
        },
    },
    "LF": {
        "drills": {"of_pop_flies": 1.3, "long_toss": 0.8},
        "stats": {
            "fielding.po": {"weight": 1.0, "dir": 1},
            "fielding.fpct": {"weight": 1.0, "dir": 1},
        },
    },
    "CF": {
        "drills": {"of_pop_flies": 1.4, "home_to_first": 1.0, "long_toss": 0.8},
        "stats": {
            "fielding.po": {"weight": 1.0, "dir": 1},
            "fielding.fpct": {"weight": 1.0, "dir": 1},
            "batting.sb": {"weight": 0.6, "dir": 1},
        },
    },
    "RF": {
        "drills": {"of_pop_flies": 1.3, "long_toss": 1.1, "arm_accuracy": 0.6},
        "stats": {
            "fielding.po": {"weight": 1.0, "dir": 1},
            "fielding.a": {"weight": 0.8, "dir": 1},
            "fielding.fpct": {"weight": 1.0, "dir": 1},
        },
    },
}

# Weight split between fresh eval drills and last-season stats when a player
# has both. New players (no stats) score on drills alone; a returning player
# with no drill logged yet scores on stats alone.
DRILL_WEIGHT = 0.6
STAT_WEIGHT = 0.4


# ── Records ───────────────────────────────────────────────────────────────

def sanitize_records(raw: Any) -> tuple[list[dict], list[str]]:
    """Validate a raw records list. Returns (clean_records, error_strings).

    A record: {"player": str, "drill_id": str, "made": int, "attempts": int,
               "value": float (seconds drills), "date": str, "notes": str}
    Count drills need made/attempts; seconds drills need value.
    """
    errors: list[str] = []
    if not isinstance(raw, list):
        return [], ["records_must_be_list"]
    if len(raw) > MAX_RECORDS:
        return [], [f"too_many_records_max_{MAX_RECORDS}"]

    clean: list[dict] = []
    for i, rec in enumerate(raw):
        if not isinstance(rec, dict):
            errors.append(f"record_{i}_not_object")
            continue
        player = str(rec.get("player") or "").strip()[:MAX_NAME_LEN]
        drill_id = str(rec.get("drill_id") or "").strip()
        drill = _DRILLS_BY_ID.get(drill_id)
        if not player or drill is None:
            errors.append(f"record_{i}_bad_player_or_drill")
            continue

        out = {
            "player": player,
            "drill_id": drill_id,
            "made": None,
            "attempts": None,
            "value": None,
            "date": str(rec.get("date") or "").strip()[:32],
            "notes": str(rec.get("notes") or "").strip()[:MAX_NOTES_LEN],
        }
        if drill["unit"] == "seconds":
            try:
                value = float(rec.get("value"))
            except (TypeError, ValueError):
                errors.append(f"record_{i}_bad_value")
                continue
            if not (0 < value <= MAX_TIMED_VALUE):
                errors.append(f"record_{i}_value_out_of_range")
                continue
            out["value"] = round(value, 2)
        else:
            try:
                made = int(rec.get("made"))
                attempts = int(rec.get("attempts"))
            except (TypeError, ValueError):
                errors.append(f"record_{i}_bad_made_attempts")
                continue
            if not (1 <= attempts <= MAX_ATTEMPTS) or not (0 <= made <= attempts):
                errors.append(f"record_{i}_made_attempts_out_of_range")
                continue
            out["made"] = made
            out["attempts"] = attempts
        clean.append(out)
    return clean, errors


def drill_score(record: dict) -> float | None:
    """Normalize one record to 0..1 (1 = best). None if unscorable."""
    drill = _DRILLS_BY_ID.get(record.get("drill_id"))
    if drill is None:
        return None
    if drill["unit"] == "seconds":
        value = record.get("value")
        if not isinstance(value, (int, float)):
            return None
        best, worst = drill["bounds"]
        return round(max(0.0, min(1.0, (worst - float(value)) / (worst - best))), 3)
    made, attempts = record.get("made"), record.get("attempts")
    if not isinstance(made, (int, float)) or not attempts:
        return None
    return round(max(0.0, min(1.0, float(made) / float(attempts))), 3)


def latest_drill_scores(records: list[dict]) -> dict[str, dict[str, float]]:
    """{player: {drill_id: score}} — later records win (the log is
    append-ordered, so a re-test replaces the earlier score)."""
    scores: dict[str, dict[str, float]] = {}
    for rec in records:
        s = drill_score(rec)
        if s is None:
            continue
        scores.setdefault(rec["player"], {})[rec["drill_id"]] = s
    return scores


# ── Last-season stats ─────────────────────────────────────────────────────

def _player_name(player: dict) -> str:
    return f"{player.get('first', '')} {player.get('last', '')}".strip()


def _stat(player: dict, path: str) -> float | None:
    node: Any = player
    for key in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    try:
        return float(node)
    except (TypeError, ValueError):
        return None


def is_returning(player: dict) -> bool:
    """A player with any recorded plate appearance or fielding chance last
    season counts as returning (has usable history)."""
    for path in ("batting.pa", "fielding.tc", "pitching.bf"):
        v = _stat(player, path)
        if v and v > 0:
            return True
    return False


def _normalized_stats(roster: list[dict]) -> dict[str, dict[str, float]]:
    """Min-max normalize every stat referenced by any position profile across
    the roster. Returns {player_name: {stat_path: 0..1}} (1 = best, direction
    already applied). Players missing a stat simply lack the key."""
    stat_paths = sorted({p for prof in POSITION_PROFILES.values() for p in prof["stats"]})
    raw: dict[str, dict[str, float]] = {}
    for player in roster:
        name = _player_name(player)
        if not name:
            continue
        for path in stat_paths:
            v = _stat(player, path)
            if v is not None:
                raw.setdefault(name, {})[path] = v

    norm: dict[str, dict[str, float]] = {name: {} for name in raw}
    for path in stat_paths:
        values = [stats[path] for stats in raw.values() if path in stats]
        if not values:
            continue
        lo, hi = min(values), max(values)
        direction = next(
            (prof["stats"][path]["dir"] for prof in POSITION_PROFILES.values() if path in prof["stats"]),
            1,
        )
        for name, stats in raw.items():
            if path not in stats:
                continue
            if hi == lo:
                scaled = 0.5
            else:
                scaled = (stats[path] - lo) / (hi - lo)
            norm[name][path] = round(scaled if direction > 0 else 1.0 - scaled, 3)
    return norm


# ── Position fit ──────────────────────────────────────────────────────────

def compute_position_fits(team: dict, records: list[dict]) -> dict:
    """Rank every roster player's fit for each position.

    fit = DRILL_WEIGHT * drill_component + STAT_WEIGHT * stat_component,
    renormalized over whichever components have data. Returns
    {"positions": {pos: [entry, ...ranked]}, "players": {name: {pos: fit}}}
    with fits on a 0-100 scale (None = no data at all for that position).
    """
    roster = [p for p in (team.get("roster") or []) if isinstance(p, dict)]
    core = [p for p in roster if p.get("core") is not False and not p.get("borrowed")]
    drill_by_player = latest_drill_scores(records)
    stats_by_player = _normalized_stats(roster)

    # Names present only in the eval log (brand-new players not yet on the
    # GC roster export) still get ranked on their drills.
    names = [_player_name(p) for p in core if _player_name(p)]
    returning = {_player_name(p): is_returning(p) for p in core}
    for name in drill_by_player:
        if name not in names:
            names.append(name)
            returning.setdefault(name, False)

    positions_out: dict[str, list[dict]] = {}
    players_out: dict[str, dict[str, Any]] = {name: {} for name in names}

    for pos in POSITIONS:
        profile = POSITION_PROFILES[pos]
        ranked = []
        for name in names:
            d_scores = drill_by_player.get(name, {})
            d_num = d_den = 0.0
            drills_logged = 0
            for drill_id, weight in profile["drills"].items():
                if drill_id in d_scores:
                    d_num += weight * d_scores[drill_id]
                    d_den += weight
                    drills_logged += 1
            drill_component = (d_num / d_den) if d_den else None

            s_scores = stats_by_player.get(name, {})
            s_num = s_den = 0.0
            for path, spec in profile["stats"].items():
                if path in s_scores:
                    s_num += spec["weight"] * s_scores[path]
                    s_den += spec["weight"]
            stat_component = (s_num / s_den) if s_den else None

            weight_total = fit_sum = 0.0
            if drill_component is not None:
                fit_sum += DRILL_WEIGHT * drill_component
                weight_total += DRILL_WEIGHT
            if stat_component is not None:
                fit_sum += STAT_WEIGHT * stat_component
                weight_total += STAT_WEIGHT
            fit = round(100 * fit_sum / weight_total, 1) if weight_total else None

            ranked.append({
                "name": name,
                "fit": fit,
                "drill_score": round(100 * drill_component, 1) if drill_component is not None else None,
                "stat_score": round(100 * stat_component, 1) if stat_component is not None else None,
                "drills_logged": drills_logged,
                "returning": bool(returning.get(name)),
            })
            players_out[name][pos] = fit

        ranked.sort(key=lambda e: (e["fit"] is None, -(e["fit"] or 0), e["name"]))
        positions_out[pos] = ranked

    return {"positions": positions_out, "players": players_out}


def build_eval_payload(team: dict, records: list[dict], generated_at: str = "") -> dict:
    """Full /api/evals payload: drill library, key stats per position, the
    record log, and computed position fits."""
    fits = compute_position_fits(team, records)
    roster = [p for p in (team.get("roster") or []) if isinstance(p, dict)]
    return {
        "generated_at": generated_at,
        "team_name": team.get("team_name", ""),
        "drills": EVAL_DRILLS,
        "positions": POSITIONS,
        "position_stats": {
            pos: [{"stat": path, "weight": spec["weight"], "lower_is_better": spec["dir"] < 0}
                  for path, spec in POSITION_PROFILES[pos]["stats"].items()]
            for pos in POSITIONS
        },
        "records": records,
        "fits": fits,
        "roster": [
            {"name": _player_name(p), "number": p.get("number"), "returning": is_returning(p),
             "core": p.get("core") is not False and not p.get("borrowed")}
            for p in roster if _player_name(p)
        ],
    }


# ── CLI ───────────────────────────────────────────────────────────────────

def _load_team(team_dir: Path) -> dict:
    for candidate in ("team_enriched.json", "team_merged.json", "team.json"):
        path = team_dir / candidate
        if path.exists():
            try:
                data = json.loads(path.read_text())
                if isinstance(data, dict):
                    return data
            except (OSError, ValueError) as e:
                logging.warning("[EvalEngine] failed reading %s: %s", path, e)
    return {}


def run(team_dir: Path) -> dict:
    """Read eval_records.json + team stats from team_dir, write evals.json."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    records_path = team_dir / "eval_records.json"
    raw = []
    if records_path.exists():
        try:
            raw = json.loads(records_path.read_text())
        except (OSError, ValueError) as e:
            logging.warning("[EvalEngine] failed reading %s: %s", records_path, e)
    records, errors = sanitize_records(raw)
    if errors:
        logging.warning("[EvalEngine] dropped %d invalid records: %s", len(errors), errors[:5])

    team = _load_team(team_dir)
    payload = build_eval_payload(
        team, records,
        generated_at=datetime.now(ZoneInfo("America/New_York")).isoformat(),
    )
    team_dir.mkdir(parents=True, exist_ok=True)
    out_path = team_dir / "evals.json"
    tmp_path = out_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2))
    tmp_path.replace(out_path)
    logging.info("[EvalEngine] wrote %s (%d records, %d players ranked)",
                 out_path, len(records), len(payload["fits"]["players"]))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute player-eval position fits.")
    parser.add_argument("--team", default="sharks",
                        help="team data_slug from config/teams.yaml (default: sharks)")
    args = parser.parse_args()

    data_slug = args.team
    try:
        from team_registry import require_by_slug
        data_slug = require_by_slug(args.team).data_slug
    except Exception:
        # Registry unavailable (env-only setups) — fall back to the raw slug.
        pass
    run(DATA_DIR / data_slug)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
