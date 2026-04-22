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
