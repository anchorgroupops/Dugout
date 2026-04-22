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
