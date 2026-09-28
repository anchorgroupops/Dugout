"""Render lifecycle contract between the announcer API and the PWA.

The Announcer tab polls /api/announcer/roster while any row says
"rendering" and stops when none does. These tests pin the rules that make
that safe: a row is marked in flight before a render request returns, a
batch marks every player up front, a dead render turns into a retryable
error, and a worker's FAILED report lands on the row it belongs to.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

import announcer_engine as ae
import sync_daemon as sd

ORIGIN = "https://test.example.com"
_REAL_RECONCILE = ae.reconcile_roster_with_team  # the roster fixture stubs it out


@pytest.fixture
def roster(tmp_path, monkeypatch):
    """Point the engine at a temp roster.json and return a writer/reader."""
    roster_file = tmp_path / "roster.json"
    monkeypatch.setattr(ae, "ROSTER_FILE", roster_file)
    monkeypatch.setattr(ae, "_ensure_dirs", lambda: None)
    monkeypatch.setattr(ae, "reconcile_roster_with_team", lambda r: (r, False))
    monkeypatch.setattr(ae, "_mark_stale_renders", lambda r: False)

    class R:
        @staticmethod
        def write(players):
            roster_file.write_text(json.dumps(players))

        @staticmethod
        def get(pid):
            return next(p for p in json.loads(roster_file.read_text()) if p["id"] == pid)

    return R


def _ago(seconds):
    return (datetime.now(ae.ET) - timedelta(seconds=seconds)).isoformat()


class TestExpireStuckRenders:
    def test_old_render_becomes_retryable_error(self, roster):
        roster.write([{"id": "a", "status": "rendering", "render_started_at": _ago(ae.RENDER_STALL_SECONDS + 5),
                       "render_job_id": "j1"}])
        p = ae.get_player_by_id("a")
        assert p["status"] == "error"
        assert p["error_message"] == ae.RENDER_STALLED_MESSAGE
        assert p["render_job_id"] == ""
        assert roster.get("a")["status"] == "error"  # persisted, not just read-time

    def test_fresh_render_stays_in_flight(self, roster):
        roster.write([{"id": "a", "status": "rendering", "render_started_at": _ago(5)}])
        assert ae.get_player_by_id("a")["status"] == "rendering"

    def test_render_without_start_time_is_stuck(self, roster):
        roster.write([{"id": "a", "status": "rendering"}])
        assert ae.get_player_by_id("a")["status"] == "error"


class TestClaimRenderBatch:
    def test_marks_pending_and_failed_players_in_one_go(self, roster):
        roster.write([
            {"id": "p", "status": "pending", "is_active": True},
            {"id": "e", "status": "error", "is_active": True, "error_message": "boom"},
            {"id": "r", "status": "ready", "is_active": True},
            {"id": "w", "status": "rendering", "is_active": True, "render_started_at": _ago(1),
             "render_job_id": "worker-job"},
            {"id": "x", "status": "pending", "is_active": False},
        ])
        ids = ae.claim_render_batch()
        assert ids == ["p", "e"]
        for pid in ids:
            p = roster.get(pid)
            assert p["status"] == "rendering" and p["error_message"] == "" and p["render_started_at"]
        assert roster.get("r")["status"] == "ready"
        assert roster.get("w")["render_job_id"] == "worker-job"  # left to its own job
        assert roster.get("x")["status"] == "pending"

    def test_render_all_pending_renders_the_claimed_batch(self, roster, monkeypatch):
        roster.write([{"id": "p", "status": "pending", "is_active": True},
                      {"id": "r", "status": "ready", "is_active": True}])
        seen = []
        monkeypatch.setattr(ae, "render_player_audio", lambda pid: seen.append(pid))
        assert ae.render_all_pending()["success"] == 1
        assert seen == ["p"]


class TestMarkJobFailed:
    def test_failure_of_the_awaited_job_marks_the_row(self, roster):
        roster.write([{"id": "a", "status": "rendering", "render_started_at": _ago(1), "render_job_id": "j1"}])
        ae.mark_job_failed({"id": "j1", "player_id": "a", "kind": "walkup"}, "qwen crashed")
        p = roster.get("a")
        assert p["status"] == "error" and p["error_message"] == "qwen crashed" and p["render_job_id"] == ""

    def test_failure_of_another_job_leaves_a_good_row_alone(self, roster):
        roster.write([{"id": "a", "status": "ready", "render_job_id": ""}])
        ae.mark_job_failed({"id": "draft-job", "player_id": "a"}, "legacy job without a script")
        assert roster.get("a")["status"] == "ready"

    def test_pa_jobs_are_ignored(self, roster):
        roster.write([{"id": "pa", "status": "ready", "render_job_id": "j1"}])
        ae.mark_job_failed({"id": "j1", "player_id": "pa", "kind": "pa"}, "x")
        assert roster.get("pa")["status"] == "ready"


class _Adb:
    """Minimal announcer_db stand-in recording what the routes enqueue."""

    def __init__(self, alive=False, heartbeat=None):
        self.alive, self.heartbeat, self.jobs = alive, heartbeat, {}

    def is_worker_alive(self, max_age_seconds=30):
        return self.alive

    def get_heartbeat_info(self):
        return self.heartbeat

    def enqueue_render(self, player_id, game_context, quality="best", **kw):
        job = {"id": f"job{len(self.jobs) + 1}", "player_id": player_id, "quality": quality,
               "kind": kw.get("kind", "walkup"), **kw}
        self.jobs[job["id"]] = job
        return job

    def update_job_status(self, job_id, status, error=None, draft_quality=False):
        self.jobs[job_id].update(status=status, error=error, draft_quality=draft_quality)

    def get_job(self, job_id):
        return self.jobs.get(job_id)


class _NoRunThread:
    """Stands in for threading.Thread so a route's background render never runs."""
    started = []

    def __init__(self, target=None, daemon=None):
        self.target = target

    def start(self):
        _NoRunThread.started.append(self.target)


