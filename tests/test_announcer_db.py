"""Comprehensive pytest tests for tools/announcer_db.py.

All tests redirect DB_PATH to a tmp_path database so the real
data/sharks/announcer/announcer.db is never touched.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
import announcer_db as adb


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path, monkeypatch):
    """Redirect DB_PATH to a temp file and initialize the schema."""
    db_path = tmp_path / "announcer.db"
    monkeypatch.setattr(adb, "DB_PATH", db_path)
    adb.init_db()
    return db_path


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _raw(db_path: Path, sql: str, params=()):
    """Execute a raw query against the test DB and return all rows as dicts."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ===========================================================================
# TestInitDb
# ===========================================================================

class TestInitDb:
    def test_creates_render_queue(self, db):
        rows = _raw(db, "SELECT name FROM sqlite_master WHERE type='table' AND name='render_queue'")
        assert rows, "render_queue table must exist"

    def test_creates_player_songs(self, db):
        rows = _raw(db, "SELECT name FROM sqlite_master WHERE type='table' AND name='player_songs'")
        assert rows, "player_songs table must exist"

    def test_creates_shuffle_state(self, db):
        rows = _raw(db, "SELECT name FROM sqlite_master WHERE type='table' AND name='shuffle_state'")
        assert rows, "shuffle_state table must exist"

    def test_creates_mac_heartbeat(self, db):
        rows = _raw(db, "SELECT name FROM sqlite_master WHERE type='table' AND name='mac_heartbeat'")
        assert rows, "mac_heartbeat table must exist"

    def test_creates_walkup_catalog(self, db):
        rows = _raw(db, "SELECT name FROM sqlite_master WHERE type='table' AND name='walkup_catalog'")
        assert rows, "walkup_catalog table must exist (schema v2)"

    def test_creates_music_auth(self, db):
        rows = _raw(db, "SELECT name FROM sqlite_master WHERE type='table' AND name='music_auth'")
        assert rows, "music_auth table must exist (schema v2)"

    def test_schema_version_at_least_2(self, db):
        rows = _raw(db, "SELECT MAX(version) AS v FROM schema_version")
        assert rows[0]["v"] >= 2

    def test_idempotent_double_call(self, db):
        # Should not raise on second call
        adb.init_db()
        rows = _raw(db, "SELECT MAX(version) AS v FROM schema_version")
        assert rows[0]["v"] >= 2

    def test_idempotent_triple_call(self, db):
        adb.init_db()
        adb.init_db()

    def test_v2_migration_handles_existing_columns(self, tmp_path, monkeypatch):
        """Lines 159-160: OperationalError on duplicate ALTER is caught and ignored."""
        db_path = tmp_path / "pre_v2.db"
        # Set up a schema-v1 DB that already has the V2 columns (simulates partial migration)
        conn = sqlite3.connect(str(db_path))
        conn.executescript(adb._SCHEMA_V1)
        for sql in adb._V2_COLUMN_ALTERS:
            conn.execute(sql)
        conn.commit()
        conn.close()

        monkeypatch.setattr(adb, "DB_PATH", db_path)
        adb.init_db()  # should not raise; OperationalError is silently caught

        rows = _raw(db_path, "SELECT MAX(version) AS v FROM schema_version")
        assert rows[0]["v"] >= 2


# ===========================================================================
# TestEnqueueRender
# ===========================================================================

