"""
Practice Plan Generator for Softball
Maps identified weaknesses from SWOT analysis to targeted drills.
Generates structured practice plans in the user's existing format.
"""

import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent.parent / "data"
SHARKS_DIR = DATA_DIR / "sharks"
ET_TZ = ZoneInfo("America/New_York")
GAME_DURATION_HOURS = 2.5
PRACTICE_DURATION_HOURS = 1.5
PLANNING_COOLDOWN_HOURS = 1.0
PRACTICE_REFRESH_LEAD_HOURS = 1.0
PLAN_FILE = SHARKS_DIR / "next_practice.txt"
PLAN_META_FILE = SHARKS_DIR / "next_practice_meta.json"


# ── Drill Library ─────────────────────────────────────────────────────────
# Each drill maps to specific weaknesses it addresses.
# Format follows the user's existing practice plan structure from Google Docs.

DRILL_LIBRARY = {
    # ── HITTING DRILLS ──
    "soft_toss": {
        "name": "Soft-Toss",
        "duration": 15,
        "targets": ["low_ba", "high_k_rate", "low_contact"],
        "setup": "One player at plate. Other players fielding.",
        "instructions": [
            "Player stands ready to hit with \"tosser\" facing 4-5 feet away.",
            "Softly toss balls so that they begin at top of strike zone and fall towards front of plate.",
            "Batter hits ball on downward arc.",
            "Game: Let batter run to 1st on 10th hit.",
        ],
        "objective": "Hand-eye coordination, bat control, contact consistency.",
    },
    "pepper_drill": {
        "name": "Pepper Drill",
        "duration": 15,
        "targets": ["low_ba", "high_k_rate", "bat_control"],
        "setup": "3-5 fielders side-by-side, facing one batter 12-15 feet away.",
        "instructions": [
            "Fielders throw an easy pitch that batter can hit (soft balls).",
            "Batter tries to hit soft ground ball back to fielders who field ball and pitch again.",
            "Key: Emphasize soft swings and ground balls.",
        ],
        "objective": "Hand-eye coordination, bat control, and intentional energy dampening.",
    },
    "tee_work": {
        "name": "Tee Work Stations",
        "duration": 20,
        "targets": ["low_ba", "low_slg", "swing_mechanics"],
        "setup": "Set up 3 tee stations: inside pitch, middle, outside pitch.",
        "instructions": [
            "Groups of 3-4 rotate through stations.",
            "Inside: Focus on pulling hands in, driving ball to pull side.",
            "Middle: Level swing, drive up the middle.",
            "Outside: Extend arms, hit to opposite field.",
            "10 swings per station, rotate.",
        ],
        "objective": "Hit all pitch locations, develop swing mechanics for full zone coverage.",
    },
    "live_bp": {
        "name": "Live Batting Practice",
        "duration": 25,
        "targets": ["low_ba", "low_obp", "game_hitting"],
        "setup": "Full infield/outfield defense. Pitcher on mound.",
        "instructions": [
            "Each batter gets 8-10 pitches.",
            "First 3: focus on making contact with any pitch.",
            "Next 3: work on driving the ball.",
            "Final 2-4: simulate game situations (2 strikes, runner on 2nd, etc.).",
            "Fielders play every ball live.",
        ],
        "objective": "Game-speed hitting, pitch recognition, situational awareness.",
    },
    "bunting_practice": {
        "name": "Bunting Stations",
        "duration": 15,
        "targets": ["low_obp", "baserunning", "small_ball"],
        "setup": "Pitcher on mound. Batter at plate. First baseman and third baseman in position.",
        "instructions": [
            "Sacrifice bunt: square early, angle bat toward 1st or 3rd.",
            "Drag bunt: show late, push ball past pitcher.",
            "5 attempts each type per batter.",
            "Key: Bat angle controls direction. Soft hands.",
        ],
        "objective": "Add bunting to offensive arsenal, improve on-base options.",
    },

    # ── PITCHING DRILLS ──
    "target_pitching": {
        "name": "Target Pitching",
        "duration": 20,
        "targets": ["high_era", "high_whip", "control_issues"],
        "setup": "Pitcher on mound, catcher with strike zone target.",
        "instructions": [
            "Set up target zones: inside low, outside low, middle.",
            "Pitcher throws 5 to each zone.",
            "Focus on hitting glove, not throwing hard.",
            "Key: Location > velocity at youth level.",
            "Game: Points for hitting each zone.",
        ],
        "objective": "Improve pitch location accuracy, reduce walks.",
    },
    "pitch_count_sim": {
        "name": "Pitch Count Simulation",
        "duration": 15,
        "targets": ["high_era", "high_bb_rate", "stamina"],
        "setup": "Pitcher, catcher, and one batter standing in (no swing).",
        "instructions": [
            "Simulate 3-inning outing: call balls and strikes.",
            "Track pitch count per inning.",
            "Goal: Fewer than 12 pitches per inning.",
            "Discuss: What caused extra pitches? How to be more efficient?",
        ],
        "objective": "Pitch efficiency, working ahead in counts.",
    },

    # ── FIELDING DRILLS ──
    "ground_ball_circuit": {
        "name": "Ground Ball Circuit",
        "duration": 20,
        "targets": ["low_fielding_pct", "errors", "fielding_fundamentals"],
        "setup": "Players at SS, 2B, 3B, 1B. Coach with bucket of balls at home.",
        "instructions": [
            "Coach hits ground balls to each position in sequence.",
            "Fielder fields cleanly, throws to 1st.",
            "After throw, rotate one position to the right.",
            "Key: Get in front of ball, field with two hands, quick transfer.",
            "Game: Team must make 10 clean plays in a row.",
        ],
        "objective": "Clean fielding mechanics, accurate throws to first.",
    },
    "fly_ball_communication": {
        "name": "Fly Ball Communication",
        "duration": 15,
        "targets": ["low_fielding_pct", "outfield_errors", "communication"],
        "setup": "Outfielders in LF, CF, RF. Infielders in gaps.",
        "instructions": [
            "Coach hits fly balls to gaps between fielders.",
            "Player calling ball MUST call 'MINE' or 'I GOT IT' loudly.",
            "Other players back up and call 'YOURS'.",
            "Key: First call wins. If no call, ball drops = error.",
        ],
        "objective": "Eliminate dropped balls from miscommunication.",
    },
    "cutoff_relay": {
        "name": "Cutoffs and Relays",
        "duration": 15,
        "targets": ["low_fielding_pct", "throwing_accuracy", "game_iq"],
        "setup": "SS, 2B in cutoff positions. Outfielders in LF, CF.",
        "instructions": [
            "Hit ball to outfielder in left. SS runs out halfway with hands up, calling for ball.",
            "Outfielder throws to SS (cutoff), who throws in to 2nd base.",
            "Key: Balls hit to left = SS cutoff. Balls hit to right = 2B cutoff.",
            "Rotate outfielders and cutoff positions.",
        ],
        "objective": "Proper cutoff alignment, quick relay throws.",
    },

    # ── BASERUNNING DRILLS ──
    "baserunning_431": {
        "name": "4-3-2-1",
        "duration": 15,
        "targets": ["slow_baserunning", "base_path", "conditioning"],
        "setup": "All players line up behind home plate.",
        "instructions": [
            "All run 4x to 1st, 3x to 2nd, twice to 3rd, once all around.",
            "Focus on running THROUGH 1st base (don't slow down).",
            "Game: Miss base or slow down, team restarts.",
        ],
        "objective": "Baserunning conditioning, speed, proper path through 1st.",
    },
    "lead_and_steal": {
        "name": "Lead-offs and Stealing",
        "duration": 20,
        "targets": ["low_sb_rate", "baserunning", "aggressiveness"],
        "setup": "Runners at each base. Pitcher on mound. Catcher at home.",
        "instructions": [
            "Pitcher delivers, runners take leads and read steal opportunities.",
            "On steal: explosive first 3 steps, slide into base.",
            "Catcher works on quick release to throw out runners.",
            "Track: successes vs caught stealing.",
        ],
        "objective": "Improve stolen base success rate and aggressiveness.",
    },
    "pickle_drill": {
        "name": "Pickle Drill",
        "duration": 20,
        "targets": ["baserunning", "fielding_agility", "game_iq"],
        "setup": "Players at SS, 3B, LF, CF. Remaining players are baserunners.",
        "instructions": [
            "Runner rounds 2nd and goes halfway to 3rd. Coach throws ball from LF to 3rd.",
            "Runner is now in a 'Pickle'.",
            "Fielders try getting runner out with fewest throws necessary.",
            "Game: Also play between 1st/2nd/3rd/home. Points for safe/out.",
        ],
        "objective": "Rundown execution, baserunning under pressure.",
    },

    # ── GENERAL / FUN ──
    "strike_at_home": {
        "name": "Strike at Home (Fun Ending Game)",
        "duration": 15,
        "targets": ["throwing_accuracy", "fun", "arm_strength"],
        "setup": "All players at 2nd base. Bucket on home plate.",
        "instructions": [
            "Each throws 3 balls to hit bucket.",
            "If you hit the bucket, advance to next round. Last player standing wins.",
            "Move forward/back for variety, tie-breaker if needed.",
        ],
        "objective": "Accurate low throws, fun competition.",
    },
    "live_situations": {
        "name": "Live Situations",
        "duration": 20,
        "targets": ["game_iq", "decision_making", "overall"],
        "setup": "Full defensive alignment. Runners on bases.",
        "instructions": [
            "Assign player to each defensive position. Remaining players run bases.",
            "Hit balls various places on field and play as if live game.",
            "Rotate runners to fielding positions and vice-versa.",
            "Before each hit, call out situation (e.g. 'runner on 2nd, one out').",
        ],
        "objective": "Game-speed decision making, situational awareness.",
    },
}


