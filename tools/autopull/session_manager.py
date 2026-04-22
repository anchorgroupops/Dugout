"""Playwright session lifecycle: login, storage_state reuse, 2FA via Gmail."""
from __future__ import annotations
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

GC_LOGIN_URL = "https://web.gc.com/login"
GC_BASE = "https://web.gc.com"


class TwoFactorTimeout(RuntimeError):
    """Raised when no 2FA code arrives within the poll window."""


class SessionError(RuntimeError):
    """Raised when login cannot be completed."""


def is_login_page(page: Any) -> bool:
    if "/login" in (page.url or ""):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def is_2fa_page(page: Any) -> bool:
    for sel in ("input[name='code']", "input[autocomplete='one-time-code']",
                "input[inputmode='numeric']"):
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


def submit_2fa_code(page: Any, code: str) -> None:
    for sel in ("input[name='code']", "input[autocomplete='one-time-code']"):
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.fill(code)
                break
        except Exception:
            continue
    for sel in ("button[type='submit']", "button:has-text('Verify')",
                "button:has-text('Submit')"):
        try:
            btn = page.locator(sel)
            if btn.count() > 0:
                btn.click()
                return
        except Exception:
            continue
    raise SessionError("No submit button found on 2FA page")


def wait_for_2fa_code(
    fetcher: Callable[[], tuple[str | None, str | None]],
    *,
    max_attempts: int = 12,
    sleep_seconds: int = 10,
) -> tuple[str, str]:
    for attempt in range(max_attempts):
        code, mid = fetcher()
        if code:
            return code, mid
        if attempt < max_attempts - 1:
            time.sleep(sleep_seconds)
    raise TwoFactorTimeout(f"No 2FA code after {max_attempts} polls")


class SessionManager:
    """High-level orchestrator: returns a logged-in Playwright page.

    Construction is kept light so callers can inject mocks for testing.
    """

    def __init__(
        self,
        *,
        auth_file: Path,
        email: str,
        password: str,
        gmail_fetcher: Callable[[], tuple[str | None, str | None]],
        login_url: str = GC_LOGIN_URL,
    ):
        self.auth_file = Path(auth_file)
        self.email = email
        self.password = password
        self.gmail_fetcher = gmail_fetcher
        self.login_url = login_url

    def new_logged_in_page(self, playwright_ctx: Any,
                           *, headless: bool = True) -> tuple[Any, bool]:
        """Returns (page, session_was_refreshed).

        Tries reusing stored cookies. On detected login/2FA, does the dance
        and persists a fresh storage_state.
        """
        browser = playwright_ctx.chromium.launch(headless=headless)
        if self.auth_file.exists():
            context = browser.new_context(storage_state=str(self.auth_file))
        else:
            context = browser.new_context()
        page = context.new_page()

        page.goto(self.login_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_load_state("networkidle", timeout=30_000)

        refreshed = False
        if is_login_page(page):
            self._submit_credentials(page)
            refreshed = True
            page.wait_for_load_state("networkidle", timeout=30_000)

        if is_2fa_page(page):
            code, mid = wait_for_2fa_code(self.gmail_fetcher)
            submit_2fa_code(page, code)
            refreshed = True
            page.wait_for_load_state("networkidle", timeout=30_000)

        if is_login_page(page) or is_2fa_page(page):
            raise SessionError("Still on login/2FA page after credential + code submission")

        if refreshed:
            self.auth_file.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(self.auth_file))
        return page, refreshed

    def _submit_credentials(self, page: Any) -> None:
        for sel in ("input[type='email']", "input[name='email']",
                    "input[autocomplete='username']"):
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.fill(self.email)
                break
        else:
            raise SessionError("Email input not found on login page")
        for sel in ("input[type='password']", "input[name='password']"):
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.fill(self.password)
                break
        else:
            raise SessionError("Password input not found on login page")
        for sel in ("button[type='submit']", "button:has-text('Log in')",
                    "button:has-text('Sign in')"):
            btn = page.locator(sel)
            if btn.count() > 0:
                btn.click()
                return
        raise SessionError("Submit button not found on login page")
