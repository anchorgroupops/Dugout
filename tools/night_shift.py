"""
Night Shift — Autonomous overnight coworker for The Sharks.

Runs the full heavy-lift data pipeline while the team sleeps:
  1. League-wide opponent discovery & deep scrape
  2. Full GameChanger data refresh (Sharks + all opponents)
  3. SWOT analysis recompute (players + team + matchups)
  4. Lineup optimization for upcoming games
  5. Practice plan generation from latest weaknesses
  6. NotebookLM payload rebuild
  7. RAG memory re-index
  8. Data integrity reconciliation
  9. Morning briefing summary generation

Schedule: 11:00 PM ET nightly (via Modal cron or n8n)
Output:   data/sharks/night_shift_report.json

Usage:
    python tools/night_shift.py                # Full run
    python tools/night_shift.py --stage scrape # Single stage
    python tools/night_shift.py --dry-run      # Report plan without executing
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

ROOT_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT_DIR / "tools"
DATA_DIR = ROOT_DIR / "data"
SHARKS_DIR = DATA_DIR / "sharks"
OPPONENTS_DIR = DATA_DIR / "opponents"
LOG_DIR = ROOT_DIR / "logs"
REPORT_FILE = SHARKS_DIR / "night_shift_report.json"

# Ensure output dirs exist
SHARKS_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Stage definitions — ordered pipeline
# ---------------------------------------------------------------------------

STAGES = [
    "discover",   # Opponent discovery via public GC API
    "scrape",     # Full GC scrape (Sharks + league)
    "analyze",    # SWOT recompute
    "optimize",   # Lineup optimization
    "practice",   # Practice plan generation
    "sync",       # NotebookLM payload + RAG memory
    "reconcile",  # Data integrity checks
    "briefing",   # Morning summary generation
]


def _ts() -> str:
    return datetime.now(ET).isoformat()


def _run_tool(label: str, args: list[str], timeout: int = 600) -> dict:
    """Run a tool subprocess and capture results."""
    print(f"[NightShift] [{_ts()}] Starting: {label}")
    start = time.time()
    try:
        proc = subprocess.run(
            [sys.executable] + args,
            cwd=str(ROOT_DIR),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        elapsed = round(time.time() - start, 1)
        success = proc.returncode == 0
        status = "ok" if success else "error"
        if proc.stdout:
            # Print last 20 lines of output for visibility
            lines = proc.stdout.strip().split("\n")
            for line in lines[-20:]:
                print(f"  {line}")
        if proc.stderr and not success:
            for line in proc.stderr.strip().split("\n")[-10:]:
                print(f"  [ERR] {line}")
        print(f"[NightShift] [{_ts()}] {label}: {status} ({elapsed}s)")
        return {
            "stage": label,
            "status": status,
            "elapsed_s": elapsed,
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "").strip()[-500:],
            "stderr_tail": (proc.stderr or "").strip()[-300:] if not success else "",
        }
    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - start, 1)
        print(f"[NightShift] [{_ts()}] {label}: TIMEOUT after {elapsed}s")
        return {
            "stage": label,
            "status": "timeout",
            "elapsed_s": elapsed,
            "returncode": -1,
            "stdout_tail": "",
            "stderr_tail": f"Timed out after {timeout}s",
        }
    except Exception as exc:
        elapsed = round(time.time() - start, 1)
        print(f"[NightShift] [{_ts()}] {label}: EXCEPTION — {exc}")
        return {
            "stage": label,
            "status": "error",
            "elapsed_s": elapsed,
            "returncode": -1,
            "stdout_tail": "",
            "stderr_tail": traceback.format_exc()[-300:],
        }


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def stage_discover() -> dict:
    """Discover all PCLL opponents via public GameChanger API."""
    return _run_tool(
        "Opponent Discovery",
        ["tools/opponent_discovery.py"],
        timeout=120,
    )


def stage_scrape() -> dict:
    """Full league scrape — Sharks + all discovered opponents."""
    return _run_tool(
        "League Scrape",
        ["tools/league_scraper.py", "--discover", "--delay", "8"],
        timeout=1800,  # 30 min — full league scrape is heavy
    )


def stage_analyze() -> dict:
    """Recompute SWOT analysis for all players and teams."""
    return _run_tool(
        "SWOT Analysis",
        ["tools/swot_analyzer.py"],
        timeout=300,
    )


def stage_optimize() -> dict:
    """Generate optimized lineups for upcoming games."""
    return _run_tool(
        "Lineup Optimization",
        ["tools/lineup_optimizer.py"],
        timeout=120,
    )


def stage_practice() -> dict:
    """Generate practice plans targeting current weaknesses."""
    return _run_tool(
        "Practice Plan Generation",
        ["tools/practice_gen.py"],
        timeout=120,
    )


def stage_sync() -> list[dict]:
    """Rebuild NotebookLM payload and re-index RAG memory."""
    results = []
    results.append(_run_tool(
        "NotebookLM Sync",
        ["tools/notebooklm_sync.py"],
        timeout=180,
    ))
    results.append(_run_tool(
        "RAG Memory Index",
        ["tools/memory_engine.py", "sync"],
        timeout=300,
    ))
    return results


def stage_reconcile() -> dict:
    """Run data integrity checks and pipeline health audit."""
    # Build a quick reconciliation report from available data
    report = {"status": "ok", "checks": []}

    # Check Sharks team.json exists and has roster
    team_file = SHARKS_DIR / "team.json"
    if team_file.exists():
        try:
            with open(team_file) as f:
                team = json.load(f)
            roster_size = len(team.get("roster", []))
            report["checks"].append({
                "check": "sharks_roster",
                "status": "ok" if roster_size > 0 else "warn",
                "detail": f"{roster_size} players on roster",
            })
        except Exception as e:
            report["checks"].append({
                "check": "sharks_roster",
                "status": "error",
                "detail": str(e),
            })
    else:
        report["checks"].append({
            "check": "sharks_roster",
            "status": "warn",
            "detail": "team.json not found",
        })

    # Check SWOT output exists
    swot_file = SHARKS_DIR / "swot_analysis.json"
    if swot_file.exists():
        try:
            with open(swot_file) as f:
                swot = json.load(f)
            player_count = len(swot) if isinstance(swot, list) else len(swot.get("players", []))
            report["checks"].append({
                "check": "swot_analysis",
                "status": "ok" if player_count > 0 else "warn",
                "detail": f"{player_count} player analyses",
            })
        except Exception as e:
            report["checks"].append({
                "check": "swot_analysis",
                "status": "error",
                "detail": str(e),
            })
    else:
        report["checks"].append({
            "check": "swot_analysis",
            "status": "missing",
            "detail": "swot_analysis.json not found",
        })

    # Check lineups
    lineup_file = SHARKS_DIR / "lineups.json"
    if lineup_file.exists():
        report["checks"].append({"check": "lineups", "status": "ok", "detail": "present"})
    else:
        report["checks"].append({"check": "lineups", "status": "missing", "detail": "lineups.json not found"})

    # Check opponent data
    opp_count = 0
    if OPPONENTS_DIR.exists():
        for d in OPPONENTS_DIR.iterdir():
            if d.is_dir() and (d / "team.json").exists():
                opp_count += 1
    report["checks"].append({
        "check": "opponent_data",
        "status": "ok" if opp_count > 0 else "warn",
        "detail": f"{opp_count} opponent team(s) scraped",
    })

    # Check pipeline health file
    health_file = SHARKS_DIR / "pipeline_health.json"
    if health_file.exists():
        try:
            with open(health_file) as f:
                health = json.load(f)
            coverage = health.get("coverage_pct", 0)
            report["checks"].append({
                "check": "pipeline_health",
                "status": "ok" if coverage > 50 else "warn",
                "detail": f"{coverage}% coverage",
            })
        except Exception:
            report["checks"].append({"check": "pipeline_health", "status": "error", "detail": "parse error"})

    # Summary
    statuses = [c["status"] for c in report["checks"]]
    if "error" in statuses:
        report["status"] = "degraded"
    elif "missing" in statuses or "warn" in statuses:
        report["status"] = "partial"

    print(f"[NightShift] Reconciliation: {report['status']} — {len(report['checks'])} checks")
    for c in report["checks"]:
        print(f"  [{c['status'].upper():>7}] {c['check']}: {c['detail']}")

    return {
        "stage": "Data Reconciliation",
        "status": report["status"],
        "elapsed_s": 0,
        "returncode": 0,
        "checks": report["checks"],
    }


def stage_briefing(stage_results: list[dict]) -> dict:
    """Generate a morning briefing summary from all stage results."""
    now = datetime.now(ET)
    briefing = {
        "generated_at": now.isoformat(),
        "generated_for": now.strftime("%A, %B %-d %Y"),
        "shift_summary": {
            "total_stages": len(stage_results),
            "passed": sum(1 for r in stage_results if r.get("status") == "ok"),
            "warnings": sum(1 for r in stage_results if r.get("status") in ("warn", "partial")),
            "errors": sum(1 for r in stage_results if r.get("status") in ("error", "timeout")),
        },
        "stages": [],
    }

    total_elapsed = 0.0
    for r in stage_results:
        elapsed = r.get("elapsed_s", 0)
        total_elapsed += elapsed
        briefing["stages"].append({
            "name": r.get("stage", "unknown"),
            "status": r.get("status", "unknown"),
            "elapsed_s": elapsed,
        })

    briefing["shift_summary"]["total_elapsed_s"] = round(total_elapsed, 1)
    briefing["shift_summary"]["total_elapsed_min"] = round(total_elapsed / 60, 1)

    # Determine overall health
    errors = briefing["shift_summary"]["errors"]
    if errors == 0:
        briefing["shift_summary"]["health"] = "green"
        briefing["shift_summary"]["headline"] = "All systems go — data is fresh for the morning."
    elif errors <= 2:
        briefing["shift_summary"]["health"] = "yellow"
        briefing["shift_summary"]["headline"] = f"{errors} stage(s) had issues — check the report."
    else:
        briefing["shift_summary"]["health"] = "red"
        briefing["shift_summary"]["headline"] = f"{errors} failures overnight — manual review needed."

    # Check for upcoming games (read schedule if available)
    schedule_file = SHARKS_DIR / "schedule.json"
    if schedule_file.exists():
        try:
            with open(schedule_file) as f:
                schedule = json.load(f)
            upcoming = []
            for game in (schedule if isinstance(schedule, list) else schedule.get("games", [])):
                game_date = game.get("date", game.get("start_ts", ""))
                if game_date and game_date > now.isoformat():
                    upcoming.append({
                        "date": game_date,
                        "opponent": game.get("opponent", game.get("opponent_name", "TBD")),
                        "location": game.get("location", ""),
                    })
            upcoming.sort(key=lambda g: g["date"])
            briefing["upcoming_games"] = upcoming[:3]
            if upcoming:
                next_game = upcoming[0]
                briefing["shift_summary"]["next_game"] = (
                    f"Next: vs {next_game['opponent']} on {next_game['date'][:10]}"
                )
        except Exception:
            pass

    return briefing


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

STAGE_MAP = {
    "discover": stage_discover,
    "scrape": stage_scrape,
    "analyze": stage_analyze,
    "optimize": stage_optimize,
    "practice": stage_practice,
}


def run_night_shift(
    stages: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Execute the Night Shift pipeline."""
    run_stages = stages or STAGES
    print(f"\n{'='*60}")
    print(f"  NIGHT SHIFT — The Sharks Autonomous Coworker")
    print(f"  Started: {_ts()}")
    print(f"  Stages:  {', '.join(run_stages)}")
    print(f"{'='*60}\n")

    if dry_run:
        print("[NightShift] DRY RUN — would execute:")
        for i, stage in enumerate(run_stages, 1):
            print(f"  {i}. {stage}")
        return {"status": "dry_run", "stages": run_stages}

    results: list[dict] = []
    overall_start = time.time()

    for stage_name in run_stages:
        print(f"\n{'—'*40}")
        print(f"  Stage: {stage_name}")
        print(f"{'—'*40}")

        if stage_name in STAGE_MAP:
            result = STAGE_MAP[stage_name]()
            results.append(result)

        elif stage_name == "sync":
            sync_results = stage_sync()
            results.extend(sync_results)

        elif stage_name == "reconcile":
            result = stage_reconcile()
            results.append(result)

        elif stage_name == "briefing":
            # Briefing is generated from all prior results (not appended to results yet)
            pass
        else:
            print(f"[NightShift] Unknown stage: {stage_name}")
            results.append({
                "stage": stage_name,
                "status": "skipped",
                "elapsed_s": 0,
                "returncode": -1,
            })

    # Always generate the briefing at the end
    briefing = stage_briefing(results)
    overall_elapsed = round(time.time() - overall_start, 1)

    # Build final report
    report = {
        "run_id": datetime.now(ET).strftime("%Y%m%d_%H%M%S"),
        "started_at": briefing["generated_at"],
        "completed_at": _ts(),
        "total_elapsed_s": overall_elapsed,
        "total_elapsed_min": round(overall_elapsed / 60, 1),
        "briefing": briefing,
        "stage_results": results,
    }

    # Write report
    try:
        with open(REPORT_FILE, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\n[NightShift] Report saved: {REPORT_FILE}")
    except Exception as e:
        print(f"\n[NightShift] Failed to save report: {e}")

    # Print summary
    summary = briefing["shift_summary"]
    print(f"\n{'='*60}")
    print(f"  NIGHT SHIFT COMPLETE")
    print(f"  Health:  {summary['health'].upper()}")
    print(f"  Stages:  {summary['passed']} ok / {summary['warnings']} warn / {summary['errors']} error")
    print(f"  Time:    {summary['total_elapsed_min']} minutes")
    print(f"  {summary['headline']}")
    if "next_game" in summary:
        print(f"  {summary['next_game']}")
    print(f"{'='*60}\n")

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Night Shift — Sharks overnight autonomous coworker",
    )
    parser.add_argument(
        "--stage",
        choices=STAGES,
        help="Run a single stage instead of the full pipeline",
    )
    parser.add_argument(
        "--stages",
        nargs="+",
        choices=STAGES,
        help="Run specific stages in order",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show execution plan without running anything",
    )
    args = parser.parse_args()

    if args.stage:
        stages = [args.stage]
    elif args.stages:
        stages = args.stages
    else:
        stages = None  # Full pipeline

    report = run_night_shift(stages=stages, dry_run=args.dry_run)

    # Exit with non-zero if any stage errored
    if not args.dry_run:
        errors = report.get("briefing", {}).get("shift_summary", {}).get("errors", 0)
        if errors > 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
