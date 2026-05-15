"""Tests for tools.autopull.session_manager — pure-logic tests, Playwright mocked."""
from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from tools.autopull import session_manager as sm


class FakePage:
    def __init__(self, url="https://web.gc.com/teams/X/season/stats"):
        self.url = url
        self._locator_results: dict[str, MagicMock] = {}
        self.goto = MagicMock()
        self.wait_for_load_state = MagicMock()
        self.wait_for_selector = MagicMock()
        self.wait_for_timeout = MagicMock()
        self.screenshot = MagicMock()
        self.content = MagicMock(return_value="<html></html>")
        self.get_by_role = MagicMock(return_value=MagicMock(first=MagicMock(count=MagicMock(return_value=0))))

    def locator(self, sel: str):
        return self._locator_results.setdefault(sel, MagicMock())


def _make_loc(count=1, raise_fill=False, raise_click=False, raise_count=False):
    """Build a locator mock with .first returning self."""
    loc = MagicMock()
    if raise_count:
        loc.count = MagicMock(side_effect=RuntimeError("count error"))
    else:
        loc.count = MagicMock(return_value=count)
    if raise_fill:
        loc.fill = MagicMock(side_effect=RuntimeError("fill error"))
    if raise_click:
        loc.click = MagicMock(side_effect=RuntimeError("click error"))
    loc.first = loc
    loc.press = MagicMock()
    loc.wait_for = MagicMock()
    return loc


def test_is_login_page_by_url():
    p = FakePage(url="https://web.gc.com/login")
    assert sm.is_login_page(p) is True


def test_is_login_page_by_form_presence():
    p = FakePage(url="https://web.gc.com/teams/X")
    p._locator_results["input[type='password']"] = MagicMock()
    p._locator_results["input[type='password']"].count.return_value = 1
    assert sm.is_login_page(p) is True


def test_is_login_page_email_only_form():
    """Lines 43-46: email input + no code input → login page (step-1 form)."""
    p = FakePage()
    # password: not present
    p._locator_results["input[type='password']"] = MagicMock(count=MagicMock(return_value=0))
    # email present, code absent
    p._locator_results["input[type='email'], input[name='email']"] = MagicMock(count=MagicMock(return_value=1))
    p._locator_results["input[name='code'], input[autocomplete='one-time-code']"] = MagicMock(count=MagicMock(return_value=0))
    assert sm.is_login_page(p) is True


def test_is_login_page_locator_exception():
    """Lines 47-48: locator raises → except catches, return False."""
    p = FakePage()
    p.locator = MagicMock(side_effect=RuntimeError("playwright not available"))
    assert sm.is_login_page(p) is False


def test_is_login_page_email_and_code_present():
    """Both email AND code present → not a step-1 login page."""
    p = FakePage()
    p._locator_results["input[type='password']"] = MagicMock(count=MagicMock(return_value=0))
    p._locator_results["input[type='email'], input[name='email']"] = MagicMock(count=MagicMock(return_value=1))
    p._locator_results["input[name='code'], input[autocomplete='one-time-code']"] = MagicMock(count=MagicMock(return_value=1))
    assert sm.is_login_page(p) is False


def test_is_2fa_page_by_code_input():
    p = FakePage(url="https://web.gc.com/verify")
    p._locator_results["input[name='code']"] = MagicMock()
    p._locator_results["input[name='code']"].count.return_value = 1
    assert sm.is_2fa_page(p) is True


def test_is_2fa_page_locator_exception_continues():
    """Lines 58-60: first locator raises → continue to next selectors."""
    call_count = {"n": 0}
    orig_locator = FakePage.locator

    p = FakePage()
    def mixed_locator(self, sel):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("playwright err")
        m = MagicMock()
        m.count.return_value = 0
        return m
    p.locator = lambda sel: mixed_locator(p, sel)
    # All selectors return 0 after the first raises → result is False
    assert sm.is_2fa_page(p) is False
    assert call_count["n"] > 1  # continued past the exception


