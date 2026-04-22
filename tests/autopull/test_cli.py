"""Unit tests for the CLI orchestrator — pure logic, no real Playwright.

These tests focus on the global short-circuit paths and the single-team
aggregate shape; multi-team loop behavior lives in test_multi_team.py.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import pytest
from tools.autopull import cli
from tools.autopull.state import StateDB

ET = ZoneInfo("America/New_York")


def _fake_cfg(tmp_path: Path, **over):
    base = dict(
        enabled=True, postgame_enabled=True, llm_adapt_enabled=False,
        idempotency_window_min=15, llm_daily_budget_usd=1.0,
        llm_model="claude-sonnet-4-6",
        gmail_username="fly386@gmail.com", gmail_app_password="abcdefghijklmnop",
        gmail_notify_from="fly386@gmail.com", gmail_notify_to="a@b.c",
        anthropic_api_key="", n8n_status_webhook="",
        n8n_weekly_webhook="",
        data_root=tmp_path / "data", log_root=tmp_path / "logs",
    )
    base.update(over)
    from tools.autopull.config import AutopullConfig
    return AutopullConfig(**base)


def _single_team_yaml(tmp_path):
    p = tmp_path / "teams.yaml"
    p.write_text(
        "teams:\n"
        "  - {id: a, season_slug: s, name: The Sharks, data_slug: sharks, active: true}\n"
    )
    return p


def test_skip_when_disabled(tmp_path):
    cfg = _fake_cfg(tmp_path, enabled=False)
    result = cli.run_once(cfg=cfg, trigger="cron", runner=MagicMock(),
                          teams_path=_single_team_yaml(tmp_path))
    assert result["outcome"] == "skipped"
    assert result["reason"] == "disabled"


def test_skip_when_recent_success(tmp_path):
    cfg = _fake_cfg(tmp_path)
    db = StateDB(cfg.data_root / "autopull" / "autopull_state.db")
    db.init_schema()
    rid = db.start_run(trigger="cron", team_id="sharks",
                      started_at=datetime.now(ET) - timedelta(minutes=5))
    db.complete_run(rid, outcome="success", csv_path=None, rows_ingested=1,
                    winning_strategy_id=None, duration_ms=1,
                    llm_fallback_invoked=False, session_refreshed=False,
                    completed_at=datetime.now(ET) - timedelta(minutes=5))
    runner = MagicMock(return_value={"outcome": "success"})
    result = cli.run_once(cfg=cfg, trigger="cron", runner=runner,
                          teams_path=_single_team_yaml(tmp_path))
    # Only one team, already succeeded → all_skipped
    assert result["outcome"] == "all_skipped"
    assert result["per_team"]["sharks"]["outcome"] == "skipped"
    assert runner.called is False


def test_skip_when_breaker_open(tmp_path):
    cfg = _fake_cfg(tmp_path)
    db = StateDB(cfg.data_root / "autopull" / "autopull_state.db")
    db.init_schema()
    for _ in range(3):
        db.breaker_record_failure("auth", open_duration_hours=24)
    result = cli.run_once(cfg=cfg, trigger="cron", runner=MagicMock(),
                          teams_path=_single_team_yaml(tmp_path))
    assert result["outcome"] == "skipped"
    assert "breaker" in result["reason"].lower()


def test_runner_invoked_when_eligible(tmp_path):
    cfg = _fake_cfg(tmp_path)
    runner = MagicMock(return_value={
        "outcome": "success",
        "csv_path": str(tmp_path / "x.csv"), "rows_ingested": 10,
        "winning_strategy_id": 1, "llm_fallback_invoked": False,
        "session_refreshed": False, "drift_severity": "none",
    })
    (tmp_path / "x.csv").write_text("Player,AB\na,1\n")
    result = cli.run_once(cfg=cfg, trigger="manual", runner=runner,
                          teams_path=_single_team_yaml(tmp_path))
    assert result["outcome"] == "all_success"
    assert result["per_team"]["sharks"]["outcome"] == "success"
    assert runner.called


def test_runner_exception_recorded_as_failure(tmp_path):
    cfg = _fake_cfg(tmp_path)
    runner = MagicMock(side_effect=RuntimeError("boom"))
    result = cli.run_once(cfg=cfg, trigger="manual", runner=runner,
                          teams_path=_single_team_yaml(tmp_path))
    assert result["outcome"] == "failure"
    assert result["per_team"]["sharks"]["outcome"] == "failure"
    assert "boom" in result["per_team"]["sharks"]["failure_reason"]
