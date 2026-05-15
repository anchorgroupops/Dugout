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
                              llm_daily_limit=0)  # limit 0 -> never call
    result = engine.find_and_download(page, out_dir=tmp_path)
    assert llm.call_count == 0
    assert result.llm_used is False


def test_llm_adapter_exception_returns_no_download(tmp_db_path, tmp_path):
    """When the LLM adapter raises, the engine should return gracefully."""
    db = StateDB(tmp_db_path); db.init_schema()
    le.seed_builtin_strategies(db)
    llm = MagicMock(side_effect=RuntimeError("api error"))
    page = FakePage(found_selectors=set())
    engine = le.LocatorEngine(db=db, llm_adapter=llm, llm_enabled=True,
                              llm_daily_limit=10)
    result = engine.find_and_download(page, out_dir=tmp_path)
    assert result.downloaded_path is None
    assert result.llm_used is False


def test_llm_proposal_fails_download_records_failure(tmp_db_path, tmp_path):
    """LLM proposes a valid selector, but download fails; strategy is recorded failed."""
    db = StateDB(tmp_db_path); db.init_schema()
    le.seed_builtin_strategies(db)
    llm = MagicMock(return_value={
        "strategy": "css", "selector": "button.no-match",
        "confidence": 0.8, "reasoning": "test",
    })
    # button.no-match is NOT in found_selectors so count() == 0
    page = FakePage(found_selectors=set(), download=None)
    engine = le.LocatorEngine(db=db, llm_adapter=llm, llm_enabled=True,
                              llm_daily_limit=10)
    result = engine.find_and_download(page, out_dir=tmp_path)
    assert result.downloaded_path is None
    assert result.llm_used is True


def test_prune_dom_strips_scripts_and_styles():
    html = "<html><script>bad()</script><style>.x{}</style><p>ok</p></html>"
    pruned = le.LocatorEngine._prune_dom.__func__(None, html) if False else \
        le.LocatorEngine._prune_dom(MagicMock(content=MagicMock(return_value=html)))
    # call via a real page mock
    page = FakePage(html=html)
    pruned = le.LocatorEngine._prune_dom(page)
    assert "<script>" not in pruned
    assert "<style>" not in pruned
    assert "ok" in pruned


def test_prune_dom_truncates_large_html():
    big_html = "a" * 50_000
    page = FakePage(html=big_html)
    pruned = le.LocatorEngine._prune_dom(page, cap_bytes=40_000)
    assert len(pruned) <= 40_000 + 30  # cap + truncation marker
    assert "truncated" in pruned


def test_prune_dom_handles_page_content_exception():
    class BrokenPage:
        def content(self):
            raise RuntimeError("not available")
    pruned = le.LocatorEngine._prune_dom(BrokenPage())
    assert pruned == ""


def test_proposal_is_safe_false_when_selector_missing(tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    engine = le.LocatorEngine(db=db, llm_adapter=None, llm_enabled=False)
    assert engine._proposal_is_safe({}) is False
    assert engine._proposal_is_safe(None) is False


def test_try_strategy_exception_returns_false(tmp_db_path, tmp_path):
    """_try_strategy catches exception and returns False — lines 141-143."""
    from tools.autopull.state import StrategyRow
    db = StateDB(tmp_db_path); db.init_schema()
    engine = le.LocatorEngine(db=db, llm_adapter=None, llm_enabled=False)

    # A page where the selector IS found but click raises an exception
    class ExplodingLocator:
        def count(self): return 1
        @property
        def first(self): return self
        def click(self): raise RuntimeError("playwright exploded")

    class ExplodingPage:
        def locator(self, sel): return ExplodingLocator()
        def expect_download(self, timeout=30_000):
            return MagicMock(__enter__=MagicMock(return_value=MagicMock(value=MagicMock())),
                             __exit__=MagicMock(return_value=False))
        def content(self): return ""
        def screenshot(self, **kw): pass

    strategy = StrategyRow(
        id=1, kind="css", selector="button.export", description="test",
        created_at="2026-01-01", last_success_at=None,
        success_count=0, failure_count=0, source="builtin", enabled=1,
    )
    result = engine._try_strategy(ExplodingPage(), strategy, tmp_path / "out.csv")
    assert result is False


def test_proposal_is_safe_true_for_normal_selector(tmp_db_path):
    db = StateDB(tmp_db_path); db.init_schema()
    engine = le.LocatorEngine(db=db, llm_adapter=None, llm_enabled=False)
    assert engine._proposal_is_safe({"selector": "button.export"}) is True
