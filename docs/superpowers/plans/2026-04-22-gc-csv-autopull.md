# GC CSV Autopull Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Pi-hosted, self-healing, adaptive GC CSV autopull that replaces the manual gc.com "download CSV" click with automated runs triggered by `sync_daemon`'s postgame event and a daily safety-net cron.

**Architecture:** New `tools/autopull/` Python package composed of 7 single-purpose modules, wired into existing `sync_daemon.py` via a subprocess call on postgame state, and scheduled via systemd timers. A SQLite state DB backs strategy ranking, circuit breakers, and schema-drift detection. A Claude API fallback proposes new DOM locators when gc.com's layout changes; safety rails (budget cap, deny-list, download validation) keep it contained.

**Tech Stack:** Python 3.11, Playwright (existing), SQLite3 (stdlib), `google-api-python-client` (Gmail), `anthropic` SDK, pytest + pytest-cov, systemd.

**Spec reference:** `docs/superpowers/specs/2026-04-22-gc-csv-autopull-design.md`

---

## File Structure

**New files:**
- `tools/autopull/__init__.py` — package marker, exports CLI main.
- `tools/autopull/config.py` — env var loading + validation (single source of truth for config).
- `tools/autopull/state.py` — SQLite wrapper: runs, strategies, circuit breakers, schema profiles.
- `tools/autopull/csv_validator.py` — post-download CSV validation + quarantine.
- `tools/autopull/notifier.py` — fan-out to email, n8n, push.
- `tools/autopull/gmail_2fa_fetcher.py` — Gmail API helper to read verification codes.
- `tools/autopull/session_manager.py` — Playwright login + storage_state reuse + 2FA orchestration.
- `tools/autopull/locator_engine.py` — strategy registry, ranking, LLM-adaptive fallback.
- `tools/autopull/cli.py` — entry point; orchestrates a single run.
- `tools/autopull/weekly_report.py` — Sunday summary → n8n webhook.
- `deploy/systemd/gc-autopull.service` — daily safety-net service unit.
- `deploy/systemd/gc-autopull.timer` — daily timer (03:00 ET).
- `deploy/systemd/gc-autopull-weekly.service` — weekly report service.
- `deploy/systemd/gc-autopull-weekly.timer` — Sunday 06:00 ET.
- `tests/autopull/__init__.py`
- `tests/autopull/conftest.py` — shared fixtures (tmp DB, mocked Playwright, fake Gmail).
- `tests/autopull/test_config.py`
- `tests/autopull/test_state.py`
- `tests/autopull/test_csv_validator.py`
- `tests/autopull/test_notifier.py`
- `tests/autopull/test_gmail_2fa_fetcher.py`
- `tests/autopull/test_session_manager.py`
- `tests/autopull/test_locator_engine.py`
- `tests/autopull/test_cli.py`
- `tests/autopull/test_cli_integration.py`
- `tests/autopull/test_circuit_breaker_integration.py`
- `tests/autopull/fixtures/stats_page.html` — minimal stats page with export button for local integration test.
- `tests/autopull/fixtures/season_stats_sample.csv` — canonical CSV for validator tests.

**Modified files:**
- `tools/sync_daemon.py` — add subprocess spawn in the postgame transition, right after the existing `gc-alert` webhook fire.
- `.env.example` — add the 14 new env keys defined in the spec section 11.
- `requirements.txt` — add `google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib`, `anthropic`.
- `CLAUDE.md` — amend the "CSV-First" rule to permit browser automation for the CSV download click.
- `pytest.ini` — add `tests/autopull/` to `testpaths` (already globbed if `tests/` is the path, verify).

---

## Task 1: Scaffold package and shared test fixtures

**Files:**
- Create: `tools/autopull/__init__.py`
- Create: `tests/autopull/__init__.py`
- Create: `tests/autopull/conftest.py`

- [ ] **Step 1: Create empty package markers**

```bash
mkdir -p tools/autopull tests/autopull tests/autopull/fixtures
```

Write `tools/autopull/__init__.py`:

```python
"""GC CSV autopull package — self-healing, adaptive stat download from gc.com."""
```

Write `tests/autopull/__init__.py`:

```python
```

- [ ] **Step 2: Write shared conftest with tmp_db fixture**

Write `tests/autopull/conftest.py`:

```python
"""Shared fixtures for autopull tests."""
from __future__ import annotations
import sqlite3
from pathlib import Path
import pytest


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Returns a path for a fresh SQLite DB in a temp dir."""
    return tmp_path / "autopull_state.db"


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Returns a temp data dir with staging and quarantine subdirs."""
    d = tmp_path / "autopull"
    (d / "staging").mkdir(parents=True)
    (d / "quarantine").mkdir(parents=True)
    return d


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Write a small valid season stats CSV to disk, return the path."""
    p = tmp_path / "season_stats_sample.csv"
    p.write_text(
        "Player,AB,H,BB,K,HBP,RBI,BA,OBP,SLG\n"
        "Alice Smith,20,8,3,4,1,6,0.400,0.500,0.600\n"
        "Bob Jones,18,5,2,5,0,3,0.278,0.350,0.389\n",
        encoding="utf-8",
    )
    return p
```

- [ ] **Step 3: Verify pytest discovers the new package**

Run: `pytest tests/autopull/ --collect-only`
Expected: exit 0, output says "no tests ran" (no test files yet) — confirms collection works.

- [ ] **Step 4: Commit**

```bash
git add tools/autopull/ tests/autopull/
git commit -m "feat(autopull): scaffold package + shared test fixtures"
```

---

## Task 2: Configuration loader

**Files:**
- Create: `tools/autopull/config.py`
- Create: `tests/autopull/test_config.py`

- [ ] **Step 1: Write failing tests**

Write `tests/autopull/test_config.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/autopull/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError` on `from tools.autopull import config`.

- [ ] **Step 3: Implement the config module**

Write `tools/autopull/config.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/autopull/test_config.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/autopull/config.py tests/autopull/test_config.py
git commit -m "feat(autopull): env-driven configuration with validation"
```

---

## Task 3: State DB — schema and CRUD

**Files:**
- Create: `tools/autopull/state.py`
- Create: `tests/autopull/test_state.py`

- [ ] **Step 1: Write failing tests**

Write `tests/autopull/test_state.py`:

```python
"""Tests for tools.autopull.state — SQLite-backed runs, strategies, breakers."""
from __future__ import annotations
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from tools.autopull.state import StateDB, StrategyRow, RunRow

ET = ZoneInfo("America/New_York")


def test_creates_schema_idempotently(tmp_db_path):
    db = StateDB(tmp_db_path)
    db.init_schema()
    db.init_schema()  # second call is a no-op
    tables = db.list_tables()
    assert {"runs", "strategies", "circuit_breaker", "schema_profile"} <= set(tables)


def test_insert_and_fetch_run(tmp_db_path):
    db = StateDB(tmp_db_path)
    db.init_schema()
    run_id = db.start_run(trigger="cron", started_at=datetime.now(ET))
    db.complete_run(run_id, outcome="success", csv_path="/tmp/x.csv",
                    rows_ingested=25, winning_strategy_id=None,
                    duration_ms=1234, llm_fallback_invoked=False,
                    session_refreshed=False)
    runs = db.recent_runs(limit=5)
    assert len(runs) == 1
    assert runs[0].outcome == "success"
    assert runs[0].rows_ingested == 25


def test_last_successful_run_within(tmp_db_path):
    db = StateDB(tmp_db_path)
    db.init_schema()
    now = datetime.now(ET)
    rid = db.start_run(trigger="cron", started_at=now - timedelta(minutes=5))
    db.complete_run(rid, outcome="success", csv_path=None, rows_ingested=1,
                    winning_strategy_id=None, duration_ms=1,
                    llm_fallback_invoked=False, session_refreshed=False,
                    completed_at=now - timedelta(minutes=5))
    assert db.last_successful_run_within(minutes=15) is not None
    assert db.last_successful_run_within(minutes=1) is None


def test_strategy_seed_and_rank(tmp_db_path):
    db = StateDB(tmp_db_path)
    db.init_schema()
    sid_a = db.upsert_strategy(kind="locator", selector='{"role":"button","name":"export"}',
                               description="role=button name=/export/", source="builtin")
    sid_b = db.upsert_strategy(kind="css", selector="[data-testid='export']",
                               description="data-testid export", source="builtin")
    now = datetime.now(ET)
    db.record_strategy_result(sid_a, success=True, at=now - timedelta(days=1))
    db.record_strategy_result(sid_a, success=True, at=now)
    db.record_strategy_result(sid_b, success=False, at=now)
    ranked = db.ranked_strategies()
    assert ranked[0].id == sid_a, "A has 2 recent successes, should rank first"
    assert ranked[1].id == sid_b


def test_strategy_auto_disable(tmp_db_path):
    db = StateDB(tmp_db_path)
    db.init_schema()
    sid = db.upsert_strategy(kind="css", selector="dead.selector",
                             description="dead", source="builtin")
    db.record_strategy_result(sid, success=True,
                              at=datetime.now(ET) - timedelta(days=60))
    for _ in range(5):
        db.record_strategy_result(sid, success=False)
    db.auto_disable_stale_strategies()
    ranked = db.ranked_strategies()
    assert all(s.id != sid for s in ranked), "stale strategy should be disabled"


def test_circuit_breaker_open_and_reset(tmp_db_path):
    db = StateDB(tmp_db_path)
    db.init_schema()
    assert db.breaker_open("auth") is False
    for _ in range(3):
        db.breaker_record_failure("auth", open_duration_hours=24)
    assert db.breaker_open("auth") is True
    db.breaker_reset("auth")
    assert db.breaker_open("auth") is False


def test_schema_profile_drift(tmp_db_path):
    db = StateDB(tmp_db_path)
    db.init_schema()
    db.record_schema(["AB", "H", "BB", "K"], row_count=20)
    db.record_schema(["AB", "H", "BB", "K", "HBP"], row_count=22)
    latest, prior = db.last_two_schemas()
    assert latest is not None and prior is not None
    overlap = db.schema_overlap(latest, prior)
    assert 0.80 <= overlap < 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/autopull/test_state.py -v`
Expected: FAIL with import error.

- [ ] **Step 3: Implement the state module**

Write `tools/autopull/state.py`:

```python
"""SQLite-backed state for autopull: runs, strategies, breakers, schema profiles."""
from __future__ import annotations
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  trigger TEXT NOT NULL,
  outcome TEXT NOT NULL DEFAULT 'in_progress',
  csv_path TEXT,
  rows_ingested INTEGER,
  winning_strategy_id INTEGER,
  failure_reason TEXT,
  duration_ms INTEGER,
  llm_fallback_invoked INTEGER DEFAULT 0,
  session_refreshed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS strategies (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  selector TEXT NOT NULL,
  description TEXT,
  created_at TEXT NOT NULL,
  last_success_at TEXT,
  success_count INTEGER DEFAULT 0,
  failure_count INTEGER DEFAULT 0,
  source TEXT NOT NULL,
  enabled INTEGER DEFAULT 1,
  UNIQUE(kind, selector)
);

CREATE TABLE IF NOT EXISTS circuit_breaker (
  key TEXT PRIMARY KEY,
  consecutive_failures INTEGER DEFAULT 0,
  opened_at TEXT,
  reset_at TEXT
);

CREATE TABLE IF NOT EXISTS schema_profile (
  observed_at TEXT PRIMARY KEY,
  column_names_json TEXT NOT NULL,
  row_count INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at);
CREATE INDEX IF NOT EXISTS idx_strategies_enabled ON strategies(enabled);
"""


@dataclass
class RunRow:
    id: int
    started_at: str
    completed_at: str | None
    trigger: str
    outcome: str
    csv_path: str | None
    rows_ingested: int | None
    winning_strategy_id: int | None
    failure_reason: str | None
    duration_ms: int | None
    llm_fallback_invoked: int
    session_refreshed: int


@dataclass
class StrategyRow:
    id: int
    kind: str
    selector: str
    description: str | None
    created_at: str
    last_success_at: str | None
    success_count: int
    failure_count: int
    source: str
    enabled: int


class StateDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.path), isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    def init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA_SQL)

    def list_tables(self) -> list[str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            return [r["name"] for r in rows]

    # ---------- runs ----------

    def start_run(self, trigger: str, started_at: datetime | None = None) -> int:
        started = (started_at or datetime.now(ET)).isoformat()
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO runs(started_at, trigger, outcome) VALUES(?,?,?)",
                (started, trigger, "in_progress"),
            )
            return int(cur.lastrowid)

    def complete_run(
        self,
        run_id: int,
        *,
        outcome: str,
        csv_path: str | None,
        rows_ingested: int | None,
        winning_strategy_id: int | None,
        duration_ms: int | None,
        llm_fallback_invoked: bool,
        session_refreshed: bool,
        failure_reason: str | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        done = (completed_at or datetime.now(ET)).isoformat()
        with self._conn() as c:
            c.execute(
                """
                UPDATE runs SET completed_at=?, outcome=?, csv_path=?, rows_ingested=?,
                  winning_strategy_id=?, failure_reason=?, duration_ms=?,
                  llm_fallback_invoked=?, session_refreshed=?
                WHERE id=?
                """,
                (done, outcome, csv_path, rows_ingested, winning_strategy_id,
                 failure_reason, duration_ms, int(llm_fallback_invoked),
                 int(session_refreshed), run_id),
            )

    def recent_runs(self, limit: int = 20) -> list[RunRow]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [RunRow(**dict(r)) for r in rows]

    def last_successful_run_within(self, minutes: int) -> RunRow | None:
        cutoff = (datetime.now(ET) - timedelta(minutes=minutes)).isoformat()
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM runs WHERE outcome='success' AND completed_at >= ? "
                "ORDER BY completed_at DESC LIMIT 1",
                (cutoff,),
            ).fetchone()
            return RunRow(**dict(r)) if r else None

    # ---------- strategies ----------

    def upsert_strategy(self, *, kind: str, selector: str,
                        description: str | None, source: str) -> int:
        now = datetime.now(ET).isoformat()
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO strategies(kind, selector, description, created_at, source)
                VALUES(?,?,?,?,?)
                ON CONFLICT(kind, selector) DO NOTHING
                """,
                (kind, selector, description, now, source),
            )
            row = c.execute(
                "SELECT id FROM strategies WHERE kind=? AND selector=?",
                (kind, selector),
            ).fetchone()
            return int(row["id"])

    def record_strategy_result(self, strategy_id: int, *, success: bool,
                               at: datetime | None = None) -> None:
        when = (at or datetime.now(ET)).isoformat()
        with self._conn() as c:
            if success:
                c.execute(
                    "UPDATE strategies SET success_count=success_count+1, "
                    "last_success_at=? WHERE id=?",
                    (when, strategy_id),
                )
            else:
                c.execute(
                    "UPDATE strategies SET failure_count=failure_count+1 WHERE id=?",
                    (strategy_id,),
                )

    def ranked_strategies(self) -> list[StrategyRow]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM strategies WHERE enabled=1"
            ).fetchall()
        out = [StrategyRow(**dict(r)) for r in rows]
        now = datetime.now(ET)

        def score(s: StrategyRow) -> float:
            if s.last_success_at:
                last = datetime.fromisoformat(s.last_success_at)
                days = max(0.0, (now - last).total_seconds() / 86400)
            else:
                days = 999.0
            return s.success_count * math.exp(-days / 14) - 0.5 * s.failure_count

        return sorted(out, key=score, reverse=True)

    def auto_disable_stale_strategies(self) -> int:
        cutoff = (datetime.now(ET) - timedelta(days=30)).isoformat()
        with self._conn() as c:
            cur = c.execute(
                """
                UPDATE strategies SET enabled=0
                WHERE failure_count > 3 * success_count
                  AND (last_success_at IS NULL OR last_success_at < ?)
                """,
                (cutoff,),
            )
            return cur.rowcount

    # ---------- breakers ----------

    def breaker_record_failure(self, key: str, *, open_duration_hours: int = 24,
                               threshold: int = 3) -> None:
        now = datetime.now(ET)
        with self._conn() as c:
            row = c.execute(
                "SELECT consecutive_failures FROM circuit_breaker WHERE key=?",
                (key,),
            ).fetchone()
            if row is None:
                c.execute(
                    "INSERT INTO circuit_breaker(key, consecutive_failures) VALUES(?, 1)",
                    (key,),
                )
                return
            new_count = int(row["consecutive_failures"]) + 1
            if new_count >= threshold:
                reset = (now + timedelta(hours=open_duration_hours)).isoformat()
                c.execute(
                    "UPDATE circuit_breaker SET consecutive_failures=?, opened_at=?, "
                    "reset_at=? WHERE key=?",
                    (new_count, now.isoformat(), reset, key),
                )
            else:
                c.execute(
                    "UPDATE circuit_breaker SET consecutive_failures=? WHERE key=?",
                    (new_count, key),
                )

    def breaker_reset(self, key: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE circuit_breaker SET consecutive_failures=0, opened_at=NULL, "
                "reset_at=NULL WHERE key=?",
                (key,),
            )

    def breaker_open(self, key: str) -> bool:
        with self._conn() as c:
            row = c.execute(
                "SELECT opened_at, reset_at FROM circuit_breaker WHERE key=?",
                (key,),
            ).fetchone()
        if not row or not row["opened_at"]:
            return False
        reset_at = row["reset_at"]
        if reset_at and datetime.fromisoformat(reset_at) < datetime.now(ET):
            self.breaker_reset(key)
            return False
        return True

    # ---------- schema ----------

    def record_schema(self, columns: Iterable[str], row_count: int) -> None:
        cols = sorted(columns)
        now = datetime.now(ET).isoformat()
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO schema_profile(observed_at, column_names_json, row_count) "
                "VALUES(?,?,?)",
                (now, json.dumps(cols), row_count),
            )

    def last_two_schemas(self) -> tuple[list[str] | None, list[str] | None]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT column_names_json FROM schema_profile "
                "ORDER BY observed_at DESC LIMIT 2"
            ).fetchall()
        if not rows:
            return None, None
        latest = json.loads(rows[0]["column_names_json"])
        prior = json.loads(rows[1]["column_names_json"]) if len(rows) > 1 else None
        return latest, prior

    @staticmethod
    def schema_overlap(a: list[str], b: list[str]) -> float:
        sa, sb = set(a), set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / max(len(sa), len(sb))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/autopull/test_state.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/autopull/state.py tests/autopull/test_state.py
git commit -m "feat(autopull): SQLite state — runs, strategies, breakers, schema profile"
```

---

## Task 4: CSV validator + quarantine

**Files:**
- Create: `tools/autopull/csv_validator.py`
- Create: `tests/autopull/test_csv_validator.py`
- Create: `tests/autopull/fixtures/season_stats_sample.csv`

- [ ] **Step 1: Write the canonical sample CSV fixture**

Write `tests/autopull/fixtures/season_stats_sample.csv`:

```
Player,AB,H,BB,K,HBP,RBI,BA,OBP,SLG
Alice Smith,20,8,3,4,1,6,0.400,0.500,0.600
Bob Jones,18,5,2,5,0,3,0.278,0.350,0.389
```

- [ ] **Step 2: Write failing tests**

Write `tests/autopull/test_csv_validator.py`:

```python
"""Tests for tools.autopull.csv_validator."""
from __future__ import annotations
from pathlib import Path
import pytest
from tools.autopull import csv_validator as cv


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_accepts_valid_csv(tmp_path, sample_csv):
    result = cv.validate(sample_csv, known_columns=["Player", "AB", "H", "BB", "K"])
    assert result.accepted is True
    assert result.row_count == 2
    assert set(result.columns) >= {"Player", "AB"}


def test_rejects_non_csv_extension(tmp_path):
    p = _write(tmp_path / "not.txt", "Player,AB\nx,1\n")
    result = cv.validate(p, known_columns=None)
    assert result.accepted is False
    assert "extension" in result.reason.lower()


def test_rejects_empty_file(tmp_path):
    p = _write(tmp_path / "empty.csv", "")
    result = cv.validate(p, known_columns=None)
    assert result.accepted is False
    assert "empty" in result.reason.lower()


def test_rejects_header_only(tmp_path):
    p = _write(tmp_path / "no_rows.csv", "Player,AB\n")
    result = cv.validate(p, known_columns=None)
    assert result.accepted is False
    assert "no data rows" in result.reason.lower()


def test_schema_overlap_below_threshold_critical(tmp_path):
    p = _write(tmp_path / "drifted.csv",
               "Name,Foo,Bar\nA,1,2\nB,3,4\n")
    result = cv.validate(p, known_columns=["Player", "AB", "H", "BB", "K"])
    assert result.accepted is False
    assert result.drift_severity == "critical"


def test_schema_overlap_advisory(tmp_path):
    # 4 of 5 known columns present → 80% overlap
    p = _write(tmp_path / "advisory.csv",
               "Player,AB,H,BB,NEW\nx,1,2,3,4\n")
    result = cv.validate(p, known_columns=["Player", "AB", "H", "BB", "K"])
    assert result.accepted is True
    assert result.drift_severity == "advisory"


def test_quarantine_moves_file(tmp_path, tmp_data_dir):
    p = _write(tmp_path / "bad.csv", "")
    result = cv.validate(p, known_columns=None)
    moved = cv.quarantine(p, result, quarantine_root=tmp_data_dir / "quarantine")
    assert moved.exists()
    assert not p.exists()
    assert "bad.csv" in moved.name
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/autopull/test_csv_validator.py -v`
Expected: FAIL — module missing.

- [ ] **Step 4: Implement the validator**

Write `tools/autopull/csv_validator.py`:

```python
"""Post-download CSV validation and quarantine.

A "valid" CSV:
  - has .csv extension
  - parses without error
  - has at least one data row
  - shares ≥ 80% column-name overlap with the last known schema (if provided)
"""
from __future__ import annotations
import csv
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

ADVISORY_THRESHOLD = 0.80  # ≥80% but <95%
HEALTHY_THRESHOLD = 0.95


@dataclass
class ValidationResult:
    accepted: bool
    reason: str = ""
    columns: list[str] = field(default_factory=list)
    row_count: int = 0
    drift_severity: str = "none"  # 'none', 'advisory', 'critical'


def validate(path: Path, known_columns: list[str] | None) -> ValidationResult:
    if path.suffix.lower() != ".csv":
        return ValidationResult(accepted=False, reason=f"Not a .csv extension: {path.suffix}")

    if not path.exists() or path.stat().st_size == 0:
        return ValidationResult(accepted=False, reason="File is empty")

    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                return ValidationResult(accepted=False, reason="File is empty (no header)")
            rows = list(reader)
    except UnicodeDecodeError as e:
        return ValidationResult(accepted=False, reason=f"UTF-8 decode failed: {e}")
    except csv.Error as e:
        return ValidationResult(accepted=False, reason=f"CSV parse error: {e}")

    columns = [c.strip() for c in header if c.strip()]
    if not columns:
        return ValidationResult(accepted=False, reason="No columns in header")

    if not rows:
        return ValidationResult(
            accepted=False, reason="No data rows", columns=columns, row_count=0
        )

    result = ValidationResult(
        accepted=True, columns=columns, row_count=len(rows), drift_severity="none"
    )

    if known_columns:
        overlap = _overlap(columns, known_columns)
        if overlap < ADVISORY_THRESHOLD:
            result.accepted = False
            result.reason = (
                f"Schema drift critical: {overlap:.0%} column overlap "
                f"(expected ≥ {ADVISORY_THRESHOLD:.0%})"
            )
            result.drift_severity = "critical"
        elif overlap < HEALTHY_THRESHOLD:
            result.drift_severity = "advisory"

    return result


def quarantine(path: Path, result: ValidationResult, *,
               quarantine_root: Path) -> Path:
    ts = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
    dest_dir = quarantine_root / ts
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    shutil.move(str(path), str(dest))
    (dest_dir / "reason.txt").write_text(
        f"reason: {result.reason}\ndrift: {result.drift_severity}\n",
        encoding="utf-8",
    )
    return dest


def _overlap(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(len(sa), len(sb))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/autopull/test_csv_validator.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add tools/autopull/csv_validator.py tests/autopull/test_csv_validator.py tests/autopull/fixtures/season_stats_sample.csv
git commit -m "feat(autopull): CSV validator with schema-drift detection + quarantine"
```

---

## Task 5: Notifier (email + n8n + push fan-out)

**Files:**
- Create: `tools/autopull/notifier.py`
- Create: `tests/autopull/test_notifier.py`

- [ ] **Step 1: Write failing tests**

Write `tests/autopull/test_notifier.py`:

```python
"""Tests for tools.autopull.notifier — 3-channel fan-out."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
from tools.autopull import notifier as n


def _summary(outcome="success", failure_reason=None, drift="none"):
    return n.RunSummary(
        run_id=42,
        trigger="cron",
        outcome=outcome,
        failure_reason=failure_reason,
        csv_path="/tmp/x.csv" if outcome == "success" else None,
        rows_ingested=100 if outcome == "success" else None,
        duration_ms=2500,
        drift_severity=drift,
    )


def test_success_silent_on_email_and_push(monkeypatch):
    gmail = MagicMock()
    n8n = MagicMock()
    push = MagicMock()
    notifier = n.Notifier(gmail_sender=gmail, n8n_poster=n8n, pusher=push)

    notifier.emit(_summary(outcome="success"))

    gmail.send.assert_not_called()
    push.notify.assert_not_called()
    n8n.post.assert_called_once()  # n8n always receives


def test_failure_fires_all_three(monkeypatch):
    gmail = MagicMock()
    n8n = MagicMock()
    push = MagicMock()
    notifier = n.Notifier(gmail_sender=gmail, n8n_poster=n8n, pusher=push)

    notifier.emit(_summary(outcome="failure", failure_reason="auth expired"))

    gmail.send.assert_called_once()
    n8n.post.assert_called_once()
    push.notify.assert_called_once()


def test_critical_drift_fires_push_even_on_success(monkeypatch):
    gmail = MagicMock()
    n8n = MagicMock()
    push = MagicMock()
    notifier = n.Notifier(gmail_sender=gmail, n8n_poster=n8n, pusher=push)

    notifier.emit(_summary(outcome="quarantined", drift="critical",
                           failure_reason="schema drift critical"))

    push.notify.assert_called_once()
    assert "drift" in push.notify.call_args[0][0].lower()


def test_advisory_drift_on_success_silent_push_but_emails(monkeypatch):
    gmail = MagicMock()
    n8n = MagicMock()
    push = MagicMock()
    notifier = n.Notifier(gmail_sender=gmail, n8n_poster=n8n, pusher=push)

    notifier.emit(_summary(outcome="success", drift="advisory"))

    gmail.send.assert_called_once()   # advisory gets email
    push.notify.assert_not_called()   # but no push noise


def test_n8n_failure_does_not_break_other_channels(monkeypatch, caplog):
    gmail = MagicMock()
    n8n = MagicMock(); n8n.post.side_effect = RuntimeError("network")
    push = MagicMock()
    notifier = n.Notifier(gmail_sender=gmail, n8n_poster=n8n, pusher=push)
    notifier.emit(_summary(outcome="failure", failure_reason="x"))
    gmail.send.assert_called_once()
    push.notify.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/autopull/test_notifier.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the notifier**

Write `tools/autopull/notifier.py`:

```python
"""Fan-out notifications to email, n8n webhook, and PushNotification."""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, asdict
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass
class RunSummary:
    run_id: int
    trigger: str
    outcome: str                    # 'success' | 'failure' | 'quarantined'
    failure_reason: str | None
    csv_path: str | None
    rows_ingested: int | None
    duration_ms: int | None
    drift_severity: str = "none"   # 'none' | 'advisory' | 'critical'


class GmailSender(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> None: ...


class N8nPoster(Protocol):
    def post(self, url: str, payload: dict) -> None: ...


class Pusher(Protocol):
    def notify(self, message: str) -> None: ...


class Notifier:
    def __init__(self, *, gmail_sender: GmailSender, n8n_poster: N8nPoster,
                 pusher: Pusher, status_webhook_url: str = "",
                 notify_to_email: str = ""):
        self._gmail = gmail_sender
        self._n8n = n8n_poster
        self._push = pusher
        self._status_url = status_webhook_url
        self._to = notify_to_email

    def emit(self, s: RunSummary) -> None:
        self._safe("n8n", lambda: self._post_n8n(s))
        is_failure = s.outcome in ("failure", "quarantined")
        is_advisory = s.drift_severity == "advisory"
        is_critical = s.drift_severity == "critical"
        if is_failure or is_advisory or is_critical:
            self._safe("email", lambda: self._send_email(s))
        if is_failure or is_critical:
            self._safe("push", lambda: self._push_alert(s))

    def _post_n8n(self, s: RunSummary) -> None:
        if not self._status_url:
            return
        self._n8n.post(self._status_url, asdict(s))

    def _send_email(self, s: RunSummary) -> None:
        if not self._to:
            return
        subject = f"[Dugout Autopull] {s.outcome.upper()} run #{s.run_id}"
        body_lines = [
            f"Run ID: {s.run_id}",
            f"Trigger: {s.trigger}",
            f"Outcome: {s.outcome}",
            f"Drift: {s.drift_severity}",
        ]
        if s.failure_reason:
            body_lines.append(f"Failure: {s.failure_reason}")
        if s.rows_ingested is not None:
            body_lines.append(f"Rows ingested: {s.rows_ingested}")
        if s.csv_path:
            body_lines.append(f"CSV: {s.csv_path}")
        if s.duration_ms is not None:
            body_lines.append(f"Duration: {s.duration_ms} ms")
        self._gmail.send(to=self._to, subject=subject,
                         body="\n".join(body_lines))

    def _push_alert(self, s: RunSummary) -> None:
        msg = self._short_message(s)
        self._push.notify(msg)

    @staticmethod
    def _short_message(s: RunSummary) -> str:
        if s.drift_severity == "critical":
            return f"GC schema drift CRITICAL (run #{s.run_id})"
        if s.outcome == "failure":
            return f"GC autopull failed: {s.failure_reason or 'unknown'} (#{s.run_id})"
        if s.outcome == "quarantined":
            return f"GC autopull quarantined: {s.failure_reason or 'bad CSV'} (#{s.run_id})"
        return f"GC autopull: {s.outcome} (#{s.run_id})"

    @staticmethod
    def _safe(channel: str, fn) -> None:
        try:
            fn()
        except Exception as e:
            log.exception("notifier channel %s failed: %s", channel, e)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/autopull/test_notifier.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/autopull/notifier.py tests/autopull/test_notifier.py
git commit -m "feat(autopull): 3-channel notifier (email/n8n/push) with per-outcome policy"
```

---

## Task 6: Gmail 2FA fetcher

**Files:**
- Create: `tools/autopull/gmail_2fa_fetcher.py`
- Create: `tests/autopull/test_gmail_2fa_fetcher.py`

- [ ] **Step 1: Write failing tests**

Write `tests/autopull/test_gmail_2fa_fetcher.py`:

```python
"""Tests for Gmail 2FA fetcher — pure logic, Gmail API mocked."""
from __future__ import annotations
import base64
from unittest.mock import MagicMock
import pytest
from tools.autopull import gmail_2fa_fetcher as g


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode()


def _message(body: str, message_id: str = "abc"):
    return {
        "id": message_id,
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": _b64(body)},
        },
    }


def test_extracts_six_digit_code():
    body = "Your GameChanger verification code is 482913. It expires in 10 minutes."
    assert g.extract_code(body) == "482913"


def test_ignores_other_numbers():
    body = "Confirm your account. Code: 123456. Order #9999 placed 04/22."
    assert g.extract_code(body) == "123456"


def test_returns_none_when_no_code():
    assert g.extract_code("Hi there, welcome to GameChanger.") is None


def test_fetch_latest_uses_gc_query():
    client = MagicMock()
    client.users().messages().list().execute.return_value = {
        "messages": [{"id": "m1"}]
    }
    client.users().messages().get().execute.return_value = _message(
        "Your verification code is 654321."
    )
    code, msg_id = g.fetch_latest_code(client, lookback_minutes=5)
    assert code == "654321"
    assert msg_id == "m1"
    # Query must target GC sender and recent window
    list_call = client.users().messages().list.call_args
    assert "from:no-reply@gc.com" in list_call.kwargs["q"]


def test_fetch_latest_returns_none_when_no_messages():
    client = MagicMock()
    client.users().messages().list().execute.return_value = {"messages": []}
    code, msg_id = g.fetch_latest_code(client, lookback_minutes=5)
    assert code is None
    assert msg_id is None


def test_mark_read_removes_unread_label():
    client = MagicMock()
    g.mark_read(client, "m1")
    client.users().messages().modify.assert_called_once()
    kwargs = client.users().messages().modify.call_args.kwargs
    assert kwargs["body"] == {"removeLabelIds": ["UNREAD"]}


