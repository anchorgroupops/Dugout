"""Tests for tools.autopull.state — SQLite-backed runs, strategies, breakers."""
from __future__ import annotations
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from tools.autopull.state import StateDB, StrategyRow, RunRow

ET = ZoneInfo("America/New_York")


def test_creates_schema_idempotently(tmp_db_path):
    db = StateDB(tmp_db_path)
    db.init_schema()
    db.init_schema()  # second call is a no-op
    tables = db.list_tables()
    assert {"runs", "strategies", "circuit_breaker", "schema_profile"} <= set(tables)


def test_insert_and_fetch_run(tmp_db_path):
    db = StateDB(tmp_db_path)
    db.init_schema()
    run_id = db.start_run(trigger="cron", started_at=datetime.now(ET))
    db.complete_run(run_id, outcome="success", csv_path="/tmp/x.csv",
                    rows_ingested=25, winning_strategy_id=None,
                    duration_ms=1234, llm_fallback_invoked=False,
                    session_refreshed=False)
    runs = db.recent_runs(limit=5)
    assert len(runs) == 1
    assert runs[0].outcome == "success"
    assert runs[0].rows_ingested == 25


def test_last_successful_run_within(tmp_db_path):
    db = StateDB(tmp_db_path)
    db.init_schema()
    now = datetime.now(ET)
    rid = db.start_run(trigger="cron", started_at=now - timedelta(minutes=5))
    db.complete_run(rid, outcome="success", csv_path=None, rows_ingested=1,
                    winning_strategy_id=None, duration_ms=1,
                    llm_fallback_invoked=False, session_refreshed=False,
                    completed_at=now - timedelta(minutes=5))
    assert db.last_successful_run_within(minutes=15) is not None
    assert db.last_successful_run_within(minutes=1) is None


def test_strategy_seed_and_rank(tmp_db_path):
    db = StateDB(tmp_db_path)
    db.init_schema()
    sid_a = db.upsert_strategy(kind="locator", selector='{"role":"button","name":"export"}',
                               description="role=button name=/export/", source="builtin")
    sid_b = db.upsert_strategy(kind="css", selector="[data-testid='export']",
                               description="data-testid export", source="builtin")
    now = datetime.now(ET)
    db.record_strategy_result(sid_a, success=True, at=now - timedelta(days=1))
    db.record_strategy_result(sid_a, success=True, at=now)
    db.record_strategy_result(sid_b, success=False, at=now)
    ranked = db.ranked_strategies()
    assert ranked[0].id == sid_a, "A has 2 recent successes, should rank first"
    assert ranked[1].id == sid_b


def test_strategy_auto_disable(tmp_db_path):
    db = StateDB(tmp_db_path)
    db.init_schema()
    sid = db.upsert_strategy(kind="css", selector="dead.selector",
                             description="dead", source="builtin")
    db.record_strategy_result(sid, success=True,
                              at=datetime.now(ET) - timedelta(days=60))
    for _ in range(5):
        db.record_strategy_result(sid, success=False)
    db.auto_disable_stale_strategies()
    ranked = db.ranked_strategies()
    assert all(s.id != sid for s in ranked), "stale strategy should be disabled"


def test_circuit_breaker_open_and_reset(tmp_db_path):
    db = StateDB(tmp_db_path)
    db.init_schema()
    assert db.breaker_open("auth") is False
    for _ in range(3):
        db.breaker_record_failure("auth", open_duration_hours=24)
    assert db.breaker_open("auth") is True
    db.breaker_reset("auth")
    assert db.breaker_open("auth") is False


def test_schema_profile_drift(tmp_db_path):
    db = StateDB(tmp_db_path)
    db.init_schema()
    db.record_schema(["AB", "H", "BB", "K"], row_count=20)
    db.record_schema(["AB", "H", "BB", "K", "HBP"], row_count=22)
    latest, prior = db.last_two_schemas()
    assert latest is not None and prior is not None
    overlap = db.schema_overlap(latest, prior)
    assert 0.80 <= overlap < 1.0


# --- Multi-team migration tests -----------------------------------------------


def test_migration_adds_team_id_column(tmp_db_path):
    # Pre-create a legacy DB with no team_id column.
    import sqlite3
    conn = sqlite3.connect(str(tmp_db_path))
    conn.executescript("""
        CREATE TABLE runs (
          id INTEGER PRIMARY KEY,
          started_at TEXT NOT NULL,
          completed_at TEXT,
          trigger TEXT NOT NULL,
          outcome TEXT NOT NULL DEFAULT 'in_progress',
          csv_path TEXT,
          rows_ingested INTEGER,
          winning_strategy_id INTEGER,
          failure_reason TEXT,
          duration_ms INTEGER,
          llm_fallback_invoked INTEGER DEFAULT 0,
          session_refreshed INTEGER DEFAULT 0
        );
        INSERT INTO runs(started_at, trigger, outcome) VALUES('2026-04-22', 'cron', 'success');
        CREATE TABLE schema_profile (
          observed_at TEXT PRIMARY KEY,
          column_names_json TEXT NOT NULL,
          row_count INTEGER NOT NULL
        );
        INSERT INTO schema_profile VALUES('2026-04-22', '["AB","H"]', 20);
    """)
    conn.commit()
    conn.close()

    db = StateDB(tmp_db_path)
    db.init_schema()

    # runs.team_id present with 'sharks' backfill
    with db._conn() as c:
        cols = [r["name"] for r in c.execute("PRAGMA table_info(runs)").fetchall()]
        assert "team_id" in cols
        row = c.execute("SELECT team_id FROM runs").fetchone()
        assert row["team_id"] == "sharks"

        # schema_profile gains team_id, old row migrated
        cols2 = [r["name"] for r in c.execute("PRAGMA table_info(schema_profile)").fetchall()]
        assert "team_id" in cols2
        row2 = c.execute("SELECT team_id FROM schema_profile").fetchone()
        assert row2["team_id"] == "sharks"


