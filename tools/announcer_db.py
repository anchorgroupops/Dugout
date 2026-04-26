"""Announcer SQLite database — render queue, player songs, shuffle state, heartbeat.

DB file: data/sharks/announcer/announcer.db
All writes go through _conn() context manager with WAL journal mode.
"""
from __future__ import annotations

import json
import logging
import random
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "sharks" / "announcer" / "announcer.db"

log = logging.getLogger("announcer_db")


def _ensure_db_dir() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    _ensure_db_dir()
    conn = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema migrations
# ---------------------------------------------------------------------------

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);

CREATE TABLE IF NOT EXISTS render_queue (
    id          TEXT PRIMARY KEY,
    player_id   TEXT NOT NULL,
    game_context TEXT DEFAULT '{}',
    quality     TEXT CHECK(quality IN ('quick','best')) NOT NULL DEFAULT 'best',
    status      TEXT CHECK(status IN ('PENDING','PROCESSING','COMPLETED','FAILED'))
                     NOT NULL DEFAULT 'PENDING',
    priority    TEXT CHECK(priority IN ('high','normal')) NOT NULL DEFAULT 'normal',
    worker_id   TEXT,
    draft_quality INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL,
    claimed_at  TEXT,
    completed_at TEXT,
    error       TEXT
);

CREATE INDEX IF NOT EXISTS idx_rq_status   ON render_queue(status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_rq_player   ON render_queue(player_id, created_at DESC);

CREATE TABLE IF NOT EXISTS player_songs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id      TEXT NOT NULL,
    song_url       TEXT NOT NULL,
    song_label     TEXT DEFAULT '',
    play_count     INTEGER DEFAULT 0,
    last_played_at TEXT,
    created_at     TEXT NOT NULL,
    UNIQUE(player_id, song_url)
);

CREATE INDEX IF NOT EXISTS idx_ps_player ON player_songs(player_id, play_count, last_played_at);

CREATE TABLE IF NOT EXISTS shuffle_state (
    player_id       TEXT NOT NULL,
    game_session_id TEXT NOT NULL,
    played_song_ids TEXT DEFAULT '[]',
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (player_id, game_session_id)
);

CREATE TABLE IF NOT EXISTS mac_heartbeat (
    worker_id    TEXT PRIMARY KEY,
    last_seen_at TEXT NOT NULL,
    version      TEXT DEFAULT ''
);

INSERT OR IGNORE INTO schema_version VALUES (1);
"""


def init_db() -> None:
    """Create or migrate schema. Safe to call repeatedly."""
    with _conn() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT MAX(version) FROM schema_version")
            row = cur.fetchone()
            current = row[0] if (row and row[0] is not None) else 0
        except sqlite3.OperationalError:
            current = 0

        if current < 1:
            conn.executescript(_SCHEMA_V1)
            log.info("[announcer_db] Applied schema v1")


# ---------------------------------------------------------------------------
# Render Queue
# ---------------------------------------------------------------------------

def enqueue_render(player_id: str, game_context: dict, quality: str = "best") -> dict:
    """Insert a PENDING job. Returns the job dict."""
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    priority = "high" if quality == "quick" else "normal"

    with _conn() as conn:
        conn.execute(
            """INSERT INTO render_queue
               (id, player_id, game_context, quality, status, priority, created_at)
               VALUES (?, ?, ?, ?, 'PENDING', ?, ?)""",
            (job_id, player_id, json.dumps(game_context), quality, priority, now),
        )

    return {
        "id": job_id, "player_id": player_id, "quality": quality,
        "status": "PENDING", "priority": priority, "created_at": now,
    }


def claim_next_job(worker_id: str, quality: str = "best") -> dict | None:
    """Atomically claim the next PENDING job for the given quality tier.

    Sets status → PROCESSING immediately so the Pi won't trigger fallover.
    Returns the full job dict or None if the queue is empty.
    """
    now = datetime.now(timezone.utc).isoformat()

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT id FROM render_queue
               WHERE status = 'PENDING' AND quality = ?
               ORDER BY CASE priority WHEN 'high' THEN 0 ELSE 1 END, created_at
               LIMIT 1""",
            (quality,),
        )
        row = cur.fetchone()
        if not row:
            return None

        job_id = row["id"]
        conn.execute(
            """UPDATE render_queue
               SET status = 'PROCESSING', worker_id = ?, claimed_at = ?
               WHERE id = ? AND status = 'PENDING'""",
            (worker_id, now, job_id),
        )
        cur.execute("SELECT * FROM render_queue WHERE id = ?", (job_id,))
        job_row = cur.fetchone()
        return dict(job_row) if job_row else None


