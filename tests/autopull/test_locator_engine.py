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
