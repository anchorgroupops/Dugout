"""
GameChanger CSV Ingestion Pipeline

Single entrypoint that orchestrates the full data pipeline from a GC CSV export:
  1. Parse CSV → team.json / app_stats.json / season_stats.csv
  2. Record SQLite snapshot
  3. (Optional) Scorebook OCR
  4. Run SWOT analysis
  5. Optimize lineups
  6. Generate practice plan
  7. Write gc_report.json (drill priorities + game strategy notes)
  8. Audit log

Usage:
    python tools/gc_ingest_pipeline.py --csv path/to/export.csv
    python tools/gc_ingest_pipeline.py --csv path/to/export.csv --scorebook path/to/scorebook.pdf
    python tools/gc_ingest_pipeline.py  # auto-discovers latest CSV in Scorebooks/Other docs/
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Ensure tools/ is importable regardless of invocation cwd
_TOOLS_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _TOOLS_DIR.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

# Change to project root so logger.py (relative path "logs/") resolves correctly
os.chdir(_ROOT_DIR)

ET = ZoneInfo("America/New_York")
SHARKS_DIR = _ROOT_DIR / "data" / "sharks"  # legacy default; new code uses _team_dir(team)

# Import works whether run as `python tools/gc_ingest_pipeline.py` (tools/ on path)
# or as `python -m tools.gc_ingest_pipeline` (repo root on path).
try:
    from team_registry import Team, require_by_slug
except ImportError:
    from tools.team_registry import Team, require_by_slug


def _team_dir(team: Team) -> Path:
    return _ROOT_DIR / "data" / team.data_slug


# ---------------------------------------------------------------------------
# Auto-discovery
# ---------------------------------------------------------------------------

def _auto_discover_csv() -> Path | None:
    """Find the most recently added GC CSV export in Scorebooks/Other docs/."""
    search_dir = _ROOT_DIR / "Scorebooks" / "Other docs"
    if not search_dir.exists():
        return None
    candidates = sorted(search_dir.glob("Sharks Spring 2026 Stats*.csv"))
    return candidates[-1] if candidates else None


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run_pipeline(csv_path: Path, scorebook_path: Path | None, out_path: Path,
                 team: Team | None = None) -> dict:
    """Execute all pipeline stages and write gc_report.json.

    Phase 1 multi-team: Stage 1 (CSV ingest) is fully team-parameterized and
    writes under data/<team.data_slug>/. Stages 2 (SQLite snapshot), 4 (SWOT),
    5 (lineup), 6 (practice) still target the Sharks only — Phase 2 parameterizes
    those. Non-Sharks teams skip stages 2/4/5/6 with an informational status.
    """
    if team is None:
        team = require_by_slug("sharks")
    team_dir = _team_dir(team)
    is_sharks = team.data_slug == "sharks"

    stages: dict = {}
    team_dir.mkdir(parents=True, exist_ok=True)
    roster: list = []

    # ── Stage 1: CSV ingest ──────────────────────────────────────────────────
    print(f"[PIPELINE] Stage 1: CSV ingest ({csv_path.name}) -> {team_dir}")
    try:
        from gc_csv_ingest import parse_gc_csv, build_team_json, build_app_stats_json

        roster = parse_gc_csv(csv_path, team_dir=team_dir)
        team_json = build_team_json(roster, csv_path, team=team, team_dir=team_dir)
        app_stats = build_app_stats_json(roster)

        team_out = team_dir / "team.json"
        with open(team_out, "w") as f:
            json.dump(team_json, f, indent=2)
        print(f"[PIPELINE]   Wrote {team_out} ({len(roster)} players)")

        app_out = team_dir / "app_stats.json"
        with open(app_out, "w") as f:
            json.dump(app_stats, f, indent=2)

        season_out = team_dir / "season_stats.csv"
        shutil.copy2(csv_path, season_out)

        stages["csv_ingest"] = {"status": "ok", "detail": f"{len(roster)} players parsed"}
    except Exception as exc:
        stages["csv_ingest"] = {"status": "error", "detail": str(exc)}
        print(f"[PIPELINE] FATAL: CSV ingest failed: {exc}")
        raise RuntimeError(f"CSV ingest failed: {exc}") from exc

    # ── Stage 2: SQLite snapshot (Sharks-only in Phase 1) ────────────────────
    print("[PIPELINE] Stage 2: SQLite snapshot")
    snapshot_id: int | None = None
    if not is_sharks:
        stages["sqlite_snapshot"] = {
            "status": "skipped",
            "detail": f"Phase 1: SQLite snapshot is Sharks-only (team={team.data_slug})",
        }
        print(f"[PIPELINE]   skipped (non-Sharks team)")
    else:
        try:
            from stats_db import record_sharks_snapshot

            snapshot_id = record_sharks_snapshot(
                team_json, source="gc_ingest_pipeline", notes=csv_path.name
            )
            stages["sqlite_snapshot"] = {"status": "ok", "detail": f"snapshot_id={snapshot_id}"}
            print(f"[PIPELINE]   snapshot_id={snapshot_id}")
        except Exception as exc:
            stages["sqlite_snapshot"] = {"status": "error", "detail": str(exc)}
            print(f"[PIPELINE] WARNING: SQLite snapshot failed (non-fatal): {exc}")

    # ── Stage 3 (optional): Scorebook OCR ────────────────────────────────────
    scorebook_data: dict | None = None
    if scorebook_path:
        print(f"[PIPELINE] Stage 3: Scorebook OCR ({scorebook_path.name})")
        try:
            from scorebook_ocr import process_scorebook

            scorebook_data = process_scorebook(scorebook_path)
            if scorebook_data and "error" not in scorebook_data and scorebook_data.get("status") != "not_implemented":
                ocr_status = "ok"
            else:
                ocr_status = "warning"
            stages["scorebook_ocr"] = {
                "status": ocr_status,
                "detail": str(scorebook_data.get("method", "")) if scorebook_data else "",
            }
        except Exception as exc:
            stages["scorebook_ocr"] = {"status": "error", "detail": str(exc)}
            print(f"[PIPELINE] WARNING: Scorebook OCR failed (non-fatal): {exc}")
    else:
        stages["scorebook_ocr"] = {"status": "skipped", "detail": "no --scorebook provided"}

    # ── Stage 4: SWOT analysis (Sharks-only in Phase 1) ──────────────────────
    print("[PIPELINE] Stage 4: SWOT analysis")
    swot_result: dict | None = None
    if not is_sharks:
        stages["swot_analysis"] = {
            "status": "skipped",
            "detail": f"Phase 1: SWOT is Sharks-only (team={team.data_slug})",
        }
        print(f"[PIPELINE]   skipped (non-Sharks team)")
    else:
        try:
            from swot_analyzer import run_sharks_analysis

            swot_result = run_sharks_analysis()
            player_count = len((swot_result or {}).get("player_analyses", []))
            stages["swot_analysis"] = {"status": "ok", "detail": f"{player_count} players analyzed"}
        except Exception as exc:
            stages["swot_analysis"] = {"status": "error", "detail": str(exc)}
            print(f"[PIPELINE] FATAL: SWOT analysis failed: {exc}")
            raise RuntimeError(f"SWOT analysis failed: {exc}") from exc

    # ── Stage 5: Lineup optimization (Sharks-only in Phase 1) ────────────────
    print("[PIPELINE] Stage 5: Lineup optimization")
    if not is_sharks:
        stages["lineup_optimization"] = {
            "status": "skipped",
            "detail": f"Phase 1: lineup optimizer is Sharks-only (team={team.data_slug})",
        }
        print(f"[PIPELINE]   skipped (non-Sharks team)")
    else:
        try:
            from lineup_optimizer import run as run_lineup

            run_lineup()
            stages["lineup_optimization"] = {"status": "ok", "detail": "3 strategies generated"}
        except Exception as exc:
            stages["lineup_optimization"] = {"status": "error", "detail": str(exc)}
            print(f"[PIPELINE] WARNING: Lineup optimization failed (non-fatal): {exc}")

    # ── Stage 6: Practice plan (Sharks-only in Phase 1) ──────────────────────
    print("[PIPELINE] Stage 6: Practice plan")
    if not is_sharks:
        stages["practice_plan"] = {
            "status": "skipped",
            "detail": f"Phase 1: practice plan is Sharks-only (team={team.data_slug})",
        }
        print(f"[PIPELINE]   skipped (non-Sharks team)")
    else:
        try:
            from practice_gen import run as run_practice

            run_practice()
            stages["practice_plan"] = {"status": "ok", "detail": "plan generated"}
        except Exception as exc:
            stages["practice_plan"] = {"status": "error", "detail": str(exc)}
            print(f"[PIPELINE] WARNING: Practice plan failed (non-fatal): {exc}")

    # ── Stage 7: Assemble report ─────────────────────────────────────────────
    print("[PIPELINE] Stage 7: Assembling gc_report.json")
    report = _assemble_report(
        csv_path=csv_path,
        scorebook_path=scorebook_path,
        roster=roster,
        stages=stages,
        swot_result=swot_result,
        snapshot_id=snapshot_id,
        scorebook_data=scorebook_data,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[PIPELINE]   Report written to {out_path.name}")

    # ── Stage 8: Audit log ───────────────────────────────────────────────────
    try:
        from logger import log_decision

        passed = sum(1 for s in stages.values() if s["status"] in ("ok", "skipped"))
        log_decision(
            category="gc_ingest_pipeline",
            input_data={
                "csv": csv_path.name,
                "scorebook": scorebook_path.name if scorebook_path else None,
            },
            output_data={"stages": stages, "report": str(out_path)},
            rationale=(
                f"CSV ingestion pipeline completed. {passed}/{len(stages)} stages ok/skipped. "
                f"Roster={len(roster)}, snapshot_id={snapshot_id}."
            ),
        )
    except Exception as exc:
        print(f"[PIPELINE] WARNING: Audit log failed: {exc}")

    return report


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def _assemble_report(
    csv_path: Path,
    scorebook_path: Path | None,
    roster: list,
    stages: dict,
    swot_result: dict | None,
    snapshot_id: int | None,
    scorebook_data: dict | None,
) -> dict:
    """Build the final gc_report.json structure from pipeline artifacts."""
    # Load lineup results
    lineups_data: dict = {}
    lineups_file = SHARKS_DIR / "lineups.json"
    if lineups_file.exists():
        try:
            with open(lineups_file) as f:
                lineups_data = json.load(f)
        except Exception:
            pass

    recommended_strategy = lineups_data.get("recommended_strategy", "balanced")
    strategy_data = lineups_data.get(recommended_strategy) or lineups_data.get("balanced") or {}
    lineup_list = strategy_data.get("lineup", [])
    simulated_runs = strategy_data.get("simulated_runs_per_game")

    # Drill priorities (top 5) from SWOT weaknesses
    drill_priorities: list = []
    if swot_result:
        try:
            from practice_gen import map_weaknesses_to_drills

            raw_drills = map_weaknesses_to_drills(swot_result)
            for i, d in enumerate(raw_drills[:5], start=1):
                drill_priorities.append({
                    "rank": i,
                    "drill_id": d["drill_id"],
                    "name": d["name"],
                    "priority_score": d["priority_score"],
                    "duration_minutes": d.get("duration", 0),
                    "targets": d.get("targets", []),
                    "reasons": d.get("reasons", []),
                })
        except Exception:
            pass

    # Game strategy notes derived from SWOT
    game_strategy_notes: list = []
    if swot_result:
        team_swot = swot_result.get("team_swot", {})
        for w in team_swot.get("weaknesses", [])[:3]:
            game_strategy_notes.append(f"Team weakness: {w} — address in practice")
        for s in team_swot.get("strengths", [])[:2]:
            game_strategy_notes.append(f"Team strength: {s} — leverage in game")
        if recommended_strategy:
            game_strategy_notes.append(
                f"Recommended lineup strategy: {recommended_strategy}"
            )

    # SWOT summary block
    swot_summary: dict = {}
    if swot_result:
        team_swot = swot_result.get("team_swot", {})
        swot_summary = {
            "team_strengths": team_swot.get("strengths", []),
            "team_weaknesses": team_swot.get("weaknesses", []),
            "team_opportunities": team_swot.get("opportunities", []),
            "priority_threats": team_swot.get("threats", []),
        }

    # Team metadata from written team.json
    team_meta: dict = {}
    team_file = SHARKS_DIR / "team.json"
    if team_file.exists():
        try:
            with open(team_file) as f:
                t = json.load(f)
            team_meta = {
                "team_name": t.get("team_name", "The Sharks"),
                "league": t.get("league", "PCLL Majors"),
                "season": t.get("season", "Spring 2026"),
                "record": t.get("record", "0-0"),
            }
        except Exception:
            pass

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(ET).isoformat(),
        "pipeline_version": "gc_ingest_pipeline:1.0",
        "csv_source": csv_path.name,
        "scorebook_source": scorebook_path.name if scorebook_path else None,
        "stages": stages,
        "team_summary": {
            **team_meta,
            "roster_size": len(roster),
            "last_updated": datetime.now(ET).isoformat(),
        },
        "drill_priorities": drill_priorities,
        "game_strategy_notes": game_strategy_notes,
        "swot_summary": swot_summary,
        "lineup_snapshot": {
            "recommended_strategy": recommended_strategy,
            "simulated_runs_per_game": simulated_runs,
            "top_5": [
                {
                    "slot": p.get("slot"),
                    "role": p.get("role"),
                    "name": p.get("name"),
                    "number": str(p.get("number", "")),
                    "obp": p.get("obp"),
                    "pa": p.get("pa"),
                }
                for p in lineup_list[:5]
            ],
        },
        "snapshot_id": snapshot_id,
        "scorebook_data": scorebook_data,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="GameChanger CSV ingestion pipeline — full analysis from a GC stats export.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/gc_ingest_pipeline.py --csv "Scorebooks/Other docs/Sharks Spring 2026 Stats (4).csv"
  python tools/gc_ingest_pipeline.py --csv export.csv --scorebook Scorebooks/game1.pdf
  python tools/gc_ingest_pipeline.py  # auto-discovers latest CSV
        """,
    )
    parser.add_argument("--csv", metavar="PATH", help="Path to GC CSV export (relative to project root or absolute)")
    parser.add_argument("--scorebook", metavar="PATH", help="Optional: path to scorebook PDF or image")
    parser.add_argument("--out", metavar="PATH", default="", help="Output path for gc_report.json (default: data/<slug>/gc_report.json)")
    parser.add_argument("--team", default="sharks",
                        help="data_slug from config/teams.yaml (default: sharks)")
    args = parser.parse_args()

    team = require_by_slug(args.team)
    team_dir = _team_dir(team)

    # Resolve CSV path
    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.is_absolute():
            csv_path = _ROOT_DIR / csv_path
    else:
        csv_path = _auto_discover_csv()
        if not csv_path:
            print("ERROR: No CSV found. Use --csv to specify a path, or place a CSV in Scorebooks/Other docs/")
            sys.exit(1)
        print(f"[PIPELINE] Auto-discovered: {csv_path.name}")

    if not csv_path.exists():
        print(f"ERROR: CSV not found: {csv_path}")
        sys.exit(1)

    # Resolve scorebook path
    scorebook_path: Path | None = None
    if args.scorebook:
        scorebook_path = Path(args.scorebook)
        if not scorebook_path.is_absolute():
            scorebook_path = _ROOT_DIR / scorebook_path
        if not scorebook_path.exists():
            print(f"WARNING: Scorebook not found: {scorebook_path} — skipping OCR")
            scorebook_path = None

    # Resolve output path
    out_path = Path(args.out) if args.out else team_dir / "gc_report.json"
    if not out_path.is_absolute():
        out_path = _ROOT_DIR / out_path

    print(f"[PIPELINE] CSV:    {csv_path.name}")
    if scorebook_path:
        print(f"[PIPELINE] Scorebook: {scorebook_path.name}")
    print(f"[PIPELINE] Output: {out_path}")
    print()

    try:
        report = run_pipeline(csv_path, scorebook_path, out_path, team=team)
        stages = report.get("stages", {})
        passed = sum(1 for s in stages.values() if s["status"] in ("ok", "skipped"))
        total = len(stages)
        print(f"\n[PIPELINE] Done: {passed}/{total} stages ok/skipped")
        errors = [(k, v["detail"]) for k, v in stages.items() if v["status"] == "error"]
        if errors:
            for name, detail in errors:
                print(f"  ERROR in '{name}': {detail}")
            sys.exit(1)
    except RuntimeError as exc:
        print(f"\n[PIPELINE] FAILED: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
