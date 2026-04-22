"""Regression tests for the 2026-04-09 mac-dev crash cascade.

The bug: gc_schedule.py had `try: from playwright.sync_api import ... except
ImportError: sync_playwright = None`, and sync_daemon.run_sync_cycle called
sched_scraper.scrape_schedule() without wrapping it in try/except. When
Playwright was absent, `None()` raised `TypeError: 'NoneType' object is not
callable` — uncaught — and aborted the whole cycle before team_enriched.json
and pipeline_health.json could be written.

These three tests pin the fix in place.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
TOOLS = REPO / "tools"


class _BlockPlaywright:
    def find_spec(self, name, path=None, target=None):
        if name == "playwright" or name.startswith("playwright."):
            raise ImportError(f"simulated-absent: {name}")
        return None


@pytest.fixture
def playwright_blocked():
    for k in list(sys.modules):
        if k == "gc_schedule" or k.startswith("playwright"):
            del sys.modules[k]
    blocker = _BlockPlaywright()
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        sys.meta_path[:] = [x for x in sys.meta_path if x is not blocker]


def test_gc_schedule_has_no_silent_none_fallback():
    src = (TOOLS / "gc_schedule.py").read_text()
    assert not re.search(
        r"^\s*sync_playwright\s*=\s*None", src, re.MULTILINE
    ), "gc_schedule.py reintroduced the silent-None fallback"
    assert not re.search(
        r"try:\s*\n\s*from\s+playwright\.sync_api\s+import.*?\n\s*except\s+ImportError",
        src,
        re.DOTALL,
    ), "gc_schedule.py reintroduced the module-level try/except around the playwright import"


def test_scrape_schedule_raises_importerror_when_playwright_absent(playwright_blocked):
    mod = importlib.import_module("gc_schedule")
    scraper = mod.ScheduleScraper()
    with pytest.raises(ImportError):
        scraper.scrape_schedule()


def test_daemon_wraps_scrape_schedule_call():
    src = (TOOLS / "sync_daemon.py").read_text()
    call = re.search(
        r"sched_scraper\s*=\s*ScheduleScraper\(\)\s*\n\s*sched_scraper\.scrape_schedule\(\)",
        src,
    )
    assert call, "cannot locate sched_scraper.scrape_schedule() call site"
    pre = src[: call.start()].splitlines()[-15:]
    post = src[call.end() :].splitlines()[:15]
    assert any(
        re.match(r"^(\s{8,})try\s*:\s*$", ln) for ln in pre
    ), "scrape_schedule() no longer has a preceding local try:"
    assert any(
        re.match(r"^(\s{8,})except\b", ln) for ln in post
    ), "scrape_schedule() no longer has a matching local except"