# ── Weakness-to-Drill Mapping ────────────────────────────────────────────

WEAKNESS_DRILL_MAP = {
    "Low batting average": ["soft_toss", "tee_work", "pepper_drill", "live_bp"],
    "Struggles to reach base": ["soft_toss", "bunting_practice", "live_bp"],
    "Limited power": ["tee_work", "live_bp"],
    "Below-average production": ["tee_work", "soft_toss", "live_bp"],
    "High strikeout rate": ["soft_toss", "pepper_drill", "tee_work"],
    "Rarely walks": ["bunting_practice", "live_bp"],
    "High ERA": ["target_pitching", "pitch_count_sim"],
    "High WHIP": ["target_pitching", "pitch_count_sim"],
    "Low strikeout rate": ["target_pitching"],
    "Control issues": ["target_pitching", "pitch_count_sim"],
    "Error-prone fielding": ["ground_ball_circuit", "fly_ball_communication", "cutoff_relay"],
    "Inefficient on the bases": ["baserunning_431", "lead_and_steal", "pickle_drill"],
}


MATCHUP_DRILL_BOOSTS: dict[str, list[str]] = {
    "Higher team batting average": ["ground_ball_circuit", "fly_ball_communication", "cutoff_relay", "target_pitching"],
    "Higher team OBP": ["target_pitching", "pitch_count_sim", "ground_ball_circuit"],
    "Higher team slugging": ["target_pitching", "cutoff_relay", "fly_ball_communication"],
    "More aggressive baserunning": ["pickle_drill", "cutoff_relay", "ground_ball_circuit"],
    "Better pitching control": ["soft_toss", "tee_work", "live_bp", "bunting_practice"],
    "Lower ERA": ["soft_toss", "tee_work", "pepper_drill", "live_bp"],
    "Lower WHIP": ["soft_toss", "bunting_practice", "live_bp"],
    "Better fielding": ["soft_toss", "tee_work", "live_bp"],
}

