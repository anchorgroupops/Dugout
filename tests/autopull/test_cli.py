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


# ---------------------------------------------------------------------------
# _breaker_key / _breaker_hours
# ---------------------------------------------------------------------------

class TestBreakerKey:
    def test_auth_errors_classified_as_auth(self):
        assert cli._breaker_key(RuntimeError("auth failure")) == "auth"

    def test_login_errors_classified_as_auth(self):
        assert cli._breaker_key(RuntimeError("login timeout")) == "auth"

    def test_2fa_errors_classified_as_auth(self):
        assert cli._breaker_key(RuntimeError("2FA required")) == "auth"

    def test_session_errors_classified_as_auth(self):
        assert cli._breaker_key(RuntimeError("session expired")) == "auth"

    def test_other_errors_classified_as_download(self):
        assert cli._breaker_key(RuntimeError("network error")) == "download"

    def test_case_insensitive_matching(self):
        assert cli._breaker_key(RuntimeError("AUTH failure")) == "auth"


class TestBreakerHours:
    def test_auth_error_returns_24_hours(self):
        assert cli._breaker_hours(RuntimeError("login failed")) == 24

    def test_download_error_returns_2_hours(self):
        assert cli._breaker_hours(RuntimeError("connection reset")) == 2

    def test_returns_int(self):
        assert isinstance(cli._breaker_hours(RuntimeError("err")), int)


# ---------------------------------------------------------------------------
# _summaries_from_result
# ---------------------------------------------------------------------------

class TestSummariesFromResult:
    def test_empty_per_team_returns_one_skipped_summary(self):
        result = {"outcome": "skipped", "reason": "disabled"}
        summaries = cli._summaries_from_result(result, trigger="cron")
        assert len(summaries) == 1
        assert summaries[0].outcome == "skipped"
        assert summaries[0].trigger == "cron"

    def test_global_failure_returns_single_summary(self):
        result = {"outcome": "failure", "failure_reason": "bad config"}
        summaries = cli._summaries_from_result(result, trigger="manual")
        assert len(summaries) == 1
        assert summaries[0].team_slug == "*"

    def test_per_team_creates_one_summary_per_team(self, tmp_path):
        p = tmp_path / "teams.yaml"
        p.write_text(
            "teams:\n"
            "  - {id: a, season_slug: s, name: Sharks, data_slug: sharks, active: true}\n"
            "  - {id: b, season_slug: s, name: Eagles, data_slug: eagles, active: true}\n"
        )
        from tools.autopull import cli as cli_mod
        result = {
            "per_team": {
                "sharks": {"outcome": "success", "run_id": 1, "drift_severity": "none"},
                "eagles": {"outcome": "failure", "run_id": 2, "failure_reason": "err", "drift_severity": "none"},
            }
        }
        from tools.team_registry import load
        import tools.team_registry as tr_mod
        original_load = tr_mod.load
        # Don't use the real teams.yaml; let require_by_slug fall through to slug name
        summaries = cli._summaries_from_result(result, trigger="cron")
        assert len(summaries) == 2

    def test_summary_outcome_from_per_team(self):
        result = {
            "per_team": {
                "sharks": {"outcome": "success", "run_id": 1, "drift_severity": "none"},
            }
        }
        summaries = cli._summaries_from_result(result, trigger="cron")
        assert summaries[0].outcome == "success"


# ---------------------------------------------------------------------------
# _build_notifier
# ---------------------------------------------------------------------------

class TestBuildNotifier:
    def test_returns_notifier_instance(self, tmp_path, monkeypatch):
        """_build_notifier returns a Notifier without making network calls."""
        from tools.autopull.notifier import Notifier
        import types
        fake_requests = types.ModuleType("requests")
        fake_requests.post = MagicMock()
        monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)
        cfg = _fake_cfg(tmp_path)
        notifier = cli._build_notifier(cfg)
        assert isinstance(notifier, Notifier)

    def test_gmail_sender_skips_when_not_configured(self, tmp_path, monkeypatch, capsys):
        """_GmailSender.send() is a no-op when gmail creds are empty."""
        import types
        fake_requests = types.ModuleType("requests")
        fake_requests.post = MagicMock()
        monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)
        cfg = _fake_cfg(tmp_path, gmail_username="", gmail_app_password="")
        notifier = cli._build_notifier(cfg)
        # Access the internal _GmailSender and call send — should not raise
        notifier._gmail.send(to="x@y.z", subject="test", body="hi")

    def test_webhook_pusher_skips_when_no_url(self, tmp_path, monkeypatch):
        """_WebhookPusher.notify() is a no-op when push URL is empty."""
        import types
        fake_requests = types.ModuleType("requests")
        fake_requests.post = MagicMock()
        monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)
        monkeypatch.setenv("PUSH_WEBHOOK_URL", "")
        cfg = _fake_cfg(tmp_path)
        notifier = cli._build_notifier(cfg)
        notifier._push.notify("hello")
        fake_requests.post.assert_not_called()

    def test_n8n_poster_calls_requests_post(self, tmp_path, monkeypatch):
        """_N8nPoster.post() calls requests.post."""
        import types
        fake_requests = types.ModuleType("requests")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        fake_requests.post = MagicMock(return_value=mock_resp)
        monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)
        cfg = _fake_cfg(tmp_path)
        notifier = cli._build_notifier(cfg)
        notifier._n8n.post("https://x/y", {"k": "v"})
        fake_requests.post.assert_called_once()

    def test_gmail_sender_calls_send_email_when_configured(self, tmp_path, monkeypatch):
        """Line 266: _GmailSender.send() calls g2fa.send_email when creds set."""
        import types
        fake_requests = types.ModuleType("requests")
        fake_requests.post = MagicMock()
        monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)
        # Mock g2fa.send_email inside the cli module
        mock_send_email = MagicMock()
        monkeypatch.setattr("tools.autopull.gmail_2fa_fetcher.send_email", mock_send_email)
        cfg = _fake_cfg(tmp_path, gmail_username="u@g.com", gmail_app_password="pw12345678")
        notifier = cli._build_notifier(cfg)
        notifier._gmail.send(to="r@x.com", subject="Test", body="Hello")
        mock_send_email.assert_called_once()

    def test_webhook_pusher_posts_when_url_set(self, tmp_path, monkeypatch):
        """Line 283: _WebhookPusher.notify() calls requests.post when URL non-empty."""
        import types
        fake_requests = types.ModuleType("requests")
        fake_requests.post = MagicMock()
        monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)
        monkeypatch.setenv("PUSH_WEBHOOK_URL", "https://push.example.com/hook")
        cfg = _fake_cfg(tmp_path)
        notifier = cli._build_notifier(cfg)
        notifier._push.notify("test message")
        fake_requests.post.assert_called_once()


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

