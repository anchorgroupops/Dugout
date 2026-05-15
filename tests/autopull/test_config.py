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
    for k in ("GMAIL_USERNAME", "GMAIL_APP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(config.ConfigError, match="GMAIL_USERNAME"):
        config.load(require_gmail=True)


def test_gmail_not_required_when_disabled(monkeypatch):
    """Kill-switch off must not require Gmail creds — inert runs need to load."""
    monkeypatch.setenv("GC_AUTOPULL_ENABLED", "false")
    for k in ("GMAIL_USERNAME", "GMAIL_APP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    cfg = config.load(require_gmail=True)
    assert cfg.enabled is False


def test_bool_parsing(monkeypatch):
    for truthy in ("true", "TRUE", "1", "yes", "on"):
        monkeypatch.setenv("GC_AUTOPULL_ENABLED", truthy)
        assert config.load().enabled is True
    for falsy in ("false", "FALSE", "0", "no", "off", ""):
        monkeypatch.setenv("GC_AUTOPULL_ENABLED", falsy)
        assert config.load().enabled is False


# ---------------------------------------------------------------------------
# _bool, _int, _float — low-level env parsers
# ---------------------------------------------------------------------------

class TestBool:
    def test_returns_default_when_not_set(self, monkeypatch):
        monkeypatch.delenv("TEST_BOOL_XYZ", raising=False)
        assert config._bool("TEST_BOOL_XYZ", default=False) is False
        assert config._bool("TEST_BOOL_XYZ", default=True) is True

    def test_true_string_values(self, monkeypatch):
        for val in ("true", "TRUE", "1", "yes", "on"):
            monkeypatch.setenv("TEST_BOOL_XYZ", val)
            assert config._bool("TEST_BOOL_XYZ") is True

    def test_false_string_values(self, monkeypatch):
        for val in ("false", "FALSE", "0", "no", "off"):
            monkeypatch.setenv("TEST_BOOL_XYZ", val)
            assert config._bool("TEST_BOOL_XYZ") is False

    def test_empty_string_is_falsy(self, monkeypatch):
        monkeypatch.setenv("TEST_BOOL_XYZ", "")
        assert config._bool("TEST_BOOL_XYZ") is False


class TestInt:
    def test_returns_default_when_not_set(self, monkeypatch):
        monkeypatch.delenv("TEST_INT_XYZ", raising=False)
        assert config._int("TEST_INT_XYZ", default=42) == 42

    def test_parses_integer_string(self, monkeypatch):
        monkeypatch.setenv("TEST_INT_XYZ", "7")
        assert config._int("TEST_INT_XYZ", default=0) == 7

    def test_parses_negative_integer(self, monkeypatch):
        monkeypatch.setenv("TEST_INT_XYZ", "-3")
        assert config._int("TEST_INT_XYZ", default=0) == -3

    def test_raises_on_non_integer(self, monkeypatch):
        monkeypatch.setenv("TEST_INT_XYZ", "abc")
        with pytest.raises(config.ConfigError):
            config._int("TEST_INT_XYZ", default=0)

    def test_empty_string_returns_default(self, monkeypatch):
        monkeypatch.setenv("TEST_INT_XYZ", "")
        assert config._int("TEST_INT_XYZ", default=99) == 99


class TestFloat:
    def test_returns_default_when_not_set(self, monkeypatch):
        monkeypatch.delenv("TEST_FLOAT_XYZ", raising=False)
        assert config._float("TEST_FLOAT_XYZ", default=1.5) == 1.5

    def test_parses_float_string(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT_XYZ", "3.14")
        assert abs(config._float("TEST_FLOAT_XYZ", default=0.0) - 3.14) < 1e-9

    def test_parses_integer_as_float(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT_XYZ", "5")
        assert config._float("TEST_FLOAT_XYZ", default=0.0) == 5.0

    def test_raises_on_non_float(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT_XYZ", "xyz")
        with pytest.raises(config.ConfigError):
            config._float("TEST_FLOAT_XYZ", default=0.0)

    def test_empty_string_returns_default(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT_XYZ", "")
        assert config._float("TEST_FLOAT_XYZ", default=2.5) == 2.5