def update_job_status(job_id: str, status: str, error: str | None = None,
                      draft_quality: bool = False) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            """UPDATE render_queue
               SET status = ?, completed_at = ?, error = ?, draft_quality = ?
               WHERE id = ?""",
            (status, now, error, 1 if draft_quality else 0, job_id),
        )


def get_pending_jobs(quality: str = "best", limit: int = 10) -> list[dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT * FROM render_queue
               WHERE status = 'PENDING' AND quality = ?
               ORDER BY CASE priority WHEN 'high' THEN 0 ELSE 1 END, created_at
               LIMIT ?""",
            (quality, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def get_job(job_id: str) -> dict | None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM render_queue WHERE id = ?", (job_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_player_render_status(player_id: str) -> dict | None:
    """Return the most recent job for a player."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT * FROM render_queue
               WHERE player_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (player_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def requeue_stale_jobs(stale_seconds: int = 120) -> int:
    """Reset PROCESSING jobs that have been claimed but not completed within stale_seconds.

    Returns the number of jobs reset.
    """
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)).isoformat()
    with _conn() as conn:
        cur = conn.execute(
            """UPDATE render_queue
               SET status = 'PENDING', worker_id = NULL, claimed_at = NULL
               WHERE status = 'PROCESSING' AND claimed_at < ?""",
            (cutoff,),
        )
        return cur.rowcount


# ---------------------------------------------------------------------------
# Player Songs
# ---------------------------------------------------------------------------

def add_player_song(player_id: str, song_url: str, song_label: str = "") -> list[dict]:
    """Add a song to a player's pool. Ignores duplicates. Returns updated pool."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO player_songs
               (player_id, song_url, song_label, created_at)
               VALUES (?, ?, ?, ?)""",
            (player_id, song_url, song_label, now),
        )
    return get_player_songs(player_id)


def remove_player_song(song_id: int, player_id: str) -> None:
    """Remove a song by its integer ID (scoped to player_id for safety)."""
    with _conn() as conn:
        conn.execute(
            "DELETE FROM player_songs WHERE id = ? AND player_id = ?",
            (song_id, player_id),
        )