EXPLOIT_DRILL_BOOSTS: dict[str, list[str]] = {
    "Higher team batting average": ["live_bp", "tee_work"],
    "Higher team OBP": ["bunting_practice", "live_bp"],
    "More aggressive baserunning": ["lead_and_steal", "baserunning_431"],
    "Better fielding": ["ground_ball_circuit", "fly_ball_communication"],
    "Better pitching control": ["target_pitching", "pitch_count_sim"],
}


def map_weaknesses_to_drills(
    swot_analysis: dict,
    matchup: dict | None = None,
) -> list[dict]:
    """Map team weaknesses to recommended drills with priority.

    If *matchup* is provided (from analyze_matchup()), boost drills that
    counter the opponent's strengths and exploit their weaknesses.
    """
    team_weaknesses = swot_analysis.get("team_swot", {}).get("weaknesses", [])

    drill_scores: dict[str, int] = {}
    drill_reasons: dict[str, list[str]] = {}

    for weakness in team_weaknesses:
        label = weakness.split("(")[0].strip()
        drills = WEAKNESS_DRILL_MAP.get(label, [])
        for drill_id in drills:
            drill_scores[drill_id] = drill_scores.get(drill_id, 0) + 1
            if drill_id not in drill_reasons:
                drill_reasons[drill_id] = []
            drill_reasons[drill_id].append(label)

    for pa in swot_analysis.get("player_analyses", []):
        for weakness in pa.get("swot", {}).get("weaknesses", []):
            label = weakness.split("(")[0].strip()
            drills = WEAKNESS_DRILL_MAP.get(label, [])
            for drill_id in drills:
                drill_scores[drill_id] = drill_scores.get(drill_id, 0) + 1

    # ── Matchup-aware boosting ───────────────────────────────────────────
    if matchup and not matchup.get("empty"):
        opponent_name = matchup.get("opponent", "")
        # Counter their strengths: boost defensive/pitching drills
        for adv in matchup.get("their_advantages", []):
            for pattern, boosts in MATCHUP_DRILL_BOOSTS.items():
                if pattern.lower() in adv.lower():
                    for drill_id in boosts:
                        drill_scores[drill_id] = drill_scores.get(drill_id, 0) + 2
                        if drill_id not in drill_reasons:
                            drill_reasons[drill_id] = []
                        drill_reasons[drill_id].append(f"Counter {opponent_name}: {pattern}")
        # Exploit our advantages: sharpen what we're already good at
        for adv in matchup.get("our_advantages", []):
            for pattern, boosts in EXPLOIT_DRILL_BOOSTS.items():
                if pattern.lower() in adv.lower():
                    for drill_id in boosts:
                        drill_scores[drill_id] = drill_scores.get(drill_id, 0) + 1
                        if drill_id not in drill_reasons:
                            drill_reasons[drill_id] = []
                        drill_reasons[drill_id].append(f"Exploit vs {opponent_name}: {pattern}")

    # Sort by priority (most needed first)
    sorted_drills = sorted(drill_scores.items(), key=lambda x: x[1], reverse=True)

    recommendations = []
    for drill_id, score in sorted_drills:
        drill = DRILL_LIBRARY.get(drill_id)
        if drill:
            recommendations.append({
                "drill_id": drill_id,
                "priority_score": score,
                "reasons": drill_reasons.get(drill_id, []),
                **drill,
            })

    return recommendations


