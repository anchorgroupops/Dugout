"""Dugout tablet: arm flag, shared files and the /api/live/tablet payload.

Files under data/live_tablet/ (shared volume, so the API and sync containers
both see them):
    armed.json         written by POST /api/live/arm; expires on its own
    status.json        worker heartbeat: last poll time, last GC HTTP code
    state.json         newest parsed game (same shape as games/<event>.json)
    games/<event>.json one parsed game per GC event, live or backfilled

A game doc is {"meta": {...}, "players": {pid: {...}}, "parsed": <gc_live_stream
snapshot>, "fetched_at": iso}. Contract for the payload: docs/live_tablet_contract.md.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ARM_DEFAULT_HOURS = 3
ARM_MAX_HOURS = 4
STALE_AFTER_S = 60
SHOW_FINAL_FOR_S = 6 * 3600
FIELD = {"width": 320, "height": 320, "home": [160, 292]}


def live_dir(data_dir) -> Path:
    return Path(data_dir) / "live_tablet"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json_atomic(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, separators=(",", ":"))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# -- arm flag ------------------------------------------------------------------

def arm(data_dir, now: datetime, hours: float = ARM_DEFAULT_HOURS) -> dict:
    hours = max(0.25, min(float(hours), ARM_MAX_HOURS))
    doc = {"armed_at": _iso(now), "expires_at": _iso(now + timedelta(hours=hours))}
    write_json_atomic(live_dir(data_dir) / "armed.json", doc)
    return doc


def disarm(data_dir) -> None:
    try:
        (live_dir(data_dir) / "armed.json").unlink()
    except FileNotFoundError:
        pass


def read_arm(data_dir, now: datetime) -> dict | None:
    """The arm doc while it is still in force, else None."""
    doc = read_json(live_dir(data_dir) / "armed.json")
    if not isinstance(doc, dict):
        return None
    expires = _parse_iso(doc.get("expires_at"))
    if not expires or expires <= now:
        return None
    return doc


def public_status(data_dir, now: datetime) -> dict:
    """/api/live/status: unauthenticated, so counts and codes only — no
    names, ids or GC URLs."""
    armed = read_arm(data_dir, now)
    st = read_json(live_dir(data_dir) / "status.json", {}) or {}
    last = _parse_iso(st.get("last_poll_at"))
    return {
        "armed": bool(armed),
        "armed_until": armed.get("expires_at") if armed else None,
        "last_poll_at": st.get("last_poll_at"),
        "last_poll_age_s": int((now - last).total_seconds()) if last else None,
        "last_http": st.get("last_http"),
        "events_seen": st.get("events_seen"),
        "phase": st.get("phase"),
        "error": st.get("error"),
    }


# -- payload -------------------------------------------------------------------

def _name_key(p: dict | None) -> str:
    name = (p or {}).get("name") or ""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _side(team_id, sharks_id) -> str:
    return "sharks" if team_id == sharks_id else "opponent"


def _player(pid, doc) -> dict | None:
    if not pid:
        return None
    sharks_id = doc["meta"].get("sharks_team_id")
    info = (doc.get("players") or {}).get(pid) or {}
    return {
        "id": pid,
        "name": info.get("name") or "Unknown",
        "number": str(info.get("number") or ""),
        "team": _side(info.get("team_id"), sharks_id) if info.get("team_id") else None,
    }


def load_games(data_dir) -> list:
    games = []
    for f in sorted((live_dir(data_dir) / "games").glob("*.json")):
        doc = read_json(f)
        if isinstance(doc, dict) and isinstance(doc.get("parsed"), dict) and isinstance(doc.get("meta"), dict):
            games.append(doc)
    return games


def _batter_card(pid, doc, games) -> dict | None:
    me = _player(pid, doc)
    if not me:
        return None
    sharks_id = doc["meta"].get("sharks_team_id")
    my_team = (doc.get("players") or {}).get(pid, {}).get("team_id") or doc["parsed"].get("batting_team")
    me["team"] = _side(my_team, sharks_id)
    key = _name_key(me) if me["name"] != "Unknown" else ""
    today_id = doc["meta"].get("event_id")

    def is_me(g, batter_id, team_id):
        if batter_id == pid:
            return True
        if not key:
            return False
        other = (g.get("players") or {}).get(batter_id)
        return (_name_key(other) == key
                and _side(team_id, g["meta"].get("sharks_team_id")) == me["team"])

    spray, pa_total, hits, game_ids = [], 0, 0, set()
    for g in [doc] + [g for g in games if g["meta"].get("event_id") != today_id]:
        is_today = g is doc
        date = g["meta"].get("date")
        for pa in g["parsed"].get("plate_appearances", []):
            if is_me(g, pa.get("batter_id"), pa.get("team_id")):
                pa_total += 1
                game_ids.add(g["meta"].get("event_id"))
                if pa.get("result") in ("Single", "Double", "Triple", "Home Run"):
                    hits += 1
        for pt in g["parsed"].get("spray", []):
            if is_me(g, pt.get("batter_id"), pt.get("team_id")):
                spray.append({
                    "x": pt["x"], "y": pt["y"], "result": pt.get("result"),
                    "hit": bool(pt.get("hit")), "play_type": pt.get("play_type"),
                    "today": is_today, "date": date,
                })
    me["today"] = [
        {"inning": pa["inning"], "result": pa["result"]}
        for pa in doc["parsed"].get("plate_appearances", [])
        if pa.get("batter_id") == pid
    ]
    me["history"] = {"games": len(game_ids), "pa": pa_total, "hits": hits, "in_play": len(spray)}
    me["spray"] = spray
    return me


def build_tablet_payload(data_dir, now: datetime) -> dict:
    armed = read_arm(data_dir, now)
    st = read_json(live_dir(data_dir) / "status.json", {}) or {}
    doc = read_json(live_dir(data_dir) / "state.json")
    fetched = _parse_iso((doc or {}).get("fetched_at")) if isinstance(doc, dict) else None
    age = int((now - fetched).total_seconds()) if fetched else None

    out = {
        "status": "idle", "armed": bool(armed),
        "armed_until": armed.get("expires_at") if armed else None,
        "updated_at": _iso(fetched) if fetched else None, "age_s": age,
        "error": st.get("error"), "field": FIELD,
        "game": None, "batter": None, "on_deck": None,
    }
    if armed:
        armed_at = _parse_iso(armed.get("armed_at"))
        if fetched is None or (armed_at and fetched < armed_at):
            out["status"] = "error" if st.get("error") else "starting"
        elif age <= STALE_AFTER_S:
            out["status"] = "live"
        else:
            out["status"] = "error" if st.get("error") else "stale"
    if not isinstance(doc, dict) or age is None or (not armed and age > SHOW_FINAL_FOR_S):
        return out
    if not isinstance(doc.get("parsed"), dict) or not isinstance(doc.get("meta"), dict):
        return out

    p, meta = doc["parsed"], doc["meta"]
    sharks_id = meta.get("sharks_team_id")
    opp_id = p.get("home_id") if p.get("away_id") == sharks_id else p.get("away_id")
    score = p.get("score") or {}
    out["game"] = {
        "opponent": meta.get("opponent_name") or "Opponent",
        "sharks_home": p.get("home_id") == sharks_id,
        "inning": p.get("inning"), "half": p.get("half"),
        "outs": p.get("outs"), "balls": p.get("balls"), "strikes": p.get("strikes"),
        "score": {"sharks": score.get(sharks_id, 0), "opponent": score.get(opp_id, 0)},
        "sharks_batting": p.get("batting_team") == sharks_id,
        "bases": {b: _player((p.get("bases") or {}).get(b), doc) for b in ("1", "2", "3")},
        "pitcher": _player(p.get("pitcher_id"), doc),
        "last_play": p.get("last_play") or "",
    }
    games = load_games(data_dir)
    out["batter"] = _batter_card(p.get("batter_id"), doc, games)
    out["on_deck"] = _batter_card(p.get("on_deck_id"), doc, games)
    return out