def test_is_2fa_page_no_inputs():
    p = FakePage()
    # All locators return count=0
    for sel in ("input[name='code']", "input[autocomplete='one-time-code']",
                "input[inputmode='numeric']"):
        p._locator_results[sel] = MagicMock(count=MagicMock(return_value=0))
    assert sm.is_2fa_page(p) is False


def test_submit_2fa_code_fills_and_submits():
    p = FakePage()
    code_input = MagicMock(); code_input.count.return_value = 1
    submit_btn = MagicMock(); submit_btn.count.return_value = 1
    p._locator_results["input[name='code']"] = code_input
    p._locator_results["button[type='submit']"] = submit_btn
    sm.submit_2fa_code(p, "482913")
    code_input.fill.assert_called_once_with("482913")
    submit_btn.click.assert_called_once()


def test_submit_2fa_code_fill_exception_continues():
    """Lines 70-71: fill raises for first selector → continue to second."""
    p = FakePage()
    bad_loc = MagicMock()
    bad_loc.count.return_value = 1
    bad_loc.fill.side_effect = RuntimeError("fill error")

    good_loc = MagicMock()
    good_loc.count.return_value = 1

    p._locator_results["input[name='code']"] = bad_loc
    p._locator_results["input[autocomplete='one-time-code']"] = good_loc

    submit_btn = MagicMock(); submit_btn.count.return_value = 1
    p._locator_results["button[type='submit']"] = submit_btn

    sm.submit_2fa_code(p, "123456")
    good_loc.fill.assert_called_once_with("123456")


def test_submit_2fa_code_button_exception_then_no_button():
    """Lines 79-81: button click raises → continue; all fail → SessionError."""
    p = FakePage()
    code_loc = MagicMock(); code_loc.count.return_value = 1
    p._locator_results["input[name='code']"] = code_loc

    # First button: raises on click (covers 79-80)
    bad_btn = MagicMock()
    bad_btn.count.return_value = 1
    bad_btn.click.side_effect = RuntimeError("click error")
    p._locator_results["button[type='submit']"] = bad_btn

    # Other buttons: not found
    for sel in ("button:has-text('Verify')", "button:has-text('Submit')"):
        p._locator_results[sel] = MagicMock(count=MagicMock(return_value=0))

    with pytest.raises(sm.SessionError, match="No submit button"):
        sm.submit_2fa_code(p, "654321")


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


# ── SessionManager ────────────────────────────────────────────────────────────

def _make_manager(tmp_path=None, **kwargs):
    auth = (tmp_path or Path("/tmp")) / "gc_session.json"
    defaults = dict(
        auth_file=auth,
        email="coach@sharks.com",
        password="secret",
        gmail_fetcher=MagicMock(return_value=(None, None)),
    )
    defaults.update(kwargs)
    return sm.SessionManager(**defaults)


def test_session_manager_init(tmp_path):
    """Lines 122-126: constructor stores attributes."""
    fetcher = MagicMock()
    mgr = sm.SessionManager(
        auth_file=tmp_path / "auth.json",
        email="test@example.com",
        password="s3cr3t",
        gmail_fetcher=fetcher,
        login_url="https://custom.gc.com/login",
    )
    assert mgr.email == "test@example.com"
    assert mgr.password == "s3cr3t"
    assert mgr.gmail_fetcher is fetcher
    assert mgr.login_url == "https://custom.gc.com/login"
    assert isinstance(mgr.auth_file, Path)


def _make_playwright_ctx(page):
    """Build a minimal playwright_ctx mock."""
    context = MagicMock()
    context.new_page.return_value = page
    browser = MagicMock()
    browser.new_context.return_value = context
    ctx = MagicMock()
    ctx.chromium.launch.return_value = browser
    return ctx, context


