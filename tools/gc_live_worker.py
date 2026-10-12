"""Live GameChanger poller for the dugout tablet. Runs as a thread in sharks_sync.

Idle until data/live_tablet/armed.json is present and unexpired, which is
written by POST /api/live/arm and expires after at most 4 h. While armed it:
  1. logs in through the autopull SessionManager (shared storage state and the
     same Gmail 2FA path), then opens the team schedule page;
  2. keeps the API headers the GC web app itself sent, in memory only, and
     replays them with context.request for read-only GETs;
  3. finds today's game, resolves its stream, and every POLL_S re-fetches the
     full event log and re-parses it (gc_live_stream) into state.json.

Fails closed: after MAX_FAILS consecutive non-200 responses it stops polling,
records the HTTP code in status.json and leaves the tablet showing "error".
Re-arming starts a fresh session. Captured headers are never logged,
serialised or written to disk.

GC scraping SOP exception (architecture/gc_scraping_sop.md): one GET every
15 s, only while armed, and only for the one game being played.
"""
from __future__ import annotations

import logging
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gc_live_stream  # noqa: E402
import live_tablet  # noqa: E402

GC_API = "https://api.team-manager.gc.com"
GC_WEB = "https://web.gc.com"
POLL_S = 15
PLAYERS_EVERY = 8          # refresh names (subs) every 8th poll, ~2 min
ARM_CHECK_S = 10
MAX_FAILS = 4
BACKFILL_GAP_S = 3         # SOP: 2-3 s between GC requests
BACKFILL_MAX_GAMES = 12    # per armed session; the rest wait for the next one
ET = ZoneInfo("America/New_York")
GAME_WINDOW_BEFORE = timedelta(hours=2)   # armed up to 2 h before first pitch
GAME_WINDOW_AFTER = timedelta(hours=4)
_DROP_HEADERS = {"cookie", "host", "content-length", "connection", "accept-encoding"}
_TEAM_RE = re.compile(r"/teams/([0-9a-f-]{36})/schedule")

log = logging.getLogger("gc_live")


class GCHttpError(RuntimeError):
    def __init__(self, status: int):
        super().__init__(f"gc_http_{status}")
        self.status = status


class GCClient:
    """Read-only GC API access that borrows the logged-in web app's headers."""

    def __init__(self, page):
        self.page = page
        self._requests: list = []
        self._headers: dict | None = None
        self.team_uuid: str | None = None

    def bootstrap(self, public_id: str, season_slug: str) -> None:
        self._capture(lambda: self.page.goto(f"{GC_WEB}/teams/{public_id}/{season_slug}/schedule",
                                             wait_until="domcontentloaded", timeout=60_000))

    def refresh(self) -> None:
        """Reload the page so the web app re-sends (and re-auths) its headers."""
        self._headers = None
        self._capture(lambda: self.page.reload(wait_until="domcontentloaded", timeout=60_000))

    def _capture(self, navigate) -> None:
        # Listen only while navigating, so the list can't grow over a 4 h game.
        on_request = self._requests.append
        self.page.on("request", on_request)
        try:
            navigate()
            self.page.wait_for_load_state("networkidle", timeout=30_000)
        finally:
            self.page.remove_listener("request", on_request)
        for req in self._requests:
            url = req.url
            if not url.startswith(GC_API):
                continue
            m = _TEAM_RE.search(url)
            if m and not self.team_uuid:
                self.team_uuid = m.group(1)
            if self._headers is None:
                try:
                    hdrs = req.all_headers()
                except Exception:
                    continue
                self._headers = {k: v for k, v in hdrs.items()
                                 if k.lower() not in _DROP_HEADERS and not k.startswith(":")}
        self._requests.clear()
        if self._headers is None or not self.team_uuid:
            raise RuntimeError("no_api_headers")

    def get(self, path: str):
        resp = self.page.context.request.get(GC_API + path, headers=self._headers, timeout=20_000)
        if resp.status != 200:
            raise GCHttpError(resp.status)
        return resp.json()