@pytest.fixture
def client(roster, monkeypatch):
    import threading
    monkeypatch.setattr(sd, "WRITE_ORIGINS", [ORIGIN])
    monkeypatch.delenv("DUGOUT_WRITE_TOKEN", raising=False)
    monkeypatch.setattr(threading, "Thread", _NoRunThread)
    _NoRunThread.started = []
    sd.app.config["TESTING"] = True
    with sd.app.test_client() as c:
        yield c


def _post(client, path, body=None):
    return client.post(path, json=body or {}, headers={"Origin": ORIGIN})


class TestRenderRoute:
    def test_worker_render_marks_row_linked_to_its_job(self, client, roster, monkeypatch):
        roster.write([{"id": "07-jane", "first": "Jane", "last": "Doe", "number": "7", "status": "ready"}])
        adb = _Adb(alive=True)
        monkeypatch.setattr(sd, "_announcer_db", lambda: adb)
        resp = _post(client, "/api/announcer/render/07-jane", {"quality": "best"})
        assert resp.status_code == 202
        job_id = resp.get_json()["job_id"]
        p = roster.get("07-jane")
        assert p["status"] == "rendering" and p["render_job_id"] == job_id

    def test_pi_render_marks_row_before_the_thread_runs(self, client, roster, monkeypatch):
        roster.write([{"id": "07-jane", "first": "Jane", "last": "Doe", "number": "7", "status": "ready"}])
        monkeypatch.setattr(sd, "_announcer_db", lambda: _Adb(alive=False))
        resp = _post(client, "/api/announcer/render/07-jane", {"quality": "best"})
        assert resp.status_code == 202
        assert _NoRunThread.started, "background render was not scheduled"
        assert roster.get("07-jane")["status"] == "rendering"

    def test_draft_rerender_job_carries_a_script(self, client, roster, monkeypatch):
        roster.write([{"id": "07-jane", "first": "Jane", "last": "Doe", "number": "7", "status": "ready"}])
        adb = _Adb(alive=False, heartbeat={"worker_id": "mac"})
        monkeypatch.setattr(sd, "_announcer_db", lambda: adb)
        monkeypatch.setattr(ae, "render_player_audio", lambda *a, **k: None)
        _post(client, "/api/announcer/render/07-jane", {"quality": "best"})
        _NoRunThread.started[0]()  # run the background render inline
        (job,) = adb.jobs.values()
        assert job["text"] and "Jane" in job["text"]
        assert job["voice"] and job["instruct"]
        assert job["draft_quality"] is True


class TestRenderAllRoute:
    def test_marks_the_whole_batch_before_returning(self, client, roster):
        roster.write([{"id": "a", "status": "pending", "is_active": True},
                      {"id": "b", "status": "error", "is_active": True},
                      {"id": "c", "status": "ready", "is_active": True}])
        resp = _post(client, "/api/announcer/render-all")
        assert resp.status_code == 202
        assert resp.get_json()["count"] == 2
        assert [roster.get(x)["status"] for x in "abc"] == ["rendering", "rendering", "ready"]

    def test_nothing_to_render_starts_no_thread(self, client, roster):
        roster.write([{"id": "c", "status": "ready", "is_active": True}])
        assert _post(client, "/api/announcer/render-all").get_json()["count"] == 0
        assert _NoRunThread.started == []