def test_new_logged_in_page_no_login_needed(tmp_path, monkeypatch):
    """Lines 135-145: no login required → returns (page, False)."""
    page = FakePage(url="https://web.gc.com/teams/X")
    pw_ctx, _ = _make_playwright_ctx(page)

    monkeypatch.setattr(sm, "is_login_page", lambda p: False)
    monkeypatch.setattr(sm, "is_2fa_page", lambda p: False)

    mgr = _make_manager(tmp_path)
    result_page, refreshed = mgr.new_logged_in_page(pw_ctx)
    assert result_page is page
    assert refreshed is False


def test_new_logged_in_page_with_stored_auth(tmp_path, monkeypatch):
    """Line 138: auth_file exists → storage_state kwarg passed to new_context."""
    auth = tmp_path / "gc_session.json"
    auth.write_text("{}")  # exists

    page = FakePage()
    pw_ctx, browser = _make_playwright_ctx(page)
    browser_mock = pw_ctx.chromium.launch.return_value

    monkeypatch.setattr(sm, "is_login_page", lambda p: False)
    monkeypatch.setattr(sm, "is_2fa_page", lambda p: False)

    mgr = _make_manager(tmp_path, auth_file=auth)
    mgr.new_logged_in_page(pw_ctx)

    assert browser_mock.new_context.called
    kwargs = browser_mock.new_context.call_args[1]
    assert "storage_state" in kwargs


def test_new_logged_in_page_login_flow_no_2fa(tmp_path, monkeypatch):
    """Lines 151-171: is_login_page=True, baseline + submit email, no 2FA."""
    page = FakePage()
    pw_ctx, context = _make_playwright_ctx(page)

    call_count = {"n": 0}
    def toggling_login(p):
        call_count["n"] += 1
        # First call: login page; subsequent: not
        return call_count["n"] == 1

    monkeypatch.setattr(sm, "is_login_page", toggling_login)
    monkeypatch.setattr(sm, "is_2fa_page", lambda p: False)

    fetcher = MagicMock(return_value=(None, "42"))  # numeric UID so int() succeeds
    mgr = _make_manager(tmp_path, gmail_fetcher=fetcher)
    monkeypatch.setattr(mgr, "_submit_email", MagicMock())

    result_page, refreshed = mgr.new_logged_in_page(pw_ctx)
    assert refreshed is True
    mgr._submit_email.assert_called_once()


def test_new_logged_in_page_login_baseline_exception(tmp_path, monkeypatch):
    """Lines 167-168: gmail baseline call raises → warning, continues."""
    page = FakePage()
    pw_ctx, _ = _make_playwright_ctx(page)

    call_count = {"n": 0}
    def toggling_login(p):
        call_count["n"] += 1
        return call_count["n"] == 1

    monkeypatch.setattr(sm, "is_login_page", toggling_login)
    monkeypatch.setattr(sm, "is_2fa_page", lambda p: False)

    fetcher = MagicMock(side_effect=RuntimeError("gmail down"))
    mgr = _make_manager(tmp_path, gmail_fetcher=fetcher)
    monkeypatch.setattr(mgr, "_submit_email", MagicMock())

    # Should not raise — exception is caught and warned
    result_page, refreshed = mgr.new_logged_in_page(pw_ctx)
    assert refreshed is True


def test_new_logged_in_page_2fa_flow(tmp_path, monkeypatch):
    """Lines 185-196: is_2fa_page=True → wait for code, submit."""
    page = FakePage()
    pw_ctx, context = _make_playwright_ctx(page)

    monkeypatch.setattr(sm, "is_login_page", lambda p: False)
    # First call to is_2fa_page: True (enter 2FA branch); second call (line 198): False
    tfa_calls = {"n": 0}
    def toggling_2fa(p):
        tfa_calls["n"] += 1
        return tfa_calls["n"] == 1
    monkeypatch.setattr(sm, "is_2fa_page", toggling_2fa)
    monkeypatch.setattr(sm, "wait_for_2fa_code",
                        MagicMock(return_value=("123456", "uid-99")))

    mgr = _make_manager(tmp_path)
    monkeypatch.setattr(mgr, "_submit_code_and_password", MagicMock())

    result_page, refreshed = mgr.new_logged_in_page(pw_ctx)
    assert refreshed is True
    mgr._submit_code_and_password.assert_called_once_with(page, "123456")


