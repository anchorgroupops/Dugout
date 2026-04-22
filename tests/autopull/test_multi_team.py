"""Tests for multi-team behavior in cli.run_once."""
from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock
from tools.autopull import cli
from tools.autopull.config import AutopullConfig
from tools.autopull.state import StateDB


def _cfg(tmp_path: Path) -> AutopullConfig:
    return AutopullConfig(
        enabled=True, postgame_enabled=True, llm_adapt_enabled=False,
        idempotency_window_min=15, llm_daily_budget_usd=1.0,
        llm_model="claude-sonnet-4-6",
        gmail_client_id="", gmail_client_secret="", gmail_refresh_token="",
        gmail_notify_from="", gmail_notify_to="",
        anthropic_api_key="", n8n_status_webhook="", n8n_weekly_webhook="",
        data_root=tmp_path / "data", log_root=tmp_path / "logs",
    )


def _two_team_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "teams.yaml"
    p.write_text(
        "teams:\n"
        "  - {id: sh, season_slug: s1, name: Sharks, data_slug: sharks, active: true}\n"
        "  - {id: dl, season_slug: s2, name: Dolphins, data_slug: dolphins, active: true}\n"
    )
    return p


def test_loops_over_active_teams(tmp_path):
    cfg = _cfg(tmp_path)
    teams_path = _two_team_yaml(tmp_path)
    runner = MagicMock(return_value={"outcome": "success", "rows_ingested": 5})
    result = cli.run_once(cfg=cfg, trigger="manual", runner=runner,
                          teams_path=teams_path)
    assert result["outcome"] == "all_success"
    assert runner.call_count == 2
    slugs_called = [c.kwargs["team"].data_slug for c in runner.call_args_list]
    assert slugs_called == ["sharks", "dolphins"]


def test_one_team_fails_other_succeeds(tmp_path):
    cfg = _cfg(tmp_path)
    teams_path = _two_team_yaml(tmp_path)

    def runner(*, cfg, db, run_id, team):
        if team.data_slug == "dolphins":
            raise RuntimeError("boom")
        return {"outcome": "success"}

    result = cli.run_once(cfg=cfg, trigger="manual", runner=runner,
                          teams_path=teams_path)
    assert result["outcome"] == "partial"
    assert result["per_team"]["sharks"]["outcome"] == "success"
    assert result["per_team"]["dolphins"]["outcome"] == "failure"


def test_inactive_team_skipped(tmp_path):
    cfg = _cfg(tmp_path)
    teams_path = tmp_path / "teams.yaml"
    teams_path.write_text(
        "teams:\n"
        "  - {id: sh, season_slug: s1, name: Sharks, data_slug: sharks, active: true}\n"
        "  - {id: dl, season_slug: s2, name: Dolphins, data_slug: dolphins, active: false}\n"
    )
    runner = MagicMock(return_value={"outcome": "success"})
    result = cli.run_once(cfg=cfg, trigger="manual", runner=runner,
                          teams_path=teams_path)
    assert runner.call_count == 1
    assert runner.call_args.kwargs["team"].data_slug == "sharks"


def test_per_team_idempotency(tmp_path):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    cfg = _cfg(tmp_path)
    teams_path = _two_team_yaml(tmp_path)

    db = StateDB(cfg.data_root / "autopull" / "autopull_state.db")
    db.init_schema()
    rid = db.start_run(trigger="cron", team_id="sharks",
                       started_at=datetime.now(et) - timedelta(minutes=5))
    db.complete_run(rid, outcome="success", csv_path=None, rows_ingested=1,
                    winning_strategy_id=None, duration_ms=1,
                    llm_fallback_invoked=False, session_refreshed=False,
                    completed_at=datetime.now(et) - timedelta(minutes=5))

    runner = MagicMock(return_value={"outcome": "success"})
    result = cli.run_once(cfg=cfg, trigger="manual", runner=runner,
                          teams_path=teams_path)
    assert result["per_team"]["sharks"]["outcome"] == "skipped"
    assert result["per_team"]["dolphins"]["outcome"] == "success"
    assert runner.call_count == 1
    assert runner.call_args.kwargs["team"].data_slug == "dolphins"
