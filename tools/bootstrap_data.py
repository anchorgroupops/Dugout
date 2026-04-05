"""
One-time bootstrap: inject scraped roster + schedule data directly into Modal volume.
Run with: modal run tools/bootstrap_data.py
"""
import json
from pathlib import Path
import modal

app = modal.App("softball-bootstrap")
vol = modal.Volume.from_name("softball-gc-session", create_if_missing=True)

TEAM_DATA = {
    "gc_team_id": "NuGgx6WvP7TO",
    "gc_season_slug": "2026-spring-sharks",
    "last_updated": "2026-04-05T12:00:00-04:00",
    "league": "PCLL",
    "record": "3-4",
    "season": "Spring 2026",
    "team_name": "The Sharks",
    "source_teams": ["The Sharks"],
    "roster": [
        {"name": "Ember Hourahan", "number": "00", "gp": 7, "pa": 17, "ab": 11, "avg": 0.727, "obp": 0.824, "ops": 2.278, "slg": 1.455, "h": 8, "singles": 5, "doubles": 0, "triples": 1, "hr": 2, "bb": 5, "so": 4, "hbp": 4},
        {"name": "Leila VanDeusen", "number": "13", "gp": 6, "pa": 16, "ab": 11, "avg": 0.455, "obp": 0.625, "ops": 1.170, "slg": 0.545, "h": 5, "singles": 4, "doubles": 1, "triples": 0, "hr": 0, "bb": 4, "so": 0, "hbp": 0},
        {"name": "Lexi McKinney", "number": "99", "gp": 7, "pa": 18, "ab": 11, "avg": 0.364, "obp": 0.611, "ops": 1.066, "slg": 0.455, "h": 4, "singles": 3, "doubles": 1, "triples": 0, "hr": 0, "bb": 4, "so": 5, "hbp": 1},
        {"name": "Ruby VanDeusen", "number": "67", "gp": 7, "pa": 18, "ab": 10, "avg": 0.300, "obp": 0.611, "ops": 1.011, "slg": 0.400, "h": 3, "singles": 2, "doubles": 1, "triples": 0, "hr": 0, "bb": 3, "so": 4, "hbp": 1},
        {"name": "Chloe Johnson", "number": "19", "gp": 3, "pa": 8, "ab": 4, "avg": 0.250, "obp": 0.625, "ops": 0.875, "slg": 0.250, "h": 1, "singles": 1, "doubles": 0, "triples": 0, "hr": 0, "bb": 3, "so": 1, "hbp": 1},
        {"name": "Sephina Santiago", "number": "8", "gp": 5, "pa": 15, "ab": 11, "avg": 0.182, "obp": 0.400, "ops": 0.673, "slg": 0.273, "h": 2, "singles": 1, "doubles": 1, "triples": 0, "hr": 0, "bb": 3, "so": 0, "hbp": 1},
        {"name": "Delilah Gomez", "number": "7", "gp": 7, "pa": 18, "ab": 6, "avg": 0.167, "obp": 0.722, "ops": 1.056, "slg": 0.333, "h": 1, "singles": 0, "doubles": 1, "triples": 0, "hr": 0, "bb": 6, "so": 1, "hbp": 1},
        {"name": "Maylani Nixon", "number": "1", "gp": 1, "pa": 3, "ab": 2, "avg": 1.000, "obp": 1.000, "ops": 2.500, "slg": 1.500, "h": 2, "singles": 1, "doubles": 1, "triples": 0, "hr": 0, "bb": 0, "so": 0, "hbp": 0},
        {"name": "Amelia", "number": "", "gp": 1, "pa": 3, "ab": 1, "avg": 1.000, "obp": 1.000, "ops": 2.000, "slg": 1.000, "h": 1, "singles": 1, "doubles": 0, "triples": 0, "hr": 0, "bb": 0, "so": 0, "hbp": 0},
        {"name": "Addy", "number": "11", "gp": 1, "pa": 3, "ab": 1, "avg": 1.000, "obp": 1.000, "ops": 2.000, "slg": 1.000, "h": 1, "singles": 1, "doubles": 0, "triples": 0, "hr": 0, "bb": 0, "so": 0, "hbp": 0},
        {"name": "Emma Williams", "number": "4", "gp": 3, "pa": 6, "ab": 2, "avg": 0.000, "obp": 0.667, "ops": 0.667, "slg": 0.000, "h": 0, "singles": 0, "doubles": 0, "triples": 0, "hr": 0, "bb": 2, "so": 0, "hbp": 0},
        {"name": "Brielle P", "number": "5", "gp": 1, "pa": 2, "ab": 0, "avg": None, "obp": 1.000, "ops": 1.000, "slg": None, "h": 0, "singles": 0, "doubles": 0, "triples": 0, "hr": 0, "bb": 0, "so": 0, "hbp": 0},
        {"name": "Addy A", "number": "11", "gp": 1, "pa": 2, "ab": 1, "avg": 0.000, "obp": 0.500, "ops": 0.500, "slg": 0.000, "h": 0, "singles": 0, "doubles": 0, "triples": 0, "hr": 0, "bb": 0, "so": 0, "hbp": 0},
        {"name": "Mikayla J", "number": "26", "gp": 1, "pa": 2, "ab": 1, "avg": 0.000, "obp": 0.500, "ops": 0.500, "slg": 0.000, "h": 0, "singles": 0, "doubles": 0, "triples": 0, "hr": 0, "bb": 0, "so": 0, "hbp": 0},
        {"name": "Juliette Moros", "number": "27", "gp": 6, "pa": 13, "ab": 10, "avg": 0.000, "obp": 0.231, "ops": 0.231, "slg": 0.000, "h": 0, "singles": 0, "doubles": 0, "triples": 0, "hr": 0, "bb": 6, "so": 7, "hbp": 0},
        {"name": "Mikayla", "number": "26", "gp": 1, "pa": 1, "ab": 1, "avg": 0.000, "obp": 0.000, "ops": 0.000, "slg": 0.000, "h": 0, "singles": 0, "doubles": 0, "triples": 0, "hr": 0, "bb": 0, "so": 0, "hbp": 0},
        {"name": "Addison", "number": "1", "gp": 1, "pa": 3, "ab": 1, "avg": 0.000, "obp": 0.667, "ops": 0.667, "slg": 0.000, "h": 0, "singles": 0, "doubles": 0, "triples": 0, "hr": 0, "bb": 0, "so": 0, "hbp": 0},
    ],
    "team_totals": {"gp": 7, "pa": 148, "ab": 84, "avg": 0.333, "obp": 0.622, "ops": 1.122, "slg": 0.500, "h": 28, "singles": 19, "doubles": 6, "triples": 1, "hr": 2},
}