def test_new_logged_in_page_still_on_login_raises(tmp_path, monkeypatch):
    """Lines 198-215: still on login page after auth → SessionError."""
    page = FakePage()
    pw_ctx, _ = _make_playwright_ctx(page)

    # First is_login_page=True (triggering login), second still True
    call_count = {"n": 0}
    def always_login(p):
        return True

    monkeypatch.setattr(sm, "is_login_page", always_login)
    monkeypatch.setattr(sm, "is_2fa_page", lambda p: False)

    fetcher = MagicMock(return_value=(None, None))
    mgr = _make_manager(tmp_path, gmail_fetcher=fetcher)
    monkeypatch.setattr(mgr, "_submit_email", MagicMock())

    with pytest.raises(sm.SessionError, match="Still on login"):
        mgr.new_logged_in_page(pw_ctx)


def test_new_logged_in_page_diagnostics_exception_ignored(tmp_path, monkeypatch):
    """Lines 210-211: diagnostic capture fails → warning, not crash."""
    page = FakePage()
    page.screenshot.side_effect = RuntimeError("screenshot fail")
    pw_ctx, _ = _make_playwright_ctx(page)

    monkeypatch.setattr(sm, "is_login_page", lambda p: True)
    monkeypatch.setattr(sm, "is_2fa_page", lambda p: False)

    mgr = _make_manager(tmp_path)
    monkeypatch.setattr(mgr, "_submit_email", MagicMock())

    with pytest.raises(sm.SessionError):
        mgr.new_logged_in_page(pw_ctx)


def test_new_logged_in_page_saves_storage_state(tmp_path, monkeypatch):
    """Lines 217-219: refreshed=True → storage_state saved."""
    page = FakePage()
    pw_ctx, context = _make_playwright_ctx(page)

    call_count = {"n": 0}
    def toggling_login(p):
        call_count["n"] += 1
        return call_count["n"] == 1

    monkeypatch.setattr(sm, "is_login_page", toggling_login)
    monkeypatch.setattr(sm, "is_2fa_page", lambda p: False)

    fetcher = MagicMock(return_value=(None, None))
    mgr = _make_manager(tmp_path, gmail_fetcher=fetcher)
    monkeypatch.setattr(mgr, "_submit_email", MagicMock())

    mgr.new_logged_in_page(pw_ctx)
    context.storage_state.assert_called_once()


def test_new_logged_in_page_wait_for_selector_exception(tmp_path, monkeypatch):
    """Lines 182-183: wait_for_selector raises → warning, continues."""
    page = FakePage()
    page.wait_for_selector = MagicMock(side_effect=Exception("timeout"))
    pw_ctx, _ = _make_playwright_ctx(page)

    call_count = {"n": 0}
    def toggling_login(p):
        call_count["n"] += 1
        return call_count["n"] == 1

    monkeypatch.setattr(sm, "is_login_page", toggling_login)
    monkeypatch.setattr(sm, "is_2fa_page", lambda p: False)

    fetcher = MagicMock(return_value=(None, None))
    mgr = _make_manager(tmp_path, gmail_fetcher=fetcher)
    monkeypatch.setattr(mgr, "_submit_email", MagicMock())

    result_page, refreshed = mgr.new_logged_in_page(pw_ctx)
    assert refreshed is True


# ── _submit_email ─────────────────────────────────────────────────────────────

