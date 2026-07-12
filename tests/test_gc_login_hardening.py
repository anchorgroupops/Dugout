"""Tests for the GC login hardening: global verification-email budget,
emailed-code reader, and shared-session behavior (guardrails SIGN-007)."""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pytest

import gc_scraper as gs


@pytest.fixture
def budget_files(tmp_path, monkeypatch):
    """Point the budget + cooldown files at a temp dir."""
    attempts = tmp_path / ".gc_login_attempts.json"
    cooldown = tmp_path / ".auth_cooldown"
    monkeypatch.setattr(gs, "_LOGIN_ATTEMPTS_FILE", attempts)
    monkeypatch.setattr(gs, "_AUTH_COOLDOWN_FILE", cooldown)
    return attempts, cooldown


# ── login budget ──────────────────────────────────────────────────────────────

def test_budget_allows_under_limit(budget_files):
    attempts, cooldown = budget_files
    for _ in range(gs.GC_LOGIN_EMAIL_BUDGET - 1):
        gs.record_login_email_submit()
    assert gs.login_budget_exhausted() is False
    assert not cooldown.exists()


def test_budget_refuses_at_limit_and_sets_cooldown(budget_files):
    attempts, cooldown = budget_files
    for _ in range(gs.GC_LOGIN_EMAIL_BUDGET):
        gs.record_login_email_submit()
    assert gs.login_budget_exhausted() is True
    assert cooldown.exists()
    reason = json.loads(cooldown.read_text())["reason"]
    assert "budget" in reason


def test_budget_window_expires_old_entries(budget_files):
    attempts, _ = budget_files
    old = datetime.now(gs.ET) - timedelta(hours=gs.GC_LOGIN_EMAIL_WINDOW_HOURS + 1)
    attempts.write_text(json.dumps([old.isoformat()] * 10))
    assert gs.login_budget_exhausted() is False
    # New submits rewrite the file with only in-window entries
    gs.record_login_email_submit()
    assert len(json.loads(attempts.read_text())) == 1


def test_budget_survives_corrupt_file(budget_files):
    attempts, _ = budget_files
    attempts.write_text("not json")
    assert gs.login_budget_exhausted() is False
    gs.record_login_email_submit()
    assert len(json.loads(attempts.read_text())) == 1


# ── emailed-code reader ───────────────────────────────────────────────────────

def test_fetch_emailed_code_without_creds_returns_none(monkeypatch):
    monkeypatch.delenv("GMAIL_USERNAME", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    assert gs.fetch_emailed_gc_code(0) is None


def test_fetch_emailed_code_polls_until_found(monkeypatch):
    monkeypatch.setenv("GMAIL_USERNAME", "u@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-pass")
    fake_mod = MagicMock()
    fake_mod.build_client.return_value = MagicMock()
    fake_mod.fetch_latest_code.side_effect = [(None, None), ("123456", "77")]
    monkeypatch.setattr(gs, "_gmail_2fa_module", lambda: fake_mod)
    monkeypatch.setattr(gs.time, "sleep", lambda s: None)
    assert gs.fetch_emailed_gc_code(42) == "123456"
    # min_uid threaded through
    assert fake_mod.fetch_latest_code.call_args[1]["min_uid"] == 42


def test_fetch_emailed_code_gives_up(monkeypatch):
    monkeypatch.setenv("GMAIL_USERNAME", "u@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-pass")
    fake_mod = MagicMock()
    fake_mod.build_client.return_value = MagicMock()
    fake_mod.fetch_latest_code.return_value = (None, None)
    monkeypatch.setattr(gs, "_gmail_2fa_module", lambda: fake_mod)
    monkeypatch.setattr(gs.time, "sleep", lambda s: None)
    assert gs.fetch_emailed_gc_code(0, max_attempts=3) is None
    assert fake_mod.fetch_latest_code.call_count == 3


def test_baseline_uid_without_creds_is_zero(monkeypatch):
    monkeypatch.delenv("GMAIL_USERNAME", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    assert gs.gc_code_baseline_uid() == 0


# ── _complete_login_flow gating ───────────────────────────────────────────────

def _scraper_with_page():
    scraper = gs.GameChangerScraper.__new__(gs.GameChangerScraper)
    scraper.email = "coach@sharks.com"
    scraper.password = "secret"
    scraper.page = MagicMock()
    return scraper


def test_login_flow_refused_when_budget_exhausted(budget_files, monkeypatch):
    scraper = _scraper_with_page()
    monkeypatch.setattr(gs, "login_budget_exhausted", lambda: True)
    with pytest.raises(RuntimeError, match="budget exhausted"):
        scraper._complete_login_flow()
    scraper.page.get_by_label.assert_not_called()


def test_login_flow_records_submit_and_baseline(budget_files, monkeypatch):
    attempts, _ = budget_files
    scraper = _scraper_with_page()
    monkeypatch.setattr(gs, "gc_code_baseline_uid", lambda: 99)
    # Stop after the budget/baseline preamble by failing the first locator
    scraper.page.get_by_label.side_effect = RuntimeError("stop here")
    scraper._capture_diagnostics = MagicMock()
    with pytest.raises(RuntimeError):
        scraper._complete_login_flow()
    assert scraper._otp_baseline_uid == 99
    assert len(json.loads(attempts.read_text())) == 1


# ── _handle_otp_if_needed uses the emailed code ───────────────────────────────

def test_otp_handler_submits_emailed_code(monkeypatch):
    scraper = _scraper_with_page()
    scraper._otp_baseline_uid = 5

    otp_field = MagicMock()
    otp_field.count.return_value = 1
    otp_field.first = otp_field
    scraper.page.locator.return_value = otp_field
    submit_btn = MagicMock()
    submit_btn.count.return_value = 1
    submit_btn.first = submit_btn
    scraper.page.get_by_role.return_value = submit_btn

    monkeypatch.setattr(gs, "pyotp", None)
    monkeypatch.setenv("GC_TOTP_SECRET", "")
    monkeypatch.setattr(gs, "fetch_emailed_gc_code",
                        lambda baseline, **kw: "654321")

    scraper._handle_otp_if_needed()
    otp_field.fill.assert_called_once_with("654321")
    submit_btn.click.assert_called_once()


def test_otp_handler_headless_no_code_sets_cooldown(monkeypatch, budget_files):
    _, cooldown = budget_files
    scraper = _scraper_with_page()
    otp_field = MagicMock()
    otp_field.count.return_value = 1
    otp_field.first = otp_field
    scraper.page.locator.return_value = otp_field

    monkeypatch.setattr(gs, "pyotp", None)
    monkeypatch.setenv("GC_TOTP_SECRET", "")
    monkeypatch.setenv("SYNC_DAEMON_MODE", "1")
    monkeypatch.setattr(gs, "fetch_emailed_gc_code", lambda baseline, **kw: None)

    with pytest.raises(RuntimeError, match="2FA/OTP required"):
        scraper._handle_otp_if_needed()
    assert cooldown.exists()
