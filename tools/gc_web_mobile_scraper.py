from __future__ import annotations

import json
import logging
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import os

from team_registry import current_gc_ids

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


def _atomic_write_json(path: Path, data) -> None:
    """Write JSON via temp-file + os.replace so a crash mid-write can't leave
    a half-written game file for the API/dashboard to read."""
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")


def _safe_int(value: str) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return 0


def _fetch_public_games(team_id: str, max_retries: int = 3) -> list[dict]:
    """Fetch GC's public games list, retrying transient failures with backoff.

    429/5xx and network timeouts are retried; a 429's Retry-After header is
    honored when present. Other 4xx responses fail immediately — retrying a
    bad team_id wastes time and gets us no further.
    """
    url = f"{GC_API_BASE}/public/teams/{team_id}/games"
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < max_retries - 1:
                    try:
                        delay = float(resp.headers.get("Retry-After") or 2 ** attempt)
                    except (TypeError, ValueError):
                        delay = 2 ** attempt  # HTTP-date form; fall back to backoff
                    time.sleep(max(0.0, min(delay, 60.0)))
                    continue
                resp.raise_for_status()
            resp.raise_for_status()
            games = resp.json()
            if not isinstance(games, list):
                return []
            return games
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    if last_exc:
        raise last_exc
    return []


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


def _sharks_score(game: dict) -> tuple[int, int]:
    """(sharks, opponent). GC's public feed reports score.team as the queried
    team's runs whether it played home or away, so no side swap is needed."""
    score = game.get("score") or {}
    return _safe_int(score.get("team")), _safe_int(score.get("opponent_team"))


def _existing_game_sources() -> tuple[dict[str, tuple[Path, str]], dict[tuple[str, str], tuple[Path, str, str]]]:
    """Existing game files, keyed by GC game id and by (date, opponent slug).

    The GC id is the stable key: opponent names drift between syncs
    ("Palm Coast Wayfinders" vs "Wayfinders"), which used to fork one game
    into two files. (date, slug) is the fallback; it also carries the file's
    gc id so a same-day doubleheader can't be matched to the other game.
    """
    by_gc_id: dict[str, tuple[Path, str]] = {}
    by_key: dict[tuple[str, str], tuple[Path, str, str]] = {}
    if not GAMES_DIR.exists():
        return by_gc_id, by_key
    for f in sorted(GAMES_DIR.glob("*.json")):
        if f.name == "index.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            date = str(data.get("date", "")).strip()
            opp = _slug(str(data.get("opponent", "")))
            src = str(data.get("source", ""))
            gc_id = str(data.get("gc_game_id", "")).strip()
            if gc_id:
                if gc_id in by_gc_id:
                    logging.warning("[web-mobile] %s and %s share gc_game_id %s; keeping the first",
                                    by_gc_id[gc_id][0].name, f.name, gc_id)
                else:
                    by_gc_id[gc_id] = (f, src)
            if date and opp:
                by_key[(date, opp)] = (f, src, gc_id)
        except Exception:
            continue
    return by_gc_id, by_key


def sync_recent_games(
    team_id: str = "",
    season_slug: str = "",
    sharks_team_name: str = "Sharks",
    max_games: int = 8,
    force: bool = False,
) -> dict:
    if not (team_id and season_slug):
        team_id, season_slug = current_gc_ids()  # never mix a caller id with a registry season
    if not (team_id and season_slug):
        raise RuntimeError("no GC team id / season slug: set GC_TEAM_ID + GC_SEASON_SLUG or config/teams.yaml")
    if sync_playwright is None:
        raise RuntimeError("playwright not installed")

    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    games = _fetch_public_games(team_id)

    completed = [g for g in games if str(g.get("game_status", "")).lower() == "completed"]
    completed.sort(key=lambda g: str(g.get("start_ts", "")), reverse=True)
    targets = completed[: max(1, int(max_games or 1))]

    existing_by_id, existing = _existing_game_sources()
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

            match = existing_by_id.get(game_id)
            if not match:
                keyed = existing.get((game_date, _slug(opponent)))
                if keyed and keyed[2] in ("", game_id):
                    match = keyed[:2]
            existing_source = ""
            if match:
                existing_file, existing_source = match
                if existing_source == "scorebook_pdf" and not force:
                    skipped_existing += 1
                    continue
                output_file = existing_file
            else:
                output_file = GAMES_DIR / f"{game_date}_{_slug(opponent)}.json"
                if output_file.exists():  # doubleheader: that name belongs to the other game
                    output_file = GAMES_DIR / f"{game_date}_{_slug(opponent)}_{game_id[:8]}.json"

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

                # The text parse has been seen returning one roster for both sides;
                # keep the score but don't publish batting lines we can't attribute.
                unparsed = [r["number"] for r in sharks_rows] == [r["number"] for r in opp_rows]
                if unparsed:
                    if existing_source == "scorebook_pdf":  # --force must not trade a scorebook for empty batting
                        skipped_existing += 1
                        continue
                    sharks_rows, opp_rows = [], []

                sharks_score, opp_score = _sharks_score(game)

                out = {
                    "game_id": output_file.stem,
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
                if unparsed:
                    out["batting_unparsed"] = True

                _atomic_write_json(output_file, out)
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

    default_team, default_season = current_gc_ids()
    parser = argparse.ArgumentParser(description="Scrape GC mobile web box scores into data/sharks/games")
    parser.add_argument("--team-id", default=default_team)
    parser.add_argument("--season-slug", default=default_season)
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
