"""
db_sync.py — PostgreSQL sync history logging for The Librarian.
Layer 3 Tool | NotebookLM Librarian

Writes sync run summaries and per-source events to PostgreSQL.
Uses the n8n_ai database already running at 192.168.7.222.

Silently skips all operations if psycopg2 is not installed or DB is unreachable.
Install: pip install psycopg2-binary

Tables created automatically on first use:
  librarian_sync_runs  — one row per notebook sync run
  librarian_sources    — one row per source add/fail event
"""
import os
from pathlib import Path

_DEFAULT_DB_URL = "postgresql://n8n:n8n@192.168.7.222:5432/n8n_ai"

_CREATE_SYNC_RUNS = """
CREATE TABLE IF NOT EXISTS librarian_sync_runs (
    id          SERIAL PRIMARY KEY,
    run_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notebook_id TEXT,
    notebook_title TEXT,
    sources_added  INTEGER NOT NULL DEFAULT 0,
    sources_failed INTEGER NOT NULL DEFAULT 0,
    duration_ms    INTEGER,
    dry_run        BOOLEAN NOT NULL DEFAULT FALSE,
    error          TEXT
);
"""

_CREATE_SOURCES = """
CREATE TABLE IF NOT EXISTS librarian_sources (
    id           SERIAL PRIMARY KEY,
    synced_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notebook_id  TEXT,
    url          TEXT,
    title        TEXT,
    source_type  TEXT,
    status       TEXT,
    source_id    TEXT,
    error        TEXT
);
"""


def _db_url() -> str:
    return os.environ.get("LIBRARIAN_DB_URL", _DEFAULT_DB_URL)


def _get_conn():
    """Return a live psycopg2 connection, or None if unavailable."""
    try:
        import psycopg2
        return psycopg2.connect(_db_url())
    except ImportError:
        return None
    except Exception:
        return None


def ensure_tables() -> bool:
    """Create librarian tables if they don't exist. Returns True on success."""
    conn = _get_conn()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE_SYNC_RUNS)
            cur.execute(_CREATE_SOURCES)
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def log_sync_run(
    notebook_id: str,
    notebook_title: str,
    sources_added: int,
    sources_failed: int,
    duration_ms: int,
    dry_run: bool = False,
    error: str = None,
) -> bool:
    """Insert a sync run summary row. Returns True on success."""
    conn = _get_conn()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO librarian_sync_runs
                    (notebook_id, notebook_title, sources_added, sources_failed,
                     duration_ms, dry_run, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (notebook_id, notebook_title, sources_added, sources_failed,
                 duration_ms, dry_run, error),
            )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def log_source(
    notebook_id: str,
    url: str,
    title: str = "",
    source_type: str = "youtube",
    status: str = "success",
    source_id: str = None,
    error: str = None,
) -> bool:
    """Insert a per-source event row. Returns True on success."""
    conn = _get_conn()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO librarian_sources
                    (notebook_id, url, title, source_type, status, source_id, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (notebook_id, url, title, source_type, status, source_id, error),
            )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def is_available() -> bool:
    """Check if PostgreSQL logging is functional."""
    conn = _get_conn()
    if not conn:
        return False
    conn.close()
    return True


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    def _load_env():
        env = Path(__file__).parent.parent / ".env"
        if env.exists():
            with open(env) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        os.environ.setdefault(k.strip(), v.strip())

    _load_env()

    if is_available():
        ensure_tables()
        ok = log_sync_run("test-nb-id", "Test Notebook", 3, 0, 1500, dry_run=True)
        print(f"[DB] Test run logged: {ok}")
    else:
        print("[DB] PostgreSQL unavailable (psycopg2 not installed or DB unreachable)")