def generate_practice_plan(
    swot_analysis: dict,
    duration_minutes: int = 120,
    date: str | None = None,
    matchup: dict | None = None,
) -> str:
    """
    Generate a structured practice plan based on SWOT weaknesses.
    If *matchup* is provided, drills are biased toward countering
    the next opponent's strengths and exploiting their weaknesses.
    Output format matches the user's existing Google Doc practice plan style.
    """
    if date is None:
        now = datetime.now(ET_TZ)
        date = f"{now.month}/{now.day}/{now.year}"

    drills = map_weaknesses_to_drills(swot_analysis, matchup=matchup)
    if not drills:
        drills = [
            DRILL_LIBRARY["baserunning_431"],
            DRILL_LIBRARY["soft_toss"],
            DRILL_LIBRARY["ground_ball_circuit"],
            DRILL_LIBRARY["live_situations"],
            DRILL_LIBRARY["strike_at_home"],
        ]

    # Build header with optional opponent context
    opponent_name = ""
    if matchup and not matchup.get("empty"):
        opponent_name = matchup.get("opponent", "")

    plan_lines = [f"{date}"]
    if opponent_name:
        plan_lines.append(f"Prep for: {opponent_name}")
    reason_set = set(r for d in drills[:5] for r in d.get("reasons", ["general development"])[:2])
    plan_lines.append(
        f"Objectives: Address identified weaknesses — "
        + ", ".join(reason_set)
        + ". Emphasize fun, safety, rotation, proper form.",
    )

    # Build practice plan
    remaining_time = duration_minutes
    drill_num = 1

    # 1. Warmup (always first)
    plan_lines.append(f"{drill_num}. Stretch/Warmup (15 min)")
    plan_lines.append("   * Dynamic stretches: Arm circles (10 forward/backward each arm), shoulder rolls, wrist rotations.")
    plan_lines.append("   * Leg stretches: Butterflies, quad pulls, hamstring reaches.")
    plan_lines.append("   * Light jog: 1 lap around the field.")
    plan_lines.append("   * Objective: Increase flexibility, prevent injury, prepare body for activity.")
    remaining_time -= 15
    drill_num += 1

    # 2. Add targeted drills based on weaknesses
    water_break_added = False
    for drill in drills:
        if remaining_time < drill.get("duration", 15) + 5:
            break

        # Add water break halfway through
        if not water_break_added and remaining_time < duration_minutes * 0.55:
            plan_lines.append(f"{drill_num}. Water Break (5 min)")
            remaining_time -= 5
            drill_num += 1
            water_break_added = True

        dur = drill.get("duration", 15)
        plan_lines.append(f"{drill_num}. {drill['name']} ({dur} min)")
        plan_lines.append(f"   * {drill.get('setup', '')}")
        for instruction in drill.get("instructions", []):
            plan_lines.append(f"   * {instruction}")
        plan_lines.append(f"   * Objective: {drill.get('objective', '')}")
        remaining_time -= dur
        drill_num += 1

    # Always end with something fun
    if remaining_time >= 15:
        fun_drill = DRILL_LIBRARY["strike_at_home"]
        plan_lines.append(f"{drill_num}. {fun_drill['name']} ({fun_drill['duration']} min)")
        for instruction in fun_drill.get("instructions", []):
            plan_lines.append(f"   * {instruction}")
        plan_lines.append(f"   * Objective: {fun_drill.get('objective', '')}")

    return "\n".join(plan_lines)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _normalize_date_str(date_str: str) -> str:
    raw = (date_str or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", raw):
        dt = datetime.strptime(raw, "%m/%d/%Y")
        return dt.strftime("%Y-%m-%d")
    return raw


def _parse_event_datetime(date_str: str, time_str: str = "", default_time: str = "12:00 PM") -> datetime | None:
    date_part = _normalize_date_str(date_str)
    if not date_part:
        return None
    time_part = (time_str or "").strip() or default_time
    date_time = f"{date_part} {time_part}".strip()
    candidates = [
        ("%Y-%m-%d %I:%M %p", date_time),
        ("%Y-%m-%d %I %p", date_time),
        ("%Y-%m-%d %H:%M", date_time),
        ("%Y-%m-%d", date_part),
    ]
    for fmt, text in candidates:
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=ET_TZ)
        except ValueError:
            continue
    return None


