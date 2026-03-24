from __future__ import annotations

import json
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
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data" / "sharks"
GAMES_DIR = DATA_DIR / "games"

GC_BASE = "https://web.gc.com"
GC_API_BASE = "https://api.team-manager.gc.com"
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")


def _safe_int(value: str) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return 0


def _fetch_public_games(team_id: str) -> list[dict]:
    url = f"{GC_API_BASE}/public/teams/{team_id}/games"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    games = resp.json()
    if not isinstance(games, list):
        return []
    return games


def _valid_team_name(text: str) -> bool:
    if not text or "\t" in text:
        return False
    t = text.strip()
    if len(t) < 2 or len(t) > 60:
        return False
    if t.upper() in {"LINEUP", "PITCHING", "TEAM", "RECAP", "BOX SCORE", "PLAYS", "VIDEOS", "INFO"}:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9 .&'/-]+", t))


def _parse_lineup(tokens: list[str], team_name: str) -> list[dict]:
    rows: list[dict] = []
    upper = [t.upper() for t in tokens]
    for idx, t in enumerate(upper):
        if t != "LINEUP" or idx == 0:
            continue
        if tokens[idx - 1].strip().lower() != team_name.strip().lower():
            continue

        i = idx + 1
        if tokens[i : i + 6] == ["AB", "R", "H", "RBI", "BB", "SO"]:
            i += 6

        while i + 7 < len(tokens):
            marker = tokens[i].upper()
            if marker in {"TEAM", "PITCHING", "LINEUP", "RECAP", "BOX SCORE", "PLAYS", "VIDEOS", "INFO"}:
                break

            name = tokens[i].strip()
            number_token = tokens[i + 1].strip()
            m = re.search(r"#\s*([0-9A-Za-z]+)", number_token)
            if not m:
                i += 1
                continue

            stats = tokens[i + 2 : i + 8]
            if not all(re.fullmatch(r"-?\d+", s.strip()) for s in stats):
                i += 1
                continue

            ab, runs, hits, rbi, bb, so = [int(s.strip()) for s in stats]
            rows.append(
                {
                    "number": m.group(1),
                    "name": name,
                    "pos": "",
                    "batting": {
                        "pa": ab + bb,
                        "ab": ab,
                        "h": hits,
                        "singles": hits,
                        "doubles": 0,
                        "triples": 0,
                        "hr": 0,
                        "bb": bb,
                        "hbp": 0,
                        "so": so,
                        "sac": 0,
                        "r": runs,
                        "rbi": rbi,
                        "sb": 0,
                    },
                }
            )
            i += 8
        break

    return rows


def _extract_teams_from_lineups(tokens: list[str]) -> list[str]:
    teams: list[str] = []
    for i, tok in enumerate(tokens):
        if tok.upper() == "LINEUP" and i > 0:
            t = tokens[i - 1].strip()
            if _valid_team_name(t) and t not in teams:
                teams.append(t)
    return teams


def _parse_all_lineups(tokens: list[str]) -> list[tuple[str, list[dict]]]:
    parsed: list[tuple[str, list[dict]]] = []
    for team in _extract_teams_from_lineups(tokens):
        rows = _parse_lineup(tokens, team)
        if rows:
            parsed.append((team, rows))
    return parsed


def _choose_sharks_lineup(
    lineups: list[tuple[str, list[dict]]],
    sharks_side: str,
) -> tuple[list[dict], list[dict], str]:
    if len(lineups) < 2:
        return [], [], ""

    # GC mobile web box-score layout is consistently away lineup first, home lineup second.
    # Use schedule home_away to map sharks/opponent deterministically.
    if str(sharks_side).lower() == "away":
        sharks_team, sharks_rows = lineups[0]
        opp_team, opp_rows = lineups[1]
    else:
        sharks_team, sharks_rows = lineups[1]
        opp_team, opp_rows = lineups[0]
    return sharks_rows, opp_rows, opp_team


def _parse_boxscore_text(body_text: str, sharks_side: str) -> tuple[list[dict], list[dict], str]:
    tokens = [line.strip() for line in body_text.splitlines() if line.strip()]
    lineups = _parse_all_lineups(tokens)
    if len(lineups) < 2:
        return [], [], ""
    return _choose_sharks_lineup(lineups, sharks_side=sharks_side)