SCHEDULE_DATA = {
    "last_updated": "2026-04-05T12:00:00-04:00",
    "past": [
        {"date": "2026-02-19", "opponent": "TBD", "result": "L", "score": {"sharks": 13, "opponent": 20}, "home_away": "away", "type": "scrimmage"},
        {"date": "2026-02-28", "opponent": "NWVLL 5 Star Tree Service Stihlers Majors SB", "result": "W", "score": {"sharks": None, "opponent": None}, "home_away": "home", "location": "Indian Trails Sports Complex, Field 8"},
        {"date": "2026-03-03", "opponent": "Peppers", "result": "W", "score": {"sharks": None, "opponent": None}, "home_away": "home", "location": "Indian Trails Sports Complex"},
        {"date": "2026-03-07", "opponent": "Riptide Rebels", "result": "W", "score": {"sharks": 11, "opponent": 10}, "home_away": "home", "location": "Indian Trails Sports Complex"},
        {"date": "2026-03-13", "opponent": "Wildcats", "result": "L", "score": {"sharks": 9, "opponent": 20}, "home_away": "away", "location": "Indian Trails Sports Complex, Field 3"},
        {"date": "2026-03-17", "opponent": "Peppers", "result": "W", "score": {"sharks": 1, "opponent": 0}, "home_away": "home", "location": "Indian Trails Sports Complex, Field 3"},
        {"date": "2026-03-23", "opponent": "Ravens - Major SB Spring 2026", "result": "W", "score": {"sharks": 16, "opponent": 7}, "home_away": "away", "location": "St. Augustine Little League Complex"},
        {"date": "2026-03-28", "opponent": "Peppers", "result": "W", "score": {"sharks": 1, "opponent": 0}, "home_away": "away", "location": "Indian Trails Sports Complex, Field 3"},
        {"date": "2026-04-01", "opponent": "Riptide Rebels", "result": "L", "score": {"sharks": 13, "opponent": 14}, "home_away": "away", "location": "Indian Trails Sports Complex, Field 8"},
        {"date": "2026-04-02", "opponent": "NWVLL 5 Star Tree Service Stihlers Majors SB", "result": "L", "score": {"sharks": 6, "opponent": 24}, "home_away": "home", "location": "Indian Trails Sports Complex, Field 3"},
    ],
    "upcoming": [
        {"date": "2026-04-07", "day": "TUE", "opponent": "NWVLL 5 Star Tree Service Stihlers Majors SB", "home_away": "away", "time": "6:00 PM", "location": "Indian Trails Sports Complex, Field 3"},
        {"date": "2026-04-09", "day": "THU", "opponent": "Peppers", "home_away": "home", "time": "6:00 PM", "location": "Indian Trails Sports Complex, Field 3"},
        {"date": "2026-04-11", "day": "SAT", "opponent": "Riptide Rebels", "home_away": "away", "time": "1:00 PM", "location": "Indian Trails Sports Complex, Field 3"},
        {"date": "2026-04-14", "day": "TUE", "opponent": "NWVLL 5 Star Tree Service Stihlers Majors SB", "home_away": "away", "time": "6:30 PM", "location": "174 W Washington Ave, Pierson FL"},
        {"date": "2026-04-18", "day": "SAT", "opponent": "Peppers", "home_away": "away", "time": "1:00 PM", "location": "Indian Trails Sports Complex, Field 3"},
        {"date": "2026-04-21", "day": "TUE", "opponent": "NWVLL 5 Star Tree Service Stihlers Majors SB", "home_away": "away", "time": "6:00 PM", "location": "Indian Trails Sports Complex, Field 3"},
        {"date": "2026-04-25", "day": "SAT", "opponent": "Riptide Rebels", "home_away": "home", "time": "1:00 PM", "location": "Indian Trails Sports Complex, Field 3"},
        {"date": "2026-04-29", "day": "WED", "opponent": "Peppers", "home_away": "home", "time": "6:00 PM", "location": "Indian Trails Sports Complex, Field 3"},
    ],
}