class TestWorkerFailureReachesRow:
    def test_failed_patch_marks_the_awaiting_player(self, client, roster, monkeypatch):
        roster.write([{"id": "07-jane", "status": "rendering", "render_started_at": _ago(1),
                       "render_job_id": "job1"}])
        adb = _Adb()
        adb.jobs["job1"] = {"id": "job1", "player_id": "07-jane", "kind": "walkup"}
        monkeypatch.setattr(sd, "_announcer_db", lambda: adb)
        monkeypatch.setenv("DUGOUT_WRITE_TOKEN", "tok")
        resp = client.patch("/api/announcer/render-queue/job1", json={"status": "FAILED", "error": "OOM"},
                            headers={"X-Dugout-Token": "tok"})
        assert resp.status_code == 200
        p = roster.get("07-jane")
        assert p["status"] == "error" and p["error_message"] == "OOM"


class TestAddSubStartsRendering:
    def test_new_sub_is_in_flight_from_the_first_write(self, client, roster):
        roster.write([{"id": "07-jane", "status": "ready"}])
        resp = _post(client, "/api/announcer/add-sub", {"first": "Sam", "last": "Lee", "number": "3"})
        assert resp.status_code == 201
        assert roster.get("3-sam-lee")["status"] == "rendering"


class TestSubsAndRemoval:
    """A sub isn't on team.json; a rostered player is re-added on every load."""

    TEAM = [{"id": "07-jane", "first": "Jane", "last": "Doe", "number": "7", "status": "pending", "is_active": True}]

    def _team(self, monkeypatch):
        monkeypatch.setattr(ae, "_bootstrap_roster_from_team", lambda: [dict(p) for p in self.TEAM])

    def test_reconcile_leaves_a_sub_active(self, monkeypatch):
        self._team(monkeypatch)
        roster = [dict(self.TEAM[0]), {"id": "42-zoe", "is_active": True, "is_sub": True},
                  {"id": "99-gone", "is_active": True}]
        out, _ = _REAL_RECONCILE(roster)
        by_id = {p["id"]: p for p in out}
        assert by_id["42-zoe"]["is_active"] is True
        assert by_id["99-gone"]["is_active"] is False  # left the team: still deactivated

    def test_added_sub_stays_active_and_is_not_a_ghost(self, client, roster, monkeypatch):
        roster.write([dict(self.TEAM[0])])
        self._team(monkeypatch)
        monkeypatch.setattr(ae, "reconcile_roster_with_team", _REAL_RECONCILE)
        monkeypatch.setattr(sd, "_read_json_file", lambda path, default=None, **k: (
            {"roster": [{"first": "Jane", "last": "Doe"}]} if "team" in str(path) else default))
        monkeypatch.setattr(sd, "_write_json_file", lambda *a, **k: None)
        assert _post(client, "/api/announcer/add-sub", {"first": "Zoe", "last": "Test", "number": "42"}).status_code == 201
        zoe = next(p for p in client.get("/api/announcer/roster").get_json()["roster"] if p["id"] == "42-zoe-test")
        assert zoe["is_sub"] is True and zoe["is_active"] is True and zoe["is_ghost"] is False

    def test_removing_a_rostered_player_is_refused(self, client, roster, monkeypatch):
        roster.write([dict(self.TEAM[0], intros=[{"id": "i1", "clip_url": "/c/a.mp3"}])])
        self._team(monkeypatch)
        resp = client.delete("/api/announcer/player/07-jane", json={}, headers={"Origin": ORIGIN})
        assert resp.status_code == 409 and resp.get_json()["error"] == "player_on_team"
        assert roster.get("07-jane")["intros"]  # her calls survive

    def test_removing_a_sub_works(self, client, roster, monkeypatch):
        roster.write([dict(self.TEAM[0]), {"id": "42-zoe", "is_sub": True, "is_active": True}])
        self._team(monkeypatch)
        resp = client.delete("/api/announcer/player/42-zoe", json={}, headers={"Origin": ORIGIN})
        assert resp.status_code == 200
        assert [p["id"] for p in json.loads(ae.ROSTER_FILE.read_text())] == ["07-jane"]
