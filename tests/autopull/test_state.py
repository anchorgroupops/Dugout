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