def test_send_email_formats_message():
    client = MagicMock()
    g.send_email(client, sender="me@x.com", to="you@x.com",
                 subject="Hello", body="Body text")
    client.users().messages().send.assert_called_once()
    kwargs = client.users().messages().send.call_args.kwargs
    assert "raw" in kwargs["body"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/autopull/test_gmail_2fa_fetcher.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the fetcher**

Write `tools/autopull/gmail_2fa_fetcher.py`:

```python
"""Headless Gmail helper to read GameChanger 2FA verification codes.

Uses a Gmail OAuth refresh token (not the claude.ai MCP) so the Pi can run
unattended. Only reads from no-reply@gc.com and only within a short window.
"""
from __future__ import annotations
import base64
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

CODE_RE = re.compile(r"\b(\d{6})\b")
GC_SENDER = "no-reply@gc.com"


def build_client(*, client_id: str, client_secret: str, refresh_token: str) -> Any:
    """Build a Gmail API client from OAuth credentials.

    Separated so tests can mock by passing their own client object.
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/gmail.modify"],
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def fetch_latest_code(client: Any, *, lookback_minutes: int = 5) -> tuple[str | None, str | None]:
    """Return (code, message_id) for the latest GC 2FA email, or (None, None)."""
    q = f"from:{GC_SENDER} newer_than:{lookback_minutes}m"
    resp = client.users().messages().list(userId="me", q=q, maxResults=5).execute()
    messages = resp.get("messages", []) or []
    for m in messages:
        mid = m["id"]
        msg = client.users().messages().get(
            userId="me", id=mid, format="full"
        ).execute()
        body = _extract_text(msg.get("payload", {}))
        code = extract_code(body)
        if code:
            return code, mid
    return None, None


def extract_code(body: str) -> str | None:
    for m in CODE_RE.finditer(body):
        return m.group(1)
    return None


def mark_read(client: Any, message_id: str) -> None:
    client.users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()


def send_email(client: Any, *, sender: str, to: str, subject: str, body: str) -> None:
    """Send a plain-text email via the same Gmail client used for 2FA reads."""
    import base64
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    client.users().messages().send(userId="me", body={"raw": raw}).execute()


def _extract_text(payload: dict) -> str:
    """Walk a Gmail message payload and concatenate text/plain bodies."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
    parts = payload.get("parts") or []
    return "\n".join(_extract_text(p) for p in parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/autopull/test_gmail_2fa_fetcher.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/autopull/gmail_2fa_fetcher.py tests/autopull/test_gmail_2fa_fetcher.py
git commit -m "feat(autopull): Gmail 2FA code fetcher (OAuth refresh-token based)"
```

---

## Task 7: Session manager — login + storage_state + 2FA orchestration

**Files:**
- Create: `tools/autopull/session_manager.py`
- Create: `tests/autopull/test_session_manager.py`

- [ ] **Step 1: Write failing tests**

Write `tests/autopull/test_session_manager.py`:

```python
"""Tests for tools.autopull.session_manager — pure-logic tests, Playwright mocked."""
from __future__ import annotations
from unittest.mock import MagicMock
import pytest
from tools.autopull import session_manager as sm


class FakePage:
    def __init__(self, url="https://web.gc.com/teams/X/season/stats"):
        self.url = url
        self._locator_results: dict[str, MagicMock] = {}
        self.goto = MagicMock()
        self.wait_for_load_state = MagicMock()
        self.fill = MagicMock()
        self.click = MagicMock()

    def locator(self, sel: str):
        return self._locator_results.setdefault(sel, MagicMock())


def test_is_login_page_by_url():
    p = FakePage(url="https://web.gc.com/login")
    assert sm.is_login_page(p) is True


def test_is_login_page_by_form_presence():
    p = FakePage(url="https://web.gc.com/teams/X")
    p._locator_results["input[type='password']"] = MagicMock()
    p._locator_results["input[type='password']"].count.return_value = 1
    assert sm.is_login_page(p) is True


def test_is_2fa_page_by_code_input():
    p = FakePage(url="https://web.gc.com/verify")
    p._locator_results["input[name='code']"] = MagicMock()
    p._locator_results["input[name='code']"].count.return_value = 1
    assert sm.is_2fa_page(p) is True


def test_submit_2fa_code_fills_and_submits():
    p = FakePage()
    code_input = MagicMock()
    submit_btn = MagicMock()
    p._locator_results["input[name='code']"] = code_input
    p._locator_results["button[type='submit']"] = submit_btn
    sm.submit_2fa_code(p, "482913")
    code_input.fill.assert_called_once_with("482913")
    submit_btn.click.assert_called_once()


def test_polls_gmail_until_code_arrives():
    fetcher = MagicMock()
    # First poll: no code. Second: code.
    fetcher.side_effect = [(None, None), ("482913", "msg1")]
    code, mid = sm.wait_for_2fa_code(fetcher, max_attempts=3, sleep_seconds=0)
    assert code == "482913"
    assert mid == "msg1"
    assert fetcher.call_count == 2


def test_wait_for_2fa_code_gives_up():
    fetcher = MagicMock(return_value=(None, None))
    with pytest.raises(sm.TwoFactorTimeout):
        sm.wait_for_2fa_code(fetcher, max_attempts=2, sleep_seconds=0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/autopull/test_session_manager.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the session manager**

Write `tools/autopull/session_manager.py`:

```python
"""Playwright session lifecycle: login, storage_state reuse, 2FA via Gmail."""
from __future__ import annotations
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

GC_LOGIN_URL = "https://web.gc.com/login"
GC_BASE = "https://web.gc.com"


class TwoFactorTimeout(RuntimeError):
    """Raised when no 2FA code arrives within the poll window."""


class SessionError(RuntimeError):
    """Raised when login cannot be completed."""


def is_login_page(page: Any) -> bool:
    if "/login" in (page.url or ""):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def is_2fa_page(page: Any) -> bool:
    for sel in ("input[name='code']", "input[autocomplete='one-time-code']",
                "input[inputmode='numeric']"):
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


def submit_2fa_code(page: Any, code: str) -> None:
    for sel in ("input[name='code']", "input[autocomplete='one-time-code']"):
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.fill(code)
                break
        except Exception:
            continue
    for sel in ("button[type='submit']", "button:has-text('Verify')",
                "button:has-text('Submit')"):
        try:
            btn = page.locator(sel)
            if btn.count() > 0:
                btn.click()
                return
        except Exception:
            continue
    raise SessionError("No submit button found on 2FA page")


def wait_for_2fa_code(
    fetcher: Callable[[], tuple[str | None, str | None]],
    *,
    max_attempts: int = 12,
    sleep_seconds: int = 10,
) -> tuple[str, str]:
    for attempt in range(max_attempts):
        code, mid = fetcher()
        if code:
            return code, mid
        if attempt < max_attempts - 1:
            time.sleep(sleep_seconds)
    raise TwoFactorTimeout(f"No 2FA code after {max_attempts} polls")


class SessionManager:
    """High-level orchestrator: returns a logged-in Playwright page.

    Construction is kept light so callers can inject mocks for testing.
    """

    def __init__(
        self,
        *,
        auth_file: Path,
        email: str,
        password: str,
        gmail_fetcher: Callable[[], tuple[str | None, str | None]],
        login_url: str = GC_LOGIN_URL,
    ):
        self.auth_file = Path(auth_file)
        self.email = email
        self.password = password
        self.gmail_fetcher = gmail_fetcher
        self.login_url = login_url

    def new_logged_in_page(self, playwright_ctx: Any,
                           *, headless: bool = True) -> tuple[Any, bool]:
        """Returns (page, session_was_refreshed).

        Tries reusing stored cookies. On detected login/2FA, does the dance
        and persists a fresh storage_state.
        """
        browser = playwright_ctx.chromium.launch(headless=headless)
        if self.auth_file.exists():
            context = browser.new_context(storage_state=str(self.auth_file))
        else:
            context = browser.new_context()
        page = context.new_page()

        page.goto(self.login_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_load_state("networkidle", timeout=30_000)

        refreshed = False
        if is_login_page(page):
            self._submit_credentials(page)
            refreshed = True
            page.wait_for_load_state("networkidle", timeout=30_000)

        if is_2fa_page(page):
            code, mid = wait_for_2fa_code(self.gmail_fetcher)
            submit_2fa_code(page, code)
            refreshed = True
            page.wait_for_load_state("networkidle", timeout=30_000)

        if is_login_page(page) or is_2fa_page(page):
            raise SessionError("Still on login/2FA page after credential + code submission")

        if refreshed:
            self.auth_file.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(self.auth_file))
        return page, refreshed

    def _submit_credentials(self, page: Any) -> None:
        for sel in ("input[type='email']", "input[name='email']",
                    "input[autocomplete='username']"):
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.fill(self.email)
                break
        else:
            raise SessionError("Email input not found on login page")
        for sel in ("input[type='password']", "input[name='password']"):
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.fill(self.password)
                break
        else:
            raise SessionError("Password input not found on login page")
        for sel in ("button[type='submit']", "button:has-text('Log in')",
                    "button:has-text('Sign in')"):
            btn = page.locator(sel)
            if btn.count() > 0:
                btn.click()
                return
        raise SessionError("Submit button not found on login page")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/autopull/test_session_manager.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/autopull/session_manager.py tests/autopull/test_session_manager.py
git commit -m "feat(autopull): session manager — storage_state reuse + auto-2FA"
```

---

## Task 8: Locator engine — strategies, ranking, safety rails

**Files:**
- Create: `tools/autopull/locator_engine.py`
- Create: `tests/autopull/test_locator_engine.py`

- [ ] **Step 1: Write failing tests**

Write `tests/autopull/test_locator_engine.py`:

```python
"""Tests for tools.autopull.locator_engine.

LLM fallback is injected as a callable so we can mock easily.
Playwright is simulated via a small FakePage.
"""
from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock
import json
import pytest
from tools.autopull import locator_engine as le
from tools.autopull.state import StateDB


class FakeLocator:
    def __init__(self, matches: int = 1, visible: bool = True):
        self._matches = matches
        self._visible = visible
        self.click = MagicMock()

    def count(self):
        return self._matches

    def is_visible(self):
        return self._visible

    @property
    def first(self):
        return self


class FakeDownload:
    def __init__(self, suggested_filename="season_stats.csv"):
        self.suggested_filename = suggested_filename
        self.save_as = MagicMock()


class FakeDownloadExpect:
    def __init__(self, download):
        self.value = download

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakePage:
    def __init__(self, *, found_selectors: set[str] | None = None,
                 download: FakeDownload | None = None,
                 html: str = "<html></html>"):
        self._found = found_selectors or set()
        self._download = download
        self._html = html
        self._wait = MagicMock()

    def locator(self, sel: str):
        return FakeLocator(matches=1 if sel in self._found else 0)

    def expect_download(self, timeout=30000):
        if self._download is None:
            raise TimeoutError("no download")
        return FakeDownloadExpect(self._download)

    def content(self):
        return self._html

    def screenshot(self, path=None, full_page=True):
        pass

    def wait_for_timeout(self, ms):
        pass


def test_seeded_builtins_are_registered(tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    le.seed_builtin_strategies(db)
    ranked = db.ranked_strategies()
    assert len(ranked) >= 4  # we seed at least 4


def test_first_working_strategy_wins(tmp_db_path, tmp_path):
    db = StateDB(tmp_db_path); db.init_schema()
    le.seed_builtin_strategies(db)
    page = FakePage(
        found_selectors={"[data-testid*='export']"},
        download=FakeDownload(),
    )
    engine = le.LocatorEngine(db=db, llm_adapter=None, llm_enabled=False)
    result = engine.find_and_download(page, out_dir=tmp_path)
    assert result.downloaded_path is not None
    assert result.winning_strategy_id is not None
    assert result.llm_used is False


def test_all_fail_without_llm_returns_failure(tmp_db_path, tmp_path):
    db = StateDB(tmp_db_path); db.init_schema()
    le.seed_builtin_strategies(db)
    page = FakePage(found_selectors=set(), download=None)
    engine = le.LocatorEngine(db=db, llm_adapter=None, llm_enabled=False)
    result = engine.find_and_download(page, out_dir=tmp_path)
    assert result.downloaded_path is None
    assert result.llm_used is False


def test_llm_fallback_persists_new_strategy_on_success(tmp_db_path, tmp_path):
    db = StateDB(tmp_db_path); db.init_schema()
    le.seed_builtin_strategies(db)
    llm = MagicMock(return_value={
        "strategy": "css", "selector": "button.new-export",
        "confidence": 0.9, "reasoning": "looks right",
    })
    # Start with no match for any builtin; after LLM, the CSS selector is present.
    page = FakePage(
        found_selectors={"button.new-export"},
        download=FakeDownload(),
    )
    engine = le.LocatorEngine(db=db, llm_adapter=llm, llm_enabled=True,
                              llm_daily_limit=2)
    result = engine.find_and_download(page, out_dir=tmp_path)
    assert result.downloaded_path is not None
    assert result.llm_used is True
    # New strategy persisted
    selectors = [s.selector for s in db.ranked_strategies()]
    assert "button.new-export" in selectors


def test_llm_deny_list_rejects_dangerous_selectors(tmp_db_path, tmp_path):
    db = StateDB(tmp_db_path); db.init_schema()
    le.seed_builtin_strategies(db)
    llm = MagicMock(return_value={
        "strategy": "css", "selector": "a[href*='logout']",
        "confidence": 1.0, "reasoning": "nope",
    })
    page = FakePage(found_selectors=set())
    engine = le.LocatorEngine(db=db, llm_adapter=llm, llm_enabled=True,
                              llm_daily_limit=2)
    result = engine.find_and_download(page, out_dir=tmp_path)
    assert result.downloaded_path is None
    assert result.llm_blocked_by_deny_list is True


def test_llm_daily_limit_enforced(tmp_db_path, tmp_path):
    db = StateDB(tmp_db_path); db.init_schema()
    le.seed_builtin_strategies(db)
    llm = MagicMock(return_value={
        "strategy": "css", "selector": "button.x",
        "confidence": 0.9, "reasoning": "ok",
    })
    page = FakePage(found_selectors=set())
    engine = le.LocatorEngine(db=db, llm_adapter=llm, llm_enabled=True,
                              llm_daily_limit=0)  # limit 0 → never call
    result = engine.find_and_download(page, out_dir=tmp_path)
    assert llm.call_count == 0
    assert result.llm_used is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/autopull/test_locator_engine.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the locator engine**

Write `tools/autopull/locator_engine.py`:

```python
"""Locator engine: ranked strategy registry + LLM-adaptive fallback.

This module owns the "click the CSV export button" responsibility.
Strategies live in the state DB and are ranked by recency-weighted success.
When every enabled strategy fails, an optional LLM adapter proposes a new
selector from the current DOM; successes are persisted back into the registry.
"""
from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tools.autopull.state import StateDB, StrategyRow

ET = ZoneInfo("America/New_York")
log = logging.getLogger(__name__)

# --- Builtins -----------------------------------------------------------------

BUILTIN_STRATEGIES: list[tuple[str, str, str]] = [
    # (kind, selector, description)
    ("css", "[data-testid*='export']", "data-testid contains export"),
    ("css", "[aria-label*='Export']", "aria-label contains Export"),
    ("css", "button:has-text('Export')", "button text contains Export"),
    ("css", "button:has-text('Download CSV')", "button text Download CSV"),
    ("css", "[class*='export'],[class*='Export']", "class contains export/Export"),
]

# Deny-list for LLM-proposed selectors: these patterns touch destructive actions.
DENY_LIST_PATTERNS = [
    re.compile(r"logout", re.I),
    re.compile(r"sign[-_ ]?out", re.I),
    re.compile(r"delete", re.I),
    re.compile(r"remove[-_ ]?team", re.I),
    re.compile(r"leave[-_ ]?team", re.I),
    re.compile(r"unsubscribe", re.I),
    re.compile(r"cancel[-_ ]?subscription", re.I),
]


def seed_builtin_strategies(db: StateDB) -> None:
    for kind, sel, desc in BUILTIN_STRATEGIES:
        db.upsert_strategy(kind=kind, selector=sel, description=desc, source="builtin")


@dataclass
class LocateResult:
    downloaded_path: Path | None
    winning_strategy_id: int | None
    llm_used: bool
    llm_blocked_by_deny_list: bool = False
    attempts: int = 0


class LocatorEngine:
    def __init__(
        self,
        *,
        db: StateDB,
        llm_adapter: Callable[[str], dict] | None,
        llm_enabled: bool,
        llm_daily_limit: int = 2,
    ):
        self.db = db
        self.llm_adapter = llm_adapter
        self.llm_enabled = llm_enabled
        self.llm_daily_limit = llm_daily_limit

    def find_and_download(self, page: Any, *, out_dir: Path) -> LocateResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"season_stats_auto_{datetime.now(ET).strftime('%Y%m%d_%H%M%S')}.csv"

        attempts = 0
        for s in self.db.ranked_strategies():
            attempts += 1
            if self._try_strategy(page, s, dest):
                self.db.record_strategy_result(s.id, success=True)
                return LocateResult(
                    downloaded_path=dest,
                    winning_strategy_id=s.id,
                    llm_used=False,
                    attempts=attempts,
                )
            self.db.record_strategy_result(s.id, success=False)

        if not self.llm_enabled or self.llm_adapter is None:
            return LocateResult(downloaded_path=None, winning_strategy_id=None,
                                llm_used=False, attempts=attempts)

        if self._llm_calls_today() >= self.llm_daily_limit:
            log.warning("LLM adaptive fallback daily limit reached")
            return LocateResult(downloaded_path=None, winning_strategy_id=None,
                                llm_used=False, attempts=attempts)

        dom = self._prune_dom(page)
        try:
            proposal = self.llm_adapter(dom)
        except Exception as e:
            log.exception("LLM adapter raised: %s", e)
            return LocateResult(downloaded_path=None, winning_strategy_id=None,
                                llm_used=False, attempts=attempts)

        if not self._proposal_is_safe(proposal):
            return LocateResult(downloaded_path=None, winning_strategy_id=None,
                                llm_used=True, llm_blocked_by_deny_list=True,
                                attempts=attempts)

        sid = self.db.upsert_strategy(
            kind=str(proposal.get("strategy", "css")),
            selector=str(proposal["selector"]),
            description=f"LLM: {proposal.get('reasoning','')[:200]}",
            source="llm",
        )
        ranked_now = {s.id: s for s in self.db.ranked_strategies()}
        proposed = ranked_now.get(sid)
        if proposed and self._try_strategy(page, proposed, dest):
            self.db.record_strategy_result(sid, success=True)
            return LocateResult(downloaded_path=dest, winning_strategy_id=sid,
                                llm_used=True, attempts=attempts + 1)
        self.db.record_strategy_result(sid, success=False)
        return LocateResult(downloaded_path=None, winning_strategy_id=None,
                            llm_used=True, attempts=attempts + 1)

    # --- helpers ---

    def _try_strategy(self, page: Any, s: StrategyRow, dest: Path) -> bool:
        try:
            loc = page.locator(s.selector)
            if loc.count() == 0:
                return False
            with page.expect_download(timeout=30_000) as dl_info:
                loc.first.click()
            dl = dl_info.value
            dl.save_as(str(dest))
            return True
        except Exception as e:
            log.info("strategy %d (%s) failed: %s", s.id, s.selector, e)
            return False

    def _proposal_is_safe(self, proposal: dict) -> bool:
        if not proposal or "selector" not in proposal:
            return False
        sel = str(proposal["selector"])
        for pat in DENY_LIST_PATTERNS:
            if pat.search(sel):
                log.warning("LLM proposal blocked by deny list: %r", sel)
                return False
        return True

    def _llm_calls_today(self) -> int:
        cutoff = (datetime.now(ET) - timedelta(hours=24)).isoformat()
        with self.db._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM runs "
                "WHERE llm_fallback_invoked=1 AND started_at >= ?",
                (cutoff,),
            ).fetchone()
        return int(row["n"]) if row else 0

    @staticmethod
    def _prune_dom(page: Any, cap_bytes: int = 40_000) -> str:
        try:
            html = page.content()
        except Exception:
            html = ""
        html = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
        html = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.I)
        html = re.sub(r"data:[^\"')]+", "data:...", html)
        if len(html) > cap_bytes:
            html = html[:cap_bytes] + "\n<!-- truncated -->"
        return html
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/autopull/test_locator_engine.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/autopull/locator_engine.py tests/autopull/test_locator_engine.py
git commit -m "feat(autopull): locator engine — ranked strategies + LLM-adaptive fallback"
```

---

## Task 9: LLM adapter (Claude API) with prompt caching

**Files:**
- Modify: `tools/autopull/locator_engine.py` (no change — callable injection stays)
- Create: `tools/autopull/llm_adapter.py`
- Create: `tests/autopull/test_llm_adapter.py`

- [ ] **Step 1: Write failing tests**

Write `tests/autopull/test_llm_adapter.py`:

```python
"""Tests for the Claude API adapter used by the locator engine."""
from __future__ import annotations
import json
from unittest.mock import MagicMock
import pytest
from tools.autopull import llm_adapter as la


def _fake_anthropic_response(json_obj: dict):
    resp = MagicMock()
    resp.content = [MagicMock(type="text", text=json.dumps(json_obj))]
    resp.usage.input_tokens = 500
    resp.usage.output_tokens = 50
    resp.usage.cache_creation_input_tokens = 0
    resp.usage.cache_read_input_tokens = 400
    return resp


def test_returns_parsed_json_on_success():
    client = MagicMock()
    client.messages.create.return_value = _fake_anthropic_response({
        "strategy": "css", "selector": "button.export",
        "confidence": 0.9, "reasoning": "big export button",
    })
    adapter = la.ClaudeLocatorAdapter(client=client, model="claude-sonnet-4-6")
    out = adapter("<html>...</html>")
    assert out["selector"] == "button.export"
    assert out["strategy"] == "css"


def test_rejects_non_json_response():
    client = MagicMock()
    resp = MagicMock()
    resp.content = [MagicMock(type="text", text="Sure, try: button.export")]
    resp.usage.input_tokens = 1; resp.usage.output_tokens = 1
    resp.usage.cache_creation_input_tokens = 0; resp.usage.cache_read_input_tokens = 0
    client.messages.create.return_value = resp
    adapter = la.ClaudeLocatorAdapter(client=client, model="claude-sonnet-4-6")
    with pytest.raises(la.LLMAdapterError):
        adapter("<html>...</html>")


def test_uses_prompt_caching_on_system_block():
    client = MagicMock()
    client.messages.create.return_value = _fake_anthropic_response({
        "strategy": "css", "selector": "x", "confidence": 0.5, "reasoning": "",
    })
    adapter = la.ClaudeLocatorAdapter(client=client, model="claude-sonnet-4-6")
    adapter("<html>...</html>")
    kwargs = client.messages.create.call_args.kwargs
    system = kwargs["system"]
    assert isinstance(system, list)
    assert any(block.get("cache_control") == {"type": "ephemeral"} for block in system)


def test_rejects_missing_required_keys():
    client = MagicMock()
    client.messages.create.return_value = _fake_anthropic_response({
        "selector": "x"   # missing 'strategy'
    })
    adapter = la.ClaudeLocatorAdapter(client=client, model="claude-sonnet-4-6")
    with pytest.raises(la.LLMAdapterError):
        adapter("<html>...</html>")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/autopull/test_llm_adapter.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the adapter (with prompt caching)**

Write `tools/autopull/llm_adapter.py`:

```python
"""Claude API adapter for locator fallback.

System prompt is cached via the ephemeral cache_control block so repeated
adaptations within the 5-minute cache window are cheap.
"""
from __future__ import annotations
import json
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You identify UI elements on GameChanger's stats page that trigger a CSV
download. You are being called only when hardcoded selectors have failed,
meaning the page structure has likely changed.

Given a pruned HTML snapshot of the current page, return a JSON object with:
{
  "strategy": "css" | "xpath",
  "selector": "<the selector string>",
  "confidence": <float 0..1>,
  "reasoning": "<one-sentence why>"
}

Rules:
- Prefer CSS over XPath.
- The element, when clicked, must trigger a direct CSV download OR open a
  submenu whose CSV option triggers a download. For submenus, chain with
  Playwright's ">>" operator (e.g. "button.actions >> li:has-text('CSV')").
- NEVER propose selectors that match logout, delete, remove, unsubscribe,
  cancel, or any destructive action.
- If you cannot find a plausible candidate, return confidence < 0.3.

Return ONLY the JSON object — no markdown fences, no prose.
"""


class LLMAdapterError(RuntimeError):
    pass


class ClaudeLocatorAdapter:
    """Callable: takes pruned DOM, returns proposal dict or raises LLMAdapterError."""

    def __init__(self, *, client: Any, model: str = "claude-sonnet-4-6",
                 max_tokens: int = 400):
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    def __call__(self, pruned_dom: str) -> dict:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[
                {"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}},
            ],
            messages=[
                {"role": "user", "content": f"Current DOM snapshot:\n\n{pruned_dom}"},
            ],
        )
        text = self._first_text(resp)
        data = self._parse_json(text)
        self._validate(data)
        return data

    @staticmethod
    def _first_text(resp: Any) -> str:
        for block in getattr(resp, "content", []) or []:
            if getattr(block, "type", None) == "text":
                return block.text
        raise LLMAdapterError("Response contained no text block")

    @staticmethod
    def _parse_json(text: str) -> dict:
        # Strip accidental code fences if the model added them
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as e:
            raise LLMAdapterError(f"Response was not JSON: {e}; got: {text!r}")
        if not isinstance(data, dict):
            raise LLMAdapterError("Response JSON was not an object")
        return data

    @staticmethod
    def _validate(data: dict) -> None:
        for key in ("strategy", "selector"):
            if key not in data or not data[key]:
                raise LLMAdapterError(f"Response missing required key {key!r}")
        if data["strategy"] not in ("css", "xpath"):
            raise LLMAdapterError(f"Unknown strategy: {data['strategy']!r}")


def build_default_adapter(*, api_key: str, model: str) -> ClaudeLocatorAdapter:
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)
    return ClaudeLocatorAdapter(client=client, model=model)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/autopull/test_llm_adapter.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/autopull/llm_adapter.py tests/autopull/test_llm_adapter.py
git commit -m "feat(autopull): Claude API adapter with prompt-cached system block"
```

---

## Task 10: CLI orchestrator + idempotency

**Files:**
- Create: `tools/autopull/cli.py`
- Create: `tests/autopull/test_cli.py`

- [ ] **Step 1: Write failing tests**

Write `tests/autopull/test_cli.py`:

```python
"""Unit tests for the CLI orchestrator — pure logic, no real Playwright."""
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
        gmail_client_id="x", gmail_client_secret="y", gmail_refresh_token="z",
        gmail_notify_from="a@b.c", gmail_notify_to="a@b.c",
        anthropic_api_key="", n8n_status_webhook="",
        n8n_weekly_webhook="", gc_team_id="T", gc_season_slug="S",
        data_root=tmp_path / "data", log_root=tmp_path / "logs",
    )
    base.update(over)
    from tools.autopull.config import AutopullConfig
    return AutopullConfig(**base)


def test_skip_when_disabled(tmp_path):
    cfg = _fake_cfg(tmp_path, enabled=False)
    result = cli.run_once(cfg=cfg, trigger="cron", runner=MagicMock())
    assert result["outcome"] == "skipped"
    assert result["reason"] == "disabled"


def test_skip_when_recent_success(tmp_path):
    cfg = _fake_cfg(tmp_path)
    db = StateDB(cfg.data_root / "autopull" / "autopull_state.db")
    db.init_schema()
    rid = db.start_run(trigger="cron", started_at=datetime.now(ET) - timedelta(minutes=5))
    db.complete_run(rid, outcome="success", csv_path=None, rows_ingested=1,
                    winning_strategy_id=None, duration_ms=1,
                    llm_fallback_invoked=False, session_refreshed=False,
                    completed_at=datetime.now(ET) - timedelta(minutes=5))
    result = cli.run_once(cfg=cfg, trigger="cron", runner=MagicMock())
    assert result["outcome"] == "skipped"
    assert "recent success" in result["reason"].lower()


def test_skip_when_breaker_open(tmp_path):
    cfg = _fake_cfg(tmp_path)
    db = StateDB(cfg.data_root / "autopull" / "autopull_state.db")
    db.init_schema()
    for _ in range(3):
        db.breaker_record_failure("auth", open_duration_hours=24)
    result = cli.run_once(cfg=cfg, trigger="cron", runner=MagicMock())
    assert result["outcome"] == "skipped"
    assert "breaker" in result["reason"].lower()


def test_runner_invoked_when_eligible(tmp_path):
    cfg = _fake_cfg(tmp_path)
    runner = MagicMock(return_value={
        "csv_path": str(tmp_path / "x.csv"), "rows_ingested": 10,
        "winning_strategy_id": 1, "llm_fallback_invoked": False,
        "session_refreshed": False, "drift_severity": "none",
    })
    (tmp_path / "x.csv").write_text("Player,AB\na,1\n")
    result = cli.run_once(cfg=cfg, trigger="manual", runner=runner)
    assert result["outcome"] == "success"
    assert runner.called


def test_runner_exception_recorded_as_failure(tmp_path):
    cfg = _fake_cfg(tmp_path)
    runner = MagicMock(side_effect=RuntimeError("boom"))
    result = cli.run_once(cfg=cfg, trigger="manual", runner=runner)
    assert result["outcome"] == "failure"
    assert "boom" in result["failure_reason"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/autopull/test_cli.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the CLI**

Write `tools/autopull/cli.py`:

```python
"""Autopull CLI — the single entry point called by cron and sync_daemon.

The heavy lifting (Playwright + Gmail + ingest) is injected via a `runner`
callable so unit tests can exercise the orchestration logic without touching
the network or a browser.
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tools.autopull import config as config_mod
from tools.autopull.state import StateDB

ET = ZoneInfo("America/New_York")
log = logging.getLogger(__name__)


def run_once(*, cfg: config_mod.AutopullConfig, trigger: str,
             runner: Callable[..., dict]) -> dict:
    """Do one full autopull run. Returns a summary dict."""
    db_path = cfg.data_root / "autopull" / "autopull_state.db"
    db = StateDB(db_path)
    db.init_schema()

    if not cfg.enabled:
        return {"outcome": "skipped", "reason": "disabled"}
    if trigger == "postgame" and not cfg.postgame_enabled:
        return {"outcome": "skipped", "reason": "postgame disabled"}

    recent = db.last_successful_run_within(minutes=cfg.idempotency_window_min)
    if recent is not None:
        return {
            "outcome": "skipped",
            "reason": f"recent success within {cfg.idempotency_window_min}m (run #{recent.id})",
        }

    if db.breaker_open("auth"):
        return {"outcome": "skipped", "reason": "auth breaker open"}

    run_id = db.start_run(trigger=trigger)
    started = time.monotonic()
    try:
        out = runner(cfg=cfg, db=db, run_id=run_id)
    except Exception as e:
        log.exception("runner raised")
        duration_ms = int((time.monotonic() - started) * 1000)
        db.complete_run(
            run_id, outcome="failure", csv_path=None, rows_ingested=None,
            winning_strategy_id=None, duration_ms=duration_ms,
            llm_fallback_invoked=False, session_refreshed=False,
            failure_reason=str(e),
        )
        db.breaker_record_failure(_breaker_key(e), open_duration_hours=_breaker_hours(e))
        return {"outcome": "failure", "run_id": run_id, "failure_reason": str(e)}

    duration_ms = int((time.monotonic() - started) * 1000)
    outcome = out.get("outcome", "success")
    db.complete_run(
        run_id,
        outcome=outcome,
        csv_path=out.get("csv_path"),
        rows_ingested=out.get("rows_ingested"),
        winning_strategy_id=out.get("winning_strategy_id"),
        duration_ms=duration_ms,
        llm_fallback_invoked=bool(out.get("llm_fallback_invoked")),
        session_refreshed=bool(out.get("session_refreshed")),
        failure_reason=out.get("failure_reason"),
    )
    if outcome == "success":
        db.breaker_reset("auth")
        db.breaker_reset("download")
    return {"outcome": outcome, "run_id": run_id, **out}


def _breaker_key(e: Exception) -> str:
    msg = str(e).lower()
    if "auth" in msg or "login" in msg or "2fa" in msg or "session" in msg:
        return "auth"
    return "download"


def _breaker_hours(e: Exception) -> int:
    return 24 if _breaker_key(e) == "auth" else 2


# --- Real runner wiring (used in production, stubbed in unit tests) -----------

def default_runner(*, cfg: config_mod.AutopullConfig,
                   db: StateDB, run_id: int) -> dict:
    """Actual run: Playwright + locator + validate + ingest + notify."""
    from playwright.sync_api import sync_playwright
    from tools.autopull import (
        session_manager as sm,
        locator_engine as le,
        csv_validator as cv,
        gmail_2fa_fetcher as g2fa,
        notifier as nt,
        llm_adapter as lla,
    )
    le.seed_builtin_strategies(db)

    staging = cfg.data_root / "autopull" / "staging"
    quarantine = cfg.data_root / "autopull" / "quarantine"
    sharks_dir = cfg.data_root / "sharks"
    staging.mkdir(parents=True, exist_ok=True)
    quarantine.mkdir(parents=True, exist_ok=True)
    sharks_dir.mkdir(parents=True, exist_ok=True)

    gmail_client = g2fa.build_client(
        client_id=cfg.gmail_client_id,
        client_secret=cfg.gmail_client_secret,
        refresh_token=cfg.gmail_refresh_token,
    )
    gmail_fetcher = lambda: g2fa.fetch_latest_code(gmail_client)
    auth_file = cfg.data_root / "autopull" / "gc_session.json"

    import os
    session = sm.SessionManager(
        auth_file=auth_file,
        email=os.getenv("GC_EMAIL", ""),
        password=os.getenv("GC_PASSWORD", ""),
        gmail_fetcher=gmail_fetcher,
    )

    llm = None
    if cfg.llm_adapt_enabled and cfg.anthropic_api_key:
        llm = lla.build_default_adapter(
            api_key=cfg.anthropic_api_key, model=cfg.llm_model
        )
    engine = le.LocatorEngine(
        db=db, llm_adapter=llm, llm_enabled=cfg.llm_adapt_enabled,
    )

    with sync_playwright() as pw:
        page, refreshed = session.new_logged_in_page(pw, headless=True)
        stats_url = (f"https://web.gc.com/teams/{cfg.gc_team_id}/"
                     f"{cfg.gc_season_slug}/stats")
        page.goto(stats_url, wait_until="networkidle", timeout=60_000)
        result = engine.find_and_download(page, out_dir=staging)

    if result.downloaded_path is None:
        return {
            "outcome": "failure",
            "failure_reason": "No strategy located the CSV export button",
            "llm_fallback_invoked": result.llm_used,
            "session_refreshed": refreshed,
        }

    latest_cols, _ = db.last_two_schemas()
    val = cv.validate(result.downloaded_path, known_columns=latest_cols)
    if not val.accepted:
        cv.quarantine(result.downloaded_path, val, quarantine_root=quarantine)
        return {
            "outcome": "quarantined", "failure_reason": val.reason,
            "llm_fallback_invoked": result.llm_used,
            "session_refreshed": refreshed,
            "drift_severity": val.drift_severity,
        }

    db.record_schema(val.columns, val.row_count)

    final = sharks_dir / f"season_stats_{datetime.now(ET).strftime('%Y%m%d')}.csv"
    result.downloaded_path.replace(final)

    # Kick the existing ingest
    import subprocess
    rc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "gc_csv_ingest.py"),
         str(final)],
        timeout=180,
    ).returncode
    if rc != 0:
        return {
            "outcome": "failure",
            "failure_reason": f"gc_csv_ingest.py exited {rc}",
            "csv_path": str(final),
            "llm_fallback_invoked": result.llm_used,
            "session_refreshed": refreshed,
            "drift_severity": val.drift_severity,
        }

    return {
        "outcome": "success",
        "csv_path": str(final),
        "rows_ingested": val.row_count,
        "winning_strategy_id": result.winning_strategy_id,
        "llm_fallback_invoked": result.llm_used,
        "session_refreshed": refreshed,
        "drift_severity": val.drift_severity,
    }


