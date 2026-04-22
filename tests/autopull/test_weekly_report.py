"""Tests for tools.autopull.weekly_report."""
from __future__ import annotations
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo
from tools.autopull.state import StateDB
from tools.autopull import weekly_report as wr

ET = ZoneInfo("America/New_York")


def test_summary_counts(tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    now = datetime.now(ET)
    for i, oc in enumerate(["success", "success", "failure", "quarantined"]):
        rid = db.start_run(trigger="cron", started_at=now - timedelta(days=i))
        db.complete_run(rid, outcome=oc, csv_path=None, rows_ingested=10,
                        winning_strategy_id=None, duration_ms=1000,
                        llm_fallback_invoked=(i == 2),
                        session_refreshed=False,
                        completed_at=now - timedelta(days=i))
    summary = wr.build_summary(db, days=7)
    assert summary["total_runs"] == 4
    assert summary["by_outcome"]["success"] == 2
    assert summary["by_outcome"]["failure"] == 1
    assert summary["by_outcome"]["quarantined"] == 1
    assert summary["llm_fallback_invocations"] == 1


def test_post_weekly(monkeypatch, tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    poster = MagicMock()
    wr.post_weekly(db, poster=poster, webhook_url="https://x/y", days=7)
    poster.assert_called_once()
    args, kwargs = poster.call_args
    assert args[0] == "https://x/y"
    assert "total_runs" in args[1]


def test_summary_groups_by_team(tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    now = datetime.now(ET)
    for team, oc in [("sharks", "success"), ("sharks", "success"),
                     ("dolphins", "failure")]:
        rid = db.start_run(trigger="cron", team_id=team, started_at=now)
        db.complete_run(rid, outcome=oc, csv_path=None, rows_ingested=5,
                        winning_strategy_id=None, duration_ms=100,
                        llm_fallback_invoked=False, session_refreshed=False,
                        completed_at=now)
    summary = wr.build_summary(db, days=7)
    assert "by_team" in summary
    assert summary["by_team"]["sharks"]["success"] == 2
    assert summary["by_team"]["dolphins"]["failure"] == 1
