"""Tests for tools.autopull.config — env-driven configuration."""
from __future__ import annotations
import os
import pytest
from tools.autopull import config


def test_load_defaults_when_missing(monkeypatch):
    """Unset env vars should give safe defaults (all features disabled)."""
    for k in [
        "GC_AUTOPULL_ENABLED",
        "GC_AUTOPULL_POSTGAME_ENABLED",
        "GC_AUTOPULL_LLM_ADAPT",
    ]:
        monkeypatch.delenv(k, raising=False)
    cfg = config.load()
    assert cfg.enabled is False
    assert cfg.postgame_enabled is False
    assert cfg.llm_adapt_enabled is False
    assert cfg.idempotency_window_min == 15
    assert cfg.llm_daily_budget_usd == 1.00
    assert cfg.llm_model == "claude-sonnet-4-6"


def test_enabled_when_true(monkeypatch):
    monkeypatch.setenv("GC_AUTOPULL_ENABLED", "true")
    cfg = config.load()
    assert cfg.enabled is True


def test_parses_numeric_overrides(monkeypatch):
    monkeypatch.setenv("GC_AUTOPULL_IDEMPOTENCY_WINDOW_MIN", "30")
    monkeypatch.setenv("GC_AUTOPULL_LLM_DAILY_BUDGET_USD", "2.50")
    cfg = config.load()
    assert cfg.idempotency_window_min == 30
    assert cfg.llm_daily_budget_usd == 2.50


def test_gmail_credentials_required_when_enabled(monkeypatch):
    monkeypatch.setenv("GC_AUTOPULL_ENABLED", "true")
    for k in ("GMAIL_OAUTH_CLIENT_ID", "GMAIL_OAUTH_CLIENT_SECRET", "GMAIL_OAUTH_REFRESH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(config.ConfigError, match="GMAIL_OAUTH"):
        config.load(require_gmail=True)


def test_bool_parsing(monkeypatch):
    for truthy in ("true", "TRUE", "1", "yes", "on"):
        monkeypatch.setenv("GC_AUTOPULL_ENABLED", truthy)
        assert config.load().enabled is True
    for falsy in ("false", "FALSE", "0", "no", "off", ""):
        monkeypatch.setenv("GC_AUTOPULL_ENABLED", falsy)
        assert config.load().enabled is False