def _build_notifier(cfg: config_mod.AutopullConfig):
    """Wire real Gmail send + HTTP webhook + push webhook into the notifier."""
    import os
    import requests
    from tools.autopull import gmail_2fa_fetcher as g2fa
    from tools.autopull import notifier as nt

    gmail_client = None
    if cfg.gmail_client_id and cfg.gmail_refresh_token:
        gmail_client = g2fa.build_client(
            client_id=cfg.gmail_client_id,
            client_secret=cfg.gmail_client_secret,
            refresh_token=cfg.gmail_refresh_token,
        )

    class _GmailSender:
        def send(self, *, to: str, subject: str, body: str) -> None:
            if gmail_client is None:
                log.info("Gmail not configured, skipping email")
                return
            g2fa.send_email(gmail_client, sender=cfg.gmail_notify_from,
                            to=to, subject=subject, body=body)

    class _N8nPoster:
        def post(self, url: str, payload: dict) -> None:
            requests.post(url, json=payload, timeout=15).raise_for_status()

    class _WebhookPusher:
        def __init__(self, url: str):
            self._url = url
        def notify(self, message: str) -> None:
            if not self._url:
                return
            requests.post(self._url, json={"message": message}, timeout=10)

    push_url = os.getenv("PUSH_WEBHOOK_URL", "")
    return nt.Notifier(
        gmail_sender=_GmailSender(),
        n8n_poster=_N8nPoster(),
        pusher=_WebhookPusher(push_url),
        status_webhook_url=cfg.n8n_status_webhook,
        notify_to_email=cfg.gmail_notify_to,
    )


