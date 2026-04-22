"""Environment-driven configuration for the autopull subsystem."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or malformed."""


_TRUTHY = {"true", "1", "yes", "on"}


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ConfigError(f"{name} must be an integer, got: {raw!r}") from e


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as e:
        raise ConfigError(f"{name} must be a float, got: {raw!r}") from e


@dataclass(frozen=True)
class AutopullConfig:
    enabled: bool
    postgame_enabled: bool
    llm_adapt_enabled: bool
    idempotency_window_min: int
    llm_daily_budget_usd: float
    llm_model: str

    gmail_client_id: str
    gmail_client_secret: str
    gmail_refresh_token: str
    gmail_notify_from: str
    gmail_notify_to: str

    anthropic_api_key: str
    n8n_status_webhook: str
    n8n_weekly_webhook: str

    gc_team_id: str
    gc_season_slug: str

    data_root: Path
    log_root: Path


def load(require_gmail: bool = False) -> AutopullConfig:
    cfg = AutopullConfig(
        enabled=_bool("GC_AUTOPULL_ENABLED", False),
        postgame_enabled=_bool("GC_AUTOPULL_POSTGAME_ENABLED", False),
        llm_adapt_enabled=_bool("GC_AUTOPULL_LLM_ADAPT", False),
        idempotency_window_min=_int("GC_AUTOPULL_IDEMPOTENCY_WINDOW_MIN", 15),
        llm_daily_budget_usd=_float("GC_AUTOPULL_LLM_DAILY_BUDGET_USD", 1.00),
        llm_model=os.getenv("GC_AUTOPULL_LLM_MODEL", "claude-sonnet-4-6"),
        gmail_client_id=os.getenv("GMAIL_OAUTH_CLIENT_ID", ""),
        gmail_client_secret=os.getenv("GMAIL_OAUTH_CLIENT_SECRET", ""),
        gmail_refresh_token=os.getenv("GMAIL_OAUTH_REFRESH_TOKEN", ""),
        gmail_notify_from=os.getenv("GMAIL_NOTIFY_FROM", ""),
        gmail_notify_to=os.getenv("GMAIL_NOTIFY_TO", ""),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        n8n_status_webhook=os.getenv("N8N_AUTOPULL_STATUS_WEBHOOK", ""),
        n8n_weekly_webhook=os.getenv("N8N_AUTOPULL_WEEKLY_WEBHOOK", ""),
        gc_team_id=os.getenv("GC_TEAM_ID", ""),
        gc_season_slug=os.getenv("GC_SEASON_SLUG", ""),
        data_root=Path(os.getenv("DUGOUT_DATA_ROOT", "data")),
        log_root=Path(os.getenv("DUGOUT_LOG_ROOT", "logs")),
    )
    if require_gmail:
        for k, v in [
            ("GMAIL_OAUTH_CLIENT_ID", cfg.gmail_client_id),
            ("GMAIL_OAUTH_CLIENT_SECRET", cfg.gmail_client_secret),
            ("GMAIL_OAUTH_REFRESH_TOKEN", cfg.gmail_refresh_token),
        ]:
            if not v:
                raise ConfigError(f"{k} is required when Gmail is enabled")
    return cfg
