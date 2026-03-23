import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


ET = ZoneInfo("America/New_York")
GC_PUBLIC_API = "https://api.team-manager.gc.com/public"
DEFAULT_ORG_IDS = ["7ZUyPJwky5DG"]  # Palm Coast Little League

SLUG_OVERRIDES = {
    "riptide": "riptide_rebels",
    "pepper": "peppers",
    "raven": "ravens",
    "wildcat": "wildcats",
    "nwvll": "nwvll",
    "stihler": "nwvll",
    "5 star": "nwvll",
    "5_star": "nwvll",
    "sharks": "sharks",
}


def _clean_name(name: str) -> str:
    txt = (name or "").strip()
    for prefix in ("@ ", "vs. ", "vs ", "at "):
        if txt.lower().startswith(prefix):
            txt = txt[len(prefix):]
    return txt.strip()


def _slug(name: str) -> str:
    raw = _clean_name(name).lower()
    for fragment, canonical in SLUG_OVERRIDES.items():
        if fragment in raw:
            return canonical
    return re.sub(r"[^a-z0-9]+", "_", raw).strip("_")[:48] or "unknown"


def _safe_get_json(url: str, timeout: int = 15):
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _record_to_string(rec: dict) -> str:
    if not isinstance(rec, dict):
        return "0-0"
    w = int(rec.get("win", 0) or 0)
    l = int(rec.get("loss", 0) or 0)
    t = int(rec.get("tie", 0) or 0)
    return f"{w}-{l}" if t == 0 else f"{w}-{l}-{t}"


def _parse_org_ids() -> list[str]:
    raw = os.getenv("GC_ORG_IDS", ",".join(DEFAULT_ORG_IDS))
    ids = [x.strip() for x in raw.split(",") if x.strip()]
    return ids or list(DEFAULT_ORG_IDS)


def _fetch_public_game_metrics(team_id: str) -> dict:
    games = _safe_get_json(f"{GC_PUBLIC_API}/teams/{team_id}/games") or []
    completed = 0
    wins = losses = ties = 0
    runs_scored = 0
    runs_allowed = 0
    for g in games:
        score = (g or {}).get("score") or {}
        if not isinstance(score, dict):
            continue
        if "team" not in score or "opponent_team" not in score:
            continue
        try:
            our = int(score.get("team", 0) or 0)
            opp = int(score.get("opponent_team", 0) or 0)
        except Exception:
            continue
        completed += 1
        runs_scored += our
        runs_allowed += opp
        if our > opp:
            wins += 1
        elif our < opp:
            losses += 1
        else:
            ties += 1

    return {
        "games_total": len(games),
        "completed_games": completed,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "runs_scored": runs_scored,
        "runs_allowed": runs_allowed,
        "runs_scored_per_game": round(runs_scored / completed, 2) if completed else 0.0,
        "runs_allowed_per_game": round(runs_allowed / completed, 2) if completed else 0.0,
    }


