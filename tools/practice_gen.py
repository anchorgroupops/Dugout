"""
Practice Plan Generator for Softball
Maps identified weaknesses from SWOT analysis to targeted drills.
Generates structured practice plans in the user's existing format.
"""

import json
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
SHARKS_DIR = DATA_DIR / "sharks"


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


def map_weaknesses_to_drills(swot_analysis: dict) -> list[dict]:
    """Map team weaknesses to recommended drills with priority."""
    team_weaknesses = swot_analysis.get("team_swot", {}).get("weaknesses", [])

    drill_scores: dict[str, int] = {}
    drill_reasons: dict[str, list[str]] = {}

    for weakness in team_weaknesses:
        # Extract the weakness label (before the player count)
        label = weakness.split("(")[0].strip()
        drills = WEAKNESS_DRILL_MAP.get(label, [])
        for drill_id in drills:
            drill_scores[drill_id] = drill_scores.get(drill_id, 0) + 1
            if drill_id not in drill_reasons:
                drill_reasons[drill_id] = []
            drill_reasons[drill_id].append(label)

    # Also analyze individual player weaknesses
    for pa in swot_analysis.get("player_analyses", []):
        for weakness in pa.get("swot", {}).get("weaknesses", []):
            label = weakness.split("(")[0].strip()
            drills = WEAKNESS_DRILL_MAP.get(label, [])
            for drill_id in drills:
                drill_scores[drill_id] = drill_scores.get(drill_id, 0) + 1

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
) -> str:
    """
    Generate a structured practice plan based on SWOT weaknesses.
    Output format matches the user's existing Google Doc practice plan style.
    """
    if date is None:
        now = datetime.now()
        date = f"{now.month}/{now.day}/{now.year}"

    drills = map_weaknesses_to_drills(swot_analysis)
    if not drills:
        drills = [
            DRILL_LIBRARY["baserunning_431"],
            DRILL_LIBRARY["soft_toss"],
            DRILL_LIBRARY["ground_ball_circuit"],
            DRILL_LIBRARY["live_situations"],
            DRILL_LIBRARY["strike_at_home"],
        ]

    # Always start with warmup
    plan_lines = [
        f"{date}",
        f"Objectives: Address identified weaknesses — "
        + ", ".join(set(r for d in drills[:5] for r in d.get("reasons", ["general development"])[:2]))
        + ". Emphasize fun, safety, rotation, proper form.",
    ]

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


def run():
    """Load SWOT analysis and generate a practice plan."""
    swot_file = SHARKS_DIR / "swot_analysis.json"
    if not swot_file.exists():
        print("[PRACTICE] No SWOT analysis found. Run swot_analyzer.py first.")
        return None

    with open(swot_file, "r") as f:
        swot = json.load(f)

    plan = generate_practice_plan(swot)
    output_file = SHARKS_DIR / "next_practice.txt"
    with open(output_file, "w") as f:
        f.write(plan)

    print(f"[PRACTICE] Plan saved to {output_file}")
    print(f"\n{'='*60}")
    print(plan)
    print(f"{'='*60}")

    return plan


if __name__ == "__main__":
    run()
