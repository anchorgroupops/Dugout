import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


ET = ZoneInfo("America/New_York")
DEFAULT_BASE = "https://dugout.joelycannoli.com"


def _req_json(session: requests.Session, url: str, method: str = "GET", **kwargs):
    fn = getattr(session, method.lower())
    resp = fn(url, timeout=30, **kwargs)
    data = None
    try:
        data = resp.json()
    except Exception:
        data = None
    return resp, data


def run_opcheck(base_url: str, include_burst: bool = True) -> dict:
    s = requests.Session()
    base = base_url.rstrip("/")
    checks = []

    def add(name: str, ok: bool, detail: str):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    # Core data endpoints
    team_r, team = _req_json(s, f"{base}/api/team")
    add("api_team_status", team_r.status_code == 200, f"status={team_r.status_code}")
    roster = (team or {}).get("roster", []) if isinstance(team, dict) else []
    roster_count = len(roster)
    pa_nonzero = sum(1 for p in roster if (p.get("batting") or {}).get("pa", 0) > 0)
    add("team_batting_nonzero", pa_nonzero > 0, f"roster={len(roster)} pa>0={pa_nonzero}")

    games_r, games = _req_json(s, f"{base}/api/games")
    add("api_games_status", games_r.status_code == 200, f"status={games_r.status_code}")
    games = games if isinstance(games, list) else []
    w = sum(1 for g in games if str(g.get("result", "")).upper() == "W")
    l = sum(1 for g in games if str(g.get("result", "")).upper() == "L")
    sharks_wl = f"{w}-{l}"

    avail_r, avail = _req_json(s, f"{base}/api/availability")
    add("api_availability_status", avail_r.status_code == 200 and isinstance(avail, dict), f"status={avail_r.status_code}")

    standings_r, standings = _req_json(s, f"{base}/api/standings")
    add("api_standings_status", standings_r.status_code == 200, f"status={standings_r.status_code}")
    sharks_row = None
    for row in (standings or {}).get("standings", []):
        if str(row.get("slug", "")).lower() == "sharks":
            sharks_row = row
            break
    add(
        "standings_games_consistency",
        bool(sharks_row) and sharks_row.get("record") == sharks_wl and sharks_row.get("team_name") == "The Sharks",
        f"games={sharks_wl} standings={None if not sharks_row else sharks_row.get('record')} name={None if not sharks_row else sharks_row.get('team_name')}",
    )

    # Matchups
    for slug, expect_nonempty in (("peppers", True), ("riptide_rebels", True), ("ravens", False)):
        mr, md = _req_json(s, f"{base}/api/matchup/{slug}")
        ok = mr.status_code == 200
        detail = f"status={mr.status_code}"
        if isinstance(md, dict):
            empty = bool(md.get("empty"))
            data_source = md.get("data_source")
            reason = md.get("reason")
            if expect_nonempty:
                ok = ok and (not empty)
            else:
                ok = ok and (reason is not None or not empty)
            detail += f" empty={empty} data_source={data_source} reason={reason}"
            if slug == "ravens" and isinstance(md.get("opponent_public_metrics"), dict):
                lsg = int(md["opponent_public_metrics"].get("line_score_games", 0) or 0)
                ok = ok and lsg >= 1
                detail += f" line_score_games={lsg}"
        add(f"matchup_{slug}", ok, detail)

    time.sleep(0.5)

    # SWOT + lineups artifacts
    swot_r, swot = _req_json(s, f"{base}/data/sharks/swot_analysis.json")
    analyses = (swot or {}).get("player_analyses", []) if isinstance(swot, dict) else []
    min_expected = max(1, roster_count - 1)
    add(
        "swot_artifact",
        swot_r.status_code == 200 and len(analyses) >= min_expected,
        f"status={swot_r.status_code} player_analyses={len(analyses)} expected>={min_expected}",
    )

    line_r, lineups = _req_json(s, f"{base}/data/sharks/lineups.json")
    balanced = (((lineups or {}).get("balanced") or {}).get("lineup") or []) if isinstance(lineups, dict) else []
    lineup_nonzero = sum(1 for p in balanced[:9] if (p.get("pa", 0) or 0) > 0)
    # Reuse availability data already fetched above
    active_count = sum(1 for v in (avail or {}).values() if v is not False)
    # Pass if lineup exists and has as many players as active roster (or 9+)
    lineup_ok = line_r.status_code == 200 and len(balanced) > 0 and (
        len(balanced) >= min(9, active_count) and lineup_nonzero > 0
    )
    add("lineups_artifact", lineup_ok, f"status={line_r.status_code} lineup={len(balanced)} active={active_count} first9_pa>0={lineup_nonzero}")

    # Reconcile team batting totals vs parsed scorebooks (team should never undercount).
    gd_r, games_detail = _req_json(s, f"{base}/api/games?detail=1")
    deficits = []
    if gd_r.status_code == 200 and isinstance(games_detail, list):
        from collections import defaultdict

        agg = defaultdict(lambda: defaultdict(int))
        for g in games_detail:
            for row in g.get("sharks_batting", []) or []:
                num = str(row.get("number", "")).strip()
                if not num:
                    continue
                batting = row.get("batting", row) if isinstance(row, dict) else {}
                for stat in ("pa", "ab", "h", "bb", "hbp", "so", "rbi", "sb", "r"):
                    agg[num][stat] += int(round(float((batting or {}).get(stat, 0) or 0)))

        team_by_num = {}
        for p in roster:
            num = str((p or {}).get("number", "")).strip()
            if num:
                team_by_num[num] = (p or {}).get("batting", {}) or {}

        for num, s_totals in agg.items():
            t = team_by_num.get(num)
            if not t:
                continue
            for stat, sb_val in s_totals.items():
                tv = int(round(float((t or {}).get(stat, 0) or 0)))
                if tv < sb_val:
                    deficits.append(f"#{num}:{stat} team={tv}<scorebook={sb_val}")
    add(
        "scorebook_reconciliation",
        gd_r.status_code == 200 and len(deficits) == 0,
        f"status={gd_r.status_code} deficits={len(deficits)} sample={deficits[:5]}",
    )

    time.sleep(0.5)

    health_r, health = _req_json(s, f"{base}/data/sharks/pipeline_health.json")
    has_required = isinstance(health, dict) and "required_field_coverage" in health
    add("pipeline_health_artifact", health_r.status_code == 200 and has_required, f"status={health_r.status_code}")

    discovery_r, discovery = _req_json(s, f"{base}/api/opponent-discovery")
    add(
        "opponent_discovery_artifact",
        discovery_r.status_code == 200 and isinstance(discovery, dict),
        f"status={discovery_r.status_code} teams={len((discovery or {}).get('teams', [])) if isinstance(discovery, dict) else 'n/a'}",
    )

    db_r, db = _req_json(s, f"{base}/api/stats-db/status")
    db_ok = (
        db_r.status_code == 200
        and isinstance(db, dict)
        and isinstance(db.get("snapshot_count"), int)
        and db.get("snapshot_count", 0) >= 1
    )
    add(
        "stats_db_status",
        db_ok,
        f"status={db_r.status_code} snapshots={None if not isinstance(db, dict) else db.get('snapshot_count')} latest={None if not isinstance(db, dict) else db.get('latest')}",
    )

    practice_r, practice = _req_json(s, f"{base}/api/practice-insights")
    practice_ok = (
        practice_r.status_code == 200
        and isinstance(practice, dict)
        and isinstance(practice.get("needs"), list)
        and isinstance(practice.get("selected_players"), list)
    )
    add(
        "practice_insights",
        practice_ok,
        f"status={practice_r.status_code} needs={len(practice.get('needs', [])) if isinstance(practice, dict) else 'n/a'} selected={len(practice.get('selected_players', [])) if isinstance(practice, dict) else 'n/a'} source={practice.get('default_player_source') if isinstance(practice, dict) else 'n/a'}",
    )

    time.sleep(0.5)

    # Security headers and method controls — reuse the first /api/team response (already fetched above)
    headers = {k.lower(): v for k, v in team_r.headers.items()}
    required_headers = [
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
        "content-security-policy",
        "cross-origin-resource-policy",
        "cross-origin-opener-policy",
        "x-permitted-cross-domain-policies",
        "strict-transport-security",
    ]
    missing = [h for h in required_headers if h not in headers]
    add("security_headers", len(missing) == 0, f"missing={missing}")
    add(
        "api_cache_control_no_store",
        "no-store" in (headers.get("cache-control", "").lower()),
        f"cache_control={headers.get('cache-control', '')}",
    )

    get_mutate = s.get(f"{base}/api/regenerate-lineups", timeout=30)
    add("mutate_method_guard", get_mutate.status_code in (403, 405), f"status={get_mutate.status_code}")

    bad_ct = s.post(
        f"{base}/api/regenerate-lineups",
        headers={"Content-Type": "text/plain", "Origin": base},
        data="{}",
        timeout=30,
    )
    add("mutate_content_type_guard", bad_ct.status_code in (415, 400), f"status={bad_ct.status_code}")

    oversized_payload = {"blob": "x" * 150000}
    too_large = s.post(
        f"{base}/api/regenerate-lineups",
        headers={"Content-Type": "application/json", "Origin": base},
        json=oversized_payload,
        timeout=30,
    )
    add("mutate_payload_size_guard", too_large.status_code == 413, f"status={too_large.status_code}")

    bad_origin = s.post(
        f"{base}/api/regenerate-lineups",
        headers={"Content-Type": "application/json", "Origin": "https://evil.example"},
        json={},
        timeout=30,
    )
    add("mutate_origin_guard", bad_origin.status_code == 403, f"status={bad_origin.status_code}")

    if include_burst:
        read_statuses = []
        for _ in range(35):
            read_statuses.append(s.get(f"{base}/api/team", timeout=20).status_code)
            time.sleep(0.03)
        read_429 = sum(1 for c in read_statuses if c == 429)
        add("read_rate_limit_smoke", read_429 >= 1, f"429={read_429}/35")

        write_statuses = []
        for _ in range(10):
            resp = s.post(
                f"{base}/api/regenerate-lineups",
                headers={"Content-Type": "application/json", "Origin": base},
                json={},
                timeout=20,
            )
            write_statuses.append(resp.status_code)
            time.sleep(0.05)
        write_429 = sum(1 for c in write_statuses if c == 429)
        add("write_rate_limit_smoke", write_429 >= 1, f"429={write_429}/10 statuses={write_statuses}")

    passed = sum(1 for c in checks if c["ok"])
    return {
        "generated_at": datetime.now(ET).isoformat(),
        "base_url": base,
        "summary": {
            "total": len(checks),
            "passed": passed,
            "failed": len(checks) - passed,
        },
        "checks": checks,
    }


