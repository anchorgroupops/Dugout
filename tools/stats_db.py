"""
Persistent running stats database for Sharks.
Stores time-series snapshots each sync cycle for auditing and trend analysis.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stats_normalizer import normalize_batting_row, normalize_fielding_row, normalize_pitching_row

ET = ZoneInfo("America/New_York")
DATA_DIR = Path(__file__).parent.parent / "data"
SHARKS_DIR = DATA_DIR / "sharks"
DB_PATH = SHARKS_DIR / "stats_history.db"


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  captured_at TEXT NOT NULL,
  source TEXT NOT NULL,
  team_name TEXT NOT NULL,
  roster_size INTEGER NOT NULL,
  notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS players (
  player_key TEXT PRIMARY KEY,
  number TEXT,
  first_name TEXT,
  last_name TEXT,
  display_name TEXT NOT NULL,
  is_shark INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batting_snapshots (
  snapshot_id INTEGER NOT NULL,
  player_key TEXT NOT NULL,
  pa INTEGER NOT NULL,
  ab INTEGER NOT NULL,
  h INTEGER NOT NULL,
  singles INTEGER NOT NULL,
  doubles INTEGER NOT NULL,
  triples INTEGER NOT NULL,
  hr INTEGER NOT NULL,
  bb INTEGER NOT NULL,
  hbp INTEGER NOT NULL,
  so INTEGER NOT NULL,
  rbi INTEGER NOT NULL,
  sb INTEGER NOT NULL,
  r INTEGER NOT NULL,
  sac INTEGER NOT NULL,
  avg REAL NOT NULL,
  obp REAL NOT NULL,
  slg REAL NOT NULL,
  ops REAL NOT NULL,
  PRIMARY KEY (snapshot_id, player_key),
  FOREIGN KEY (snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE,
  FOREIGN KEY (player_key) REFERENCES players(player_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pitching_snapshots (
  snapshot_id INTEGER NOT NULL,
  player_key TEXT NOT NULL,
  ip REAL NOT NULL,
  er INTEGER NOT NULL,
  bb INTEGER NOT NULL,
  h INTEGER NOT NULL,
  so INTEGER NOT NULL,
  whip REAL NOT NULL,
  era REAL NOT NULL,
  PRIMARY KEY (snapshot_id, player_key),
  FOREIGN KEY (snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE,
  FOREIGN KEY (player_key) REFERENCES players(player_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fielding_snapshots (
  snapshot_id INTEGER NOT NULL,
  player_key TEXT NOT NULL,
  po INTEGER NOT NULL,
  a INTEGER NOT NULL,
  e INTEGER NOT NULL,
  fpct REAL NOT NULL,
  PRIMARY KEY (snapshot_id, player_key),
  FOREIGN KEY (snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE,
  FOREIGN KEY (player_key) REFERENCES players(player_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS h2h_games (
  game_id TEXT PRIMARY KEY,
  opponent_slug TEXT NOT NULL,
  date TEXT NOT NULL,
  runs_for INTEGER NOT NULL,
  runs_against INTEGER NOT NULL,
  result TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_captured_at ON snapshots(captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_batting_player ON batting_snapshots(player_key, snapshot_id DESC);
CREATE INDEX IF NOT EXISTS idx_pitching_player ON pitching_snapshots(player_key, snapshot_id DESC);
CREATE INDEX IF NOT EXISTS idx_fielding_player ON fielding_snapshots(player_key, snapshot_id DESC);
CREATE INDEX IF NOT EXISTS idx_h2h_opponent ON h2h_games(opponent_slug, date DESC);
"""


def _now_iso() -> str:
    return datetime.now(ET).isoformat()


def _player_name(player: dict) -> str:
    explicit = str(player.get("name", "")).strip()
    if explicit:
        return explicit
    first = str(player.get("first", "")).strip()
    last = str(player.get("last", "")).strip()
    return f"{first} {last}".strip() or "Unknown"


def _player_key(player: dict) -> str:
    number = str(player.get("number", "")).strip()
    name = _player_name(player).lower().replace(" ", "_")
    if number:
        return f"sharks:{number}:{name}"
    return f"sharks:nonumber:{name}"


_schema_initialized = False

def _connect() -> sqlite3.Connection:
    global _schema_initialized
    SHARKS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON;")
    if not _schema_initialized:
        conn.executescript(SCHEMA_SQL)
        _schema_initialized = True
    return conn