def _summary_from_result(result: dict, trigger: str):
    from tools.autopull.notifier import RunSummary
    return RunSummary(
        run_id=result.get("run_id", -1),
        trigger=trigger,
        outcome=result.get("outcome", "failure"),
        failure_reason=result.get("failure_reason"),
        csv_path=result.get("csv_path"),
        rows_ingested=result.get("rows_ingested"),
        duration_ms=result.get("duration_ms"),
        drift_severity=result.get("drift_severity", "none"),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dugout GC CSV autopull")
    ap.add_argument("--trigger", choices=["cron", "postgame", "manual"],
                    default="manual")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config_mod.load(require_gmail=True)
    result = run_once(cfg=cfg, trigger=args.trigger, runner=default_runner)

    # Skipped runs are silent — nothing to fan out.
    if result.get("outcome") != "skipped":
        try:
            notifier = _build_notifier(cfg)
            notifier.emit(_summary_from_result(result, args.trigger))
        except Exception as e:
            log.exception("notifier wiring failed: %s", e)

    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("outcome") in ("success", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/autopull/test_cli.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/autopull/cli.py tests/autopull/test_cli.py
git commit -m "feat(autopull): CLI orchestrator with idempotency + breaker gating"
```

---

## Task 11: End-to-end integration test with local fixture

**Files:**
- Create: `tests/autopull/fixtures/stats_page.html`
- Create: `tests/autopull/test_cli_integration.py`

- [ ] **Step 1: Write the HTML fixture**

Write `tests/autopull/fixtures/stats_page.html`:

```html
<!DOCTYPE html>
<html>
<head><title>Sharks Stats</title></head>
<body>
  <h1>Season Stats</h1>
  <button data-testid="export-csv" id="dl">Export CSV</button>
  <script>
    document.getElementById('dl').addEventListener('click', function() {
      const blob = new Blob(
        ["Player,AB,H,BB,K,HBP,RBI,BA,OBP,SLG\n" +
         "Alice Smith,20,8,3,4,1,6,0.400,0.500,0.600\n" +
         "Bob Jones,18,5,2,5,0,3,0.278,0.350,0.389\n"],
        {type: "text/csv"}
      );
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = "season_stats.csv";
      document.body.appendChild(a); a.click(); a.remove();
    });
  </script>
</body>
</html>
```

- [ ] **Step 2: Write the integration test**

Write `tests/autopull/test_cli_integration.py`:

```python
"""End-to-end: serve the HTML fixture, drive Playwright, validate the download.

Skipped if Playwright chromium is not installed.
"""
from __future__ import annotations
import http.server
import socketserver
import threading
from pathlib import Path
import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright

from tools.autopull import locator_engine as le
from tools.autopull import csv_validator as cv
from tools.autopull.state import StateDB


@pytest.fixture
def local_http_server(tmp_path):
    fixtures = Path(__file__).parent / "fixtures"
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
        *a, directory=str(fixtures), **kw
    )
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}/stats_page.html"
    server.shutdown()
    server.server_close()