def _discover_from_orgs(org_ids: list[str]) -> dict[str, dict]:
    """Return mapping keyed by team_id with merged org/public-team metadata."""
    discovered: dict[str, dict] = {}
    now = datetime.now(ET)
    start = f"{now.year - 1}-01-01"
    end = f"{now.year + 1}-12-31"

    for org_id in org_ids:
        teams = _safe_get_json(f"{GC_PUBLIC_API}/organizations/{org_id}/teams") or []
        standings = _safe_get_json(f"{GC_PUBLIC_API}/organizations/{org_id}/standings") or []
        events = _safe_get_json(
            f"{GC_PUBLIC_API}/organizations/{org_id}/events?startDate={start}&endDate={end}"
        ) or []

        standings_by_team = {}
        for row in standings:
            team_id = (row or {}).get("team_id")
            overall = (row or {}).get("overall") or {}
            if team_id:
                standings_by_team[team_id] = {
                    "win": int(overall.get("wins", 0) or 0),
                    "loss": int(overall.get("losses", 0) or 0),
                    "tie": int(overall.get("ties", 0) or 0),
                }

        # Primary source: explicit org teams feed.
        for t in teams:
            team_id = str((t or {}).get("id", "")).strip()
            if not team_id:
                continue
            name = (t or {}).get("name", "") or team_id
            item = discovered.setdefault(
                team_id,
                {
                    "team_id": team_id,
                    "team_name": name,
                    "slug": _slug(name),
                    "organization_ids": [],
                    "record": "0-0",
                    "season_slug": "",
                },
            )
            if org_id not in item["organization_ids"]:
                item["organization_ids"].append(org_id)
            if team_id in standings_by_team:
                item["record"] = _record_to_string(standings_by_team[team_id])

        # Secondary source: org events can include teams not currently in /teams list.
        for ev in events:
            for side in ("home_team", "away_team"):
                t = (ev or {}).get(side) or {}
                team_id = str(t.get("id", "")).strip()
                if not team_id:
                    continue
                name = t.get("name", "") or team_id
                item = discovered.setdefault(
                    team_id,
                    {
                        "team_id": team_id,
                        "team_name": name,
                        "slug": _slug(name),
                        "organization_ids": [],
                        "record": "0-0",
                        "season_slug": "",
                    },
                )
                if org_id not in item["organization_ids"]:
                    item["organization_ids"].append(org_id)

    # Enrich with public team details (record/season from team profile API).
    for team_id, item in discovered.items():
        detail = _safe_get_json(f"{GC_PUBLIC_API}/teams/{team_id}") or {}
        team_name = (detail.get("name") or "").strip()
        if team_name:
            item["team_name"] = team_name
            item["slug"] = _slug(team_name)
        season = (detail.get("team_season") or {}).get("season")
        year = (detail.get("team_season") or {}).get("year")
        record = (detail.get("team_season") or {}).get("record")
        if isinstance(record, dict):
            item["record"] = _record_to_string(record)
        if season and year and not item.get("season_slug"):
            # Best effort fallback; exact slug may differ for special naming.
            safe_name = re.sub(r"[^a-z0-9]+", "-", item["team_name"].lower()).strip("-")
            item["season_slug"] = f"{year}-{season}-{safe_name}"
        item["public_game_metrics"] = _fetch_public_game_metrics(team_id)

    return discovered