def _make_page_with_locators(**named_locators):
    """FakePage where each key maps to a locator mock."""
    page = MagicMock()
    page.url = "https://web.gc.com/login"
    page.wait_for_load_state = MagicMock()
    page.goto = MagicMock()

    def locator_se(sel):
        loc = named_locators.get(sel, _make_loc(count=0))
        return loc
    page.locator.side_effect = locator_se
    return page


def test_submit_email_fills_and_clicks_role_button(tmp_path):
    """Lines 224-240: email found, role button found → click and return."""
    mgr = _make_manager(tmp_path)

    page = MagicMock()
    email_loc = _make_loc(count=1)
    page.locator.side_effect = lambda sel: email_loc if "email" in sel else _make_loc(count=0)

    btn = _make_loc(count=1)
    page.get_by_role = MagicMock(return_value=MagicMock(first=btn))

    mgr._submit_email(page)
    btn.click.assert_called_once()


def test_submit_email_role_button_exception_falls_through(tmp_path):
    """Lines 241-242: get_by_role raises → fall through to selector buttons."""
    mgr = _make_manager(tmp_path)

    page = MagicMock()
    email_loc = _make_loc(count=1)
    page.locator.side_effect = lambda sel: (
        email_loc if "email" in sel
        else _make_loc(count=1)  # selector buttons: all found
    )
    page.get_by_role = MagicMock(side_effect=RuntimeError("role error"))

    mgr._submit_email(page)
    # At least one locator button was clicked (via selector loop)


def test_submit_email_no_role_no_selector_button_presses_enter(tmp_path):
    """Line 250: no button found anywhere → press Enter on email field."""
    mgr = _make_manager(tmp_path)

    page = MagicMock()
    email_loc = _make_loc(count=1)
    page.locator.side_effect = lambda sel: email_loc if "email" in sel else _make_loc(count=0)
    page.get_by_role = MagicMock(return_value=MagicMock(first=_make_loc(count=0)))

    mgr._submit_email(page)
    email_loc.press.assert_called_once_with("Enter")


def test_submit_email_no_email_input_raises(tmp_path):
    """Line 231: no email input in any selector → SessionError."""
    mgr = _make_manager(tmp_path)

    page = MagicMock()
    page.locator.return_value = _make_loc(count=0)
    page.get_by_role = MagicMock()

    with pytest.raises(sm.SessionError, match="Email input not found"):
        mgr._submit_email(page)


# ── _submit_code_and_password ─────────────────────────────────────────────────

def test_submit_code_and_password_success(tmp_path):
    """Lines 255-296: code + password filled, button clicked."""
    mgr = _make_manager(tmp_path)

    page = MagicMock()
    code_loc = _make_loc(count=1)
    pwd_loc = _make_loc(count=1)
    btn = _make_loc(count=1)

    def locator_se(sel):
        if "code" in sel or "one-time" in sel or "numeric" in sel or "placeholder*='ode'" in sel or "label*='ode'" in sel:
            return code_loc
        if "password" in sel:
            return pwd_loc
        return _make_loc(count=0)
    page.locator.side_effect = locator_se
    page.get_by_role = MagicMock(return_value=MagicMock(first=_make_loc(count=0)))

    mgr._submit_code_and_password(page, "887766")
    code_loc.fill.assert_called_once_with("887766")
    pwd_loc.fill.assert_called_once_with(mgr.password)


def test_submit_code_and_password_no_code_raises(tmp_path):
    """Lines 263-264: no code input found → SessionError."""
    mgr = _make_manager(tmp_path)
    page = MagicMock()
    page.locator.return_value = _make_loc(count=0)
    page.get_by_role = MagicMock()

    with pytest.raises(sm.SessionError, match="Code input not found"):
        mgr._submit_code_and_password(page, "123")


