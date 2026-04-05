"""
GameChanger Scraper for Softball
Browser automation via Playwright to scrape ALL stat categories from web.gc.com.

STAT CATEGORIES SCRAPED:
  • Batting: Standard, Advanced
  • Pitching: Standard, Advanced, Breakdown
  • Fielding: Standard, Catching, Innings Played

REQUIRES: pip install playwright && playwright install chromium
REQUIRES: GC_EMAIL and GC_PASSWORD in .env
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

try:
    import pyotp
except ImportError:
    pyotp = None

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DATA_DIR = Path(__file__).parent.parent / "data"
SHARKS_DIR = DATA_DIR / "sharks"
OPPONENTS_DIR = DATA_DIR / "opponents"
TMP_DIR = Path(__file__).parent.parent / ".tmp"

GC_BASE_URL = "https://web.gc.com"
GC_LOGIN_URL = f"{GC_BASE_URL}/login"

# Team-specific config (env-overridable)
GC_TEAM_ID = os.getenv("GC_TEAM_ID", "NuGgx6WvP7TO")
GC_SEASON_SLUG = os.getenv("GC_SEASON_SLUG", "2026-spring-sharks")
GC_STATS_URL = f"{GC_BASE_URL}/teams/{GC_TEAM_ID}/{GC_SEASON_SLUG}/season-stats"

# Headless mode: set GC_HEADLESS=false in .env to watch the browser
GC_HEADLESS = os.getenv("GC_HEADLESS", "true").lower() != "false"

# Auth cooldown: prevent rapid-fire 2FA code emails when session is expired.
# After a login failure, wait this many hours before retrying authenticated scraping.
AUTH_COOLDOWN_HOURS = float(os.getenv("AUTH_COOLDOWN_HOURS", "4"))
# GC_AUTH_COOLDOWN_FILE can be overridden (e.g. in Modal to point to a persistent volume)
_AUTH_COOLDOWN_FILE = Path(os.getenv("GC_AUTH_COOLDOWN_FILE", str(DATA_DIR / ".auth_cooldown")))


def set_auth_cooldown(reason: str = ""):
    """Record that auth failed — prevents retries for AUTH_COOLDOWN_HOURS."""
    try:
        _AUTH_COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _AUTH_COOLDOWN_FILE.write_text(
            json.dumps({"failed_at": datetime.now(ET).isoformat(), "reason": reason}),
            encoding="utf-8",
        )
        print(f"[GC] Auth cooldown set for {AUTH_COOLDOWN_HOURS}h: {reason}")
    except Exception as e:
        print(f"[GC] [WARN] Could not write cooldown file: {e}")


def clear_auth_cooldown():
    """Remove cooldown after a successful login."""
    try:
        if _AUTH_COOLDOWN_FILE.exists():
            _AUTH_COOLDOWN_FILE.unlink()
    except Exception:
        pass


def is_auth_on_cooldown() -> bool:
    """Check if we're in an auth cooldown period (recent login failure)."""
    if not _AUTH_COOLDOWN_FILE.exists():
        return False
    try:
        data = json.loads(_AUTH_COOLDOWN_FILE.read_text(encoding="utf-8"))
        failed_at = datetime.fromisoformat(data["failed_at"])
        elapsed = (datetime.now(ET) - failed_at).total_seconds() / 3600
        if elapsed < AUTH_COOLDOWN_HOURS:
            print(f"[GC] Auth on cooldown ({elapsed:.1f}h / {AUTH_COOLDOWN_HOURS}h). "
                  f"Reason: {data.get('reason', 'unknown')}")
            return True
        # Cooldown expired — clean up
        _AUTH_COOLDOWN_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return False

# ---------- Column mappings for each stat category ---------- #
# Maps raw GC column header -> clean JSON key name

BATTING_STD_MAP = {
    "GP": "gp", "PA": "pa", "AB": "ab", "AVG": "avg", "OBP": "obp",
    "OPS": "ops", "SLG": "slg", "H": "h", "1B": "singles", "2B": "doubles",
    "3B": "triples", "HR": "hr", "RBI": "rbi", "R": "r", "BB": "bb",
    "HBP": "hbp", "ROE": "roe", "FC": "fc", "CI": "ci", "SAC": "sac",
    "SF": "sf", "SO": "so", "K-L": "kl", "SB": "sb", "CS": "cs",
    "SB%": "sb_pct", "PIK": "pik",
}

BATTING_ADV_MAP = {
    "GP": "gp", "PA": "pa", "TB": "tb", "XBH": "xbh", "AB/HR": "ab_hr",
    "BA/RISP": "ba_risp", "BABIP": "babip", "PS": "ps", "PS/PA": "ps_pa",
    "QAB": "qab", "QAB%": "qab_pct", "BB/K": "bb_k", "C%": "c_pct",
    "2OUTRBI": "two_out_rbi", "HHB": "hhb", "GIDP": "gidp", "GITP": "gitp",
    "6+": "six_plus", "6+%": "six_plus_pct", "2S+3": "two_s_three",
    "2S+3%": "two_s_three_pct", "FB%": "fb_pct", "GB%": "gb_pct", "LD%": "ld_pct",
}

PITCHING_STD_MAP = {
    "GP": "gp", "GS": "gs", "W": "w", "L": "l", "SV": "sv", "SVO": "svo",
    "SV%": "sv_pct", "IP": "ip", "H": "h", "R": "r", "ER": "er", "BB": "bb",
    "SO": "so", "K-L": "kl", "ERA": "era", "WHIP": "whip", "BAA": "baa",
    "BF": "bf", "#P": "np", "PIK": "pik", "SB": "sb", "CS": "cs",
    "SB%": "sb_pct", "HBP": "hbp", "WP": "wp", "BK": "bk", "LOB": "lob",
}