def _extract_time_hint(raw_event: dict[str, Any]) -> str:
    for key in ("time", "start_time", "start", "practice_time"):
        val = str(raw_event.get(key, "")).strip()
        if val:
            return val
    title = str(raw_event.get("title", "")).strip()
    if title:
        match = re.search(r"\b(\d{1,2}(?::\d{2})?\s*[APMapm]{2})\b", title)
        if match:
            return match.group(1).upper().replace("  ", " ")
    return ""


def _load_practice_events(now: datetime) -> list[dict[str, Any]]:
    rsvp_file = SHARKS_DIR / "practice_rsvp.json"
    data = _load_json(rsvp_file, {})
    if not isinstance(data, dict):
        return []

    raw_events: list[dict[str, Any]] = []
    if isinstance(data.get("next"), dict):
        raw_events.append(data["next"])
    if isinstance(data.get("practices"), list):
        raw_events.extend([p for p in data["practices"] if isinstance(p, dict)])

    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for raw in raw_events:
        date_str = str(raw.get("date", "")).strip()
        if not date_str:
            continue
        time_hint = _extract_time_hint(raw)
        start = _parse_event_datetime(date_str, time_hint, default_time="6:00 PM")
        if not start:
            continue
        title = str(raw.get("title", "Practice")).strip() or "Practice"
        key = (_normalize_date_str(date_str), time_hint, title)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "kind": "practice",
                "title": title,
                "start": start,
                "end": start + timedelta(hours=PRACTICE_DURATION_HOURS),
                "is_future": start > now,
            }
        )
    out.sort(key=lambda e: e["start"])
    return out