def test_submit_code_and_password_no_password_raises(tmp_path):
    """Line 277: no password input → SessionError."""
    mgr = _make_manager(tmp_path)

    page = MagicMock()
    code_loc = _make_loc(count=1)

    def locator_se(sel):
        if "code" in sel or "one-time" in sel or "numeric" in sel or "placeholder*='ode'" in sel or "label*='ode'" in sel:
            return code_loc
        return _make_loc(count=0)  # password not found
    page.locator.side_effect = locator_se
    page.get_by_role = MagicMock()

    with pytest.raises(sm.SessionError, match="Password input not found"):
        mgr._submit_code_and_password(page, "123")


def test_submit_code_and_password_password_wait_exception(tmp_path):
    """Lines 271-272: wait_for raises on first password sel → continue to next."""
    mgr = _make_manager(tmp_path)

    page = MagicMock()
    code_loc = _make_loc(count=1)
    bad_pwd = _make_loc(count=1)
    bad_pwd.wait_for = MagicMock(side_effect=Exception("timeout"))
    good_pwd = _make_loc(count=1)

    call_counts = {"pwd": 0}
    def locator_se(sel):
        if "code" in sel or "one-time" in sel or "numeric" in sel or "placeholder*='ode'" in sel or "label*='ode'" in sel:
            return code_loc
        if "password" in sel:
            call_counts["pwd"] += 1
            return bad_pwd if call_counts["pwd"] == 1 else good_pwd
        return _make_loc(count=0)
    page.locator.side_effect = locator_se
    page.get_by_role = MagicMock(return_value=MagicMock(first=_make_loc(count=0)))

    mgr._submit_code_and_password(page, "999")
    good_pwd.fill.assert_called_once()


def test_submit_code_and_password_role_button(tmp_path):
    """Lines 281-287: get_by_role button found → clicked."""
    mgr = _make_manager(tmp_path)

    page = MagicMock()
    code_loc = _make_loc(count=1)
    pwd_loc = _make_loc(count=1)
    role_btn = _make_loc(count=1)

    def locator_se(sel):
        if "code" in sel or "one-time" in sel or "numeric" in sel or "placeholder*='ode'" in sel or "label*='ode'" in sel:
            return code_loc
        if "password" in sel:
            return pwd_loc
        return _make_loc(count=0)
    page.locator.side_effect = locator_se
    page.get_by_role = MagicMock(return_value=MagicMock(first=role_btn))

    mgr._submit_code_and_password(page, "111222")
    role_btn.click.assert_called_once()


def test_submit_code_and_password_role_exception_fallback(tmp_path):
    """Lines 288-289: get_by_role raises → fall to selector buttons."""
    mgr = _make_manager(tmp_path)

    page = MagicMock()
    code_loc = _make_loc(count=1)
    pwd_loc = _make_loc(count=1)
    submit_btn = _make_loc(count=1)

    def locator_se(sel):
        if "code" in sel or "one-time" in sel or "numeric" in sel or "placeholder*='ode'" in sel or "label*='ode'" in sel:
            return code_loc
        if "password" in sel:
            return pwd_loc
        if "submit" in sel:
            return submit_btn
        return _make_loc(count=0)
    page.locator.side_effect = locator_se
    page.get_by_role = MagicMock(side_effect=RuntimeError("role err"))

    mgr._submit_code_and_password(page, "333444")
    submit_btn.click.assert_called_once()


def test_submit_code_and_password_no_button_presses_enter(tmp_path):
    """Line 296: no button found → press Enter on last locator."""
    mgr = _make_manager(tmp_path)

    page = MagicMock()
    code_loc = _make_loc(count=1)
    pwd_loc = _make_loc(count=1)

    def locator_se(sel):
        if "code" in sel or "one-time" in sel or "numeric" in sel or "placeholder*='ode'" in sel or "label*='ode'" in sel:
            return code_loc
        if "password" in sel:
            return pwd_loc
        return _make_loc(count=0)
    page.locator.side_effect = locator_se
    page.get_by_role = MagicMock(return_value=MagicMock(first=_make_loc(count=0)))

    mgr._submit_code_and_password(page, "555666")
    pwd_loc.press.assert_called_once_with("Enter")