PITCHING_ADV_MAP = {
    "IP": "ip", "S%": "s_pct", "P/IP": "p_ip", "P/BF": "p_bf",
    "FPS%": "fps_pct", "FPSW%": "fpsw_pct", "FPSO%": "fpso_pct",
    "FPSH%": "fpsh_pct", "<3%": "lt3_pct", "<13": "lt13",
    "LOO": "loo", "1ST2OUT": "first_2out", "123INN": "one23_inn",
    "0BBINN": "zero_bb_inn", "FIP": "fip", "K/BF": "k_bf", "K/BB": "k_bb",
    "BB/INN": "bb_inn", "BA/RISP": "ba_risp", "BABIP": "babip",
    "LD%": "ld_pct", "GB%": "gb_pct", "FB%": "fb_pct", "HHB%": "hhb_pct",
    "WEAK%": "weak_pct", "GO/AO": "go_ao", "P/HR": "p_hr",
    "SM%": "sm_pct", "BBS": "bbs", "LOBBS": "lobbs", "LOBB": "lobb",
}

PITCHING_BRK_MAP = {
    "#P": "np",
    "FB": "fb", "FBS": "fbs", "FBS%": "fbs_pct", "FBSM%": "fbsm_pct", "FBSW%": "fbsw_pct",
    "CH": "ch", "CHS": "chs", "CHS%": "chs_pct", "CHSM%": "chsm_pct", "CHSW%": "chsw_pct",
    "CB": "cb", "CBS": "cbs", "CBS%": "cbs_pct", "CBSM%": "cbsm_pct", "CBSW%": "cbsw_pct",
    "SC": "sc", "SCS": "scs", "SCS%": "scs_pct", "SCSM%": "scsm_pct", "SCSW%": "scsw_pct",
    "RB": "rb", "RBS": "rbs", "RBS%": "rbs_pct", "RBSM%": "rbsm_pct", "RBSW%": "rbsw_pct",
    "DB": "db", "DBS": "dbs", "DBS%": "dbs_pct", "DBSM%": "dbsm_pct", "DBSW%": "dbsw_pct",
    "DC": "dc", "DCS": "dcs", "DCS%": "dcs_pct", "DCSM%": "dcsm_pct", "DCSW%": "dcsw_pct",
    "KB": "kb", "KBS": "kbs", "KBS%": "kbs_pct", "KBSM%": "kbsm_pct", "KBSW%": "kbsw_pct",
    "KC": "kc", "KCS": "kcs", "KCS%": "kcs_pct", "KCSM%": "kcsm_pct", "KCSW%": "kcsw_pct",
    "OS": "os_pitch", "OSS": "oss", "OSS%": "oss_pct", "OSSM%": "ossm_pct", "OSSW%": "ossw_pct",
    "MPHFB": "mph_fb", "MPHCH": "mph_ch", "MPHCB": "mph_cb",
    "MPHSC": "mph_sc", "MPHRB": "mph_rb", "MPHDB": "mph_db",
    "MPHDC": "mph_dc", "MPHKB": "mph_kb", "MPHKC": "mph_kc",
}

FIELDING_STD_MAP = {
    "TC": "tc", "PO": "po", "A": "a", "E": "e", "FPCT": "fpct",
    "DP": "dp", "TP": "tp",
}

FIELDING_CATCH_MAP = {
    "INN": "inn", "SB": "sb", "CS": "cs", "CS%": "cs_pct",
    "SB-ATT": "sb_att", "PB": "pb", "PIK": "pik", "CI": "ci",
}

FIELDING_INN_MAP = {
    "IP:F": "total", "IP:P": "p", "IP:C": "c", "IP:1B": "first_base",
    "IP:2B": "second_base", "IP:3B": "third_base", "IP:SS": "ss",
    "IP:LF": "lf", "IP:CF": "cf", "IP:RF": "rf", "IP:SF": "sf",
}

# The 9 stat views, in scraping order (major_tab, sub_tab, column_map, json_key)
STAT_VIEWS = [
    ("Batting",  "Standard",      BATTING_STD_MAP,   "batting"),
    ("Batting",  "Advanced",      BATTING_ADV_MAP,   "batting_advanced"),
    ("Pitching", "Standard",      PITCHING_STD_MAP,  "pitching"),
    ("Pitching", "Advanced",      PITCHING_ADV_MAP,  "pitching_advanced"),
    ("Pitching", "Breakdown",     PITCHING_BRK_MAP,  "pitching_breakdown"),
    ("Fielding", "Standard",      FIELDING_STD_MAP,  "fielding"),
    ("Fielding", "Catching",      FIELDING_CATCH_MAP, "catching"),
    ("Fielding", "Innings Played", FIELDING_INN_MAP,  "innings_played"),
]


def _safe_val(val: str):
    """Convert a scraped cell value to int/float/string as appropriate."""
    if val is None:
        return None
    val = val.strip()
    if val in ("", "-", "—", "N/A"):
        return None
    # Try int first
    try:
        return int(val)
    except ValueError:
        pass
    # Try float
    try:
        return float(val)
    except ValueError:
        pass
    return val