def _resolve_exact_season_slugs(team_ids: list[str]) -> dict[str, str]:
    """Resolve exact season slug via hydrated team page links.
    This improves reliability for teams with non-standard season slugs."""
    slugs: dict[str, str] = {}
    if sync_playwright is None or not team_ids:
        return slugs
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            for team_id in team_ids:
                try:
                    page.goto(f"https://web.gc.com/teams/{team_id}", wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(4500)
                    html = page.content()
                    matches = re.findall(rf"/teams/{re.escape(team_id)}/([A-Za-z0-9\-]+)", html)
                    candidates = [m for m in matches if m != "schedule"]
                    if candidates:
                        slugs[team_id] = candidates[0]
                except Exception:
                    continue
            browser.close()
    except Exception:
        return slugs
    return slugs


def _load_schedule_opponents(data_dir: Path) -> list[str]:
    schedule_file = data_dir / "sharks" / "schedule_manual.json"
    if not schedule_file.exists():
        return []
    try:
        with open(schedule_file) as f:
            sched = json.load(f)
    except Exception:
        return []
    names = []
    for section in ("upcoming", "past"):
        for game in (sched.get(section) or []):
            if game.get("is_game"):
                names.append(_clean_name(game.get("opponent", "")))
    return [n for n in names if n]


def discover_and_persist_opponents(data_dir: Path | None = None, sharks_team_id: str = "NuGgx6WvP7TO") -> dict:
    data_root = Path(data_dir) if data_dir else (Path(__file__).parent.parent / "data")
    opponents_dir = data_root / "opponents"
    sharks_dir = data_root / "sharks"
    pcll_teams_file = data_root / "pcll_teams.json"
    artifact_file = sharks_dir / "opponent_discovery.json"
    opponents_dir.mkdir(parents=True, exist_ok=True)
    sharks_dir.mkdir(parents=True, exist_ok=True)

    org_ids = _parse_org_ids()
    discovered_by_id = _discover_from_orgs(org_ids)
    exact_slugs = _resolve_exact_season_slugs(list(discovered_by_id.keys()))
    for team_id, season_slug in exact_slugs.items():
        if team_id in discovered_by_id and season_slug:
            discovered_by_id[team_id]["season_slug"] = season_slug

    by_slug = {}
    for team_id, item in discovered_by_id.items():
        slug = item.get("slug") or _slug(item.get("team_name", ""))
        by_slug[slug] = item

    discovered_written = 0
    for slug, item in by_slug.items():
        if item.get("team_id") == sharks_team_id or slug == "sharks":
            continue
        path = opponents_dir / slug / "team.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = {}
        if path.exists():
            try:
                with open(path) as f:
                    existing = json.load(f)
            except Exception:
                existing = {}

        out = {
            "team_name": item.get("team_name") or existing.get("team_name") or slug.replace("_", " ").title(),
            "slug": slug,
            "record": item.get("record") or existing.get("record", "0-0"),
            "gc_team_id": item.get("team_id") or existing.get("gc_team_id"),
            "gc_season_slug": item.get("season_slug") or existing.get("gc_season_slug", ""),
            "last_updated": datetime.now(ET).isoformat(),
            "source": existing.get("source", "gc_app"),
            "roster": existing.get("roster", []),
            "batting_stats": existing.get("batting_stats", []),
            "pitching_stats": existing.get("pitching_stats", []),
            "fielding_stats": existing.get("fielding_stats", []),
            "public_game_metrics": item.get("public_game_metrics", existing.get("public_game_metrics", {})),
            "discovery": {
                "method": "gc_public_org_api",
                "organization_ids": item.get("organization_ids", []),
                "discovered_at": datetime.now(ET).isoformat(),
            },
        }

        with open(path, "w") as f:
            json.dump(out, f, indent=2)
        discovered_written += 1

    pcll_rows = []
    for slug, item in by_slug.items():
        if item.get("team_id"):
            pcll_rows.append(
                {
                    "team_name": item.get("team_name", slug),
                    "slug": slug,
                    "gc_team_id": item.get("team_id"),
                    "gc_season_slug": item.get("season_slug", ""),
                }
            )
    pcll_rows.sort(key=lambda x: x["team_name"].lower())
    with open(pcll_teams_file, "w") as f:
        json.dump(pcll_rows, f, indent=2)

    schedule_opponents = _load_schedule_opponents(data_root)
    known_slugs = set(by_slug.keys()) | {"sharks"}
    missing_from_discovery = []
    for opp in schedule_opponents:
        sl = _slug(opp)
        if sl not in known_slugs:
            missing_from_discovery.append({"name": opp, "slug": sl})

    artifact = {
        "generated_at": datetime.now(ET).isoformat(),
        "organization_ids": org_ids,
        "discovered_teams": len(by_slug),
        "persisted_opponents": discovered_written,
        "missing_schedule_opponents": missing_from_discovery,
        "teams": sorted(
            [
                {
                    "team_name": item.get("team_name", ""),
                    "slug": slug,
                    "gc_team_id": item.get("team_id", ""),
                    "gc_season_slug": item.get("season_slug", ""),
                    "record": item.get("record", "0-0"),
                    "public_game_metrics": item.get("public_game_metrics", {}),
                    "organization_ids": item.get("organization_ids", []),
                }
                for slug, item in by_slug.items()
                if slug != "sharks"
            ],
            key=lambda x: x["team_name"].lower(),
        ),
    }
    with open(artifact_file, "w") as f:
        json.dump(artifact, f, indent=2)

    logging.info(
        "[OpponentDiscovery] org_ids=%s discovered=%s persisted=%s missing_schedule=%s",
        ",".join(org_ids),
        len(by_slug),
        discovered_written,
        len(missing_from_discovery),
    )
    return artifact


if __name__ == "__main__":
    result = discover_and_persist_opponents()
    print(json.dumps(result, indent=2))
