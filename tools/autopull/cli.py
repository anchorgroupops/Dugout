"""Autopull CLI — the single entry point called by cron and sync_daemon.

Phase 1 multi-team: `run_once` loops over all `active` teams from the
registry (config/teams.yaml by default). Each team has its own
idempotency check, its own staging/quarantine/data dirs, and its own
notification. The browser + session are shared across the sweep to
amortize login + 2FA cost.
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
             runner: Callable[..., dict],
             teams_path: Path | None = None) -> dict:
    """Orchestrate one autopull sweep over all active teams.

    Returns a dict with an aggregate `outcome` plus `per_team` details:
      - 'skipped' — global short-circuit before any team runs
      - 'failure' (with no per_team) — bad teams.yaml
      - 'all_success' — every eligible team succeeded
      - 'all_skipped' — every team was skipped (idempotency or breaker)
      - 'partial' — mixed success/failure across teams
      - 'failure' — every eligible team failed
    """
    db_path = cfg.data_root / "autopull" / "autopull_state.db"
    db = StateDB(db_path)
    db.init_schema()

    if not cfg.enabled:
        return {"outcome": "skipped", "reason": "disabled"}
    if trigger == "postgame" and not cfg.postgame_enabled:
        return {"outcome": "skipped", "reason": "postgame disabled"}

    # Load active teams from the registry.
    from tools import team_registry
    try:
        teams = team_registry.load_active(teams_path)
    except team_registry.RegistryError as e:
        return {"outcome": "failure", "failure_reason": f"bad teams.yaml: {e}"}
    if not teams:
        return {"outcome": "skipped", "reason": "no active teams"}

    # Global auth breaker — one login serves all teams.
    if db.breaker_open("auth"):
        return {"outcome": "skipped", "reason": "auth breaker open"}

    per_team: dict[str, dict] = {}
    for team in teams:
        per_team[team.data_slug] = _run_team(
            cfg=cfg, db=db, trigger=trigger, runner=runner, team=team,
        )

    outcomes = [v["outcome"] for v in per_team.values()]
    if all(o == "skipped" for o in outcomes):
        agg = "all_skipped"
    elif all(o == "success" for o in outcomes):
        agg = "all_success"
    elif any(o == "success" for o in outcomes):
        agg = "partial"
    else:
        agg = "failure"
    return {"outcome": agg, "per_team": per_team}


def _run_team(*, cfg, db, trigger, runner, team) -> dict:
    """Drive one team through start_run → runner → complete_run."""
    recent = db.last_successful_run_within(
        minutes=cfg.idempotency_window_min, team_id=team.data_slug,
    )
    if recent is not None:
        return {"outcome": "skipped",
                "reason": f"recent success within {cfg.idempotency_window_min}m "
                          f"(run #{recent.id})"}

    run_id = db.start_run(trigger=trigger, team_id=team.data_slug)
    started = time.monotonic()
    try:
        out = runner(cfg=cfg, db=db, run_id=run_id, team=team)
    except Exception as e:
        log.exception("runner raised for team %s", team.data_slug)
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
        db.breaker_reset(f"download:{team.data_slug}")
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
                   db: StateDB, run_id: int, team) -> dict:
    """Actual run for one team: Playwright + locator + validate + ingest."""
    from playwright.sync_api import sync_playwright
    from tools.autopull import (
        session_manager as sm,
        locator_engine as le,
        csv_validator as cv,
        gmail_2fa_fetcher as g2fa,
        llm_adapter as lla,
    )
    le.seed_builtin_strategies(db)

    staging = cfg.data_root / "autopull" / "staging" / team.data_slug
    quarantine = cfg.data_root / "autopull" / "quarantine" / team.data_slug
    team_dir = cfg.data_root / team.data_slug
    staging.mkdir(parents=True, exist_ok=True)
    quarantine.mkdir(parents=True, exist_ok=True)
    team_dir.mkdir(parents=True, exist_ok=True)

    gmail_client = g2fa.build_client(
        username=cfg.gmail_username,
        app_password=cfg.gmail_app_password,
    )
    gmail_fetcher = lambda min_uid=0: g2fa.fetch_latest_code(
        gmail_client, min_uid=min_uid,
    )
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
            api_key=cfg.anthropic_api_key, model=cfg.llm_model,
        )
    engine = le.LocatorEngine(
        db=db, llm_adapter=llm, llm_enabled=cfg.llm_adapt_enabled,
    )

    with sync_playwright() as pw:
        page, refreshed = session.new_logged_in_page(pw, headless=True)
        page.goto(team.stats_url, wait_until="networkidle", timeout=60_000)
        result = engine.find_and_download(page, out_dir=staging)

    if result.downloaded_path is None:
        return {
            "outcome": "failure",
            "failure_reason": "No strategy located the CSV export button",
            "llm_fallback_invoked": result.llm_used,
            "session_refreshed": refreshed,
        }

    latest_cols, _ = db.last_two_schemas(team_id=team.data_slug)
    val = cv.validate(result.downloaded_path, known_columns=latest_cols)
    if not val.accepted:
        cv.quarantine(result.downloaded_path, val, quarantine_root=quarantine)
        return {
            "outcome": "quarantined", "failure_reason": val.reason,
            "llm_fallback_invoked": result.llm_used,
            "session_refreshed": refreshed,
            "drift_severity": val.drift_severity,
        }

    db.record_schema(val.columns, val.row_count, team_id=team.data_slug)

    final = team_dir / f"season_stats_{datetime.now(ET).strftime('%Y%m%d')}.csv"
    result.downloaded_path.replace(final)

    # Ingest: pass the team slug so gc_csv_ingest writes into data/<slug>/.
    import subprocess
    rc = subprocess.run(
        [sys.executable,
         str(Path(__file__).resolve().parents[1] / "gc_csv_ingest.py"),
         "--team", team.data_slug, str(final)],
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

    class _GmailSender:
        def send(self, *, to: str, subject: str, body: str) -> None:
            if not (cfg.gmail_username and cfg.gmail_app_password):
                log.info("Gmail not configured, skipping email")
                return
            g2fa.send_email(
                username=cfg.gmail_username,
                app_password=cfg.gmail_app_password,
                sender=cfg.gmail_notify_from or cfg.gmail_username,
                to=to, subject=subject, body=body,
            )

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


def _summaries_from_result(result: dict, trigger: str) -> list:
    """Flatten a multi-team run_once result into per-team RunSummary objects."""
    from tools.autopull.notifier import RunSummary
    from tools import team_registry

    per_team = result.get("per_team") or {}
    if not per_team:
        # Global short-circuit (disabled, skipped, bad config). One empty summary.
        return [RunSummary(
            run_id=-1, trigger=trigger,
            team_slug="*", team_name="(all teams)",
            outcome=result.get("outcome", "skipped"),
            failure_reason=result.get("reason") or result.get("failure_reason"),
            csv_path=None, rows_ingested=None, duration_ms=None,
            drift_severity="none",
        )]

    summaries = []
    for slug, out in per_team.items():
        try:
            team_name = team_registry.require_by_slug(slug).name
        except Exception:
            team_name = slug
        summaries.append(RunSummary(
            run_id=out.get("run_id", -1),
            trigger=trigger,
            team_slug=slug,
            team_name=team_name,
            outcome=out.get("outcome", "failure"),
            failure_reason=out.get("failure_reason"),
            csv_path=out.get("csv_path"),
            rows_ingested=out.get("rows_ingested"),
            duration_ms=out.get("duration_ms"),
            drift_severity=out.get("drift_severity", "none"),
        ))
    return summaries


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dugout GC CSV autopull")
    ap.add_argument("--trigger", choices=["cron", "postgame", "manual"],
                    default="manual")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config_mod.load(require_gmail=True)
    result = run_once(cfg=cfg, trigger=args.trigger, runner=default_runner)

    # Fan out per-team notifications (skipped runs stay silent overall).
    if result.get("outcome") not in ("skipped",):
        try:
            notifier = _build_notifier(cfg)
            for summary in _summaries_from_result(result, args.trigger):
                notifier.emit(summary)
        except Exception as e:
            log.exception("notifier wiring failed: %s", e)

    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("outcome") in ("all_success", "all_skipped", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
