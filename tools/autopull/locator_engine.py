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
