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
    code_input = MagicMock(); code_input.count.return_value = 1
    submit_btn = MagicMock(); submit_btn.count.return_value = 1
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
