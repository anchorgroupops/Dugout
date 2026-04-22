# Multi-Team Dugout — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the single-team data pipeline into a multi-team one. Add `config/teams.yaml` + team registry, rewire the autopull CLI to loop over active teams, parameterize `gc_csv_ingest.py` and `gc_ingest_pipeline.py` by team, and scope the autopull state DB per-team.

**Architecture:** New `tools/team_registry.py` is the single source of truth for team metadata (loaded from `config/teams.yaml`). Autopull CLI loops over active teams with shared Playwright browser + shared session but per-team idempotency and notifications. State DB gets a `team_id` column via additive migration. Ingest scripts gain a `--team` CLI flag; the Sharks remain byte-identical by default.

**Tech Stack:** Python 3.11, PyYAML, pytest, SQLite3 (stdlib). No new runtime deps.

**Spec reference:** `docs/superpowers/specs/2026-04-22-multi-team-phase1-design.md`

**Depends on:** PR #53 (autopull) must be either merged to main or remain this branch's base.

---

## File Structure

**New:**
- `tools/team_registry.py` — `Team` dataclass, YAML loader, validation, registry helpers.
- `config/teams.yaml` — seeded with a single Sharks entry.
- `tests/test_team_registry.py` — 8 unit tests.
- `tests/autopull/test_multi_team.py` — multi-team CLI loop unit tests.

**Modified:**
- `tools/autopull/state.py` — migration + `team_id` scoping on `runs`, `schema_profile`.
- `tools/autopull/config.py` — remove `gc_team_id`, `gc_season_slug` fields.
- `tools/autopull/cli.py` — `default_runner` becomes a team loop.
- `tools/autopull/notifier.py` — `RunSummary.team_slug` + `team_name`.
- `tools/autopull/weekly_report.py` — group by team in summary.
- `tools/gc_csv_ingest.py` — add `team` parameter throughout; `--team` CLI flag.
- `tools/gc_ingest_pipeline.py` — same treatment.
- `tests/autopull/test_state.py` — add migration + scoping tests.
- `tests/autopull/test_cli.py` — multi-team loop scenarios.
- `tests/autopull/test_cli_integration.py` — serve two fixture pages.
- `requirements.txt` — add `PyYAML`.

---

## Task 1: Team registry module

**Files:**
- Create: `tools/team_registry.py`
- Create: `tests/test_team_registry.py`

- [ ] **Step 1: Write failing tests**

Write `tests/test_team_registry.py`:

```python
"""Tests for tools.team_registry."""
from __future__ import annotations
from pathlib import Path
import pytest
from tools import team_registry as tr


def _yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "teams.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def test_loads_single_team(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: abc123
    season_slug: 2026-spring-sharks
    name: The Sharks
    data_slug: sharks
    league: PCLL
    is_own_team: true
    active: true
""")
    teams = tr.load(path)
    assert len(teams) == 1
    assert teams[0].name == "The Sharks"
    assert teams[0].stats_url == "https://web.gc.com/teams/abc123/2026-spring-sharks/stats"


def test_load_active_filters(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: a
    season_slug: s1
    name: A
    data_slug: a
    active: true
  - id: b
    season_slug: s2
    name: B
    data_slug: b
    active: false
""")
    assert [t.data_slug for t in tr.load_active(path)] == ["a"]
    assert [t.data_slug for t in tr.load(path)] == ["a", "b"]


def test_duplicate_data_slug_raises(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: a
    season_slug: s
    name: A
    data_slug: dup
    active: true
  - id: b
    season_slug: s2
    name: B
    data_slug: dup
    active: true
""")
    with pytest.raises(tr.RegistryError, match="duplicate data_slug"):
        tr.load(path)


def test_duplicate_id_raises(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: same
    season_slug: s
    name: A
    data_slug: a
    active: true
  - id: same
    season_slug: s2
    name: B
    data_slug: b
    active: true
""")
    with pytest.raises(tr.RegistryError, match="duplicate id"):
        tr.load(path)


def test_bad_data_slug_format_raises(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: a
    season_slug: s
    name: A
    data_slug: "Has Spaces!"
    active: true
""")
    with pytest.raises(tr.RegistryError, match="data_slug"):
        tr.load(path)


def test_missing_file_uses_env_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("GC_TEAM_ID", "fallback_id")
    monkeypatch.setenv("GC_SEASON_SLUG", "fallback_season")
    teams = tr.load(tmp_path / "nope.yaml")
    assert len(teams) == 1
    assert teams[0].id == "fallback_id"
    assert teams[0].data_slug == "sharks"


def test_require_by_slug(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: a
    season_slug: s
    name: A
    data_slug: a_slug
    active: true
""")
    team = tr.require_by_slug("a_slug", path)
    assert team.id == "a"
    with pytest.raises(tr.RegistryError, match="unknown team"):
        tr.require_by_slug("does_not_exist", path)


def test_defaults_optional_fields(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: a
    season_slug: s
    name: A
    data_slug: a
    active: true
""")
    teams = tr.load(path)
    assert teams[0].league == ""
    assert teams[0].is_own_team is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_team_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.team_registry'`.

- [ ] **Step 3: Implement the registry**

Write `tools/team_registry.py`:

```python
"""Team registry — single source of truth for team metadata.

Teams are defined in `config/teams.yaml`. When that file is missing,
`load()` falls back to a synthetic single-team list seeded from legacy
env vars (GC_TEAM_ID, GC_SEASON_SLUG) so Phase 1 can ship without
requiring a `teams.yaml` to exist.
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")
_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "teams.yaml"


class RegistryError(RuntimeError):
    """Raised on malformed or inconsistent team registry data."""


@dataclass(frozen=True)
class Team:
    id: str
    season_slug: str
    name: str
    data_slug: str
    league: str = ""
    is_own_team: bool = True
    active: bool = True

    @property
    def stats_url(self) -> str:
        return f"https://web.gc.com/teams/{self.id}/{self.season_slug}/stats"


def load(path: Path | None = None) -> list[Team]:
    path = Path(path) if path else _DEFAULT_PATH
    if not path.exists():
        return _env_fallback()

    try:
        import yaml
    except ImportError as e:
        raise RegistryError("PyYAML is required to read teams.yaml") from e

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    if not isinstance(data, dict) or "teams" not in data:
        raise RegistryError(f"{path}: top-level key 'teams' missing")

    raw = data["teams"]
    if not isinstance(raw, list) or not raw:
        raise RegistryError(f"{path}: 'teams' must be a non-empty list")

    teams: list[Team] = []
    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise RegistryError(f"{path}[{idx}]: each team must be a mapping")
        team = _parse_team(entry, source=f"{path}[{idx}]")
        if team.id in seen_ids:
            raise RegistryError(f"{path}: duplicate id {team.id!r}")
        if team.data_slug in seen_slugs:
            raise RegistryError(f"{path}: duplicate data_slug {team.data_slug!r}")
        seen_ids.add(team.id)
        seen_slugs.add(team.data_slug)
        teams.append(team)

    return teams


def load_active(path: Path | None = None) -> list[Team]:
    return [t for t in load(path) if t.active]


def require_by_slug(slug: str, path: Path | None = None) -> Team:
    for t in load(path):
        if t.data_slug == slug:
            return t
    raise RegistryError(f"unknown team: {slug!r}")


def _parse_team(entry: dict[str, Any], *, source: str) -> Team:
    required = ("id", "season_slug", "name", "data_slug", "active")
    for key in required:
        if key not in entry:
            raise RegistryError(f"{source}: missing required field {key!r}")

    data_slug = str(entry["data_slug"])
    if not _SLUG_RE.match(data_slug):
        raise RegistryError(
            f"{source}: data_slug {data_slug!r} must match [a-z0-9_-]+"
        )
    team_id = str(entry["id"]).strip()
    if not team_id:
        raise RegistryError(f"{source}: id must be non-empty")

    return Team(
        id=team_id,
        season_slug=str(entry["season_slug"]),
        name=str(entry["name"]),
        data_slug=data_slug,
        league=str(entry.get("league", "")),
        is_own_team=bool(entry.get("is_own_team", True)),
        active=bool(entry["active"]),
    )


def _env_fallback() -> list[Team]:
    team_id = os.getenv("GC_TEAM_ID", "").strip()
    season = os.getenv("GC_SEASON_SLUG", "").strip()
    if not team_id or not season:
        raise RegistryError(
            "No teams.yaml and GC_TEAM_ID/GC_SEASON_SLUG not set"
        )
    return [Team(
        id=team_id,
        season_slug=season,
        name="The Sharks",
        data_slug="sharks",
        league="PCLL",
        is_own_team=True,
        active=True,
    )]
```

- [ ] **Step 4: Add PyYAML to requirements**

Append to `requirements.txt`:

```
# Multi-team registry
PyYAML>=6.0,<7
```

Install in the dev venv:

```bash
/tmp/dugout-venv/bin/pip install 'PyYAML>=6.0,<7'
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_team_registry.py -v`
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add tools/team_registry.py tests/test_team_registry.py requirements.txt
git commit -m "feat(team-registry): Team dataclass + teams.yaml loader with env fallback"
```

---

## Task 2: Seed `config/teams.yaml`

**Files:**
- Create: `config/teams.yaml`

- [ ] **Step 1: Check config dir exists**

Run: `ls -d config/ 2>/dev/null && echo ok || mkdir -p config`
Expected: either `ok` or silent `mkdir`.

- [ ] **Step 2: Write seed file**

Write `config/teams.yaml`:

```yaml
# Dugout team registry — source of truth for multi-team autopull + ingest.
# Add a new team by appending a new list entry. Pause a team with active: false.
# See docs/superpowers/specs/2026-04-22-multi-team-phase1-design.md §4 for schema.

teams:
  - id: NuGgx6WvP7TO
    season_slug: 2026-spring-sharks
    name: The Sharks
    data_slug: sharks
    league: PCLL
    is_own_team: true
    active: true
```

- [ ] **Step 3: Verify registry loads it**

Run: `/tmp/dugout-venv/bin/python -c "from tools.team_registry import load; print([t.name for t in load()])"`
Expected: `['The Sharks']`

- [ ] **Step 4: Commit**

```bash
git add config/teams.yaml
git commit -m "feat(team-registry): seed teams.yaml with Sharks entry"
```

---

## Task 3: State DB — `team_id` migration

**Files:**
- Modify: `tools/autopull/state.py`
- Modify: `tests/autopull/test_state.py`

- [ ] **Step 1: Write failing migration tests**

Append to `tests/autopull/test_state.py`:

```python
# --- Multi-team migration tests -----------------------------------------------


def test_migration_adds_team_id_column(tmp_db_path):
    # Pre-create a legacy DB with no team_id column.
    import sqlite3
    conn = sqlite3.connect(str(tmp_db_path))
    conn.executescript("""
        CREATE TABLE runs (
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
        INSERT INTO runs(started_at, trigger, outcome) VALUES('2026-04-22', 'cron', 'success');
        CREATE TABLE schema_profile (
          observed_at TEXT PRIMARY KEY,
          column_names_json TEXT NOT NULL,
          row_count INTEGER NOT NULL
        );
        INSERT INTO schema_profile VALUES('2026-04-22', '["AB","H"]', 20);
    """)
    conn.commit()
    conn.close()

    db = StateDB(tmp_db_path)
    db.init_schema()

    # runs.team_id present with 'sharks' backfill
    with db._conn() as c:
        cols = [r["name"] for r in c.execute("PRAGMA table_info(runs)").fetchall()]
        assert "team_id" in cols
        row = c.execute("SELECT team_id FROM runs").fetchone()
        assert row["team_id"] == "sharks"

        # schema_profile gains team_id, old row migrated
        cols2 = [r["name"] for r in c.execute("PRAGMA table_info(schema_profile)").fetchall()]
        assert "team_id" in cols2
        row2 = c.execute("SELECT team_id FROM schema_profile").fetchone()
        assert row2["team_id"] == "sharks"