def pick_game(schedule: list, now: datetime) -> dict | None:
    """The game whose start is nearest to now within the playing window."""
    best, best_gap = None, None
    for item in schedule or []:
        ev = (item or {}).get("event") or {}
        if ev.get("event_type") != "game" or ev.get("status") == "canceled":
            continue
        start = live_tablet._parse_iso(((ev.get("start") or {}).get("datetime") or "").replace("Z", "+00:00"))
        if not start or not (start - GAME_WINDOW_BEFORE <= now <= start + GAME_WINDOW_AFTER):
            continue
        gap = abs((now - start).total_seconds())
        if best_gap is None or gap < best_gap:
            best, best_gap = item, gap
    return best


def players_from_plays(plays: dict) -> dict:
    out = {}
    for team_id, plist in ((plays or {}).get("team_players") or {}).items():
        for p in plist or []:
            if p.get("id"):
                name = f"{p.get('first_name') or ''} {p.get('last_name') or ''}".strip()
                out[p["id"]] = {"name": name, "number": str(p.get("number") or ""), "team_id": team_id}
    return out


def build_doc(meta: dict, players: dict, events: list, now: datetime) -> dict:
    parsed = gc_live_stream.parse_stream(events, meta.get("home_id"), meta.get("away_id"))
    return {"meta": meta, "players": players, "parsed": parsed, "fetched_at": live_tablet._iso(now)}


