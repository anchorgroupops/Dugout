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