def test_last_successful_run_scoped_by_team(tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    now = datetime.now(ET)

    rid_s = db.start_run(trigger="cron", team_id="sharks",
                         started_at=now - timedelta(minutes=5))
    db.complete_run(rid_s, outcome="success", csv_path=None, rows_ingested=1,
                    winning_strategy_id=None, duration_ms=1,
                    llm_fallback_invoked=False, session_refreshed=False,
                    completed_at=now - timedelta(minutes=5))

    # Sharks succeeded within 15m; Dolphins did not run at all.
    assert db.last_successful_run_within(15, team_id="sharks") is not None
    assert db.last_successful_run_within(15, team_id="dolphins") is None


def test_record_schema_scoped_by_team(tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    db.record_schema(["AB", "H"], row_count=10, team_id="sharks")
    db.record_schema(["AB", "H", "BB"], row_count=12, team_id="sharks")
    db.record_schema(["X", "Y"], row_count=3, team_id="dolphins")
    sharks_latest, sharks_prior = db.last_two_schemas(team_id="sharks")
    dolphins_latest, dolphins_prior = db.last_two_schemas(team_id="dolphins")
    assert sharks_latest == ["AB", "BB", "H"]
    assert sharks_prior == ["AB", "H"]
    assert dolphins_latest == ["X", "Y"]
    assert dolphins_prior is None


# ---------------------------------------------------------------------------
# list_tables / _table_exists / _columns
# ---------------------------------------------------------------------------

def test_list_tables_contains_expected(tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    tables = db.list_tables()
    assert "runs" in tables
    assert "strategies" in tables


def test_list_tables_returns_list(tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    assert isinstance(db.list_tables(), list)


def test_table_exists_true_for_runs(tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    with db._conn() as conn:
        assert StateDB._table_exists(conn, "runs") is True


def test_table_exists_false_for_nonexistent(tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    with db._conn() as conn:
        assert StateDB._table_exists(conn, "nonexistent_table_xyz") is False


def test_columns_includes_known_columns(tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    with db._conn() as conn:
        cols = StateDB._columns(conn, "runs")
    assert "id" in cols
    assert "trigger" in cols
    assert "outcome" in cols


# ---------------------------------------------------------------------------
# recent_runs
# ---------------------------------------------------------------------------

def test_recent_runs_returns_empty_when_no_runs(tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    assert db.recent_runs() == []


def test_recent_runs_includes_completed_run(tmp_db_path):
    now = datetime.now(ET)
    db = StateDB(tmp_db_path); db.init_schema()
    run_id = db.start_run("cron", team_id="sharks")
    db.complete_run(
        run_id, outcome="success", csv_path=None, rows_ingested=10,
        winning_strategy_id=None, duration_ms=500,
        llm_fallback_invoked=False, session_refreshed=False,
        completed_at=now,
    )
    runs = db.recent_runs()
    assert len(runs) >= 1
    assert runs[0].outcome == "success"


def test_recent_runs_limit_respected(tmp_db_path):
    now = datetime.now(ET)
    db = StateDB(tmp_db_path); db.init_schema()
    for _ in range(5):
        run_id = db.start_run("cron", team_id="sharks")
        db.complete_run(
            run_id, outcome="success", csv_path=None, rows_ingested=1,
            winning_strategy_id=None, duration_ms=100,
            llm_fallback_invoked=False, session_refreshed=False,
            completed_at=now,
        )
    runs = db.recent_runs(limit=3)
    assert len(runs) <= 3


# ---------------------------------------------------------------------------
# schema_overlap static method
# ---------------------------------------------------------------------------

def test_schema_overlap_full(tmp_db_path):
    assert StateDB.schema_overlap(["a", "b", "c"], ["a", "b", "c"]) == 1.0


def test_schema_overlap_empty_b(tmp_db_path):
    # StateDB.schema_overlap returns 0.0 when either set is empty
    assert StateDB.schema_overlap(["a", "b"], []) == 0.0


def test_schema_overlap_partial(tmp_db_path):
    result = StateDB.schema_overlap(["a", "b"], ["a", "b", "c"])
    assert abs(result - 2 / 3) < 1e-9


def test_last_two_schemas_returns_none_none_when_no_rows(tmp_db_path):
    """last_two_schemas with no rows for a team returns (None, None)."""
    db = StateDB(tmp_db_path); db.init_schema()
    latest, prior = db.last_two_schemas(team_id="nonexistent")
    assert latest is None
    assert prior is None


def test_breaker_auto_resets_after_open_duration_passes(tmp_db_path):
    """breaker_open returns False and resets itself once reset_at is in the past."""
    from datetime import timedelta
    db = StateDB(tmp_db_path); db.init_schema()
    # Open the breaker with an already-elapsed duration (negative hours = past)
    for _ in range(3):
        db.breaker_record_failure("auth", open_duration_hours=-1)  # already expired
    # breaker_open should detect reset_at is in the past, reset, and return False
    result = db.breaker_open("auth")
    assert result is False