def test_download_and_validate_end_to_end(tmp_db_path, tmp_path, local_http_server):
    db = StateDB(tmp_db_path); db.init_schema()
    le.seed_builtin_strategies(db)
    engine = le.LocatorEngine(db=db, llm_adapter=None, llm_enabled=False)
    staging = tmp_path / "staging"; staging.mkdir()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.goto(local_http_server, wait_until="networkidle")
        result = engine.find_and_download(page, out_dir=staging)
        browser.close()

    assert result.downloaded_path is not None
    assert result.downloaded_path.exists()

    val = cv.validate(result.downloaded_path,
                      known_columns=["Player", "AB", "H", "BB", "K"])
    assert val.accepted is True
    assert val.row_count == 2
```

- [ ] **Step 3: Run the integration test**

Run: `pytest tests/autopull/test_cli_integration.py -v`
Expected: 1 passed (if Playwright is installed). If `playwright` isn't installed in dev, it is `skipped` — CI installs it.

- [ ] **Step 4: Commit**

```bash
git add tests/autopull/fixtures/stats_page.html tests/autopull/test_cli_integration.py
git commit -m "test(autopull): end-to-end integration with local HTML fixture"
```

---

## Task 12: Circuit breaker integration test

**Files:**
- Create: `tests/autopull/test_circuit_breaker_integration.py`

- [ ] **Step 1: Write the test**

Write `tests/autopull/test_circuit_breaker_integration.py`:

```python
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
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/autopull/test_circuit_breaker_integration.py -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/autopull/test_circuit_breaker_integration.py
git commit -m "test(autopull): auth breaker trips after 3 failures"
```

---

## Task 13: sync_daemon postgame hook

**Files:**
- Modify: `tools/sync_daemon.py`

- [ ] **Step 1: Find the postgame webhook-fire site**

Run: `grep -n "gc-alert\|POSTGAME\|postgame" tools/sync_daemon.py | head -20`

Expected: locate the line(s) where the n8n `gc-alert` webhook is POSTed on postgame transition.

- [ ] **Step 2: Add a subprocess spawn right after the webhook**

In `tools/sync_daemon.py`, locate the block that fires the `gc-alert` webhook on postgame transition. Immediately after that block, add:

```python
    # Kick the autopull (CSV download + ingest) in a detached subprocess so we
    # don't block the daemon's state loop. The autopull CLI handles its own
    # idempotency and kill-switch.
    try:
        import subprocess, sys
        subprocess.Popen(
            [sys.executable, "-m", "tools.autopull.cli", "--trigger=postgame"],
            cwd=str(Path(__file__).resolve().parent.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("autopull postgame trigger dispatched")
    except Exception as e:
        logger.warning("autopull postgame trigger failed to dispatch: %s", e)
```

The variable name may need to match the daemon's logger. Verify by `grep -n "logger\|getLogger" tools/sync_daemon.py | head -3` and use the same name.

- [ ] **Step 3: Smoke-test import path**

Run: `python -c "from tools.autopull.cli import main; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Verify existing sync_daemon tests still pass**

Run: `pytest tests/ -k sync_daemon -v`
Expected: existing tests still green. If there are no sync_daemon tests, skip this step.

- [ ] **Step 5: Commit**

```bash
git add tools/sync_daemon.py
git commit -m "feat(sync_daemon): dispatch autopull on postgame transition"
```

---

## Task 14: Weekly self-report

**Files:**
- Create: `tools/autopull/weekly_report.py`
- Create: `tests/autopull/test_weekly_report.py`

- [ ] **Step 1: Write failing tests**

Write `tests/autopull/test_weekly_report.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/autopull/test_weekly_report.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the weekly report**

Write `tools/autopull/weekly_report.py`:

```python
"""Weekly self-report: summarises the last N days of autopull runs and
POSTs the result to an n8n webhook for inclusion in the morning briefing.
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from tools.autopull import config as config_mod
from tools.autopull.state import StateDB

ET = ZoneInfo("America/New_York")
log = logging.getLogger(__name__)


def build_summary(db: StateDB, *, days: int = 7) -> dict:
    cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
    with db._conn() as c:
        rows = c.execute(
            "SELECT outcome, llm_fallback_invoked, winning_strategy_id, "
            "session_refreshed, failure_reason "
            "FROM runs WHERE started_at >= ?",
            (cutoff,),
        ).fetchall()
    by_outcome: Counter = Counter()
    by_winner: Counter = Counter()
    failures: list[str] = []
    llm_count = 0
    refresh_count = 0
    for r in rows:
        by_outcome[r["outcome"]] += 1
        if r["winning_strategy_id"]:
            by_winner[r["winning_strategy_id"]] += 1
        if r["llm_fallback_invoked"]:
            llm_count += 1
        if r["session_refreshed"]:
            refresh_count += 1
        if r["failure_reason"]:
            failures.append(r["failure_reason"])
    return {
        "generated_at": datetime.now(ET).isoformat(),
        "window_days": days,
        "total_runs": len(rows),
        "by_outcome": dict(by_outcome),
        "top_winning_strategies": by_winner.most_common(5),
        "llm_fallback_invocations": llm_count,
        "session_refreshes": refresh_count,
        "recent_failures": failures[-10:],
    }


def post_weekly(db: StateDB, *, poster: Callable[[str, dict], None],
                webhook_url: str, days: int = 7) -> dict:
    summary = build_summary(db, days=days)
    if webhook_url:
        poster(webhook_url, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dugout GC autopull weekly report")
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    cfg = config_mod.load()
    db = StateDB(cfg.data_root / "autopull" / "autopull_state.db")
    db.init_schema()
    import requests
    def poster(url: str, body: dict) -> None:
        requests.post(url, json=body, timeout=15).raise_for_status()
    summary = post_weekly(db, poster=poster,
                          webhook_url=cfg.n8n_weekly_webhook, days=args.days)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/autopull/test_weekly_report.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/autopull/weekly_report.py tests/autopull/test_weekly_report.py
git commit -m "feat(autopull): weekly self-report → n8n webhook"
```

---

## Task 15: systemd units (daily cron + weekly)

**Files:**
- Create: `deploy/systemd/gc-autopull.service`
- Create: `deploy/systemd/gc-autopull.timer`
- Create: `deploy/systemd/gc-autopull-weekly.service`
- Create: `deploy/systemd/gc-autopull-weekly.timer`
- Create: `deploy/systemd/README.md`

- [ ] **Step 1: Create the daily service**

Write `deploy/systemd/gc-autopull.service`:

```ini
[Unit]
Description=Dugout GC CSV autopull (daily safety-net)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=joelycannoli
WorkingDirectory=/home/joelycannoli/dugout
EnvironmentFile=/home/joelycannoli/dugout/.env
ExecStart=/usr/bin/env python3 -m tools.autopull.cli --trigger=cron
StandardOutput=append:/home/joelycannoli/dugout/logs/autopull.log
StandardError=append:/home/joelycannoli/dugout/logs/autopull.log
TimeoutStartSec=600
```

- [ ] **Step 2: Create the daily timer**

Write `deploy/systemd/gc-autopull.timer`:

```ini
[Unit]
Description=Dugout GC CSV autopull (daily 03:00 ET)

[Timer]
OnCalendar=*-*-* 03:00:00 America/New_York
Persistent=true
Unit=gc-autopull.service

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: Create the weekly units**

Write `deploy/systemd/gc-autopull-weekly.service`:

```ini
[Unit]
Description=Dugout GC autopull weekly self-report
After=network-online.target

[Service]
Type=oneshot
User=joelycannoli
WorkingDirectory=/home/joelycannoli/dugout
EnvironmentFile=/home/joelycannoli/dugout/.env
ExecStart=/usr/bin/env python3 -m tools.autopull.weekly_report --days 7
StandardOutput=append:/home/joelycannoli/dugout/logs/autopull-weekly.log
StandardError=append:/home/joelycannoli/dugout/logs/autopull-weekly.log
TimeoutStartSec=120
```

Write `deploy/systemd/gc-autopull-weekly.timer`:

```ini
[Unit]
Description=Dugout GC autopull weekly report (Sunday 06:00 ET)

[Timer]
OnCalendar=Sun *-*-* 06:00:00 America/New_York
Persistent=true
Unit=gc-autopull-weekly.service

[Install]
WantedBy=timers.target
```

- [ ] **Step 4: Install script + README**

Write `deploy/systemd/README.md`:

```markdown
# Dugout Autopull — systemd units

Install on the Pi:

```bash
cd ~/dugout
sudo cp deploy/systemd/gc-autopull.service /etc/systemd/system/
sudo cp deploy/systemd/gc-autopull.timer /etc/systemd/system/
sudo cp deploy/systemd/gc-autopull-weekly.service /etc/systemd/system/
sudo cp deploy/systemd/gc-autopull-weekly.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gc-autopull.timer
sudo systemctl enable --now gc-autopull-weekly.timer
```

Verify:

```bash
systemctl list-timers | grep autopull
journalctl -u gc-autopull.service --since today
```

Pause the daily run without removing: set `GC_AUTOPULL_ENABLED=false` in `.env`.
The timer still fires but the CLI exits early with `outcome=skipped`.
```

- [ ] **Step 5: Commit**

```bash
git add deploy/systemd/
git commit -m "feat(autopull): systemd units for daily cron + weekly report"
```

---

## Task 16: Env, requirements, policy updates

**Files:**
- Modify: `.env.example`
- Modify: `requirements.txt`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Append env keys**

Append to `.env.example`:

```
# --- GC CSV autopull ---------------------------------------------------------
GC_AUTOPULL_ENABLED=false
GC_AUTOPULL_POSTGAME_ENABLED=false
GC_AUTOPULL_LLM_ADAPT=false
GC_AUTOPULL_IDEMPOTENCY_WINDOW_MIN=15
GC_AUTOPULL_LLM_DAILY_BUDGET_USD=1.00
GC_AUTOPULL_LLM_MODEL=claude-sonnet-4-6

# Gmail OAuth (headless) for 2FA code read + failure notifications
GMAIL_OAUTH_CLIENT_ID=
GMAIL_OAUTH_CLIENT_SECRET=
GMAIL_OAUTH_REFRESH_TOKEN=
GMAIL_NOTIFY_FROM=anchorgroupops@gmail.com
GMAIL_NOTIFY_TO=anchorgroupops@gmail.com

# Anthropic API for LLM-adaptive locator fallback
ANTHROPIC_API_KEY=

# n8n webhooks
N8N_AUTOPULL_STATUS_WEBHOOK=https://n8n.joelycannoli.com/webhook/gc-pull-status
N8N_AUTOPULL_WEEKLY_WEBHOOK=https://n8n.joelycannoli.com/webhook/autopull-weekly

# Push notifications (ntfy.sh, Pushover, or any HTTP POST endpoint that
# delivers to your phone). Leave empty to disable push.
PUSH_WEBHOOK_URL=
```

- [ ] **Step 2: Add new dependencies**

Append to `requirements.txt` (check first for duplicates):

```
google-api-python-client>=2.120.0
google-auth>=2.28.0
google-auth-oauthlib>=1.2.0
google-auth-httplib2>=0.2.0
anthropic>=0.40.0
```

Run: `grep -c "^anthropic\|^google-api" requirements.txt` first — if already present, skip that line.

- [ ] **Step 3: Amend CLAUDE.md policy**

In `CLAUDE.md`, find the "Development Patterns" section and replace the first bullet. Old:

```
- **CSV-First**: GameChanger CSV export is the primary data source. No browser automation or API scraping.
```

New:

```
- **CSV-First**: GameChanger CSV export is the primary data source. Browser
  automation is permitted ONLY for the single CSV-download click in
  `tools/autopull/` (scheduled, self-healing, on the Pi). No scraping of
  live pages, play-by-play, or opponent stats beyond this flow.
```

- [ ] **Step 4: Commit**

```bash
git add .env.example requirements.txt CLAUDE.md
git commit -m "chore(autopull): env keys, deps, CLAUDE.md policy amendment"
```

---

## Task 17: Full suite + coverage check

- [ ] **Step 1: Install new deps in dev env**

Run: `pip install -r requirements.txt`

- [ ] **Step 2: Run the full autopull test suite with coverage**

Run: `pytest tests/autopull/ --cov=tools.autopull --cov-report=term-missing -v`

Expected:
- All tests pass.
- Coverage ≥ 85% on every module under `tools.autopull`.

If any module is below 85%, add focused tests in that module's test file before committing.

- [ ] **Step 3: Run the complete existing test suite to confirm no regressions**

Run: `pytest tests/ -v --ignore=tests/autopull/test_cli_integration.py`

Expected: all pre-existing tests still green.

- [ ] **Step 4: Commit any added tests**

```bash
git add tests/autopull/
git commit -m "test(autopull): bring per-module coverage to ≥85%" || true
```

---

## Task 18: Push and open PR

- [ ] **Step 1: Push the branch**

Run:

```bash
git push -u origin claude/gc-autopull-adaptive
```

- [ ] **Step 2: Create PR**

Run:

```bash
gh pr create --title "feat(autopull): self-healing GC CSV autopull with LLM-adaptive fallback" --body "$(cat <<'EOF'
## Summary
- Automates the manual gc.com "Export CSV" click as a Pi-hosted, self-healing pipeline
- Triggered by sync_daemon postgame event AND a daily 03:00 ET safety-net systemd timer
- Adaptive: when DOM strategies fail, Claude API proposes a new selector (deny-listed, budget-capped, quarantine-validated)
- Observability: SQLite run log, strategy ranking, circuit breakers, 3-channel notifications, weekly self-report to n8n

## Design doc
`docs/superpowers/specs/2026-04-22-gc-csv-autopull-design.md`

## Test plan
- [ ] `pytest tests/autopull/ --cov=tools.autopull` ≥85% on every module
- [ ] Full repo tests still green
- [ ] On Pi: `GC_AUTOPULL_ENABLED=true` + manual `python -m tools.autopull.cli --trigger=manual` succeeds
- [ ] `systemctl list-timers | grep autopull` shows both timers
- [ ] Intentionally break locator selector → verify quarantine + push + email fire
- [ ] Trigger 3 auth failures → verify breaker opens and 4th run short-circuits

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review checklist

Before handing off:

1. **Spec coverage** — every section of `docs/superpowers/specs/2026-04-22-gc-csv-autopull-design.md`:
   - §3.1 modules → Tasks 2, 3, 4, 5, 6, 7, 8, 9, 10, 14 ✓
   - §3.2 DB schema → Task 3 ✓
   - §4 self-healing → Tasks 3 (breaker), 7 (session auto-refresh), 10 (idempotency), 16 (kill switch) ✓
   - §5 self-improving / adaptive → Tasks 8 (ranking), 9 (LLM adapter), 14 (weekly report) ✓
   - §6 scheduling → Tasks 13 (postgame), 15 (timers) ✓
   - §7 notifications → Task 5 ✓
   - §8 data flow → Task 10 (CLI `default_runner`) ✓
   - §9 testing → Tasks 2–14 unit tests + Task 11 integration + Task 12 breaker integration ✓
   - §10 deployment → Tasks 15, 16, 18 ✓
   - §11 configuration → Tasks 2, 16 ✓
   - §12 safety → Tasks 3 (breaker), 4 (quarantine), 8 (deny list), 9 (budget cap) ✓

2. **No placeholders** — every step shows real code, real commands, real expected outputs.

3. **Type consistency** — `RunSummary` fields match between `notifier.py` and `cli.py` usage; `StrategyRow` used consistently; `ValidationResult` fields aligned.

4. **Order matters** — later tasks don't import modules created in still-later tasks.
