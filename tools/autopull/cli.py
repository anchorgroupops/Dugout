"""Autopull CLI — the single entry point called by cron and sync_daemon.

The heavy lifting (Playwright + Gmail + ingest) is injected via a `runner`
callable so unit tests can exercise the orchestration logic without touching
the network or a browser.
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tools.autopull import config as config_mod
from tools.autopull.state import StateDB

ET = ZoneInfo("America/New_York")
log = logging.getLogger(__name__)


def run_once(*, cfg: config_mod.AutopullConfig, trigger: str,
             runner: Callable[..., dict]) -> dict:
    """Do one full autopull run. Returns a summary dict."""
    db_path = cfg.data_root / "autopull" / "autopull_state.db"
    db = StateDB(db_path)
    db.init_schema()

    if not cfg.enabled:
        return {"outcome": "skipped", "reason": "disabled"}
    if trigger == "postgame" and not cfg.postgame_enabled:
        return {"outcome": "skipped", "reason": "postgame disabled"}

    recent = db.last_successful_run_within(minutes=cfg.idempotency_window_min)
    if recent is not None:
        return {
            "outcome": "skipped",
            "reason": f"recent success within {cfg.idempotency_window_min}m (run #{recent.id})",
        }

    if db.breaker_open("auth"):
        return {"outcome": "skipped", "reason": "auth breaker open"}

    run_id = db.start_run(trigger=trigger)
    started = time.monotonic()
    try:
        out = runner(cfg=cfg, db=db, run_id=run_id)
    except Exception as e:
        log.exception("runner raised")
        duration_ms = int((time.monotonic() - started) * 1000)
        db.complete_run(
            run_id, outcome="failure", csv_path=None, rows_ingested=None,
            winning_strategy_id=None, duration_ms=duration_ms,
            llm_fallback_invoked=False, session_refreshed=False,
            failure_reason=str(e),
        )
        db.breaker_record_failure(_breaker_key(e), open_duration_hours=_breaker_hours(e))
        return {"outcome": "failure", "run_id": run_id, "failure_reason": str(e)}

    duration_ms = int((time.monotonic() - started) * 1000)
    outcome = out.get("outcome", "success")
    db.complete_run(
        run_id,
        outcome=outcome,
        csv_path=out.get("csv_path"),
        rows_ingested=out.get("rows_ingested"),
        winning_strategy_id=out.get("winning_strategy_id"),
        duration_ms=duration_ms,
        llm_fallback_invoked=bool(out.get("llm_fallback_invoked")),
        session_refreshed=bool(out.get("session_refreshed")),
        failure_reason=out.get("failure_reason"),
    )
    if outcome == "success":
        db.breaker_reset("auth")
        db.breaker_reset("download")
    return {"outcome": outcome, "run_id": run_id, **out}


def _breaker_key(e: Exception) -> str:
    msg = str(e).lower()
    if "auth" in msg or "login" in msg or "2fa" in msg or "session" in msg:
        return "auth"
    return "download"


def _breaker_hours(e: Exception) -> int:
    return 24 if _breaker_key(e) == "auth" else 2


# --- Real runner wiring (used in production, stubbed in unit tests) -----------

def default_runner(*, cfg: config_mod.AutopullConfig,
                   db: StateDB, run_id: int) -> dict:
    """Actual run: Playwright + locator + validate + ingest + notify."""
    from playwright.sync_api import sync_playwright
    from tools.autopull import (
        session_manager as sm,
        locator_engine as le,
        csv_validator as cv,
        gmail_2fa_fetcher as g2fa,
        llm_adapter as lla,
    )
    le.seed_builtin_strategies(db)

    staging = cfg.data_root / "autopull" / "staging"
    quarantine = cfg.data_root / "autopull" / "quarantine"
    sharks_dir = cfg.data_root / "sharks"
    staging.mkdir(parents=True, exist_ok=True)
    quarantine.mkdir(parents=True, exist_ok=True)
    sharks_dir.mkdir(parents=True, exist_ok=True)

    gmail_client = g2fa.build_client(
        client_id=cfg.gmail_client_id,
        client_secret=cfg.gmail_client_secret,
        refresh_token=cfg.gmail_refresh_token,
    )
    gmail_fetcher = lambda: g2fa.fetch_latest_code(gmail_client)
    auth_file = cfg.data_root / "autopull" / "gc_session.json"

    import os
    session = sm.SessionManager(
        auth_file=auth_file,
        email=os.getenv("GC_EMAIL", ""),
        password=os.getenv("GC_PASSWORD", ""),
        gmail_fetcher=gmail_fetcher,
    )

    llm = None
    if cfg.llm_adapt_enabled and cfg.anthropic_api_key:
        llm = lla.build_default_adapter(
            api_key=cfg.anthropic_api_key, model=cfg.llm_model
        )
    engine = le.LocatorEngine(
        db=db, llm_adapter=llm, llm_enabled=cfg.llm_adapt_enabled,
    )

    with sync_playwright() as pw:
        page, refreshed = session.new_logged_in_page(pw, headless=True)
        stats_url = (f"https://web.gc.com/teams/{cfg.gc_team_id}/"
                     f"{cfg.gc_season_slug}/stats")
        page.goto(stats_url, wait_until="networkidle", timeout=60_000)
        result = engine.find_and_download(page, out_dir=staging)

    if result.downloaded_path is None:
        return {
            "outcome": "failure",
            "failure_reason": "No strategy located the CSV export button",
            "llm_fallback_invoked": result.llm_used,
            "session_refreshed": refreshed,
        }

    latest_cols, _ = db.last_two_schemas()
    val = cv.validate(result.downloaded_path, known_columns=latest_cols)
    if not val.accepted:
        cv.quarantine(result.downloaded_path, val, quarantine_root=quarantine)
        return {
            "outcome": "quarantined", "failure_reason": val.reason,
            "llm_fallback_invoked": result.llm_used,
            "session_refreshed": refreshed,
            "drift_severity": val.drift_severity,
        }

    db.record_schema(val.columns, val.row_count)

    final = sharks_dir / f"season_stats_{datetime.now(ET).strftime('%Y%m%d')}.csv"
    result.downloaded_path.replace(final)

    # Kick the existing ingest
    import subprocess
    rc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "gc_csv_ingest.py"),
         str(final)],
        timeout=180,
    ).returncode
    if rc != 0:
        return {
            "outcome": "failure",
            "failure_reason": f"gc_csv_ingest.py exited {rc}",
            "csv_path": str(final),
            "llm_fallback_invoked": result.llm_used,
            "session_refreshed": refreshed,
            "drift_severity": val.drift_severity,
        }

    return {
        "outcome": "success",
        "csv_path": str(final),
        "rows_ingested": val.row_count,
        "winning_strategy_id": result.winning_strategy_id,
        "llm_fallback_invoked": result.llm_used,
        "session_refreshed": refreshed,
        "drift_severity": val.drift_severity,
    }


def _build_notifier(cfg: config_mod.AutopullConfig):
    """Wire real Gmail send + HTTP webhook + push webhook into the notifier."""
    import os
    import requests
    from tools.autopull import gmail_2fa_fetcher as g2fa
    from tools.autopull import notifier as nt

    gmail_client = None
    if cfg.gmail_client_id and cfg.gmail_refresh_token:
        gmail_client = g2fa.build_client(
            client_id=cfg.gmail_client_id,
            client_secret=cfg.gmail_client_secret,
            refresh_token=cfg.gmail_refresh_token,
        )

    class _GmailSender:
        def send(self, *, to: str, subject: str, body: str) -> None:
            if gmail_client is None:
                log.info("Gmail not configured, skipping email")
                return
            g2fa.send_email(gmail_client, sender=cfg.gmail_notify_from,
                            to=to, subject=subject, body=body)

    class _N8nPoster:
        def post(self, url: str, payload: dict) -> None:
            requests.post(url, json=payload, timeout=15).raise_for_status()

    class _WebhookPusher:
        def __init__(self, url: str):
            self._url = url
        def notify(self, message: str) -> None:
            if not self._url:
                return
            requests.post(self._url, json={"message": message}, timeout=10)

    push_url = os.getenv("PUSH_WEBHOOK_URL", "")
    return nt.Notifier(
        gmail_sender=_GmailSender(),
        n8n_poster=_N8nPoster(),
        pusher=_WebhookPusher(push_url),
        status_webhook_url=cfg.n8n_status_webhook,
        notify_to_email=cfg.gmail_notify_to,
    )


def _summary_from_result(result: dict, trigger: str):
    from tools.autopull.notifier import RunSummary
    return RunSummary(
        run_id=result.get("run_id", -1),
        trigger=trigger,
        outcome=result.get("outcome", "failure"),
        failure_reason=result.get("failure_reason"),
        csv_path=result.get("csv_path"),
        rows_ingested=result.get("rows_ingested"),
        duration_ms=result.get("duration_ms"),
        drift_severity=result.get("drift_severity", "none"),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dugout GC CSV autopull")
    ap.add_argument("--trigger", choices=["cron", "postgame", "manual"],
                    default="manual")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config_mod.load(require_gmail=True)
    result = run_once(cfg=cfg, trigger=args.trigger, runner=default_runner)

    # Skipped runs are silent — nothing to fan out.
    if result.get("outcome") != "skipped":
        try:
            notifier = _build_notifier(cfg)
            notifier.emit(_summary_from_result(result, args.trigger))
        except Exception as e:
            log.exception("notifier wiring failed: %s", e)

    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("outcome") in ("success", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
