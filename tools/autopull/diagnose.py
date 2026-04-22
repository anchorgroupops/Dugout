"""Diagnose the autopull setup end-to-end without pulling a CSV.

Checks, in order:
  1. teams.yaml parses and has at least one active team
  2. .env has the expected autopull keys present (values not printed)
  3. Python deps importable (google-api-python-client, anthropic, playwright, yaml)
  4. Playwright Chromium binary installed
  5. systemd timer units present and active
  6. State DB reachable; migrations complete
  7. GC credentials (email/password) present in env

Exit 0 if everything passes, 1 otherwise. Secrets are never printed.

Usage:
    /tmp/dugout-venv/bin/python -m tools.autopull.diagnose
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from pathlib import Path

OK = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
WARN = "\033[33m!\033[0m"


def _check(label: str, ok: bool, detail: str = "") -> bool:
    mark = OK if ok else FAIL
    line = f"  {mark} {label}"
    if detail:
        line += f"  — {detail}"
    print(line)
    return ok


def _warn(label: str, detail: str = "") -> None:
    print(f"  {WARN} {label}  — {detail}")


def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip("'").strip('"')
        if k and k not in os.environ:
            os.environ[k] = v


def main() -> int:
    _load_env()
    all_ok = True

    print("\n[1] Team registry")
    try:
        from tools import team_registry
        teams = team_registry.load()
        active = [t for t in teams if t.active]
        all_ok &= _check(f"teams.yaml parses ({len(teams)} teams, {len(active)} active)", True)
        for t in active:
            print(f"       - {t.name} ({t.data_slug}, season={t.season_slug})")
    except Exception as e:
        all_ok &= _check("teams.yaml parses", False, str(e))

    print("\n[2] Environment variables")
    required = {
        "GC_EMAIL": "GC login",
        "GC_PASSWORD": "GC password",
        "GMAIL_USERNAME": "Gmail account for 2FA reading + notification send",
        "GMAIL_APP_PASSWORD": "Generated at myaccount.google.com/apppasswords",
    }
    optional = {
        "ANTHROPIC_API_KEY": "Only needed if GC_AUTOPULL_LLM_ADAPT=true",
        "N8N_AUTOPULL_STATUS_WEBHOOK": "Optional; n8n fan-out",
        "PUSH_WEBHOOK_URL": "Optional; push notifications",
    }
    for k, purpose in required.items():
        all_ok &= _check(f"{k} set ({purpose})", bool(os.getenv(k)))
    for k, purpose in optional.items():
        if os.getenv(k):
            _check(f"{k} set", True, purpose)
        else:
            _warn(f"{k} not set", purpose)

    flags = {
        "GC_AUTOPULL_ENABLED": os.getenv("GC_AUTOPULL_ENABLED", "false"),
        "GC_AUTOPULL_POSTGAME_ENABLED": os.getenv("GC_AUTOPULL_POSTGAME_ENABLED", "false"),
        "GC_AUTOPULL_LLM_ADAPT": os.getenv("GC_AUTOPULL_LLM_ADAPT", "false"),
    }
    for k, v in flags.items():
        print(f"       {k}={v}")

    print("\n[3] Python dependencies")
    for mod in ("yaml", "playwright", "anthropic",
                "googleapiclient", "google_auth_oauthlib"):
        try:
            __import__(mod)
            all_ok &= _check(f"import {mod}", True)
        except ImportError as e:
            all_ok &= _check(f"import {mod}", False, str(e))

    print("\n[4] Playwright Chromium")
    chromium_cache = Path.home() / ".cache" / "ms-playwright"
    has_chromium = chromium_cache.exists() and any(
        p.name.startswith(("chromium", "chrome")) for p in chromium_cache.iterdir()
    )
    all_ok &= _check(f"Chromium in {chromium_cache}", has_chromium,
                     "Run: /tmp/dugout-venv/bin/playwright install chromium" if not has_chromium else "")

    print("\n[5] systemd timers")
    for unit in ("gc-autopull.timer", "gc-autopull-weekly.timer"):
        rc = subprocess.run(
            ["systemctl", "is-active", unit], capture_output=True, text=True,
        )
        all_ok &= _check(f"{unit} active", rc.stdout.strip() == "active",
                         rc.stdout.strip() or rc.stderr.strip())

    print("\n[6] State DB")
    try:
        from tools.autopull import config as config_mod
        from tools.autopull.state import StateDB
        cfg = config_mod.load()
        db_path = cfg.data_root / "autopull" / "autopull_state.db"
        db = StateDB(db_path)
        db.init_schema()
        tables = set(db.list_tables())
        expected = {"runs", "strategies", "circuit_breaker", "schema_profile"}
        all_ok &= _check(f"State DB at {db_path}", expected <= tables,
                         f"missing tables: {expected - tables}" if not (expected <= tables) else "")
        runs = db.recent_runs(limit=3)
        if runs:
            print(f"       {len(runs)} recent runs on file:")
            for r in runs:
                print(f"         - #{r.id} {r.team_id} {r.outcome} ({r.trigger})")
        else:
            print(f"       no runs yet")
    except Exception as e:
        all_ok &= _check("State DB", False, str(e))

    print("\n[7] Dry-run CLI")
    cli_path = Path(__file__).parent / "cli.py"
    try:
        rc = subprocess.run(
            [sys.executable, "-m", "tools.autopull.cli", "--trigger=manual"],
            capture_output=True, text=True, timeout=20,
            cwd=Path(__file__).resolve().parents[2],
        )
        all_ok &= _check(f"CLI runs (exit {rc.returncode})", rc.returncode == 0)
        if rc.stdout:
            print(f"       output: {rc.stdout.strip()[:200]}")
    except Exception as e:
        all_ok &= _check("CLI dry-run", False, str(e))

    print()
    print("=" * 60)
    if all_ok:
        print(f"{OK} All checks passed. Flip GC_AUTOPULL_ENABLED=true when ready.")
    else:
        print(f"{FAIL} Some checks failed. Review above.")
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