def get_player_songs(player_id: str) -> list[dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT * FROM player_songs
               WHERE player_id = ?
               ORDER BY play_count ASC,
                        CASE WHEN last_played_at IS NULL THEN 0 ELSE 1 END ASC,
                        last_played_at ASC""",
            (player_id,),
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Shuffle Engine — Least-Recently-Played
# ---------------------------------------------------------------------------

def pick_walkup_song(player_id: str, game_session_id: str) -> str | None:
    """Pick the next walk-up song using Least-Recently-Played logic.

    Algorithm:
      1. Load all songs, ordered by (play_count ASC, last_played_at ASC NULLS FIRST).
      2. Filter to songs not yet played this game session.
      3. If all played this session, reset the session played list (full cycle).
      4. Pick randomly from the lowest play_count tier among available songs.
      5. Increment play_count, set last_played_at, record in shuffle_state.

    Returns song_url or None if no songs configured.
    """
    with _conn() as conn:
        cur = conn.cursor()

        cur.execute(
            """SELECT id, song_url, play_count
               FROM player_songs
               WHERE player_id = ?
               ORDER BY play_count ASC,
                        CASE WHEN last_played_at IS NULL THEN 0 ELSE 1 END ASC,
                        last_played_at ASC""",
            (player_id,),
        )
        all_songs = [dict(r) for r in cur.fetchall()]
        if not all_songs:
            return None

        if len(all_songs) == 1:
            chosen = all_songs[0]
        else:
            cur.execute(
                "SELECT played_song_ids FROM shuffle_state WHERE player_id = ? AND game_session_id = ?",
                (player_id, game_session_id),
            )
            state_row = cur.fetchone()
            played_ids: list = json.loads(state_row["played_song_ids"]) if state_row else []

            available = [s for s in all_songs if s["id"] not in played_ids]
            if not available:
                played_ids = []
                available = list(all_songs)

            min_count = available[0]["play_count"]
            tier = [s for s in available if s["play_count"] == min_count]
            chosen = random.choice(tier)

        # Commit the play
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE player_songs SET play_count = play_count + 1, last_played_at = ? WHERE id = ?",
            (now, chosen["id"]),
        )

        # Update session state
        cur.execute(
            "SELECT played_song_ids FROM shuffle_state WHERE player_id = ? AND game_session_id = ?",
            (player_id, game_session_id),
        )
        state_row = cur.fetchone()
        session_played = json.loads(state_row["played_song_ids"]) if state_row else []
        session_played.append(chosen["id"])

        conn.execute(
            """INSERT OR REPLACE INTO shuffle_state
               (player_id, game_session_id, played_song_ids, updated_at)
               VALUES (?, ?, ?, ?)""",
            (player_id, game_session_id, json.dumps(session_played), now),
        )

        return chosen["song_url"]


def peek_next_songs(player_ids: list[str], game_session_id: str) -> dict[str, str]:
    """Preview the next song URL for each player without committing the play.

    Used for pre-buffering: the PWA calls preload() on the returned URLs.
    Returns {player_id: song_url}.
    """
    result: dict[str, str] = {}

    with _conn() as conn:
        cur = conn.cursor()
        for pid in player_ids:
            cur.execute(
                "SELECT played_song_ids FROM shuffle_state WHERE player_id = ? AND game_session_id = ?",
                (pid, game_session_id),
            )
            state_row = cur.fetchone()
            played_ids = json.loads(state_row["played_song_ids"]) if state_row else []

            cur.execute(
                """SELECT id, song_url, play_count
                   FROM player_songs
                   WHERE player_id = ?
                   ORDER BY play_count ASC,
                            CASE WHEN last_played_at IS NULL THEN 0 ELSE 1 END ASC,
                            last_played_at ASC""",
                (pid,),
            )
            all_songs = [dict(r) for r in cur.fetchall()]
            if not all_songs:
                continue

            available = [s for s in all_songs if s["id"] not in played_ids]
            if not available:
                available = list(all_songs)

            min_count = available[0]["play_count"]
            tier = [s for s in available if s["play_count"] == min_count]
            result[pid] = random.choice(tier)["song_url"]

    return result


# ---------------------------------------------------------------------------
# Mac Heartbeat
# ---------------------------------------------------------------------------

def update_heartbeat(worker_id: str, version: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO mac_heartbeat (worker_id, last_seen_at, version)
               VALUES (?, ?, ?)""",
            (worker_id, now, version),
        )


def get_heartbeat_info() -> dict | None:
    """Return the most recent worker heartbeat record (id, last_seen_at, version)."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM mac_heartbeat ORDER BY last_seen_at DESC LIMIT 1")
        row = cur.fetchone()
        return dict(row) if row else None


def is_worker_alive(max_age_seconds: int = 30) -> bool:
    """Return True if any worker has heartbeated within max_age_seconds."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT last_seen_at FROM mac_heartbeat ORDER BY last_seen_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return False
        try:
            last_seen = datetime.fromisoformat(row["last_seen_at"].replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - last_seen).total_seconds()
            return age <= max_age_seconds
        except Exception:
            return False