class LiveWorker:
    def __init__(self, data_dir, session_factory=None, clock=None, sleep=time.sleep):
        self.data_dir = Path(data_dir)
        self.session_factory = session_factory or _default_session
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep
        self._status: dict = {}
        self._done_for = None

    # status.json carries codes and counts only.
    def _set_status(self, **kw):
        self._status.update(kw)
        live_tablet.write_json_atomic(live_tablet.live_dir(self.data_dir) / "status.json", self._status)

    def armed(self) -> dict | None:
        return live_tablet.read_arm(self.data_dir, self.clock())

    def run_forever(self):
        while True:
            self.tick()
            self.sleep(ARM_CHECK_S)

    def tick(self):
        """Start at most one session per arm: a session that fails stays
        stopped until the coach re-arms, so a GC outage can't become a
        login loop."""
        arm = self.armed()
        if not arm or arm.get("armed_at") == self._done_for:
            return
        self._done_for = arm.get("armed_at")
        try:
            self.run_session()
        except Exception as e:  # never let the thread die
            log.warning("[Live] session ended: %s", type(e).__name__)
            self._set_status(phase="stopped", error=type(e).__name__)

    def run_session(self):
        """One armed period: login, find game, poll until disarmed or failed."""
        self._status = {}
        self._set_status(phase="login", error=None, last_http=None, events_seen=0)
        session = None
        try:
            session = self.session_factory()
            public_id, season_slug = session.team_ids()
            gc = GCClient(session.page())
            try:
                gc.bootstrap(public_id, season_slug)
            except RuntimeError as e:
                self._set_status(phase="stopped", error=str(e))
                return
            self._backfill(gc)
            self._poll_game(gc)
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    def _poll_game(self, gc: GCClient):
        fails, game, stream_id, meta, players, n = 0, None, None, None, {}, 0
        refreshed = False
        while self.armed():
            now = self.clock()
            try:
                if game is None:
                    self._set_status(phase="finding_game")
                    game = pick_game(gc.get(f"/teams/{gc.team_uuid}/schedule?fetch_place_details=true"), now)
                    self._set_status(last_http=200)
                    if game is None:
                        self._set_status(error="no_game_found")
                        self.sleep(120)
                        continue
                if stream_id is None:
                    event_id = game["event"]["id"]
                    stream_id = (gc.get(f"/events/{event_id}/best-game-stream-id") or {}).get("game_stream_id")
                    if not stream_id:
                        self._set_status(error="no_stream_yet")
                        self.sleep(60)
                        continue
                    pre = game.get("pregame_data") or {}
                    sharks_home = pre.get("home_away") == "home"
                    meta = {
                        "event_id": event_id, "date": now.astimezone(ET).date().isoformat(),
                        "opponent_name": pre.get("opponent_name") or "",
                        "sharks_team_id": gc.team_uuid,
                        "home_id": gc.team_uuid if sharks_home else pre.get("opponent_id"),
                        "away_id": pre.get("opponent_id") if sharks_home else gc.team_uuid,
                    }
                if n % PLAYERS_EVERY == 0:
                    players = players_from_plays(gc.get(f"/game-stream-processing/{stream_id}/plays")) or players
                events = gc.get(f"/game-streams/{stream_id}/events")
                doc = build_doc(meta, players, events, self.clock())
                ldir = live_tablet.live_dir(self.data_dir)
                live_tablet.write_json_atomic(ldir / "games" / f"{meta['event_id']}.json", doc)
                live_tablet.write_json_atomic(ldir / "state.json", doc)
                fails, n, refreshed = 0, n + 1, False
                self._set_status(phase="polling", error=None, last_http=200,
                                 last_poll_at=doc["fetched_at"], events_seen=len(events or []))
            except GCHttpError as e:
                fails += 1
                self._set_status(last_http=e.status, error=str(e))
                if e.status == 401 and not refreshed:
                    # GC's access token is short-lived: re-capture once, then fail closed.
                    refreshed = True
                    try:
                        gc.refresh()
                        continue
                    except Exception:
                        pass
                if fails >= MAX_FAILS or e.status in (401, 403, 429):
                    self._set_status(phase="stopped")
                    return
            except Exception as e:  # timeouts, bad JSON: count, don't crash
                fails += 1
                self._set_status(error=type(e).__name__)
                if fails >= MAX_FAILS:
                    self._set_status(phase="stopped")
                    return
            self.sleep(POLL_S)
        self._set_status(phase="disarmed")


    def _backfill(self, gc: GCClient):
        """Parse completed games not yet on disk, so opponents carry spray
        history. At SOP pace; a game GC won't serve is skipped, but auth or
        rate-limit refusals end the session like any other poll."""
        games_dir = live_tablet.live_dir(self.data_dir) / "games"
        self._set_status(phase="backfill")
        summaries = gc.get(f"/teams/{gc.team_uuid}/game-summaries")
        todo = [s for s in summaries or []
                if s.get("game_status") == "completed" and (s.get("game_stream") or {}).get("id")
                and s.get("event_id") and not (games_dir / f"{s['event_id']}.json").exists()]
        if not todo:
            return
        self.sleep(BACKFILL_GAP_S)
        schedule = {((i or {}).get("event") or {}).get("id"): i
                    for i in gc.get(f"/teams/{gc.team_uuid}/schedule?fetch_place_details=true") or []}
        for summ in todo[:BACKFILL_MAX_GAMES]:
            if not self.armed():
                return
            stream_id = summ["game_stream"]["id"]
            item = schedule.get(summ["event_id"]) or {}
            pre = item.get("pregame_data") or {}
            start = live_tablet._parse_iso(((item.get("event") or {}).get("start") or {})
                                           .get("datetime", "").replace("Z", "+00:00"))
            sharks_home = (summ.get("home_away") or pre.get("home_away")) == "home"
            opp = pre.get("opponent_id") or (summ.get("game_stream") or {}).get("opponent_id")
            meta = {
                "event_id": summ["event_id"],
                "date": start.astimezone(ET).date().isoformat() if start else None,
                "opponent_name": pre.get("opponent_name") or "",
                "sharks_team_id": gc.team_uuid,
                "home_id": gc.team_uuid if sharks_home else opp,
                "away_id": opp if sharks_home else gc.team_uuid,
            }
            try:
                self.sleep(BACKFILL_GAP_S)
                events = gc.get(f"/game-streams/{stream_id}/events")
                self.sleep(BACKFILL_GAP_S)
                players = players_from_plays(gc.get(f"/game-stream-processing/{stream_id}/plays"))
            except GCHttpError as e:
                if e.status in (401, 403, 429):
                    raise
                continue
            live_tablet.write_json_atomic(games_dir / f"{meta['event_id']}.json",
                                          build_doc(meta, players, events, self.clock()))


class _SessionAdapter:
    """Wraps autopull's SharedGCSession: one browser, one login, 2FA via Gmail."""

    def __init__(self):
        from tools.autopull import cli, config as config_mod
        import team_registry
        self._shared = cli.SharedGCSession(config_mod.load(require_gmail=False))
        self._ids = team_registry.current_gc_ids()

    def team_ids(self):
        return self._ids

    def page(self):
        return self._shared.page()[0]

    def close(self):
        self._shared.close()


def _default_session():
    return _SessionAdapter()


def start_thread(data_dir) -> threading.Thread:
    t = threading.Thread(target=LiveWorker(data_dir).run_forever, daemon=True, name="gc-live")
    t.start()
    return t