def check_local_pipeline_artifacts(root_dir: Path = None) -> dict:
    """
    Check local pipeline artifact health (offline, no HTTP calls).
    Verifies that the CSV-based ingest pipeline has produced expected outputs.

    Run with: python tools/opcheck.py --local
    """
    if root_dir is None:
        root_dir = Path(__file__).resolve().parent.parent
    sharks_dir = root_dir / "data" / "sharks"

    checks = []

    def add(name: str, ok: bool, detail: str):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    # 1. Pipeline scripts exist
    tools_dir = root_dir / "tools"
    add(
        "gc_ingest_pipeline_exists",
        (tools_dir / "gc_ingest_pipeline.py").exists(),
        f"path={tools_dir / 'gc_ingest_pipeline.py'}",
    )
    add(
        "scorebook_ocr_exists",
        (tools_dir / "scorebook_ocr.py").exists(),
        f"path={tools_dir / 'scorebook_ocr.py'}",
    )

    # 2. CSV source ingested (season_stats.csv = copy of the source export)
    season_csv = sharks_dir / "season_stats.csv"
    add("csv_source_ingested", season_csv.exists(), f"path={season_csv} exists={season_csv.exists()}")

    # 3. team.json exists and has a non-empty roster
    team_file = sharks_dir / "team.json"
    roster_count = 0
    if team_file.exists():
        try:
            with open(team_file) as f:
                team = json.load(f)
            roster_count = len(team.get("roster", []))
        except Exception:
            pass
    add("team_json_has_roster", roster_count > 0, f"path={team_file} roster_size={roster_count}")

    # 4. swot_analysis.json exists and has player analyses
    swot_file = sharks_dir / "swot_analysis.json"
    swot_count = 0
    if swot_file.exists():
        try:
            with open(swot_file) as f:
                swot = json.load(f)
            swot_count = len(swot.get("player_analyses", []))
        except Exception:
            pass
    add("swot_analysis_populated", swot_count > 0, f"path={swot_file} player_analyses={swot_count}")

    # 5. lineups.json exists and has a balanced lineup
    lineups_file = sharks_dir / "lineups.json"
    lineup_len = 0
    if lineups_file.exists():
        try:
            with open(lineups_file) as f:
                lineups = json.load(f)
            lineup_len = len((lineups.get("balanced") or {}).get("lineup", []))
        except Exception:
            pass
    add("lineups_json_populated", lineup_len > 0, f"path={lineups_file} balanced_lineup={lineup_len}")

    # 6. next_practice.txt exists and is non-empty
    practice_file = sharks_dir / "next_practice.txt"
    practice_size = practice_file.stat().st_size if practice_file.exists() else 0
    add("practice_plan_generated", practice_size > 0, f"path={practice_file} size={practice_size}")

    # 7. gc_report.json exists (pipeline ran to completion)
    report_file = sharks_dir / "gc_report.json"
    add("gc_report_exists", report_file.exists(), f"path={report_file} exists={report_file.exists()}")

    # 8. stats_history.db exists (SQLite snapshot recorded)
    db_file = sharks_dir / "stats_history.db"
    add("sqlite_db_exists", db_file.exists(), f"path={db_file} exists={db_file.exists()}")

    passed = sum(1 for c in checks if c["ok"])
    return {
        "generated_at": datetime.now(ET).isoformat(),
        "type": "local_pipeline_artifacts",
        "summary": {
            "total": len(checks),
            "passed": passed,
            "failed": len(checks) - passed,
        },
        "checks": checks,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--no-burst", action="store_true", help="Skip burst/rate-limit checks.")
    parser.add_argument("--out", default="", help="Optional output file for JSON report.")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run local artifact checks only (no HTTP calls). Use after running gc_ingest_pipeline.py.",
    )
    args = parser.parse_args()

    if args.local:
        report = check_local_pipeline_artifacts()
    else:
        report = run_opcheck(args.base_url, include_burst=not args.no_burst)

    text = json.dumps(report, indent=2)
    print(text)

    out_file = args.out.strip()
    if out_file:
        out_path = Path(out_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