def record_sharks_snapshot(team_data: dict, source: str = "sync_cycle", notes: str = "") -> int:
    roster = team_data.get("roster", [])
    team_name = str(team_data.get("team_name", "The Sharks")).strip() or "The Sharks"
    captured_at = _now_iso()

    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO snapshots(captured_at, source, team_name, roster_size, notes) VALUES(?,?,?,?,?)",
            (captured_at, source, team_name, len(roster), notes),
        )
        snapshot_id = int(cur.lastrowid)

        for player in roster:
            pkey = _player_key(player)
            number = str(player.get("number", "")).strip()
            first = str(player.get("first", "")).strip()
            last = str(player.get("last", "")).strip()
            display = _player_name(player)

            cur.execute(
                """
                INSERT INTO players(player_key, number, first_name, last_name, display_name, is_shark, updated_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(player_key) DO UPDATE SET
                  number=excluded.number,
                  first_name=excluded.first_name,
                  last_name=excluded.last_name,
                  display_name=excluded.display_name,
                  is_shark=1,
                  updated_at=excluded.updated_at
                """,
                (pkey, number, first, last, display, 1, captured_at),
            )

            b = normalize_batting_row(player.get("batting", player))
            cur.execute(
                """
                INSERT INTO batting_snapshots(
                  snapshot_id, player_key, pa, ab, h, singles, doubles, triples, hr, bb, hbp, so, rbi, sb, r, sac,
                  avg, obp, slg, ops
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    snapshot_id,
                    pkey,
                    int(b.get("pa", 0)),
                    int(b.get("ab", 0)),
                    int(b.get("h", 0)),
                    int(b.get("1b", b.get("singles", 0))),
                    int(b.get("2b", b.get("doubles", 0))),
                    int(b.get("3b", b.get("triples", 0))),
                    int(b.get("hr", 0)),
                    int(b.get("bb", 0)),
                    int(b.get("hbp", 0)),
                    int(b.get("so", 0)),
                    int(b.get("rbi", 0)),
                    int(b.get("sb", 0)),
                    int(b.get("r", 0)),
                    int(b.get("sac", 0)),
                    float(b.get("avg", 0.0)),
                    float(b.get("obp", 0.0)),
                    float(b.get("slg", 0.0)),
                    float(b.get("ops", 0.0)),
                ),
            )

            p = normalize_pitching_row(player.get("pitching", player))
            cur.execute(
                """
                INSERT INTO pitching_snapshots(snapshot_id, player_key, ip, er, bb, h, so, whip, era)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    snapshot_id,
                    pkey,
                    float(p.get("ip", 0.0)),
                    int(p.get("er", 0)),
                    int(p.get("bb", 0)),
                    int(p.get("h", 0)),
                    int(p.get("so", 0)),
                    float(p.get("whip", 0.0)),
                    float(p.get("era", 0.0)),
                ),
            )

            f = normalize_fielding_row(player.get("fielding", player))
            cur.execute(
                """
                INSERT INTO fielding_snapshots(snapshot_id, player_key, po, a, e, fpct)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    snapshot_id,
                    pkey,
                    int(f.get("po", 0)),
                    int(f.get("a", 0)),
                    int(f.get("e", 0)),
                    float(f.get("fpct", 0.0)),
                ),
            )

        conn.commit()
        return snapshot_id
    finally:
        conn.close()


def get_db_status() -> dict:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM snapshots")
        snapshot_count = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM players")
        player_count = int(cur.fetchone()[0])
        cur.execute("SELECT id, captured_at, source, roster_size FROM snapshots ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        latest = None
        if row:
            latest = {
                "snapshot_id": int(row[0]),
                "captured_at": row[1],
                "source": row[2],
                "roster_size": int(row[3]),
            }
        return {
            "db_path": str(DB_PATH),
            "snapshot_count": snapshot_count,
            "player_count": player_count,
            "latest": latest,
        }
    finally:
        conn.close()


def insert_h2h_game(game_id: str, opponent_slug: str, date: str,
                     runs_for: int, runs_against: int, result: str) -> bool:
    """Insert a head-to-head game record. Returns True if inserted, False if duplicate."""
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO h2h_games (game_id, opponent_slug, date, runs_for, runs_against, result, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (game_id, opponent_slug, date, runs_for, runs_against, result, _now_iso()),
        )
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()


def get_h2h_history(opponent_slug: str) -> list[dict]:
    """Return all head-to-head games against a specific opponent, newest first."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT game_id, date, runs_for, runs_against, result "
            "FROM h2h_games WHERE opponent_slug = ? ORDER BY date DESC",
            (opponent_slug,),
        )
        return [
            {"game_id": r[0], "date": r[1], "runs_for": r[2], "runs_against": r[3], "result": r[4]}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def get_h2h_summary(opponent_slug: str) -> dict:
    """Return a W-L-T summary for head-to-head against an opponent."""
    games = get_h2h_history(opponent_slug)
    wins = sum(1 for g in games if g["result"] == "W")
    losses = sum(1 for g in games if g["result"] == "L")
    ties = sum(1 for g in games if g["result"] == "T")
    total_rf = sum(g["runs_for"] for g in games)
    total_ra = sum(g["runs_against"] for g in games)
    return {
        "opponent_slug": opponent_slug,
        "games_played": len(games),
        "wins": wins, "losses": losses, "ties": ties,
        "record": f"{wins}-{losses}" + (f"-{ties}" if ties else ""),
        "runs_for": total_rf, "runs_against": total_ra,
        "avg_runs_for": round(total_rf / len(games), 1) if games else 0,
        "avg_runs_against": round(total_ra / len(games), 1) if games else 0,
        "games": games,
    }
