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

# GC's web app serves a stripped-down "get the app" splash to headless UAs.
# A desktop Chrome UA string gets us the real login form and the real stats page.
DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class TwoFactorTimeout(RuntimeError):
    """Raised when no 2FA code arrives within the poll window."""


class SessionError(RuntimeError):
    """Raised when login cannot be completed."""


def is_login_page(page: Any) -> bool:
    """True if the page is showing GC's step-1 email form (no session yet).

    GC's two-page flow: step-1 has only an email input; step-2 has code + password.
    We also treat any page with a visible password input as a login page.
    """
    if "/login" in (page.url or "") or "/signin" in (page.url or ""):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
        # Step 1: email-only form, no password field yet, no code field.
        has_email = page.locator("input[type='email'], input[name='email']").count() > 0
        has_code = page.locator("input[name='code'], input[autocomplete='one-time-code']").count() > 0
        if has_email and not has_code:
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
    fetcher: Callable[..., tuple[str | None, str | None]],
    *,
    max_attempts: int = 12,
    sleep_seconds: int = 10,
    min_uid: int = 0,
) -> tuple[str, str]:
    """Poll until a 2FA code arrives, passing `min_uid` so we only accept
    codes from emails sent AFTER the login attempt's baseline UID.
    """
    for attempt in range(max_attempts):
        try:
            code, mid = fetcher(min_uid=min_uid)
        except TypeError:
            # Fetcher doesn't accept min_uid (e.g. legacy test mocks)
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
        ctx_kwargs = {"user_agent": DESKTOP_UA}
        if self.auth_file.exists():
            ctx_kwargs["storage_state"] = str(self.auth_file)
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()

        page.goto(self.login_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_load_state("networkidle", timeout=30_000)

        refreshed = False
        # GC uses a TWO-PAGE flow:
        #   page 1: email only → Continue
        #   page 2: verification code + password (both on same form) → Sign in
        # (GC emails the code right after the email step submits.)
        pre_submit_uid = 0
        if is_login_page(page):
            # Record the highest GC-sender UID BEFORE triggering a new code
            # email. Only codes with UID > this baseline are new for THIS
            # attempt; older codes are from prior attempts and already expired.
            try:
                from tools.autopull.gmail_2fa_fetcher import build_client as _b, current_max_uid
                # Reuse the same gmail_fetcher's client if we can — but the
                # fetcher is a callable that already has a client bound. So
                # instead, we tell it to skip emails <= a baseline.
                # We get the baseline by calling the fetcher once WITHOUT a
                # min_uid (it will return the newest existing code), and
                # remember that uid.
                baseline_code, baseline_uid = self.gmail_fetcher()
                if baseline_uid:
                    pre_submit_uid = int(baseline_uid)
                    log.info("2FA baseline UID=%s (will require newer)", pre_submit_uid)
            except Exception as e:
                log.warning("Could not compute 2FA baseline UID: %s", e)

            self._submit_email(page)
            refreshed = True
            page.wait_for_load_state("networkidle", timeout=30_000)
            # After clicking Continue, give GC up to 15s to render the step-2
            # form (code + password). networkidle alone isn't reliable — GC's
            # SPA dismisses the email form immediately and then renders the
            # next one after an API round-trip.
            try:
                page.wait_for_selector(
                    "input[name='code'], input[type='password']",
                    state="visible", timeout=15_000,
                )
            except Exception:
                log.info("No 2FA form appeared within 15s; will re-check")

        if is_2fa_page(page):
            code, mid = wait_for_2fa_code(
                self.gmail_fetcher, min_uid=pre_submit_uid,
            )
            log.info("Fetched 2FA code from Gmail (uid=%s, baseline=%s)",
                     mid, pre_submit_uid)
            self._submit_code_and_password(page, code)
            refreshed = True
            # GC's SPA can take a moment to navigate away after submit; give it
            # a few seconds in addition to networkidle.
            page.wait_for_load_state("networkidle", timeout=30_000)
            page.wait_for_timeout(3_000)

        if is_login_page(page) or is_2fa_page(page):
            # Dump diagnostics for post-mortem
            try:
                from pathlib import Path
                from datetime import datetime
                diag_dir = Path("logs/autopull/diagnostics")
                diag_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                page.screenshot(path=str(diag_dir / f"login_fail_{ts}.png"),
                                full_page=True)
                (diag_dir / f"login_fail_{ts}.html").write_text(page.content())
                log.warning("Diagnostics saved to %s/login_fail_%s.*", diag_dir, ts)
            except Exception as e:
                log.warning("Diagnostic capture failed: %s", e)
            raise SessionError(
                f"Still on login/2FA page after credential + code submission "
                f"(url={page.url})"
            )

        if refreshed:
            self.auth_file.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(self.auth_file))
        return page, refreshed

    def _submit_email(self, page: Any) -> None:
        """Step 1 of GC login: fill email, click Continue."""
        for sel in ("input[type='email']", "input[name='email']",
                    "input[autocomplete='username']"):
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.fill(self.email)
                break
        else:
            raise SessionError("Email input not found on login page")

        # Role-based selector first (matches "Continue" / "Sign in" button)
        import re as _re
        try:
            btn = page.get_by_role("button",
                                   name=_re.compile("Continue|Sign in", _re.I)).first
            if btn.count() > 0:
                btn.click()
                return
        except Exception:
            pass
        for sel in ("button[type='submit']", "button:has-text('Continue')",
                    "button:has-text('Sign in')"):
            btn = page.locator(sel).first
            if btn.count() > 0:
                btn.click()
                return
        # Last resort: submit by pressing Enter in the email field
        loc.press("Enter")

    def _submit_code_and_password(self, page: Any, code: str) -> None:
        """Step 2 of GC login: fill 2FA code + password, click Sign in."""
        # Fill the 2FA code
        for sel in ("input[name='code']", "input[placeholder*='ode']",
                    "input[aria-label*='ode']",
                    "input[autocomplete='one-time-code']",
                    "input[inputmode='numeric']"):
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.fill(code)
                break
        else:
            raise SessionError("Code input not found on 2FA page")

        # Fill the password (GC shows this on the same page as the code)
        for sel in ("input[type='password']", "input[name='password']"):
            loc = page.locator(sel).first
            try:
                loc.wait_for(state="visible", timeout=10_000)
            except Exception:
                continue
            if loc.count() > 0:
                loc.fill(self.password)
                break
        else:
            raise SessionError("Password input not found on 2FA page")

        # Submit
        import re as _re
        try:
            btn = page.get_by_role(
                "button", name=_re.compile("Sign in|Continue|Log in", _re.I),
            ).first
            if btn.count() > 0:
                btn.click()
                return
        except Exception:
            pass
        for sel in ("button[type='submit']", "button:has-text('Sign in')",
                    "button:has-text('Continue')", "button:has-text('Log in')"):
            btn = page.locator(sel).first
            if btn.count() > 0:
                btn.click()
                return
        loc.press("Enter")