def _clean_opponent_name(name: str) -> str:
    cleaned = (name or "").strip()
    for prefix in ("@ ", "vs. ", "vs "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    return cleaned.strip()


def _load_game_events(now: datetime) -> list[dict[str, Any]]:
    schedule = _load_json(SHARKS_DIR / "schedule_manual.json", {})
    if not isinstance(schedule, dict):
        return []
    rows = []
    for section in ("past", "upcoming"):
        payload = schedule.get(section, [])
        if isinstance(payload, list):
            rows.extend([r for r in payload if isinstance(r, dict)])

    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("is_game") is False:
            continue
        date_str = str(row.get("date", "")).strip()
        if not date_str:
            continue
        start = _parse_event_datetime(date_str, str(row.get("time", "")).strip(), default_time="12:00 PM")
        if not start:
            continue
        opponent = _clean_opponent_name(str(row.get("opponent", "Game")).strip() or "Game")
        out.append(
            {
                "kind": "game",
                "title": opponent,
                "start": start,
                "end": start + timedelta(hours=GAME_DURATION_HOURS),
                "is_future": start > now,
            }
        )
    out.sort(key=lambda e: e["start"])
    return out


def _compute_windows(now: datetime) -> dict[str, Any]:
    practice_events = _load_practice_events(now)
    game_events = _load_game_events(now)
    completed = [e for e in (practice_events + game_events) if e["end"] <= now]
    latest_completed = max(completed, key=lambda e: e["end"]) if completed else None
    latest_completed_end = latest_completed["end"] if latest_completed else None
    planning_allowed_after = (
        latest_completed_end + timedelta(hours=PLANNING_COOLDOWN_HOURS)
        if latest_completed_end
        else now
    )

    next_practice = next((p for p in practice_events if p["start"] >= now), None)
    next_practice_start = next_practice["start"] if next_practice else None
    refresh_window_start = (
        next_practice_start - timedelta(hours=PRACTICE_REFRESH_LEAD_HOURS)
        if next_practice_start
        else None
    )

    return {
        "latest_completed_event": latest_completed,
        "latest_completed_end": latest_completed_end,
        "planning_allowed_after": planning_allowed_after,
        "next_practice": next_practice,
        "next_practice_start": next_practice_start,
        "refresh_window_start": refresh_window_start,
    }


def _snapshot_source_files() -> dict[str, dict[str, Any]]:
    candidates = [
        SHARKS_DIR / "swot_analysis.json",
        SHARKS_DIR / "team_enriched.json",
        SHARKS_DIR / "team_merged.json",
        SHARKS_DIR / "team.json",
        SHARKS_DIR / "app_stats.json",
        SHARKS_DIR / "availability.json",
        SHARKS_DIR / "practice_rsvp.json",
        SHARKS_DIR / "schedule_manual.json",
        SHARKS_DIR / "opponent_discovery.json",
    ]

    snapshot: dict[str, dict[str, Any]] = {}
    for path in candidates:
        key = str(path.relative_to(DATA_DIR.parent))
        if not path.exists():
            snapshot[key] = {"exists": False}
            continue
        stat = path.stat()
        hasher = hashlib.sha1()
        with open(path, "rb") as f:
            hasher.update(f.read())
        snapshot[key] = {
            "exists": True,
            "mtime_ns": int(stat.st_mtime_ns),
            "size": int(stat.st_size),
            "sha1": hasher.hexdigest(),
        }
    return snapshot


def _load_plan_meta() -> dict[str, Any]:
    data = _load_json(PLAN_META_FILE, {})
    return data if isinstance(data, dict) else {}


def _save_plan_meta(meta: dict[str, Any]) -> None:
    SHARKS_DIR.mkdir(parents=True, exist_ok=True)
    with open(PLAN_META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def _write_plan(swot: dict[str, Any], windows: dict[str, Any], matchup: dict | None = None) -> str:
    target_date = windows.get("next_practice_start") or datetime.now(ET_TZ)
    plan_date = f"{target_date.month}/{target_date.day}/{target_date.year}"
    plan = generate_practice_plan(swot, date=plan_date, matchup=matchup)
    with open(PLAN_FILE, "w", encoding="utf-8") as f:
        f.write(plan)
    return plan


def _resolve_next_opponent_matchup() -> dict | None:
    """Load matchup data for the next upcoming opponent, if available."""
    schedule = _load_json(SHARKS_DIR / "schedule_manual.json", {})
    if not isinstance(schedule, dict):
        return None
    now = datetime.now(ET_TZ)
    for game in schedule.get("upcoming", []):
        if not isinstance(game, dict) or game.get("is_game") is False:
            continue
        start = _parse_event_datetime(
            str(game.get("date", "")),
            str(game.get("time", "")),
            default_time="12:00 PM",
        )
        if start and start > now:
            opponent_name = _clean_opponent_name(str(game.get("opponent", "")))
            slug = _resolve_opponent_slug(opponent_name)
            if slug:
                matchup_file = DATA_DIR / "opponents" / slug / "team.json"
                if matchup_file.exists():
                    try:
                        from swot_analyzer import analyze_matchup, load_team
                        our_team = load_team(SHARKS_DIR, prefer_merged=True)
                        with open(matchup_file, "r", encoding="utf-8") as f:
                            opp_team = json.load(f)
                        if our_team:
                            m = analyze_matchup(our_team, opp_team)
                            m["opponent"] = opponent_name
                            m["opponent_slug"] = slug
                            return m
                    except Exception:
                        pass
            return None
    return None


def _resolve_opponent_slug(opponent_name: str) -> str | None:
    """Map a schedule opponent name to a data/opponents/ directory slug."""
    discovery = _load_json(SHARKS_DIR / "opponent_discovery.json", {})
    if isinstance(discovery, dict):
        for team in discovery.get("teams", []):
            if not isinstance(team, dict):
                continue
            team_name = team.get("team_name", "")
            slug = team.get("slug", "")
            if team_name and slug:
                if team_name.lower() in opponent_name.lower() or opponent_name.lower() in team_name.lower():
                    return slug
    # Fallback: fuzzy match against opponent directory names
    opponents_dir = DATA_DIR / "opponents"
    if opponents_dir.exists():
        name_lower = opponent_name.lower().replace(" ", "_").replace("-", "_")
        for d in opponents_dir.iterdir():
            if d.is_dir() and d.name in name_lower:
                return d.name
    return None


def run_scheduled(force: bool = False) -> dict[str, Any]:
    """Run planner with timing policy:
    1) wait 1h after completed game/practice to begin planning
    2) refresh 1h before next practice only when new inputs exist."""
    now = datetime.now(ET_TZ)
    swot_file = SHARKS_DIR / "swot_analysis.json"
    if not swot_file.exists():
        return {"status": "skipped", "reason": "missing_swot"}

    with open(swot_file, "r", encoding="utf-8") as f:
        swot = json.load(f)

    windows = _compute_windows(now)
    source_snapshot = _snapshot_source_files()
    meta = _load_plan_meta()

    if not force and now < windows["planning_allowed_after"]:
        return {
            "status": "skipped",
            "reason": "cooldown_after_event",
            "planning_allowed_after": _iso(windows["planning_allowed_after"]),
        }

    next_practice_start = windows.get("next_practice_start")
    refresh_window_start = windows.get("refresh_window_start")
    latest_completed_end = windows.get("latest_completed_end")
    cycle_anchor_end = _iso(latest_completed_end)
    prev_cycle_anchor_end = str(meta.get("cycle_anchor_end") or "")

    mode = "scheduled_initial"
    reason = "initial_after_event_cooldown"

    if force:
        mode = "scheduled_force"
        reason = "force"
    elif not meta or prev_cycle_anchor_end != (cycle_anchor_end or ""):
        mode = "scheduled_initial"
        reason = "initial_after_event_cooldown"
    else:
        in_refresh_window = bool(
            next_practice_start
            and refresh_window_start
            and refresh_window_start <= now <= next_practice_start
        )
        if in_refresh_window:
            refresh_for = _iso(next_practice_start)
            already_refreshed = str(meta.get("last_refresh_for_practice") or "") == (refresh_for or "")
            if already_refreshed:
                return {
                    "status": "skipped",
                    "reason": "refresh_already_done",
                    "refresh_for": refresh_for,
                }
            if meta.get("source_snapshot") != source_snapshot:
                mode = "scheduled_refresh"
                reason = "pre_practice_new_info"
            else:
                return {
                    "status": "skipped",
                    "reason": "no_new_info",
                    "refresh_for": refresh_for,
                }
        else:
            return {"status": "skipped", "reason": "outside_refresh_window"}

    matchup = _resolve_next_opponent_matchup()
    _write_plan(swot, windows, matchup=matchup)
    next_practice = windows.get("next_practice") or {}
    refresh_for = _iso(next_practice_start) if mode == "scheduled_refresh" else None
    new_meta = {
        "updated_at": now.isoformat(),
        "mode": mode,
        "reason": reason,
        "cycle_anchor_end": cycle_anchor_end,
        "planning_allowed_after": _iso(windows.get("planning_allowed_after")),
        "next_practice": {
            "title": next_practice.get("title"),
            "start": _iso(next_practice_start),
            "refresh_window_start": _iso(refresh_window_start),
        },
        "last_refresh_for_practice": refresh_for,
        "source_snapshot": source_snapshot,
    }
    _save_plan_meta(new_meta)

    return {
        "status": "generated",
        "mode": mode,
        "reason": reason,
        "next_practice_start": _iso(next_practice_start),
    }


def run() -> str | None:
    """Manual plan generation (immediate)."""
    swot_file = SHARKS_DIR / "swot_analysis.json"
    if not swot_file.exists():
        print("[PRACTICE] No SWOT analysis found. Run swot_analyzer.py first.")
        return None

    with open(swot_file, "r", encoding="utf-8") as f:
        swot = json.load(f)

    matchup = _resolve_next_opponent_matchup()
    if matchup and not matchup.get("empty"):
        print(f"[PRACTICE] Next opponent: {matchup.get('opponent', '?')} — tailoring drills")
    windows = _compute_windows(datetime.now(ET_TZ))
    plan = _write_plan(swot, windows, matchup=matchup)
    print(f"[PRACTICE] Plan saved to {PLAN_FILE}")
    print(f"\n{'='*60}")
    print(plan)
    print(f"{'='*60}")
    return plan


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate practice plans.")
    parser.add_argument("--scheduled", action="store_true", help="Apply scheduling policy and refresh checks.")
    parser.add_argument("--force", action="store_true", help="Force generation in scheduled mode.")
    args = parser.parse_args()

    if args.scheduled:
        result = run_scheduled(force=args.force)
        print(f"[PRACTICE] status={result.get('status')} reason={result.get('reason')}")
    else:
        run()
