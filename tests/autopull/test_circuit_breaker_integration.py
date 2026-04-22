"""Simulate 3 auth failures in a row, assert 4th run short-circuits."""
from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock
from tools.autopull import cli
from tools.autopull.config import AutopullConfig


def _cfg(tmp_path: Path) -> AutopullConfig:
    return AutopullConfig(
        enabled=True, postgame_enabled=True, llm_adapt_enabled=False,
        idempotency_window_min=0, llm_daily_budget_usd=1.0,
        llm_model="claude-sonnet-4-6",
        gmail_client_id="", gmail_client_secret="", gmail_refresh_token="",
        gmail_notify_from="", gmail_notify_to="",
        anthropic_api_key="", n8n_status_webhook="", n8n_weekly_webhook="",
        gc_team_id="T", gc_season_slug="S",
        data_root=tmp_path / "data", log_root=tmp_path / "logs",
    )


def test_breaker_trips_after_three_auth_failures(tmp_path):
    cfg = _cfg(tmp_path)
    auth_runner = MagicMock(side_effect=RuntimeError("auth expired"))
    for _ in range(3):
        r = cli.run_once(cfg=cfg, trigger="manual", runner=auth_runner)
        assert r["outcome"] == "failure"

    # 4th run: breaker should short-circuit without calling the runner.
    auth_runner.reset_mock()
    r4 = cli.run_once(cfg=cfg, trigger="manual", runner=auth_runner)
    assert r4["outcome"] == "skipped"
    assert "breaker" in r4["reason"].lower()
    auth_runner.assert_not_called()