def test_last_successful_run_scoped_by_team(tmp_db_path):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    db = StateDB(tmp_db_path); db.init_schema()
    now = datetime.now(et)

    rid_s = db.start_run(trigger="cron", team_id="sharks",
                         started_at=now - timedelta(minutes=5))
    db.complete_run(rid_s, outcome="success", csv_path=None, rows_ingested=1,
                    winning_strategy_id=None, duration_ms=1,
                    llm_fallback_invoked=False, session_refreshed=False,
                    completed_at=now - timedelta(minutes=5))

    # Sharks succeeded within 15m; Dolphins did not run at all.
    assert db.last_successful_run_within(15, team_id="sharks") is not None
    assert db.last_successful_run_within(15, team_id="dolphins") is None


def test_record_schema_scoped_by_team(tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    db.record_schema(["AB", "H"], row_count=10, team_id="sharks")
    db.record_schema(["AB", "H", "BB"], row_count=12, team_id="sharks")
    db.record_schema(["X", "Y"], row_count=3, team_id="dolphins")
    sharks_latest, sharks_prior = db.last_two_schemas(team_id="sharks")
    dolphins_latest, dolphins_prior = db.last_two_schemas(team_id="dolphins")
    assert sharks_latest == ["AB", "BB", "H"]
    assert sharks_prior == ["AB", "H"]
    assert dolphins_latest == ["X", "Y"]
    assert dolphins_prior is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/autopull/test_state.py -v -k "team_id or scoped"`
Expected: FAIL — `start_run()` takes no `team_id` kwarg yet.

- [ ] **Step 3: Implement the migration and scoping**

Replace the contents of `tools/autopull/state.py` with the updated version. The key changes:

1. `SCHEMA_SQL` — add `team_id` to `runs` and rebuild `schema_profile`:

```python
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  trigger TEXT NOT NULL,
  team_id TEXT NOT NULL DEFAULT 'sharks',
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
  team_id TEXT NOT NULL DEFAULT 'sharks',
  observed_at TEXT NOT NULL,
  column_names_json TEXT NOT NULL,
  row_count INTEGER NOT NULL,
  PRIMARY KEY(team_id, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at);
CREATE INDEX IF NOT EXISTS idx_runs_team ON runs(team_id);
CREATE INDEX IF NOT EXISTS idx_strategies_enabled ON strategies(enabled);
"""
```

2. Add a `_migrate()` step in `init_schema` that detects legacy tables and upgrades in place:

```python
    def init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA_SQL)
            self._migrate_runs_team_id(c)
            self._migrate_schema_profile(c)

    @staticmethod
    def _migrate_runs_team_id(conn) -> None:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(runs)").fetchall()]
        if "team_id" in cols:
            return
        conn.execute("ALTER TABLE runs ADD COLUMN team_id TEXT NOT NULL DEFAULT 'sharks'")
        conn.execute("UPDATE runs SET team_id='sharks' WHERE team_id IS NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_team ON runs(team_id)")

    @staticmethod
    def _migrate_schema_profile(conn) -> None:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(schema_profile)").fetchall()]
        if "team_id" in cols:
            return
        # Rebuild with team_id + composite PK
        conn.executescript("""
            CREATE TABLE schema_profile_v2 (
              team_id TEXT NOT NULL DEFAULT 'sharks',
              observed_at TEXT NOT NULL,
              column_names_json TEXT NOT NULL,
              row_count INTEGER NOT NULL,
              PRIMARY KEY(team_id, observed_at)
            );
            INSERT OR IGNORE INTO schema_profile_v2(team_id, observed_at, column_names_json, row_count)
              SELECT 'sharks', observed_at, column_names_json, row_count FROM schema_profile;
            DROP TABLE schema_profile;
            ALTER TABLE schema_profile_v2 RENAME TO schema_profile;
        """)
```

3. `start_run` and `complete_run` gain `team_id`:

```python
    def start_run(self, trigger: str, team_id: str = "sharks",
                  started_at: datetime | None = None) -> int:
        started = (started_at or datetime.now(ET)).isoformat()
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO runs(started_at, trigger, team_id, outcome) VALUES(?,?,?,?)",
                (started, trigger, team_id, "in_progress"),
            )
            return int(cur.lastrowid)
```

4. `last_successful_run_within` gains an optional `team_id`:

```python
    def last_successful_run_within(self, minutes: int,
                                   team_id: str | None = None) -> RunRow | None:
        cutoff = (datetime.now(ET) - timedelta(minutes=minutes)).isoformat()
        sql = ("SELECT * FROM runs WHERE outcome='success' AND completed_at >= ? ")
        args: list = [cutoff]
        if team_id is not None:
            sql += "AND team_id=? "
            args.append(team_id)
        sql += "ORDER BY completed_at DESC LIMIT 1"
        with self._conn() as c:
            r = c.execute(sql, tuple(args)).fetchone()
            return RunRow(**dict(r)) if r else None
```

5. `record_schema` and `last_two_schemas` gain `team_id`:

```python
    def record_schema(self, columns: Iterable[str], row_count: int,
                      team_id: str = "sharks") -> None:
        cols = sorted(columns)
        now = datetime.now(ET).isoformat()
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO schema_profile(team_id, observed_at, "
                "column_names_json, row_count) VALUES(?,?,?,?)",
                (team_id, now, json.dumps(cols), row_count),
            )

    def last_two_schemas(self, team_id: str = "sharks") -> tuple[list[str] | None, list[str] | None]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT column_names_json FROM schema_profile WHERE team_id=? "
                "ORDER BY observed_at DESC LIMIT 2",
                (team_id,),
            ).fetchall()
        if not rows:
            return None, None
        latest = json.loads(rows[0]["column_names_json"])
        prior = json.loads(rows[1]["column_names_json"]) if len(rows) > 1 else None
        return latest, prior
```

6. `RunRow` dataclass gains `team_id: str` field right after `trigger`:

```python
@dataclass
class RunRow:
    id: int
    started_at: str
    completed_at: str | None
    trigger: str
    team_id: str
    outcome: str
    csv_path: str | None
    rows_ingested: int | None
    winning_strategy_id: int | None
    failure_reason: str | None
    duration_ms: int | None
    llm_fallback_invoked: int
    session_refreshed: int
```

- [ ] **Step 4: Run all state tests to verify**

Run: `pytest tests/autopull/test_state.py -v`
Expected: all state tests pass (original + 3 new migration tests).

- [ ] **Step 5: Commit**

```bash
git add tools/autopull/state.py tests/autopull/test_state.py
git commit -m "feat(autopull/state): team_id scoping + additive migration"
```

---

## Task 4: Autopull config — drop team fields

**Files:**
- Modify: `tools/autopull/config.py`
- Modify: `tests/autopull/test_config.py`
- Modify: `tests/autopull/test_cli.py` (fixture update)
- Modify: `tests/autopull/test_circuit_breaker_integration.py` (fixture update)

- [ ] **Step 1: Remove team fields from AutopullConfig**

In `tools/autopull/config.py`:

1. Remove `gc_team_id: str` and `gc_season_slug: str` from the `AutopullConfig` dataclass.
2. Remove the corresponding two lines in `load()` that read `GC_TEAM_ID` / `GC_SEASON_SLUG`.

The fields now live in `config/teams.yaml` and the env-var fallback path is in `team_registry._env_fallback()`.

- [ ] **Step 2: Update test fixtures in test_cli.py and test_circuit_breaker_integration.py**

In both files, remove these two lines from the `_fake_cfg` / `_cfg` helper:

```python
    gc_team_id="T", gc_season_slug="S",
```

And (in test_cli.py) from the `base` dict inside `_fake_cfg`:

```python
    gc_team_id="T", gc_season_slug="S",
```

- [ ] **Step 3: Run tests to verify**

Run: `pytest tests/autopull/ -v --ignore=tests/autopull/test_cli_integration.py`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tools/autopull/config.py tests/autopull/
git commit -m "refactor(autopull/config): drop team fields (now in teams.yaml)"
```

---

## Task 5: Notifier — team in RunSummary

**Files:**
- Modify: `tools/autopull/notifier.py`
- Modify: `tests/autopull/test_notifier.py`

- [ ] **Step 1: Update tests**

In `tests/autopull/test_notifier.py`, change `_summary()` to include team:

```python
def _summary(outcome="success", failure_reason=None, drift="none",
             team_slug="sharks", team_name="The Sharks"):
    return n.RunSummary(
        run_id=42,
        trigger="cron",
        team_slug=team_slug,
        team_name=team_name,
        outcome=outcome,
        failure_reason=failure_reason,
        csv_path="/tmp/x.csv" if outcome == "success" else None,
        rows_ingested=100 if outcome == "success" else None,
        duration_ms=2500,
        drift_severity=drift,
    )
```

Add a new test:

```python
def test_subject_and_push_include_team_name():
    gmail = MagicMock()
    n8n = MagicMock()
    push = MagicMock()
    notifier = n.Notifier(gmail_sender=gmail, n8n_poster=n8n, pusher=push,
                          status_webhook_url="https://x/y", notify_to_email="a@b")
    notifier.emit(_summary(outcome="failure", failure_reason="auth",
                           team_name="The Dolphins"))
    subject = gmail.send.call_args.kwargs["subject"]
    assert "Dolphins" in subject
    msg = push.notify.call_args[0][0]
    assert "Dolphins" in msg
```

- [ ] **Step 2: Update RunSummary dataclass**

In `tools/autopull/notifier.py`, change the dataclass definition:

```python
@dataclass
class RunSummary:
    run_id: int
    trigger: str
    team_slug: str
    team_name: str
    outcome: str
    failure_reason: str | None
    csv_path: str | None
    rows_ingested: int | None
    duration_ms: int | None
    drift_severity: str = "none"
```

- [ ] **Step 3: Update subject and push message**

In `_send_email`:

```python
        subject = f"[Dugout Autopull] {s.outcome.upper()} {s.team_name} run #{s.run_id}"
```

In `_short_message`:

```python
    @staticmethod
    def _short_message(s: "RunSummary") -> str:
        tag = f"[{s.team_name}]"
        if s.drift_severity == "critical":
            return f"GC schema drift CRITICAL {tag} (run #{s.run_id})"
        if s.outcome == "failure":
            return f"GC autopull failed: {s.failure_reason or 'unknown'} {tag} (#{s.run_id})"
        if s.outcome == "quarantined":
            return f"GC autopull quarantined: {s.failure_reason or 'bad CSV'} {tag} (#{s.run_id})"
        return f"GC autopull: {s.outcome} {tag} (#{s.run_id})"
```

Also add `Team: {s.team_name}` to the email body's `body_lines` list right after `f"Trigger: {s.trigger}"`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/autopull/test_notifier.py -v`
Expected: 6 passed (5 original + 1 new).

- [ ] **Step 5: Commit**

```bash
git add tools/autopull/notifier.py tests/autopull/test_notifier.py
git commit -m "feat(autopull/notifier): include team in subject + push message"
```

---

## Task 6: CLI multi-team loop

**Files:**
- Modify: `tools/autopull/cli.py`
- Modify: `tests/autopull/test_cli.py`
- Create: `tests/autopull/test_multi_team.py`

- [ ] **Step 1: Update test_cli.py runner signature**

The tests pass `runner` as a callable. Its signature changes from `runner(cfg=..., db=..., run_id=...)` to `runner(cfg=..., db=..., run_id=..., team=...)`. Update the `runner` mocks in each existing `test_cli.py` test to accept a `team` kwarg — `MagicMock` already does this so most tests don't need changes. Only the idempotency test needs updating:

```python
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

    # Create a teams.yaml with only the Sharks so the idempotency check sees it
    teams_path = tmp_path / "teams.yaml"
    teams_path.write_text("teams:\n  - {id: a, season_slug: s, name: The Sharks, "
                          "data_slug: sharks, active: true}\n")

    result = cli.run_once(cfg=cfg, trigger="cron", runner=runner,
                          teams_path=teams_path)
    assert result["outcome"] == "all_skipped"
    assert "sharks" in result["per_team"]
    assert result["per_team"]["sharks"]["outcome"] == "skipped"
    assert runner.called is False
```

Update similar shape in `test_skip_when_disabled`, `test_skip_when_breaker_open`,
`test_runner_invoked_when_eligible`, `test_runner_exception_recorded_as_failure`:

```python
def test_skip_when_disabled(tmp_path):
    cfg = _fake_cfg(tmp_path, enabled=False)
    result = cli.run_once(cfg=cfg, trigger="cron", runner=MagicMock(),
                          teams_path=_single_team_yaml(tmp_path))
    assert result["outcome"] == "skipped"
    assert result["reason"] == "disabled"
```

Add a helper at top of `test_cli.py`:

```python
def _single_team_yaml(tmp_path):
    p = tmp_path / "teams.yaml"
    p.write_text("teams:\n  - {id: a, season_slug: s, name: The Sharks, "
                 "data_slug: sharks, active: true}\n")
    return p
```

- [ ] **Step 2: Write multi-team tests**

Write `tests/autopull/test_multi_team.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/autopull/test_multi_team.py tests/autopull/test_cli.py -v`
Expected: most failing — `run_once` doesn't accept `teams_path` yet.

- [ ] **Step 4: Rewrite `run_once` as a multi-team loop**

In `tools/autopull/cli.py`, replace `run_once` with:

```python
def run_once(*, cfg: config_mod.AutopullConfig, trigger: str,
             runner: Callable[..., dict],
             teams_path: Path | None = None) -> dict:
    """Orchestrate one autopull sweep over all active teams.

    Returns a dict with an aggregate `outcome` plus `per_team` details:
      - 'disabled', 'skipped' — global short-circuit before any team runs
      - 'all_success' — every eligible team succeeded
      - 'all_skipped' — every team was skipped (idempotency or breaker)
      - 'partial' — mixed success/failure across teams
      - 'failure' — every eligible team failed
    """
    db_path = cfg.data_root / "autopull" / "autopull_state.db"
    db = StateDB(db_path)
    db.init_schema()

    if not cfg.enabled:
        return {"outcome": "skipped", "reason": "disabled"}
    if trigger == "postgame" and not cfg.postgame_enabled:
        return {"outcome": "skipped", "reason": "postgame disabled"}

    # Load active teams from the registry.
    from tools import team_registry
    try:
        teams = team_registry.load_active(teams_path)
    except team_registry.RegistryError as e:
        return {"outcome": "failure", "failure_reason": f"bad teams.yaml: {e}"}
    if not teams:
        return {"outcome": "skipped", "reason": "no active teams"}

    # Global auth breaker — one login serves all teams.
    if db.breaker_open("auth"):
        return {"outcome": "skipped", "reason": "auth breaker open"}

    per_team: dict[str, dict] = {}
    for team in teams:
        per_team[team.data_slug] = _run_team(
            cfg=cfg, db=db, trigger=trigger, runner=runner, team=team,
        )

    # Aggregate outcome
    outcomes = [v["outcome"] for v in per_team.values()]
    if all(o == "skipped" for o in outcomes):
        agg = "all_skipped"
    elif all(o == "success" for o in outcomes):
        agg = "all_success"
    elif any(o == "success" for o in outcomes):
        agg = "partial"
    else:
        agg = "failure"
    return {"outcome": agg, "per_team": per_team}


def _run_team(*, cfg, db, trigger, runner, team) -> dict:
    """Drive one team through start_run → runner → complete_run."""
    import time

    recent = db.last_successful_run_within(
        minutes=cfg.idempotency_window_min, team_id=team.data_slug,
    )
    if recent is not None:
        return {"outcome": "skipped",
                "reason": f"recent success within {cfg.idempotency_window_min}m "
                          f"(run #{recent.id})"}

    run_id = db.start_run(trigger=trigger, team_id=team.data_slug)
    started = time.monotonic()
    try:
        out = runner(cfg=cfg, db=db, run_id=run_id, team=team)
    except Exception as e:
        log.exception("runner raised for team %s", team.data_slug)
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
        db.breaker_reset(f"download:{team.data_slug}")
    return {"outcome": outcome, "run_id": run_id, **out}
```

- [ ] **Step 5: Rewrite `default_runner` to accept `team` and write to team-scoped dirs**

Replace `default_runner` in `tools/autopull/cli.py`:

```python
def default_runner(*, cfg: config_mod.AutopullConfig,
                   db: StateDB, run_id: int, team) -> dict:
    """Actual run for one team: Playwright + locator + validate + ingest."""
    from playwright.sync_api import sync_playwright
    from tools.autopull import (
        session_manager as sm,
        locator_engine as le,
        csv_validator as cv,
        gmail_2fa_fetcher as g2fa,
        llm_adapter as lla,
    )
    le.seed_builtin_strategies(db)

    staging = cfg.data_root / "autopull" / "staging" / team.data_slug
    quarantine = cfg.data_root / "autopull" / "quarantine" / team.data_slug
    team_dir = cfg.data_root / team.data_slug
    staging.mkdir(parents=True, exist_ok=True)
    quarantine.mkdir(parents=True, exist_ok=True)
    team_dir.mkdir(parents=True, exist_ok=True)

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
            api_key=cfg.anthropic_api_key, model=cfg.llm_model,
        )
    engine = le.LocatorEngine(
        db=db, llm_adapter=llm, llm_enabled=cfg.llm_adapt_enabled,
    )

    with sync_playwright() as pw:
        page, refreshed = session.new_logged_in_page(pw, headless=True)
        page.goto(team.stats_url, wait_until="networkidle", timeout=60_000)
        result = engine.find_and_download(page, out_dir=staging)

    if result.downloaded_path is None:
        return {
            "outcome": "failure",
            "failure_reason": "No strategy located the CSV export button",
            "llm_fallback_invoked": result.llm_used,
            "session_refreshed": refreshed,
        }

    latest_cols, _ = db.last_two_schemas(team_id=team.data_slug)
    val = cv.validate(result.downloaded_path, known_columns=latest_cols)
    if not val.accepted:
        cv.quarantine(result.downloaded_path, val, quarantine_root=quarantine)
        return {
            "outcome": "quarantined", "failure_reason": val.reason,
            "llm_fallback_invoked": result.llm_used,
            "session_refreshed": refreshed,
            "drift_severity": val.drift_severity,
        }

    db.record_schema(val.columns, val.row_count, team_id=team.data_slug)

    final = team_dir / f"season_stats_{datetime.now(ET).strftime('%Y%m%d')}.csv"
    result.downloaded_path.replace(final)

    # Ingest: pass the team slug so gc_csv_ingest writes into data/<slug>/.
    import subprocess
    rc = subprocess.run(
        [sys.executable,
         str(Path(__file__).resolve().parents[1] / "gc_csv_ingest.py"),
         "--team", team.data_slug, str(final)],
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
```

- [ ] **Step 6: Update `_summary_from_result` and `main` for multi-team fan-out**

Replace the helper and main:

```python
def _summaries_from_result(result: dict, trigger: str) -> list:
    """Flatten a multi-team run_once result into per-team RunSummary objects."""
    from tools.autopull.notifier import RunSummary
    from tools import team_registry

    per_team = result.get("per_team") or {}
    if not per_team:
        # Global short-circuit (disabled, skipped, bad config). One empty summary.
        return [RunSummary(
            run_id=-1, trigger=trigger,
            team_slug="*", team_name="(all teams)",
            outcome=result.get("outcome", "skipped"),
            failure_reason=result.get("reason") or result.get("failure_reason"),
            csv_path=None, rows_ingested=None, duration_ms=None,
            drift_severity="none",
        )]

    summaries = []
    for slug, out in per_team.items():
        try:
            team_name = team_registry.require_by_slug(slug).name
        except Exception:
            team_name = slug
        summaries.append(RunSummary(
            run_id=out.get("run_id", -1),
            trigger=trigger,
            team_slug=slug,
            team_name=team_name,
            outcome=out.get("outcome", "failure"),
            failure_reason=out.get("failure_reason"),
            csv_path=out.get("csv_path"),
            rows_ingested=out.get("rows_ingested"),
            duration_ms=out.get("duration_ms"),
            drift_severity=out.get("drift_severity", "none"),
        ))
    return summaries


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dugout GC CSV autopull")
    ap.add_argument("--trigger", choices=["cron", "postgame", "manual"],
                    default="manual")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config_mod.load(require_gmail=True)
    result = run_once(cfg=cfg, trigger=args.trigger, runner=default_runner)

    # Fan out per-team notifications (skipped runs stay silent overall).
    if result.get("outcome") not in ("skipped",):
        try:
            notifier = _build_notifier(cfg)
            for summary in _summaries_from_result(result, args.trigger):
                notifier.emit(summary)
        except Exception as e:
            log.exception("notifier wiring failed: %s", e)

    print(json.dumps(result, indent=2, default=str))
    # Exit 0 for all_success / all_skipped / skipped; otherwise 1.
    return 0 if result.get("outcome") in ("all_success", "all_skipped", "skipped") else 1
```

- [ ] **Step 7: Run full autopull test suite**

Run: `pytest tests/autopull/ -v --ignore=tests/autopull/test_cli_integration.py`
Expected: every test green (existing + new multi-team).

- [ ] **Step 8: Commit**

```bash
git add tools/autopull/cli.py tests/autopull/test_cli.py tests/autopull/test_multi_team.py
git commit -m "feat(autopull/cli): multi-team loop with per-team idempotency + fan-out"
```

---

## Task 7: Weekly report — group by team

**Files:**
- Modify: `tools/autopull/weekly_report.py`
- Modify: `tests/autopull/test_weekly_report.py`

- [ ] **Step 1: Add a test for per-team grouping**

Append to `tests/autopull/test_weekly_report.py`:

```python
def test_summary_groups_by_team(tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))

    for team, oc in [("sharks", "success"), ("sharks", "success"),
                     ("dolphins", "failure")]:
        rid = db.start_run(trigger="cron", team_id=team, started_at=now)
        db.complete_run(rid, outcome=oc, csv_path=None, rows_ingested=5,
                        winning_strategy_id=None, duration_ms=100,
                        llm_fallback_invoked=False, session_refreshed=False,
                        completed_at=now)
    summary = wr.build_summary(db, days=7)
    assert "by_team" in summary
    assert summary["by_team"]["sharks"]["success"] == 2
    assert summary["by_team"]["dolphins"]["failure"] == 1
```

- [ ] **Step 2: Update `build_summary` to include `by_team`**

In `tools/autopull/weekly_report.py`, inside `build_summary`, add the team grouping:

```python
def build_summary(db: StateDB, *, days: int = 7) -> dict:
    cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
    with db._conn() as c:
        rows = c.execute(
            "SELECT outcome, llm_fallback_invoked, winning_strategy_id, "
            "session_refreshed, failure_reason, team_id "
            "FROM runs WHERE started_at >= ?",
            (cutoff,),
        ).fetchall()
    by_outcome: Counter = Counter()
    by_winner: Counter = Counter()
    by_team: dict[str, Counter] = {}
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
        team = r["team_id"] or "sharks"
        by_team.setdefault(team, Counter())[r["outcome"]] += 1
    return {
        "generated_at": datetime.now(ET).isoformat(),
        "window_days": days,
        "total_runs": len(rows),
        "by_outcome": dict(by_outcome),
        "by_team": {k: dict(v) for k, v in by_team.items()},
        "top_winning_strategies": by_winner.most_common(5),
        "llm_fallback_invocations": llm_count,
        "session_refreshes": refresh_count,
        "recent_failures": failures[-10:],
    }
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/autopull/test_weekly_report.py -v`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add tools/autopull/weekly_report.py tests/autopull/test_weekly_report.py
git commit -m "feat(autopull/weekly-report): group runs by team"
```

---

## Task 8: `gc_csv_ingest.py` — parameterize by team

**Files:**
- Modify: `tools/gc_csv_ingest.py`

- [ ] **Step 1: Add team-aware helpers at top of file**

Near the top of `tools/gc_csv_ingest.py`, after the existing `DATA_DIR` / `SHARKS_DIR` constants, add:

```python
from tools.team_registry import Team, require_by_slug

def _team_dir(team: "Team") -> Path:
    return DATA_DIR / team.data_slug


def _default_team() -> "Team":
    """Back-compat fallback when no --team flag is given."""
    return require_by_slug("sharks")
```

Keep `SHARKS_DIR = DATA_DIR / "sharks"` unchanged — nothing should break.

- [ ] **Step 2: Change the main write points to accept a Team**

The file has roughly 7 call sites that write into `SHARKS_DIR`. Change each to accept an explicit `team_dir: Path` parameter. Specifically, in the docstring and in each function body that currently writes to `SHARKS_DIR / "team.json"`, `SHARKS_DIR / "app_stats.json"`, `SHARKS_DIR / "season_stats.csv"`, `SHARKS_DIR / "roster_manifest.json"`:

1. Rename `SHARKS_DIR` references inside write functions to `team_dir`, making `team_dir` an explicit parameter on those functions.
2. The `"team_name": "The Sharks"` default in the `team.json` construction becomes `"team_name": team.name`.

Since this file is large (664 lines), a precise diff is impractical to write inline. Instead, the rule is:

> Every occurrence of `SHARKS_DIR` in a **write path** (files opened for `"w"`) becomes a parameter passed in from `main()`. The constant `SHARKS_DIR` stays defined for any legacy read path that hasn't been refactored yet.

- [ ] **Step 3: Rewrite `main()` with --team**

Change `main()` to:

```python
def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Ingest a GC CSV for one team.")
    ap.add_argument("csv_path")
    ap.add_argument("--team", default="sharks",
                    help="data_slug from config/teams.yaml (default: sharks)")
    args = ap.parse_args()

    team = require_by_slug(args.team)
    team_dir = _team_dir(team)
    team_dir.mkdir(parents=True, exist_ok=True)

    csv_path = Path(args.csv_path)
    # Call the existing ingest pipeline, passing team + team_dir down.
    _run(team=team, team_dir=team_dir, csv_path=csv_path)
```

Where `_run` is a newly-extracted top-level function that wraps what `main()` used to do, but threads `team` / `team_dir` through to every write.

- [ ] **Step 4: Smoke test**

Run the existing Sharks CSV through the new CLI:

```bash
/tmp/dugout-venv/bin/python tools/gc_csv_ingest.py --team sharks tests/autopull/fixtures/season_stats_sample.csv
```

Expected: `data/sharks/team.json`, `data/sharks/season_stats.csv`, `data/sharks/app_stats.json` updated without error. Diff against the pre-refactor output should show only path-equivalent output (same contents, same filenames).

- [ ] **Step 5: Run existing ingest tests**

Run: `pytest tests/ -k "ingest or csv" -v --ignore=tests/autopull/test_cli_integration.py 2>&1 | tail -20`
Expected: all existing green.

- [ ] **Step 6: Commit**

```bash
git add tools/gc_csv_ingest.py
git commit -m "refactor(gc_csv_ingest): parameterize by team via --team flag"
```

---

## Task 9: `gc_ingest_pipeline.py` — parameterize by team

**Files:**
- Modify: `tools/gc_ingest_pipeline.py`

- [ ] **Step 1: Apply the same refactor pattern**

Follow exactly the same recipe as Task 8 for `tools/gc_ingest_pipeline.py`:

1. Import `from tools.team_registry import require_by_slug`.
2. Keep `SHARKS_DIR = _ROOT_DIR / "data" / "sharks"` for legacy compat.
3. Add a `_team_dir(team)` helper.
4. Change `main()` to accept `--team <slug>` (default `sharks`), look up the team, pass `team`/`team_dir` into the pipeline function.
5. Update the `"team_name": "The Sharks"` default to `team.name`.
6. Keep the `stats_db.record_sharks_snapshot` and `swot_analyzer.run_sharks_analysis` calls **unchanged** — Phase 2 parameterizes those. In Phase 1 they only fire when `team.data_slug == "sharks"`:

```python
    if team.data_slug == "sharks":
        # Phase 1 keeps analysis Sharks-only. Phase 2 parameterizes these.
        from stats_db import record_sharks_snapshot
        snapshot_id = record_sharks_snapshot(...)
        from swot_analyzer import run_sharks_analysis
        swot_result = run_sharks_analysis()
    else:
        logging.info("Phase 1: skipping SWOT/stats_db for non-Sharks team %s",
                     team.data_slug)
```

- [ ] **Step 2: Smoke test**

Run: `/tmp/dugout-venv/bin/python tools/gc_ingest_pipeline.py --team sharks --csv tests/autopull/fixtures/season_stats_sample.csv`
Expected: exits 0, writes into `data/sharks/`.

- [ ] **Step 3: Commit**

```bash
git add tools/gc_ingest_pipeline.py
git commit -m "refactor(gc_ingest_pipeline): parameterize by team, gate SWOT to sharks"
```

---

## Task 10: Multi-team integration test

**Files:**
- Modify: `tests/autopull/test_cli_integration.py`
- Create: `tests/autopull/fixtures/dolphins_stats_page.html`

- [ ] **Step 1: Create the second team fixture**

Write `tests/autopull/fixtures/dolphins_stats_page.html`:

```html
<!DOCTYPE html>
<html>
<head><title>Dolphins Stats</title></head>
<body>
  <h1>Season Stats — Dolphins</h1>
  <button data-testid="export-csv" id="dl">Export CSV</button>
  <script>
    document.getElementById('dl').addEventListener('click', function() {
      const blob = new Blob(
        ["Player,AB,H,BB,K,HBP,RBI,BA,OBP,SLG\n" +
         "Finn Green,22,10,4,3,0,7,0.455,0.538,0.727\n" +
         "Marina Blue,19,6,3,6,1,4,0.316,0.391,0.421\n"],
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

- [ ] **Step 2: Add a multi-team test**

Append to `tests/autopull/test_cli_integration.py`:

```python
def test_two_teams_land_in_separate_dirs(tmp_db_path, tmp_path, local_http_server):
    db = StateDB(tmp_db_path); db.init_schema()
    le.seed_builtin_strategies(db)
    engine = le.LocatorEngine(db=db, llm_adapter=None, llm_enabled=False)
    staging_a = tmp_path / "staging" / "sharks"; staging_a.mkdir(parents=True)
    staging_b = tmp_path / "staging" / "dolphins"; staging_b.mkdir(parents=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()

        page.goto(local_http_server, wait_until="networkidle")
        r1 = engine.find_and_download(page, out_dir=staging_a)

        # Navigate to the dolphins page served by the same fixtures dir
        base = local_http_server.rsplit("/", 1)[0]
        page.goto(f"{base}/dolphins_stats_page.html", wait_until="networkidle")
        r2 = engine.find_and_download(page, out_dir=staging_b)
        browser.close()

    assert r1.downloaded_path is not None
    assert r2.downloaded_path is not None
    assert r1.downloaded_path.read_text() != r2.downloaded_path.read_text()
    # Dolphins CSV includes the unique player name
    assert "Finn Green" in r2.downloaded_path.read_text()
    assert "Finn Green" not in r1.downloaded_path.read_text()
```

- [ ] **Step 3: Verify it skips cleanly on dev without Playwright**

Run: `pytest tests/autopull/test_cli_integration.py -v`
Expected: 2 skipped (dev env has no Playwright); pass on the Pi when `playwright install chromium` is done.

- [ ] **Step 4: Commit**

```bash
git add tests/autopull/fixtures/dolphins_stats_page.html tests/autopull/test_cli_integration.py
git commit -m "test(autopull): integration test for two-team CSV download"
```

---

## Task 11: Full suite regression + coverage

- [ ] **Step 1: Run the whole suite**

Run: `/tmp/dugout-venv/bin/python -m pytest tests/ --ignore=tests/autopull/test_cli_integration.py -q 2>&1 | tail -15`
Expected: the pre-existing `structlog` test_api errors remain (not our concern). Every other test green.

- [ ] **Step 2: Coverage on autopull + team_registry**

Run: `/tmp/dugout-venv/bin/python -m pytest tests/autopull/ tests/test_team_registry.py --cov=tools.autopull --cov=tools.team_registry --cov-report=term-missing --ignore=tests/autopull/test_cli_integration.py -q 2>&1 | tail -20`
Expected: every module ≥85% except the Playwright/real-Gmail integration paths (same carve-out as the prior plan).

- [ ] **Step 3: Commit any follow-up test additions if coverage slipped**

```bash
git add tests/autopull/ tests/test_team_registry.py 2>/dev/null
git commit -m "test(autopull): restore coverage after multi-team refactor" || true
```

---

## Task 12: Push and open PR

- [ ] **Step 1: Push the branch**

Run: `git push 2>&1 | tail -3`
(Branch `claude/gc-autopull-adaptive` is already tracked; this adds the Phase 1 commits to the existing PR #53.)

- [ ] **Step 2: Append a note to PR #53 or open a follow-up**

If PR #53 is still open and unmerged: this work goes into the same PR (same branch). Add a review comment explaining the additional scope.

If PR #53 is merged: open a new PR against main from the same branch (or rebase it).

```bash
gh pr comment 53 --body "$(cat <<'EOF'
Adds Phase 1 of multi-team support on top of the autopull:
- `config/teams.yaml` + `tools/team_registry.py`
- Autopull CLI loops over active teams with shared browser + per-team idempotency
- `state.py` migration: `team_id` on `runs` + `schema_profile`
- `gc_csv_ingest.py` / `gc_ingest_pipeline.py` take `--team <slug>`
- SWOT / lineups / dashboard stay Sharks-only — Phase 2 spec follows

With only the Sharks in `teams.yaml`, behavior is byte-identical to before.
EOF
)"
```

---

## Self-review

1. **Spec coverage**
   - §3 architecture: Tasks 1 (registry), 3 (state), 6 (cli), 8-9 (ingest) ✓
   - §4 teams.yaml schema: Task 2 ✓
   - §5 Team dataclass: Task 1 ✓
   - §6 state migration: Task 3 ✓
   - §7 run flow: Task 6 (per-team loop + breaker + serial + idempotency) ✓
   - §8 ingest refactor: Tasks 8-9 ✓
   - §9 notifications: Tasks 5, 6 ✓
   - §10 testing: Tasks 1 (registry), 3 (state), 6 (multi-team unit), 7 (weekly), 10 (integration), 11 (regression) ✓
   - §11 rollout: Task 12 (PR) + teams.yaml ships with Sharks only ✓
   - §12 self-sustaining: covered by registry load-per-CLI-invocation + data_slug stability ✓

2. **Placeholder scan** — no TBD / TODO / "add validation" / "similar to Task N". Task 8's "precise diff is impractical" is a factual statement about a 664-line file, not a placeholder — the rule stated right after it ("every SHARKS_DIR in a write path becomes a parameter") is the actionable directive.

3. **Type consistency**
   - `Team.data_slug` used consistently as the team key everywhere
   - `RunSummary` new fields `team_slug`, `team_name` match between notifier + cli
   - `team_id` column name matches across state.py + SQL + Python call sites
   - `run_once` new kwarg `teams_path` matches in tests and impl
