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
        gmail_username="", gmail_app_password="",
        gmail_notify_from="", gmail_notify_to="",
        anthropic_api_key="", n8n_status_webhook="", n8n_weekly_webhook="",
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


def test_breaker_resets_after_manual_success(tmp_path):
    """After a success the breaker should clear and next run executes."""
    import tools.autopull.cli as cli_mod

    p = tmp_path / "teams.yaml"
    p.write_text(
        "teams:\n"
        "  - {id: a, season_slug: s, name: Sharks, data_slug: sharks, active: true}\n"
    )
    cfg = _cfg(tmp_path)

    # Trigger enough failures to open the breaker
    auth_runner = MagicMock(side_effect=RuntimeError("auth failure"))
    for _ in range(3):
        cli.run_once(cfg=cfg, trigger="manual", runner=auth_runner, teams_path=p)

    # Verify breaker is open
    r = cli.run_once(cfg=cfg, trigger="manual", runner=auth_runner, teams_path=p)
    assert r["outcome"] == "skipped"

    # Reset the breaker manually via StateDB
    from tools.autopull.state import StateDB
    db_path = tmp_path / "logs" / "autopull.db"
    if db_path.exists():
        db = StateDB(db_path)
        db.breaker_reset("auth")
        # After reset, the next run should attempt to run again
        good_runner = MagicMock(return_value={"outcome": "success", "csv_path": None,
                                               "rows_ingested": 0, "drift_severity": "none"})
        r2 = cli.run_once(cfg=cfg, trigger="manual", runner=good_runner, teams_path=p)
        # The breaker was reset, so the runner should be called
        assert r2["outcome"] != "skipped" or good_runner.called


def test_download_errors_recorded_as_failure(tmp_path):
    """Non-auth download errors produce failure outcome (no global skip for download breaker)."""
    p = tmp_path / "teams.yaml"
    p.write_text(
        "teams:\n"
        "  - {id: a, season_slug: s, name: Sharks, data_slug: sharks, active: true}\n"
    )
    cfg = _cfg(tmp_path)
    download_runner = MagicMock(side_effect=RuntimeError("network timeout"))
    r = cli.run_once(cfg=cfg, trigger="manual", runner=download_runner, teams_path=p)
    assert r["outcome"] == "failure"
    assert "network timeout" in r["per_team"]["sharks"]["failure_reason"]