@app.function(volumes={"/vol": vol}, timeout=120)
def bootstrap():
    """Write team + schedule data directly to Modal volume."""
    sharks_dir = Path("/vol/softball-gc/sharks")
    sharks_dir.mkdir(parents=True, exist_ok=True)

    # Write team_enriched.json
    team_path = sharks_dir / "team_enriched.json"
    team_path.write_text(json.dumps(TEAM_DATA, indent=2))
    print(f"[Bootstrap] Wrote {team_path} ({len(TEAM_DATA['roster'])} players)")

    # Also write as team.json for compatibility
    team_json_path = sharks_dir / "team.json"
    team_json_path.write_text(json.dumps(TEAM_DATA, indent=2))
    print(f"[Bootstrap] Wrote {team_json_path}")

    # Write schedule.json
    sched_path = sharks_dir / "schedule.json"
    sched_path.write_text(json.dumps(SCHEDULE_DATA, indent=2))
    print(f"[Bootstrap] Wrote {sched_path} ({len(SCHEDULE_DATA['past'])} past, {len(SCHEDULE_DATA['upcoming'])} upcoming)")

    # Also write as schedule_manual.json for sync_daemon compatibility
    sched_manual_path = sharks_dir / "schedule_manual.json"
    sched_manual_path.write_text(json.dumps(SCHEDULE_DATA, indent=2))
    print(f"[Bootstrap] Wrote {sched_manual_path}")

    # Clear any auth cooldown so next scrape attempt isn't blocked
    cooldown = Path("/vol/softball-gc/auth/.auth_cooldown")
    if cooldown.exists():
        cooldown.unlink()
        print("[Bootstrap] Cleared auth cooldown file")

    vol.commit()
    print("[Bootstrap] Volume committed. Data is now live.")
    return {"status": "ok", "files": ["team_enriched.json", "team.json", "schedule.json", "schedule_manual.json"]}


@app.local_entrypoint()
def main():
    print("Bootstrapping Sharks data into Modal volume...")
    result = bootstrap.remote()
    print(f"Result: {result}")
    print("\nNext steps:")
    print("  1. modal deploy tools/modal_app.py")
    print("  2. curl -X POST https://anchorgroupops--softball-strategy-sharks-manual-sync.modal.run")