class GameChangerScraper:
    """Scrape softball statistics from GameChanger (web.gc.com)."""

    def __init__(
        self,
        team_id: str | None = None,
        season_slug: str | None = None,
        team_name: str | None = None,
        out_dir: Path | None = None,
        roster_manifest_path: Path | None = None,
        use_manifest: bool = True,
    ):
        self.email = os.getenv("GC_EMAIL", "")
        self.password = os.getenv("GC_PASSWORD", "")
        self.team_name = team_name or os.getenv("TEAM_NAME", "The Sharks")
        self.team_id = team_id or os.getenv("GC_TEAM_ID", GC_TEAM_ID)
        self.season_slug = season_slug or os.getenv("GC_SEASON_SLUG", GC_SEASON_SLUG)
        self.stats_url = f"{GC_BASE_URL}/teams/{self.team_id}/{self.season_slug}/season-stats"
        self.out_dir = out_dir or SHARKS_DIR
        self.roster_manifest_path = roster_manifest_path or (SHARKS_DIR / "roster_manifest.json")
        self.use_manifest = use_manifest
        self.browser = None
        self.context = None
        self.page = None

    def _validate_credentials(self):
        """Ensure GC credentials are available (cookies OR email/password)."""
        has_cookies = bool(os.getenv("GC_SESSION_COOKIES", "").strip())
        has_creds = bool(self.email and self.password)
        if not has_cookies and not has_creds:
            raise ValueError(
                "[GC] Missing credentials. Set GC_SESSION_COOKIES (JSON cookie array) "
                "or GC_EMAIL + GC_PASSWORD in .env"
            )

    def _capture_diagnostics(self, label: str):
        """Capture screenshot and HTML source for debugging on failure."""
        if not self.page:
            return
        
        # Use global ET (America/New_York)
        ts = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
        diag_dir = Path(__file__).parent.parent / "logs" / "diagnostics"
        diag_dir.mkdir(parents=True, exist_ok=True)
        
        screenshot_path = diag_dir / f"fail_{label}_{ts}.png"
        html_path = diag_dir / f"fail_{label}_{ts}.html"
        
        try:
            self.page.screenshot(path=str(screenshot_path), full_page=True)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(self.page.content())
            print(f"[GC] [IMG] Diagnostics saved: {screenshot_path.name}")
        except Exception as e:
            print(f"[GC] [WARN] Could not capture diagnostics: {e}")

    def _get_auth_state(self) -> str:
        """Categorize the current page state."""
        url = self.page.url.lower()
        if "login" in url or "signin" in url:
            return "LOGIN_REQUIRED"
        if "challenge" in url or "verif" in url:
            return "CHALLENGED"

        # Check for login form
        if self.page.locator('input[name="email"], input[type="email"]').count() > 0:
            return "LOGIN_REQUIRED"

        # Check if we are on a team/stats page — but verify actual auth content.
        # GC serves the SAME URL to unauthenticated users with a public "Download the app"
        # promo banner instead of the stats grid. Check for that to avoid a false positive.
        if "/teams/" in url or "stats" in url:
            try:
                # Sign-in button in nav → unauthenticated
                if self.page.locator(
                    '[data-testid="desktop-sign-in-button"], '
                    '[data-testid="mobile-sign-in-button"]'
                ).count() > 0:
                    return "LOGIN_REQUIRED"
                # App promo banner → unauthenticated public view
                if self.page.locator(
                    '.AppInstructionsBanner__wrapper, '
                    '.TeamAppInstructions__container'
                ).count() > 0:
                    return "LOGIN_REQUIRED"
            except Exception:
                pass
            return "AUTHENTICATED"

        return "UNKNOWN"

    def _complete_login_flow(self):
        """Handle current GC login UX (email step -> password step -> optional OTP)."""
        print("[GC] Entering credentials...")

        try:
            # Step 1: email gate
            email_field = self.page.get_by_label("Email", exact=False).or_(
                self.page.locator('input[name="email"], input[type="email"]')
            ).first

            email_field.wait_for(state="visible", timeout=15000)
            email_field.fill(self.email)

            # Look for Continue/Next button (GC may use different labels across versions)
            continue_btn = self.page.get_by_role("button", name=re.compile(r"Continue|Sign.?[Ii]n|Log.?[Ii]n|Next", re.I)).first
            if continue_btn.count() > 0:
                continue_btn.click()
            else:
                email_field.press("Enter")

            # Step 2: password gate
            pwd_field = self.page.get_by_label("Password", exact=False).or_(
                self.page.locator('input[name="password"], input[type="password"]')
            ).first

            pwd_field.wait_for(state="visible", timeout=15000)
            pwd_field.fill(self.password)

            sign_in_btn = self.page.get_by_role("button", name=re.compile(r"Sign.?[Ii]n|Log.?[Ii]n|Continue|Submit", re.I)).first
            if sign_in_btn.count() > 0:
                sign_in_btn.click()
            else:
                pwd_field.press("Enter")

            # Wait for navigation away from login
            self.page.wait_for_load_state("networkidle", timeout=30000)

            # Step 3: OTP / MFA gate (GC sends a 6-digit email code)
            self._handle_otp_if_needed()

        except Exception as e:
            self._capture_diagnostics("login_flow_error")
            raise RuntimeError(f"[GC] Error during login flow: {e}")

    def _handle_otp_if_needed(self):
        """Detect and complete GC's email OTP challenge if present."""
        # Look for an OTP/verification code input
        otp_field = self.page.locator(
            'input[autocomplete="one-time-code"], '
            'input[name="code"], '
            'input[placeholder*="code" i], '
            'input[placeholder*="verification" i]'
        ).first

        if otp_field.count() == 0:
            # Also try text-based detection
            page_text = self.page.inner_text("body")
            if not any(kw in page_text.lower() for kw in ["verification code", "check your email", "enter code", "one-time"]):
                return  # No OTP prompt detected
            # Try a generic number input fallback
            otp_field = self.page.locator('input[type="number"], input[type="text"][maxlength="6"]').first

        if otp_field.count() == 0:
            print("[GC] No OTP field found, proceeding...")
            return

        print("[GC] [OTP] OTP/MFA prompt detected!")

        # Strategy 1: Generate a fresh TOTP code if GC_TOTP_SECRET is set
        totp_secret = os.getenv("GC_TOTP_SECRET", "").strip()
        if totp_secret and pyotp:
            otp_code = pyotp.TOTP(totp_secret).now()
            print(f"[GC] Generated fresh TOTP: {otp_code[:2]}****")
            otp_field.fill(otp_code)
            submit_btn = self.page.get_by_role("button", name=re.compile("Verify|Continue|Submit|Confirm", re.I)).first
            if submit_btn.count() > 0:
                submit_btn.click()
            else:
                otp_field.press("Enter")
            self.page.wait_for_load_state("networkidle", timeout=30000)
            print("[GC] [OK] TOTP submitted.")
            return

        # Strategy 2: Headless without TOTP — fail clearly
        is_headless = GC_HEADLESS or os.getenv("SYNC_DAEMON_MODE", "").strip()
        if is_headless:
            set_auth_cooldown("2FA code required — set GC_TOTP_SECRET or GC_SESSION_COOKIES")
            raise RuntimeError(
                "[GC] 2FA/OTP required but no GC_TOTP_SECRET set. "
                "Add GC_TOTP_SECRET to Modal secrets at "
                "modal.com/secrets/anchorgroupops/main/softball-sharks-auth"
            )

        # Strategy 3: Interactive mode — wait for manual entry
        print("[GC] [WARN] OTP required. Waiting 180s for manual entry...")
        print("[GC]    → Enter the code in the browser window NOW. You have 3 minutes.")
        self.page.wait_for_timeout(180000)
        print("[GC] Resuming after OTP wait...")


    def _heal_locator(self, target_text: str, role: str = "button") -> Any:
        """Self-healing locator factory. Tries multiple strategies to find an element."""
        # Strategy 1: Strict role + text
        loc = self.page.get_by_role(role, name=target_text, exact=False).first
        if loc.count() > 0:
            return loc

        # Strategy 2: Fuzzy text matching (any element)
        loc = self.page.get_by_text(target_text, exact=False).first
        if loc.count() > 0:
            print(f"[GC] [HEAL] Found '{target_text}' via fuzzy text instead of role '{role}'")
            return loc

        # Strategy 3: Regex match on all clickable elements
        try:
            loc = self.page.locator(f"button, a, [role='button'], [role='tab']").filter(
                has_text=re.compile(target_text, re.I)
            ).first
            if loc.count() > 0:
                print(f"[GC] [HEAL] Found '{target_text}' via regex filter on clickable elements")
                return loc
        except Exception:
            pass

        return None

    def login(self, playwright, force_refresh: bool = False):
        """Log in to GameChanger via browser automation using persistent sessions."""
        # Check cooldown BEFORE attempting login to avoid triggering 2FA codes
        if is_auth_on_cooldown() and not force_refresh:
            raise RuntimeError(
                "[GC] Auth on cooldown — skipping login to avoid triggering 2FA codes. "
                "Cooldown clears automatically or set GC_OTP env var and re-run."
            )

        self._validate_credentials()
        self.playwright = playwright

        auth_file_env = os.getenv("GC_AUTH_FILE", "").strip()
        auth_file = Path(auth_file_env) if auth_file_env else (DATA_DIR / "auth.json")
        auth_file.parent.mkdir(parents=True, exist_ok=True)

        context_dir = os.getenv("GC_PLAYWRIGHT_CONTEXT_DIR", "").strip()
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        # Common context kwargs: consistent viewport + locale reduce bot-detection triggers
        _ctx_kwargs = {
            "user_agent": user_agent,
            "viewport": {"width": 1280, "height": 800},
            "locale": "en-US",
        }

        if context_dir:
            # Persistent context manages its own browser — don't launch a separate one
            context_path = Path(context_dir)
            context_path.mkdir(parents=True, exist_ok=True)
            print(f"[GC] Using persistent context at {context_path}")
            self.context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(context_path),
                headless=GC_HEADLESS,
                **_ctx_kwargs,
            )
            self.browser = self.context
        else:
            self.browser = playwright.chromium.launch(
                headless=GC_HEADLESS,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            if auth_file.exists() and not force_refresh:
                print(f"[GC] Loading session from {auth_file.name}")
                self.context = self.browser.new_context(
                    storage_state=str(auth_file),
                    **_ctx_kwargs,
                )
            else:
                print("[GC] Creating new clean context")
                self.context = self.browser.new_context(**_ctx_kwargs)

        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

        # --- Cookie injection auth path (preferred — avoids 2FA entirely) ---
        session_cookies_json = os.getenv("GC_SESSION_COOKIES", "").strip()
        if session_cookies_json:
            try:
                cookies = json.loads(session_cookies_json)
                if isinstance(cookies, list) and cookies:
                    # Ensure each cookie has the required domain field
                    for c in cookies:
                        if "domain" not in c:
                            c["domain"] = ".gc.com"
                        if "path" not in c:
                            c["path"] = "/"
                    self.context.add_cookies(cookies)
                    print(f"[GC] Injected {len(cookies)} session cookies from GC_SESSION_COOKIES")
            except (json.JSONDecodeError, TypeError) as e:
                print(f"[GC] [WARN] Failed to parse GC_SESSION_COOKIES: {e}")

        print(f"[GC] Navigating to {GC_BASE_URL}...")
        self.page.goto(GC_BASE_URL, wait_until="domcontentloaded", timeout=60000)

        # Check initial state
        state = self._get_auth_state()
        print(f"[GC] Initial state: {state}")

        if state == "LOGIN_REQUIRED":
            # If we only have cookies (no email/password), fail clearly
            if session_cookies_json and not (self.email and self.password):
                self._capture_diagnostics("cookie_auth_failed")
                raise RuntimeError(
                    "[GC] Cookie-based auth failed — session cookies may be expired. "
                    "Update GC_SESSION_COOKIES with fresh cookies from a logged-in browser."
                )
            print("[GC] Session invalid or expired. Running login flow...")
            self._complete_login_flow()
            self._wait_for_stable_page(self.stats_url)
        elif state == "AUTHENTICATED":
            print("[GC] Session restored from storage state.")
            self._wait_for_stable_page(self.stats_url)
        elif state == "CHALLENGED":
            self._capture_diagnostics("auth_challenged")
            if not force_refresh:
                print("[GC] [HEAL] Attempting fresh context after challenge...")
                self.close()
                return self.login(playwright, force_refresh=True)
            raise RuntimeError("[GC] Blocked by security challenge (Bot detection).")

        # Final validation
        final_state = self._get_auth_state()
        if final_state != "AUTHENTICATED":
            if not force_refresh:
                # Only retry once — avoid cascading login attempts that spam 2FA emails
                print("[GC] [HEAL] Auth failed with cached state, trying fresh login...")
                self.close()
                return self.login(playwright, force_refresh=True)

            self._capture_diagnostics("auth_failed")
            print(f"[GC] Current URL: {self.page.url}")
            # Longer cooldown (4h default) to prevent 2FA email storms
            cooldown_hours = float(os.getenv("AUTH_COOLDOWN_HOURS", "4"))
            set_auth_cooldown(f"Login failed, state={final_state}")
            raise RuntimeError(
                f"[GC] Authentication failed. State: {final_state}. "
                f"Cooldown set for {cooldown_hours}h to prevent 2FA spam. "
                f"To bypass: delete {DATA_DIR / '.auth_cooldown'}"
            )

        print(f"[GC] Authenticated. Current URL: {self.page.url}")
        clear_auth_cooldown()

        # Save session for next time (even if using persistent context, helps on Modal)
        if not context_dir:
            self.context.storage_state(path=str(auth_file))
            print(f"[GC] Session state saved to {auth_file.name}")

        return self.page

    def _wait_for_stable_page(self, url: str, timeout: int = 30000):
        """Wait for page navigation and stability."""
        try:
            self.page.goto(url, wait_until="networkidle", timeout=timeout)
            self.page.wait_for_timeout(1000) # Final settle
        except Exception as e:
            print(f"[GC] [WARN] Network idle not reached for {url}: {e}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)

    # ------------------------------------------------------------------ #
    #  Core: Extract a single stat table from the current view
    # ------------------------------------------------------------------ #
    def _extract_table(self) -> list[dict]:
        """Extract data from a table or ag-grid."""
        return self.page.evaluate("""
            () => {
                const results = [];
                const gridRoot = document.querySelector('.ag-root-wrapper');
                
                if (gridRoot) {
                    // 1. ag-grid extraction (Header labels are often mapped to col-id)
                    const headerCells = Array.from(gridRoot.querySelectorAll('.ag-header-cell'));
                    const colMap = headerCells.map(cell => {
                        const label = cell.querySelector('.ag-header-cell-label')?.innerText.trim();
                        const colId = cell.getAttribute('col-id');
                        return { label, colId };
                    }).filter(c => c.label);

                    const rows = Array.from(gridRoot.querySelectorAll('.ag-row'));
                    rows.forEach(row => {
                        const obj = {};
                        colMap.forEach(col => {
                            const cell = row.querySelector(`.ag-cell[col-id="${col.colId}"]`);
                            if (cell) {
                                obj[col.label] = cell.innerText.trim();
                            }
                        });
                        
                        // Specialized player name lookup
                        const playerLink = row.querySelector('a.ag-cell-info, [class*="player-name"]');
                        if (playerLink) {
                            obj['Player'] = playerLink.innerText.trim();
                            const href = playerLink.getAttribute('href') || '';
                            if (href.includes('/players/')) {
                                obj['_gc_id'] = href.split('/').filter(Boolean).pop();
                            }
                        }

                        if (Object.keys(obj).length > 0) results.push(obj);
                    });
                    if (results.length > 0) return results;
                }
                
                // 2. Fallback to standard table
                const table = document.querySelector('table, [role="table"]');
                if (table) {
                    const headers = Array.from(table.querySelectorAll('th, .ag-header-cell-label'))
                        .map(th => th.innerText.trim())
                        .filter(h => h !== '');
                    const rows = Array.from(table.querySelectorAll('tbody tr, .ag-row'));
                    return rows.map(row => {
                        const cells = Array.from(row.querySelectorAll('td, .ag-cell'));
                        const obj = {};
                        headers.forEach((h, i) => { if (cells[i]) obj[h] = cells[i].innerText.trim(); });
                        return obj;
                    });
                }
                return [];
            }
        """)

    def _click_tab(self, tab_text: str) -> bool:
        """Click a tab/button with self-healing capabilities."""
        print(f"[GC] Attempting to click tab: {tab_text}")
        try:
            # 1. Try specific GC chooser class (multi-pattern — CSS modules change on each GC deploy)
            for _class_pat in [
                '.TabViewChooserItem__tabViewChooserItem',
                '[class*="TabViewChooser"]',
                '[class*="tabViewChooser"]',
                '[class*="StatsTab"]',
            ]:
                loc = self.page.locator(f'{_class_pat}:has-text("{tab_text}")').first
                if loc.count() > 0:
                    try:
                        loc.click(timeout=3000)
                        self.page.wait_for_timeout(2000)
                        print(f"[GC]   [OK] Clicked '{tab_text}' via {_class_pat}")
                        return True
                    except Exception:
                        continue

            # 2. Try the sub-tab dropdown (Standard, Advanced, etc.)
            if tab_text in ["Standard", "Advanced", "Breakdown", "Catching", "Innings Played"]:
                dropdown = self.page.locator(
                    '.StatsDropdownViewChooser__textButton, '
                    '[class*="StatsDropdown"][class*="Button"], '
                    '[class*="DropdownViewChooser"]'
                ).first
                if dropdown.is_visible():
                    dropdown.click()
                    self.page.wait_for_timeout(500)
                    # Options are titles in labels
                    option = self.page.locator(f"label[title*='{tab_text}'], text='{tab_text}'").first
                    if option.count() > 0:
                        option.click()
                        self.page.wait_for_timeout(2000)
                        print(f"[GC]   [OK] Selected '{tab_text}' from dropdown")
                        return True

            # 3. Fallback to general roles
            for role in ["tab", "button", "link"]:
                btn = self._heal_locator(tab_text, role=role)
                if btn:
                    btn.click()
                    self.page.wait_for_timeout(2000)
                    print(f"[GC]   [OK] Clicked '{tab_text}' via common {role}")
                    return True
            
            print(f"[GC]   [WARN] Could not find tab '{tab_text}'")
            self._capture_diagnostics(f"click_tab_failed_{tab_text}")
            return False
                
        except Exception as e:
            print(f"[GC] [ERROR] Tab click failed for '{tab_text}': {e}")
            return False

    # ------------------------------------------------------------------ #
    #  Scrape W-L record from schedule page
    # ------------------------------------------------------------------ #
    def scrape_record(self) -> str:
        """Scrape the team W-L-T record. Heuristic based on common GC header elements."""
        try:
            # Check for standard record patterns in text blocks
            record_match = self.page.evaluate("""
                () => {
                    const text = document.body.innerText;
                    const matches = text.match(/(\\d+-\\d+-\\d+)/) || text.match(/(\\d+-\\d+)/);
                    return matches ? matches[0] : null;
                }
            """)
            if record_match: return record_match
            
            # Secondary check specifically in headers
            header = self.page.locator('header').first
            if header.count() > 0:
                t = header.inner_text()
                m = re.search(r'(\d+-\d+(-\d+)?)', t)
                if m: return m.group(1)
        except Exception as e:
            print(f"[GC] [WARN] Record scrape failed: {e}")
        return "0-0"

    # ------------------------------------------------------------------ #
    #  Scrape per-game box scores from the schedule page
    # ------------------------------------------------------------------ #
    def scrape_game_box_scores(self) -> list[dict]:
        """
        Scrape per-game box scores for all completed games.
        Returns a list of game dicts; also saves each to data/sharks/games/.
        """
        if not self.page:
            raise RuntimeError("[GC] Not logged in. Call login() first.")

        schedule_url = f"{GC_BASE_URL}/teams/{self.team_id}/{self.season_slug}/schedule"
        games_dir = self.out_dir / "games"
        games_dir.mkdir(parents=True, exist_ok=True)

        print(f"[GC] Navigating to schedule: {schedule_url}")
        self.page.goto(schedule_url, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(3000)

        # Find all completed game links (links that have a score visible)
        game_links = self.page.evaluate("""
        (() => {
            const links = [];
            // GC schedule links often include /games/ or /plays in the path
            document.querySelectorAll('a[href*="/schedule/"]').forEach(a => {
                const href = a.href;
                if (!links.includes(href)) links.push(href);
            });
            return links;
        })()
        """)

        print(f"[GC] Found {len(game_links)} schedule links")
        games = []

        for link in game_links[:20]:  # cap at 20 to avoid runaway
            try:
                # Navigate to the game page
                self.page.goto(link, wait_until="domcontentloaded", timeout=60000)
                self.page.wait_for_timeout(2000)

                # Click "Box Score" tab if present
                has_boxscore = self._click_tab("Box Score")
                if not has_boxscore:
                    # Try "Summary" as fallback
                    self._click_tab("Summary")

                self.page.wait_for_timeout(1500)

                # Extract game metadata from page
                meta = self.page.evaluate("""
                (() => {
                    const title = document.title || '';
                    // Look for score elements
                    const scores = Array.from(document.querySelectorAll('[class*="score"], [class*="Score"]'))
                        .map(el => el.textContent.trim()).filter(t => /^\\d+$/.test(t)).slice(0, 2);
                    // Look for date
                    const dateEl = document.querySelector('time, [datetime]');
                    const date = dateEl ? (dateEl.getAttribute('datetime') || dateEl.textContent.trim()) : '';
                    // Team names
                    const teamEls = Array.from(document.querySelectorAll('[class*="team-name"], [class*="teamName"]'))
                        .map(el => el.textContent.trim()).filter(Boolean).slice(0, 2);
                    return { title, scores, date, teams: teamEls };
                })()
                """)

                rows = self._extract_table()

                if not rows:
                    continue

                # Parse players from rows
                box_players = []
                for row in rows:
                    raw_name = (row.get("Player") or row.get("player") or row.get("") or "").strip()
                    if not raw_name or raw_name.lower() in ("team", "totals", "team totals"):
                        continue
                    player_stats = {"name": raw_name}
                    for gc_col, key in BATTING_STD_MAP.items():
                        if gc_col in row:
                            player_stats[key] = _safe_val(row[gc_col])
                    box_players.append(player_stats)

                if not box_players:
                    continue

                # Derive a filename from the URL
                url_slug = re.sub(r"[^a-z0-9]+", "_", link.lower().rstrip("/").split("/")[-1])
                game_data = {
                    "source_url": link,
                    "meta": meta,
                    "batting": box_players,
                    "scraped_at": datetime.now(ET).isoformat(),
                }

                out_file = games_dir / f"{url_slug}.json"
                with open(out_file, "w") as f:
                    json.dump(game_data, f, indent=2)
                print(f"[GC] [OK] Saved box score: {out_file.name} ({len(box_players)} players)")
                games.append(game_data)

                self.page.wait_for_timeout(2000)

            except Exception as e:
                print(f"[GC] [WARN] Error scraping game {link}: {e}")
                continue

        print(f"[GC] [OK] Box scores complete: {len(games)} games scraped")
        return games

    # ------------------------------------------------------------------ #
    #  Main: Scrape all 9 stat views
    # ------------------------------------------------------------------ #
    def scrape_all_stats(self) -> dict | None:
        """
        Scrape ALL stat categories from the GC Season Stats page.
        Merges data across all views into a unified per-player structure.
        Returns the full team dict ready for team.json.
        """
        if not self.page:
            raise RuntimeError("[GC] Not logged in. Call login() first.")

        print(f"[GC] Navigating to stats page: {self.stats_url}")
        self.page.goto(self.stats_url, wait_until="networkidle", timeout=60000)
        
        # Mandatory wait for UI to render — try multiple selector patterns
        _STATS_TAB_SELS = [
            ".TabViewChooserItem__tabViewChooserItem",
            "[class*='TabViewChooser']",
            "[class*='tabViewChooser']",
            "[class*='StatsTab']",
            "[role='tab']",
        ]
        _found_stats_ui = False
        for _sel in _STATS_TAB_SELS:
            try:
                print(f"[GC] Waiting for stats UI ({_sel})...")
                self.page.wait_for_selector(_sel, timeout=12000)
                print(f"[GC] [OK] Stats UI detected via {_sel}.")
                _found_stats_ui = True
                break
            except Exception:
                continue
        if not _found_stats_ui:
            print("[GC] [WARN] No stats UI selector matched. Attempting fallback wait...")
            self.page.wait_for_timeout(5000)
            self._capture_diagnostics("stats_ui_missing")

        # Dismiss any popups (follow team dialog etc.)
        try:
            maybe_later = self.page.locator('button:has-text("Maybe later"), button:has-text("No thanks")').first
            if maybe_later.count() > 0:
                maybe_later.click()
                self.page.wait_for_timeout(1000)
        except Exception:
            pass

        # Player accumulator: keyed by canonical name
        players = {}  # name -> {stat_category: {key: val}}
        team_totals = {}  # stat_category -> {key: val}

        last_major = None

        for major_tab, sub_tab, col_map, json_key in STAT_VIEWS:
            print(f"[GC] Scraping: {major_tab} -> {sub_tab}...")

            # Click major tab only if we're switching categories
            if major_tab != last_major:
                if not self._click_tab(major_tab):
                    print(f"[GC]   [WARN] Could not find major tab '{major_tab}', skipping...")
                    continue
                last_major = major_tab

            # Click sub tab
            if sub_tab != "Standard":
                if not self._click_tab(sub_tab):
                    print(f"[GC]   [WARN] Could not find sub tab '{sub_tab}', skipping...")
                    continue

            # Extract the table
            rows = self._extract_table()
            if not rows:
                print(f"[GC]   [WARN] No data found for {major_tab}/{sub_tab}")
                continue

            print(f"[GC]   [OK] Got {len(rows)} rows")

            for row in rows:
                # Identify player: first column is usually "Player" or the player name
                # GC sometimes uses "Player" header, sometimes just puts the name
                raw_name = (
                    row.get("Player")
                    or row.get("player")
                    or row.get("")
                    or row.get("col0")
                    or ""
                ).strip()

                if not raw_name:
                    continue

                # Team totals row
                if raw_name.lower() in ("team", "totals", "team totals"):
                    totals = {}
                    for gc_col, key in col_map.items():
                        if gc_col in row:
                            totals[key] = _safe_val(row[gc_col])
                    team_totals[json_key] = totals
                    continue

                # Parse player name and number
                # GC format: "FirstName LastName, #NN" or "FirstName LastName #NN"
                name = raw_name
                number = ""
                # Extract number if present
                num_match = re.search(r'#(\d+)', raw_name)
                if num_match:
                    number = num_match.group(1)
                    name = raw_name[:num_match.start()].strip().rstrip(',').strip()

                # Also check the "#" column
                if not number and "#" in row:
                    number = str(row["#"]).strip()

                # Canonical key for merging
                canon = name.lower().strip()

                if canon not in players:
                    # Split name
                    name_parts = name.split(" ", 1)
                    first = name_parts[0]
                    last = name_parts[1] if len(name_parts) > 1 else ""
                    players[canon] = {
                        "first": first,
                        "last": last,
                        "number": number,
                        "core": True,  # will be filtered later by manifest
                    }

                # Update number if we didn't have it
                if number and not players[canon].get("number"):
                    players[canon]["number"] = number

                # Map columns
                stat_obj = {}
                for gc_col, key in col_map.items():
                    if gc_col in row:
                        stat_obj[key] = _safe_val(row[gc_col])

                players[canon][json_key] = stat_obj

        # ---- Post-processing ---- #
        # Scrape actual record from schedule page
        record = self.scrape_record()
        print(f"[GC] Team record: {record}")
        print(f"[GC] Raw player count: {len(players)}")

        # Load roster manifest for core/non-core tagging
        manifest = {}
        if self.use_manifest and self.roster_manifest_path.exists():
            with open(self.roster_manifest_path, "r") as mf:
                manifest = json.load(mf)

        def _norm_name(name: str) -> str:
            return re.sub(r"[^a-z]", "", name.lower())

        core_names = {_norm_name(n) for n in manifest.get("core_players", [])}
        borrowed_names = {_norm_name(n) for n in manifest.get("borrowed_players", [])}
        alias_map = {_norm_name(k): _norm_name(v) for k, v in manifest.get("aliases", {}).items()}
        core_numbers = {str(n).lstrip("0") for n in manifest.get("core_numbers", [])}

        def _is_core(pdata: dict) -> bool:
            full_name = f"{pdata['first']} {pdata['last']}".strip()
            norm = _norm_name(full_name)
            if norm in alias_map:
                norm = alias_map[norm]
            number = str(pdata.get("number", "")).lstrip("0")
            if norm in borrowed_names:
                return False
            if core_names and norm in core_names:
                return True
            if core_numbers and number in core_numbers:
                return True
            if core_names:
                return False
            return True

        # Tag core/non-core and sort (keep ALL players for lineup management)
        roster = []
        for canon, pdata in players.items():
            full_name = f"{pdata['first']} {pdata['last']}".strip()
            pdata["core"] = _is_core(pdata)
            pdata["borrowed"] = not pdata["core"]
            if pdata["borrowed"]:
                print(f"[GC] Non-core player tagged: {full_name}")
            roster.append(pdata)

        # Sort alphabetically by first name
        roster.sort(key=lambda x: x.get("first", "").lower())
        # GUARD: Do not overwrite existing data with empty results
        if not roster:
            print("[GC] [WARN] No players scraped! Skipping team.json write to preserve existing data.")
            return None

        team = {
            "team_name": self.team_name,
            "league": "PCLL Majors",
            "season": "Spring 2026",
            "gc_team_url": self.stats_url,
            "gc_team_id": self.team_id,
            "gc_season_slug": self.season_slug,
            "last_updated": datetime.now(ET).isoformat(),
            "record": record,
            "roster": roster,
            "team_totals": team_totals,
        }

        # Save
        self.out_dir.mkdir(parents=True, exist_ok=True)
        output = self.out_dir / "team.json"
        with open(output, "w") as f:
            json.dump(team, f, indent=2)
        print(f"[GC] [OK] Team data saved to {output} ({len(roster)} players, {len(STAT_VIEWS)} stat categories)")

        return team

    # Legacy method for backward compat with sync_daemon
    def scrape_team_stats(self) -> dict | None:
        """Alias to scrape_all_stats for backward compatibility."""
        return self.scrape_all_stats()

    def close(self):
        """Close the browser."""
        if self.context:
            self.context.close()
            print("[GC] Browser context closed.")
        if self.browser and self.browser is not self.context:
            self.browser.close()
            print("[GC] Browser closed.")
        self.context = None
        self.browser = None


def run():
    """Main entry point for the GC scraper."""
    import sys

    if sync_playwright is None:
        print("[GC] ERROR: Playwright not installed.")
        print("[GC] Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="GameChanger stats scraper")
    parser.add_argument("--team-id", dest="team_id", default=None, help="GC Team ID")
    parser.add_argument("--season-slug", dest="season_slug", default=None, help="GC season slug (e.g. 2026-spring-sharks)")
    parser.add_argument("--team-name", dest="team_name", default=None, help="Team display name")
    parser.add_argument("--out-dir", dest="out_dir", default=None, help="Output directory for team.json")
    parser.add_argument("--no-manifest", dest="no_manifest", action="store_true", help="Disable roster manifest core tagging")
    parser.add_argument("--box-scores", dest="box_scores", action="store_true", help="Also scrape per-game box scores")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else None
    scraper = GameChangerScraper(
        team_id=args.team_id,
        season_slug=args.season_slug,
        team_name=args.team_name,
        out_dir=out_dir,
        use_manifest=not args.no_manifest,
    )

    had_error = False
    with sync_playwright() as pw:
        try:
            scraper.login(pw)
            team = scraper.scrape_all_stats()
            if team:
                print(f"[GC] Successfully scraped {len(team.get('roster', []))} players")
            if args.box_scores:
                print("[GC] Scraping per-game box scores...")
                scraper.scrape_game_box_scores()
        except Exception as e:
            print(f"[GC] Error: {e}")
            import traceback
            traceback.print_exc()
            had_error = True
        finally:
            scraper.close()

    if had_error:
        sys.exit(1)


if __name__ == "__main__":
    run()