class TestMain:
    def _mock_cfg(self, tmp_path):
        return _fake_cfg(tmp_path)

    def test_main_returns_0_on_skipped(self, tmp_path, monkeypatch):
        """main() returns 0 when outcome is 'skipped'."""
        cfg = _fake_cfg(tmp_path)
        monkeypatch.setattr("tools.autopull.cli.config_mod.load", lambda **kw: cfg)
        monkeypatch.setattr("tools.autopull.cli.run_once",
                            lambda **kw: {"outcome": "skipped", "reason": "disabled"})
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
        result = cli.main(argv=["--trigger", "manual"])
        assert result == 0

    def test_main_returns_0_on_all_success(self, tmp_path, monkeypatch):
        """main() returns 0 when outcome is 'all_success'."""
        cfg = _fake_cfg(tmp_path)
        monkeypatch.setattr("tools.autopull.cli.config_mod.load", lambda **kw: cfg)
        monkeypatch.setattr("tools.autopull.cli.run_once",
                            lambda **kw: {"outcome": "all_success",
                                         "per_team": {"sharks": {"outcome": "success",
                                                                  "run_id": 1,
                                                                  "drift_severity": "none"}}})
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
        monkeypatch.setattr("tools.autopull.cli._build_notifier",
                            lambda cfg: MagicMock())
        result = cli.main(argv=["--trigger", "cron"])
        assert result == 0

    def test_main_returns_1_on_failure(self, tmp_path, monkeypatch):
        """main() returns 1 when outcome is 'failure'."""
        cfg = _fake_cfg(tmp_path)
        monkeypatch.setattr("tools.autopull.cli.config_mod.load", lambda **kw: cfg)
        monkeypatch.setattr("tools.autopull.cli.run_once",
                            lambda **kw: {"outcome": "failure",
                                         "per_team": {"sharks": {"outcome": "failure",
                                                                  "run_id": 1,
                                                                  "failure_reason": "err",
                                                                  "drift_severity": "none"}}})
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
        monkeypatch.setattr("tools.autopull.cli._build_notifier",
                            lambda cfg: MagicMock())
        result = cli.main(argv=["--trigger", "cron"])
        assert result == 1

    def test_main_notifier_exception_logged_not_raised(self, tmp_path, monkeypatch, capsys):
        """Notifier wiring failure is logged, main() still returns normally."""
        cfg = _fake_cfg(tmp_path)
        monkeypatch.setattr("tools.autopull.cli.config_mod.load", lambda **kw: cfg)
        monkeypatch.setattr("tools.autopull.cli.run_once",
                            lambda **kw: {"outcome": "all_success",
                                         "per_team": {"sharks": {"outcome": "success",
                                                                  "run_id": 1,
                                                                  "drift_severity": "none"}}})
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
        monkeypatch.setattr("tools.autopull.cli._build_notifier",
                            lambda cfg: (_ for _ in ()).throw(RuntimeError("notifier broke")))
        result = cli.main(argv=["--trigger", "cron"])
        assert result == 0  # doesn't crash

    def test_main_prints_json_result(self, tmp_path, monkeypatch, capsys):
        """main() prints JSON result to stdout."""
        import json as _json
        cfg = _fake_cfg(tmp_path)
        monkeypatch.setattr("tools.autopull.cli.config_mod.load", lambda **kw: cfg)
        monkeypatch.setattr("tools.autopull.cli.run_once",
                            lambda **kw: {"outcome": "skipped", "reason": "disabled"})
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
        cli.main(argv=["--trigger", "manual"])
        out = capsys.readouterr().out
        parsed = _json.loads(out)
        assert parsed["outcome"] == "skipped"