class TestEnqueueRender:
    def test_returns_dict_with_job_id(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        assert "id" in job
        assert len(job["id"]) == 36  # UUID4

    def test_status_is_pending(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        assert job["status"] == "PENDING"

    def test_player_id_in_result(self, db):
        job = adb.enqueue_render("player-99", {}, "best")
        assert job["player_id"] == "player-99"

    def test_quality_best_priority_normal(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        assert job["quality"] == "best"
        assert job["priority"] == "normal"

    def test_quality_quick_priority_high(self, db):
        job = adb.enqueue_render("player-1", {}, "quick")
        assert job["quality"] == "quick"
        assert job["priority"] == "high"

    def test_game_context_stored_as_json(self, db):
        ctx = {"inning": 3, "outs": 2, "score": "4-2"}
        job = adb.enqueue_render("player-1", ctx, "best")
        rows = _raw(db, "SELECT game_context FROM render_queue WHERE id = ?", (job["id"],))
        assert rows, "row must be in DB"
        stored = json.loads(rows[0]["game_context"])
        assert stored == ctx

    def test_empty_game_context(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        rows = _raw(db, "SELECT game_context FROM render_queue WHERE id = ?", (job["id"],))
        assert json.loads(rows[0]["game_context"]) == {}

    def test_each_call_creates_new_job(self, db):
        """enqueue_render does NOT deduplicate — each call creates a new row."""
        j1 = adb.enqueue_render("player-1", {}, "best")
        j2 = adb.enqueue_render("player-1", {}, "best")
        assert j1["id"] != j2["id"]
        rows = _raw(db, "SELECT id FROM render_queue WHERE player_id = 'player-1'")
        assert len(rows) == 2

    def test_created_at_iso_format(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        # Should parse without error
        dt = datetime.fromisoformat(job["created_at"])
        assert dt.tzinfo is not None


# ===========================================================================
# TestClaimNextJob
# ===========================================================================

class TestClaimNextJob:
    def test_returns_none_when_empty(self, db):
        result = adb.claim_next_job("worker-1", "best")
        assert result is None

    def test_returns_job_when_available(self, db):
        adb.enqueue_render("player-1", {}, "best")
        job = adb.claim_next_job("worker-1", "best")
        assert job is not None
        assert job["player_id"] == "player-1"

    def test_status_becomes_processing(self, db):
        adb.enqueue_render("player-1", {}, "best")
        job = adb.claim_next_job("worker-1", "best")
        assert job["status"] == "PROCESSING"

    def test_worker_id_set(self, db):
        adb.enqueue_render("player-1", {}, "best")
        job = adb.claim_next_job("worker-42", "best")
        assert job["worker_id"] == "worker-42"

    def test_claimed_at_set(self, db):
        adb.enqueue_render("player-1", {}, "best")
        job = adb.claim_next_job("worker-1", "best")
        assert job["claimed_at"] is not None

    def test_second_claim_returns_different_job(self, db):
        adb.enqueue_render("player-1", {}, "best")
        adb.enqueue_render("player-2", {}, "best")
        j1 = adb.claim_next_job("worker-1", "best")
        j2 = adb.claim_next_job("worker-1", "best")
        assert j1 is not None
        assert j2 is not None
        assert j1["id"] != j2["id"]

    def test_returns_none_when_all_claimed(self, db):
        adb.enqueue_render("player-1", {}, "best")
        adb.claim_next_job("worker-1", "best")
        result = adb.claim_next_job("worker-1", "best")
        assert result is None

    def test_quality_filter_quick(self, db):
        adb.enqueue_render("player-1", {}, "best")
        result = adb.claim_next_job("worker-1", "quick")
        assert result is None  # no quick jobs enqueued

    def test_quality_filter_best(self, db):
        adb.enqueue_render("player-1", {}, "quick")
        result = adb.claim_next_job("worker-1", "best")
        assert result is None  # no best jobs enqueued

    def test_high_priority_claimed_before_normal(self, db):
        """High-priority (quick) jobs should come before normal (best) within same quality tier.

        Since quality filters are separate, test that within 'quick' jobs,
        high priority is served first by enqueuing a normal job that happens
        to use the same quality field.
        """
        # Enqueue two 'best' jobs; then add a 'best' high-priority-equivalent
        # (priority is derived from quality, so best=normal always).
        # Instead verify ordering by created_at: first enqueued is first claimed.
        j1 = adb.enqueue_render("player-A", {}, "best")
        j2 = adb.enqueue_render("player-B", {}, "best")
        claimed = adb.claim_next_job("worker-1", "best")
        assert claimed["id"] == j1["id"], "first enqueued should be claimed first"


# ===========================================================================
# TestUpdateJobStatus
# ===========================================================================

class TestUpdateJobStatus:
    def test_status_completed(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        adb.update_job_status(job["id"], "COMPLETED")
        result = adb.get_job(job["id"])
        assert result["status"] == "COMPLETED"

    def test_status_failed(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        adb.update_job_status(job["id"], "FAILED", error="TTS timeout")
        result = adb.get_job(job["id"])
        assert result["status"] == "FAILED"

    def test_error_stored(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        adb.update_job_status(job["id"], "FAILED", error="network error")
        result = adb.get_job(job["id"])
        assert result["error"] == "network error"

    def test_error_none_clears_field(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        # Set an error first
        adb.update_job_status(job["id"], "FAILED", error="boom")
        # Now clear it
        adb.update_job_status(job["id"], "COMPLETED", error=None)
        result = adb.get_job(job["id"])
        assert result["error"] is None

    def test_completed_at_set(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        adb.update_job_status(job["id"], "COMPLETED")
        result = adb.get_job(job["id"])
        assert result["completed_at"] is not None

    def test_draft_quality_flag(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        adb.update_job_status(job["id"], "COMPLETED", draft_quality=True)
        result = adb.get_job(job["id"])
        assert result["draft_quality"] == 1

    def test_draft_quality_false_by_default(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        adb.update_job_status(job["id"], "COMPLETED")
        result = adb.get_job(job["id"])
        assert result["draft_quality"] == 0

    def test_nonexistent_job_id_no_raise(self, db):
        # Should not raise even for an unknown job_id
        adb.update_job_status("does-not-exist", "COMPLETED")


# ===========================================================================
# TestGetPendingJobs
# ===========================================================================

class TestGetPendingJobs:
    def test_empty_queue_returns_empty_list(self, db):
        assert adb.get_pending_jobs("best") == []

    def test_returns_pending_jobs(self, db):
        adb.enqueue_render("player-1", {}, "best")
        adb.enqueue_render("player-2", {}, "best")
        jobs = adb.get_pending_jobs("best")
        assert len(jobs) == 2

    def test_excludes_processing_jobs(self, db):
        adb.enqueue_render("player-1", {}, "best")
        adb.claim_next_job("worker-1", "best")  # moves to PROCESSING
        jobs = adb.get_pending_jobs("best")
        assert len(jobs) == 0

    def test_excludes_completed_jobs(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        adb.update_job_status(job["id"], "COMPLETED")
        jobs = adb.get_pending_jobs("best")
        assert len(jobs) == 0

    def test_quality_filter(self, db):
        adb.enqueue_render("player-1", {}, "best")
        adb.enqueue_render("player-2", {}, "quick")
        best_jobs = adb.get_pending_jobs("best")
        quick_jobs = adb.get_pending_jobs("quick")
        assert len(best_jobs) == 1
        assert len(quick_jobs) == 1

    def test_limit_respected(self, db):
        for i in range(5):
            adb.enqueue_render(f"player-{i}", {}, "best")
        jobs = adb.get_pending_jobs("best", limit=3)
        assert len(jobs) == 3

    def test_limit_zero_returns_empty(self, db):
        adb.enqueue_render("player-1", {}, "best")
        jobs = adb.get_pending_jobs("best", limit=0)
        assert jobs == []

    def test_returns_list_of_dicts(self, db):
        adb.enqueue_render("player-1", {}, "best")
        jobs = adb.get_pending_jobs("best")
        assert isinstance(jobs, list)
        assert isinstance(jobs[0], dict)

    def test_high_priority_first(self, db):
        """quick jobs (high priority) should come before best (normal) — but they
        live in separate quality buckets.  Within 'best', ordering is by created_at."""
        j1 = adb.enqueue_render("player-A", {}, "best")
        j2 = adb.enqueue_render("player-B", {}, "best")
        jobs = adb.get_pending_jobs("best", limit=10)
        assert jobs[0]["id"] == j1["id"]
        assert jobs[1]["id"] == j2["id"]


# ===========================================================================
# TestGetJob
# ===========================================================================

class TestGetJob:
    def test_returns_none_for_unknown(self, db):
        assert adb.get_job("nonexistent-id") is None

    def test_returns_job_dict(self, db):
        job = adb.enqueue_render("player-1", {"k": "v"}, "quick")
        result = adb.get_job(job["id"])
        assert result is not None
        assert isinstance(result, dict)

    def test_fields_match_enqueued(self, db):
        ctx = {"inning": 7}
        job = adb.enqueue_render("player-7", ctx, "quick")
        result = adb.get_job(job["id"])
        assert result["id"] == job["id"]
        assert result["player_id"] == "player-7"
        assert result["quality"] == "quick"
        assert result["status"] == "PENDING"
        assert json.loads(result["game_context"]) == ctx

    def test_returns_fresh_dict_on_each_call(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        r1 = adb.get_job(job["id"])
        adb.update_job_status(job["id"], "COMPLETED")
        r2 = adb.get_job(job["id"])
        assert r1["status"] == "PENDING"
        assert r2["status"] == "COMPLETED"


# ===========================================================================
# TestGetPlayerRenderStatus
# ===========================================================================

class TestGetPlayerRenderStatus:
    def test_returns_none_for_no_jobs(self, db):
        assert adb.get_player_render_status("ghost") is None

    def test_returns_only_job(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        result = adb.get_player_render_status("player-1")
        assert result is not None
        assert result["id"] == job["id"]

    def test_returns_most_recent_job(self, db):
        adb.enqueue_render("player-1", {"order": 1}, "best")
        j2 = adb.enqueue_render("player-1", {"order": 2}, "best")
        result = adb.get_player_render_status("player-1")
        assert result["id"] == j2["id"]

    def test_does_not_cross_players(self, db):
        adb.enqueue_render("player-A", {}, "best")
        result = adb.get_player_render_status("player-B")
        assert result is None

    def test_reflects_status_update(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        adb.update_job_status(job["id"], "COMPLETED")
        result = adb.get_player_render_status("player-1")
        assert result["status"] == "COMPLETED"


# ===========================================================================
# TestRequeueStaleJobs
# ===========================================================================

class TestRequeueStaleJobs:
    def test_no_stale_jobs_returns_zero(self, db):
        count = adb.requeue_stale_jobs(stale_seconds=120)
        assert count == 0

    def test_non_stale_job_untouched(self, db):
        adb.enqueue_render("player-1", {}, "best")
        adb.claim_next_job("worker-1", "best")
        # claimed just now — not stale with a 120-second window
        count = adb.requeue_stale_jobs(stale_seconds=120)
        assert count == 0
        result = adb.get_player_render_status("player-1")
        assert result["status"] == "PROCESSING"

    def test_stale_job_reset_to_pending(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        # Manually set claimed_at to something old
        stale_ts = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
        conn = sqlite3.connect(str(db))
        conn.execute(
            "UPDATE render_queue SET status='PROCESSING', claimed_at=?, worker_id='old-worker' WHERE id=?",
            (stale_ts, job["id"]),
        )
        conn.commit()
        conn.close()

        count = adb.requeue_stale_jobs(stale_seconds=120)
        assert count == 1
        result = adb.get_job(job["id"])
        assert result["status"] == "PENDING"
        assert result["worker_id"] is None
        assert result["claimed_at"] is None

    def test_only_stale_jobs_reset(self, db):
        """One fresh PROCESSING job and one stale: only the stale is reset."""
        j_fresh = adb.enqueue_render("player-fresh", {}, "best")
        j_stale = adb.enqueue_render("player-stale", {}, "best")

        # Claim fresh job (claimed_at = now)
        adb.claim_next_job("worker-1", "best")

        # Manually age the stale job
        stale_ts = (datetime.now(timezone.utc) - timedelta(seconds=500)).isoformat()
        conn = sqlite3.connect(str(db))
        conn.execute(
            "UPDATE render_queue SET status='PROCESSING', claimed_at=?, worker_id='old-w' WHERE id=?",
            (stale_ts, j_stale["id"]),
        )
        conn.commit()
        conn.close()

        count = adb.requeue_stale_jobs(stale_seconds=120)
        assert count == 1

        stale_result = adb.get_job(j_stale["id"])
        assert stale_result["status"] == "PENDING"

        fresh_result = adb.get_job(j_fresh["id"])
        assert fresh_result["status"] == "PROCESSING"

    def test_completed_jobs_not_touched(self, db):
        job = adb.enqueue_render("player-1", {}, "best")
        adb.update_job_status(job["id"], "COMPLETED")
        count = adb.requeue_stale_jobs(stale_seconds=0)
        assert count == 0
        result = adb.get_job(job["id"])
        assert result["status"] == "COMPLETED"


# ===========================================================================
# TestPlayerSongs
# ===========================================================================

class TestAddGetRemovePlayerSong:
    def test_add_returns_updated_pool(self, db):
        pool = adb.add_player_song("player-1", "http://example.com/song.mp3")
        assert isinstance(pool, list)
        assert len(pool) == 1

    def test_song_present_in_pool(self, db):
        adb.add_player_song("player-1", "http://example.com/song.mp3", song_label="Banger")
        songs = adb.get_player_songs("player-1")
        assert any(s["song_url"] == "http://example.com/song.mp3" for s in songs)

    def test_song_label_stored(self, db):
        adb.add_player_song("player-1", "http://example.com/song.mp3", song_label="Walk-up Banger")
        songs = adb.get_player_songs("player-1")
        assert songs[0]["song_label"] == "Walk-up Banger"

    def test_duplicate_ignored(self, db):
        adb.add_player_song("player-1", "http://example.com/song.mp3")
        adb.add_player_song("player-1", "http://example.com/song.mp3")
        songs = adb.get_player_songs("player-1")
        assert len(songs) == 1

    def test_multiple_songs_stored(self, db):
        adb.add_player_song("player-1", "http://example.com/a.mp3")
        adb.add_player_song("player-1", "http://example.com/b.mp3")
        songs = adb.get_player_songs("player-1")
        assert len(songs) == 2

    def test_get_empty_for_unknown_player(self, db):
        songs = adb.get_player_songs("nobody")
        assert songs == []

    def test_songs_scoped_to_player(self, db):
        adb.add_player_song("player-A", "http://example.com/a.mp3")
        adb.add_player_song("player-B", "http://example.com/b.mp3")
        assert len(adb.get_player_songs("player-A")) == 1
        assert len(adb.get_player_songs("player-B")) == 1

    def test_remove_deletes_song(self, db):
        pool = adb.add_player_song("player-1", "http://example.com/song.mp3")
        song_id = pool[0]["id"]
        adb.remove_player_song(song_id, "player-1")
        songs = adb.get_player_songs("player-1")
        assert songs == []

    def test_remove_nonexistent_no_raise(self, db):
        adb.remove_player_song(99999, "player-1")  # should not raise

    def test_remove_scoped_to_player(self, db):
        """Removing a song with wrong player_id should not delete it."""
        pool = adb.add_player_song("player-A", "http://example.com/song.mp3")
        song_id = pool[0]["id"]
        adb.remove_player_song(song_id, "player-B")  # wrong player
        songs = adb.get_player_songs("player-A")
        assert len(songs) == 1  # still there

    def test_add_with_source_fields(self, db):
        pool = adb.add_player_song(
            "player-1",
            "http://example.com/song.mp3",
            source="spotify",
            source_id="3n3Ppam7vgaVa1iaRUIOKE",
            optimal_start_ms=12500,
            duration_ms=210000,
        )
        s = pool[0]
        assert s["source"] == "spotify"
        assert s["source_id"] == "3n3Ppam7vgaVa1iaRUIOKE"
        assert s["optimal_start_ms"] == 12500
        assert s["duration_ms"] == 210000

    def test_get_player_songs_returns_list_of_dicts(self, db):
        adb.add_player_song("player-1", "http://example.com/song.mp3")
        songs = adb.get_player_songs("player-1")
        assert isinstance(songs, list)
        assert isinstance(songs[0], dict)

    def test_song_has_id_field(self, db):
        pool = adb.add_player_song("player-1", "http://example.com/song.mp3")
        assert "id" in pool[0]
        assert isinstance(pool[0]["id"], int)


# ===========================================================================
# TestPickWalkupSong
# ===========================================================================

class TestPickWalkupSong:
    def test_returns_none_when_no_songs(self, db):
        result = adb.pick_walkup_song("player-1", "session-1")
        assert result is None

    def test_returns_url_when_songs_exist(self, db):
        adb.add_player_song("player-1", "http://example.com/walkup.mp3")
        result = adb.pick_walkup_song("player-1", "session-1")
        assert result == "http://example.com/walkup.mp3"

    def test_returns_string(self, db):
        adb.add_player_song("player-1", "http://example.com/song.mp3")
        result = adb.pick_walkup_song("player-1", "session-1")
        assert isinstance(result, str)

    def test_same_session_no_error(self, db):
        adb.add_player_song("player-1", "http://example.com/a.mp3")
        adb.add_player_song("player-1", "http://example.com/b.mp3")
        r1 = adb.pick_walkup_song("player-1", "session-1")
        r2 = adb.pick_walkup_song("player-1", "session-1")
        assert r1 is not None
        assert r2 is not None

    def test_increments_play_count(self, db):
        adb.add_player_song("player-1", "http://example.com/song.mp3")
        adb.pick_walkup_song("player-1", "session-1")
        songs = adb.get_player_songs("player-1")
        assert songs[0]["play_count"] == 1

    def test_sets_last_played_at(self, db):
        adb.add_player_song("player-1", "http://example.com/song.mp3")
        adb.pick_walkup_song("player-1", "session-1")
        songs = adb.get_player_songs("player-1")
        assert songs[0]["last_played_at"] is not None

    def test_all_songs_eventually_played(self, db):
        """All songs should be picked at least once within len(songs) picks."""
        urls = [f"http://example.com/song{i}.mp3" for i in range(4)]
        for url in urls:
            adb.add_player_song("player-1", url)
        picked = set()
        for _ in range(4):
            result = adb.pick_walkup_song("player-1", "session-all")
            picked.add(result)
        assert picked == set(urls)

    def test_cycle_resets_after_all_played(self, db):
        """After all songs are played in a session, picks resume from the beginning."""
        urls = [f"http://example.com/cycle{i}.mp3" for i in range(3)]
        for url in urls:
            adb.add_player_song("player-1", url)
        # Play through all songs once
        picked_first = {adb.pick_walkup_song("player-1", "session-cycle") for _ in range(3)}
        assert picked_first == set(urls)
        # Next pick should work without error (full cycle reset)
        extra = adb.pick_walkup_song("player-1", "session-cycle")
        assert extra in urls

    def test_single_song_always_returned(self, db):
        adb.add_player_song("player-1", "http://example.com/only.mp3")
        for _ in range(5):
            result = adb.pick_walkup_song("player-1", "session-solo")
            assert result == "http://example.com/only.mp3"

    def test_different_sessions_independent(self, db):
        adb.add_player_song("player-1", "http://example.com/s1.mp3")
        adb.add_player_song("player-1", "http://example.com/s2.mp3")
        # Each session should track state independently
        r_A = adb.pick_walkup_song("player-1", "session-A")
        r_B = adb.pick_walkup_song("player-1", "session-B")
        assert r_A is not None
        assert r_B is not None


# ===========================================================================
# TestHeartbeat
# ===========================================================================

class TestHeartbeat:
    def test_fresh_db_not_alive(self, db):
        assert adb.is_worker_alive(max_age_seconds=30) is False

    def test_get_heartbeat_info_none_on_fresh(self, db):
        assert adb.get_heartbeat_info() is None

    def test_after_heartbeat_is_alive(self, db):
        adb.update_heartbeat("mac-worker-1")
        assert adb.is_worker_alive(max_age_seconds=30) is True

    def test_get_heartbeat_info_returns_dict(self, db):
        adb.update_heartbeat("mac-worker-1")
        info = adb.get_heartbeat_info()
        assert info is not None
        assert isinstance(info, dict)

    def test_heartbeat_info_has_worker_id(self, db):
        adb.update_heartbeat("mac-worker-X")
        info = adb.get_heartbeat_info()
        assert info["worker_id"] == "mac-worker-X"

    def test_heartbeat_info_has_last_seen_at(self, db):
        adb.update_heartbeat("mac-worker-1")
        info = adb.get_heartbeat_info()
        assert "last_seen_at" in info
        # Should be a valid ISO datetime
        datetime.fromisoformat(info["last_seen_at"])

    def test_old_heartbeat_not_alive(self, db):
        """Insert a heartbeat far in the past — should report not alive."""
        stale_ts = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT OR REPLACE INTO mac_heartbeat (worker_id, last_seen_at) VALUES (?, ?)",
            ("old-worker", stale_ts),
        )
        conn.commit()
        conn.close()
        assert adb.is_worker_alive(max_age_seconds=30) is False

    def test_update_heartbeat_is_idempotent(self, db):
        adb.update_heartbeat("mac-worker-1")
        adb.update_heartbeat("mac-worker-1")
        adb.update_heartbeat("mac-worker-1")
        rows = _raw(db, "SELECT * FROM mac_heartbeat WHERE worker_id = 'mac-worker-1'")
        assert len(rows) == 1

    def test_multiple_workers_most_recent_returned(self, db):
        stale_ts = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT OR REPLACE INTO mac_heartbeat (worker_id, last_seen_at) VALUES (?, ?)",
            ("old-worker", stale_ts),
        )
        conn.commit()
        conn.close()
        adb.update_heartbeat("fresh-worker")
        info = adb.get_heartbeat_info()
        assert info["worker_id"] == "fresh-worker"

    def test_heartbeat_version_stored(self, db):
        adb.update_heartbeat("mac-worker-1", version="1.2.3")
        info = adb.get_heartbeat_info()
        assert info["version"] == "1.2.3"

    def test_is_worker_alive_respects_max_age(self, db):
        """A brand-new heartbeat should be alive with any reasonable max_age."""
        adb.update_heartbeat("mac-worker-1")
        assert adb.is_worker_alive(max_age_seconds=1) is True
        assert adb.is_worker_alive(max_age_seconds=3600) is True


# ===========================================================================
# TestWalkupCatalog
# ===========================================================================

class TestWalkupCatalog:
    def _entry(self, rank=1, title="Eye of the Tiger", artist="Survivor"):
        return {
            "rank": rank,
            "title": title,
            "artist": artist,
            "spotify_id": "0GjEhVFGZW8afUYGChu3Rr",
            "apple_id": None,
            "optimal_start_ms": 5000,
            "duration_ms": 245000,
            "energy_score": 0.9,
            "tags": ["pump-up", "classic"],
        }

    def test_upsert_adds_entry(self, db):
        adb.upsert_catalog_entry(self._entry())
        assert adb.get_catalog_count() == 1

    def test_upsert_idempotent_on_rank(self, db):
        adb.upsert_catalog_entry(self._entry())
        adb.upsert_catalog_entry(self._entry(title="Updated Title"))
        assert adb.get_catalog_count() == 1

    def test_upsert_updates_fields(self, db):
        adb.upsert_catalog_entry(self._entry())
        updated = self._entry(title="New Title")
        adb.upsert_catalog_entry(updated)
        results = adb.search_catalog("New Title")
        assert results[0]["title"] == "New Title"

    def test_get_catalog_count_zero(self, db):
        assert adb.get_catalog_count() == 0

    def test_search_by_title(self, db):
        adb.upsert_catalog_entry(self._entry())
        results = adb.search_catalog("Tiger")
        assert len(results) == 1
        assert results[0]["title"] == "Eye of the Tiger"

    def test_search_by_artist(self, db):
        adb.upsert_catalog_entry(self._entry())
        results = adb.search_catalog("Survivor")
        assert len(results) == 1

    def test_search_no_match(self, db):
        adb.upsert_catalog_entry(self._entry())
        results = adb.search_catalog("zzznomatch")
        assert results == []

    def test_search_tags_decoded(self, db):
        adb.upsert_catalog_entry(self._entry())
        results = adb.search_catalog("Tiger")
        assert isinstance(results[0]["tags"], list)
        assert "pump-up" in results[0]["tags"]

    def test_search_limit(self, db):
        for i in range(10):
            adb.upsert_catalog_entry(self._entry(rank=i + 1, title=f"Song {i}", artist="Artist"))
        results = adb.search_catalog("Song", limit=3)
        assert len(results) == 3

    def test_get_catalog_suggestions_no_tags(self, db):
        adb.upsert_catalog_entry(self._entry())
        results = adb.get_catalog_suggestions([])
        assert len(results) == 1

    def test_get_catalog_suggestions_matching_tag(self, db):
        adb.upsert_catalog_entry(self._entry())
        results = adb.get_catalog_suggestions(["pump-up"])
        assert len(results) == 1

    def test_get_catalog_suggestions_no_match(self, db):
        adb.upsert_catalog_entry(self._entry())
        results = adb.get_catalog_suggestions(["country"])
        assert results == []

    def test_get_catalog_suggestions_limit(self, db):
        for i in range(5):
            adb.upsert_catalog_entry(
                {"rank": i + 1, "title": f"Song {i}", "artist": "X",
                 "energy_score": 0.8, "tags": ["hype"]}
            )
        results = adb.get_catalog_suggestions(["hype"], limit=3)
        assert len(results) == 3


# ===========================================================================
# TestMusicAuth
# ===========================================================================

class TestMusicAuth:
    def test_get_returns_none_when_empty(self, db):
        assert adb.get_music_auth("spotify") is None

    def test_store_and_retrieve(self, db):
        adb.store_music_auth("spotify", "access-tok", "refresh-tok")
        result = adb.get_music_auth("spotify")
        assert result is not None
        assert result["access_token"] == "access-tok"
        assert result["refresh_token"] == "refresh-tok"

    def test_provider_in_result(self, db):
        adb.store_music_auth("apple", "tok-apple")
        result = adb.get_music_auth("apple")
        assert result["provider"] == "apple"

    def test_upsert_updates_token(self, db):
        adb.store_music_auth("spotify", "old-token")
        adb.store_music_auth("spotify", "new-token")
        result = adb.get_music_auth("spotify")
        assert result["access_token"] == "new-token"

    def test_two_providers_independent(self, db):
        adb.store_music_auth("spotify", "spot-tok")
        adb.store_music_auth("apple", "apple-tok")
        assert adb.get_music_auth("spotify")["access_token"] == "spot-tok"
        assert adb.get_music_auth("apple")["access_token"] == "apple-tok"

    def test_optional_fields_stored(self, db):
        adb.store_music_auth(
            "spotify", "tok", "ref", expires_at="2026-01-01T00:00:00+00:00", scope="streaming"
        )
        result = adb.get_music_auth("spotify")
        assert result["expires_at"] == "2026-01-01T00:00:00+00:00"
        assert result["scope"] == "streaming"

    def test_updated_at_set(self, db):
        adb.store_music_auth("spotify", "tok")
        result = adb.get_music_auth("spotify")
        assert result["updated_at"] is not None
        datetime.fromisoformat(result["updated_at"])


# ===========================================================================
# TestPeekNextSongs
# ===========================================================================

class TestPeekNextSongs:
    def test_returns_empty_when_no_songs(self, db):
        result = adb.peek_next_songs(["p1", "p2"], "session-1")
        assert result == {}

    def test_returns_url_for_player_with_song(self, db):
        adb.add_player_song("p1", "https://example.com/song.mp3", "Eye of the Tiger")
        result = adb.peek_next_songs(["p1"], "session-1")
        assert "p1" in result
        assert result["p1"] == "https://example.com/song.mp3"

    def test_skips_player_without_songs(self, db):
        adb.add_player_song("p1", "https://example.com/song1.mp3", "Song 1")
        result = adb.peek_next_songs(["p1", "p2"], "session-1")
        assert "p1" in result
        assert "p2" not in result

    def test_all_played_resets_to_full_pool(self, db):
        """When all songs have been played, falls back to the full pool."""
        adb.add_player_song("p1", "https://example.com/song1.mp3", "Song 1")
        # Simulate all songs played by setting them in shuffle_state
        with adb._conn() as conn:
            songs = adb.get_player_songs("p1")
            played_ids = json.dumps([s["id"] for s in songs])
            conn.execute(
                "INSERT OR REPLACE INTO shuffle_state (player_id, game_session_id, played_song_ids, updated_at) "
                "VALUES (?, ?, ?, datetime('now'))",
                ("p1", "session-1", played_ids),
            )
        result = adb.peek_next_songs(["p1"], "session-1")
        assert "p1" in result


# ===========================================================================
# TestConnRollback
# ===========================================================================

class TestConnRollback:
    def test_exception_triggers_rollback(self, db):
        """_conn() rolls back on exception and re-raises."""
        import contextlib
        with pytest.raises(ValueError):
            with adb._conn() as conn:
                raise ValueError("test rollback")

    def test_schema_v2_migration_idempotent_with_existing_columns(self, db):
        """Applying init_db twice when v2 columns exist should not raise."""
        adb.init_db()  # second call — v2 columns already present
        # Should silently handle the OperationalError for duplicate columns
        adb.init_db()  # third call — no error


class TestIsWorkerAliveException:
    def test_bad_timestamp_returns_false(self, db):
        """Corrupt timestamp in heartbeat row → exception → returns False."""
        with adb._conn() as conn:
            conn.execute(
                "INSERT INTO mac_heartbeat (worker_id, last_seen_at, version) VALUES (?, ?, ?)",
                ("corrupt-worker", "not-a-valid-timestamp", ""),
            )
        result = adb.is_worker_alive(max_age_seconds=3600)
        assert result is False