def _existing_game_sources() -> dict[tuple[str, str], tuple[Path, str]]:
    out: dict[tuple[str, str], tuple[Path, str]] = {}
    if not GAMES_DIR.exists():
        return out
    for f in GAMES_DIR.glob("*.json"):
        if f.name == "index.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            date = str(data.get("date", "")).strip()
            opp = _slug(str(data.get("opponent", "")))
            src = str(data.get("source", ""))
            if date and opp:
                out[(date, opp)] = (f, src)
        except Exception:
            continue
    return out


def sync_recent_games(
    team_id: str = "NuGgx6WvP7TO",
    season_slug: str = "2026-spring-sharks",
    sharks_team_name: str = "Sharks",
    max_games: int = 8,
    force: bool = False,
) -> dict:
    if sync_playwright is None:
        raise RuntimeError("playwright not installed")

    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    games = _fetch_public_games(team_id)

    completed = [g for g in games if str(g.get("game_status", "")).lower() == "completed"]
    completed.sort(key=lambda g: str(g.get("start_ts", "")), reverse=True)
    targets = completed[: max(1, int(max_games or 1))]

    existing = _existing_game_sources()
    saved = 0
    skipped_existing = 0
    failed = 0
    outputs: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(user_agent=MOBILE_UA, viewport={"width": 390, "height": 844})
        page = context.new_page()

        for game in targets:
            game_id = str(game.get("id", "")).strip()
            if not game_id:
                continue

            opponent = ((game.get("opponent_team") or {}).get("name") or "Opponent").strip()
            start_ts = str(game.get("start_ts", "")).strip()
            try:
                game_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00")).astimezone(ET)
                game_date = game_dt.date().isoformat()
            except Exception:
                game_date = datetime.now(ET).date().isoformat()

            key = (game_date, _slug(opponent))
            if key in existing and not force:
                existing_file, existing_source = existing[key]
                if existing_source == "scorebook_pdf":
                    skipped_existing += 1
                    continue
                output_file = existing_file
            else:
                output_file = GAMES_DIR / f"{game_date}_{_slug(opponent)}.json"

            box_url = f"{GC_BASE}/teams/{team_id}/{season_slug}/schedule/{game_id}/box-score"
            try:
                page.goto(box_url, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(2500)
                body_text = page.inner_text("body")
                sharks_side = "home" if str(game.get("home_away", "")).lower() == "home" else "away"
                sharks_rows, opp_rows, parsed_opp_name = _parse_boxscore_text(body_text, sharks_side=sharks_side)
                if not sharks_rows:
                    failed += 1
                    continue

                if sharks_side == "home":
                    sharks_score = _safe_int(((game.get("score") or {}).get("team")))
                    opp_score = _safe_int(((game.get("score") or {}).get("opponent_team")))
                else:
                    sharks_score = _safe_int(((game.get("score") or {}).get("opponent_team")))
                    opp_score = _safe_int(((game.get("score") or {}).get("team")))

                out = {
                    "game_id": f"{game_date}_{_slug(opponent)}",
                    "gc_game_id": game_id,
                    "date": game_date,
                    "opponent": opponent,
                    "opponent_parsed": parsed_opp_name or opponent,
                    "sharks_side": sharks_side,
                    "source": "gc_web_mobile_boxscore",
                    "box_score_url": box_url,
                    "captured_at": datetime.now(ET).isoformat(),
                    "score": {"sharks": sharks_score, "opponent": opp_score},
                    "sharks_batting": sharks_rows,
                    "opponent_batting": opp_rows,
                }

                output_file.write_text(json.dumps(out, indent=2), encoding="utf-8")
                outputs.append(str(output_file))
                saved += 1
            except Exception:
                failed += 1
                continue

        context.close()
        browser.close()

    return {
        "target_games": len(targets),
        "saved": saved,
        "skipped_existing": skipped_existing,
        "failed": failed,
        "outputs": outputs,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Scrape GC mobile web box scores into data/sharks/games")
    parser.add_argument("--team-id", default="NuGgx6WvP7TO")
    parser.add_argument("--season-slug", default="2026-spring-sharks")
    parser.add_argument("--sharks-name", default="Sharks")
    parser.add_argument("--max-games", type=int, default=8)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = sync_recent_games(
        team_id=args.team_id,
        season_slug=args.season_slug,
        sharks_team_name=args.sharks_name,
        max_games=args.max_games,
        force=args.force,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("saved", 0) > 0 or result.get("skipped_existing", 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
