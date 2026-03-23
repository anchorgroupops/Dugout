import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


ET = ZoneInfo("America/New_York")
DEFAULT_BASE = "https://sharks.joelycannoli.com"


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
    add("lineups_artifact", line_r.status_code == 200 and len(balanced) >= 9 and lineup_nonzero > 0, f"status={line_r.status_code} first9_pa>0={lineup_nonzero}")

    health_r, health = _req_json(s, f"{base}/data/sharks/pipeline_health.json")
    has_required = isinstance(health, dict) and "required_field_coverage" in health
    add("pipeline_health_artifact", health_r.status_code == 200 and has_required, f"status={health_r.status_code}")

    discovery_r, discovery = _req_json(s, f"{base}/api/opponent-discovery")
    add(
        "opponent_discovery_artifact",
        discovery_r.status_code == 200 and isinstance(discovery, dict),
        f"status={discovery_r.status_code} teams={len((discovery or {}).get('teams', [])) if isinstance(discovery, dict) else 'n/a'}",
    )

    # Security headers and method controls
    hdr_r = s.get(f"{base}/api/team", timeout=30)
    headers = {k.lower(): v for k, v in hdr_r.headers.items()}
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--no-burst", action="store_true", help="Skip burst/rate-limit checks.")
    parser.add_argument("--out", default="", help="Optional output file for JSON report.")
    args = parser.parse_args()

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
