"""
Runtime operator utilities:
  - bootstrap-secrets: load session env values from H:\\APIs.csv safely
  - smoke-all: run end-to-end runtime smoke sequence with gated checks
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_APIS_CSV = Path(r"H:\APIs.csv")
LOCAL_BASE = "http://127.0.0.1:5001"
PROD_BASE = "https://dugout.joelycannoli.com"
DEFAULT_FALLBACK_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
ENV_KEYS = (
    "PINECONE_API_KEY",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID",
    "GC_EMAIL",
    "GC_PASSWORD",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
)


def _mask(secret: str) -> str:
    if not secret:
        return "<missing>"
    if len(secret) <= 8:
        return f"{secret[:1]}***{secret[-1:]}"
    return f"{secret[:4]}...{secret[-4:]} (len={len(secret)})"


def _norm_token(token: str) -> str:
    return (token or "").strip().strip('"').strip("'")


def _section_windows(rows: list[list[str]], section_name: str) -> list[list[str]]:
    out: list[list[str]] = []
    low_name = section_name.lower()
    for i, row in enumerate(rows):
        cells = [_norm_token(c) for c in row]
        if not any(c.lower() == low_name for c in cells if c):
            continue

        window: list[str] = []
        for j in range(i + 1, len(rows)):
            r = [_norm_token(c) for c in rows[j]]
            # section ends on full blank row
            if not any(r):
                break
            for c in r:
                if c:
                    window.append(c)
        out.append(window)
    return out


def _collect_key_values(rows: list[list[str]]) -> dict[str, str]:
    kv: dict[str, str] = {}
    for row in rows:
        cells = [_norm_token(c) for c in row if _norm_token(c)]
        if not cells:
            continue

        # Forms:
        # - KEY=VALUE
        # - KEY: VALUE
        # - KEY,VALUE
        for cell in cells:
            m = re.match(r"^([A-Z0-9_]+)\s*[:=]\s*(.+)$", cell, flags=re.IGNORECASE)
            if m:
                key = m.group(1).upper()
                val = m.group(2).strip()
                if key:
                    kv[key] = val
        if len(cells) >= 2:
            key = cells[0].strip().upper()
            if re.fullmatch(r"[A-Z0-9_]{3,}", key):
                kv[key] = cells[1].strip()
    return kv


def _choose_pinecone_key(candidates: list[str]) -> str:
    scored: list[tuple[int, str]] = []
    for token in candidates:
        t = token.strip()
        if not t or "http://" in t or "https://" in t:
            continue
        if "=" in t and ("POSTGRES_" in t or "PASSWORD" in t.upper()):
            continue
        score = 0
        if t.lower().startswith("pcsk_"):
            score += 10
        if len(t) >= 30:
            score += 4
        if re.fullmatch(r"[A-Za-z0-9_\-]+", t):
            score += 2
        if "pinecone" in t.lower():
            score -= 2
        scored.append((score, t))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored and scored[0][0] >= 4 else ""


def _choose_elevenlabs_key(candidates: list[str]) -> str:
    scored: list[tuple[int, str]] = []
    for token in candidates:
        t = token.strip()
        if not t:
            continue
        score = 0
        if t.startswith("sk_"):
            score += 10
        if len(t) >= 30:
            score += 4
        if re.fullmatch(r"[A-Za-z0-9_\-]+", t):
            score += 2
        scored.append((score, t))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored and scored[0][0] >= 8 else ""


def _choose_elevenlabs_voice_id(candidates: list[str]) -> str:
    for token in candidates:
        t = token.strip()
        if t.startswith("sk_"):
            continue
        if re.fullmatch(r"[A-Za-z0-9]{20}", t):
            return t
    return ""


def _choose_gc_email(candidates: list[str]) -> str:
    for token in candidates:
        t = token.strip()
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", t):
            return t
    return ""


def _choose_gc_password(candidates: list[str]) -> str:
    for token in candidates:
        t = token.strip()
        if not t:
            continue
        if "@" in t and "." in t:
            continue
        if len(t) >= 8:
            return t
    return ""


def _is_google_api_key(value: str) -> bool:
    t = (value or "").strip()
    return bool(re.fullmatch(r"AIza[0-9A-Za-z_\-]{20,}", t))


def _is_oauth_client_secret(value: str) -> bool:
    return (value or "").strip().startswith("GOCSPX-")


def extract_secrets_from_csv(csv_path: Path) -> dict[str, str]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Secrets CSV not found: {csv_path}")

    with open(csv_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        rows = list(csv.reader(f))

    kv = _collect_key_values(rows)

    pinecone_tokens = [t for w in _section_windows(rows, "Pinecone") for t in w]
    eleven_tokens = [t for w in _section_windows(rows, "Elevenlabs") for t in w]
    gc_tokens = [t for w in (_section_windows(rows, "GameChanger") + _section_windows(rows, "GC")) for t in w]
    gemini_tokens = [t for w in _section_windows(rows, "Gemini") for t in w]

    pinecone_key = (kv.get("PINECONE_API_KEY", "") or _choose_pinecone_key(pinecone_tokens)).strip()
    eleven_key = (kv.get("ELEVENLABS_API_KEY", "") or _choose_elevenlabs_key(eleven_tokens)).strip()
    eleven_voice = (kv.get("ELEVENLABS_VOICE_ID", "") or _choose_elevenlabs_voice_id(eleven_tokens)).strip()

    gc_email = (kv.get("GC_EMAIL", "") or _choose_gc_email(gc_tokens)).strip()
    gc_password = (kv.get("GC_PASSWORD", "") or _choose_gc_password(gc_tokens)).strip()

    gemini_api_key = kv.get("GEMINI_API_KEY", "").strip()
    google_api_key = kv.get("GOOGLE_API_KEY", "").strip()
    google_client_id = kv.get("GOOGLE_CLIENT_ID", "").strip()
    google_client_secret = kv.get("GOOGLE_CLIENT_SECRET", "").strip()

    # Accept API keys only in the GEMINI/GOOGLE_API_KEY slots; preserve OAuth creds separately.
    if gemini_api_key and not _is_google_api_key(gemini_api_key):
        google_client_secret = google_client_secret or gemini_api_key
        gemini_api_key = ""
    if google_api_key and not _is_google_api_key(google_api_key):
        google_client_secret = google_client_secret or google_api_key
        google_api_key = ""

    # Fall back from GEMINI section text when explicit env keys are not present.
    if not google_client_id:
        for token in gemini_tokens:
            m = re.match(r"^(?:ID|CLIENT[_ ]?ID)\s*[:=]\s*(.+)$", token, flags=re.IGNORECASE)
            if m:
                google_client_id = m.group(1).strip()
                break
    if not google_client_secret:
        for token in gemini_tokens:
            m = re.match(r"^(?:SECRET|CLIENT[_ ]?SECRET)\s*[:=]\s*(.+)$", token, flags=re.IGNORECASE)
            if m:
                google_client_secret = m.group(1).strip()
                break
    if not gemini_api_key and not google_api_key:
        for token in gemini_tokens:
            m = re.match(r"^(?:API[_ ]?KEY|GEMINI_API_KEY|GOOGLE_API_KEY)\s*[:=]\s*(.+)$", token, flags=re.IGNORECASE)
            if not m:
                continue
            candidate = m.group(1).strip()
            if _is_google_api_key(candidate):
                google_api_key = candidate
            else:
                google_client_secret = google_client_secret or candidate

    return {
        "PINECONE_API_KEY": pinecone_key,
        "ELEVENLABS_API_KEY": eleven_key,
        "ELEVENLABS_VOICE_ID": eleven_voice,
        "GC_EMAIL": gc_email,
        "GC_PASSWORD": gc_password,
        "GEMINI_API_KEY": gemini_api_key,
        "GOOGLE_API_KEY": google_api_key,
        "GOOGLE_CLIENT_ID": google_client_id,
        "GOOGLE_CLIENT_SECRET": google_client_secret,
    }


def bootstrap_secrets(csv_path: Path, apply: bool = True) -> dict[str, str]:
    found = extract_secrets_from_csv(csv_path)

    # Fill voice with known safe default only when ElevenLabs key exists and no id found.
    if found.get("ELEVENLABS_API_KEY") and not found.get("ELEVENLABS_VOICE_ID"):
        found["ELEVENLABS_VOICE_ID"] = os.getenv("ELEVENLABS_VOICE_ID", "").strip() or DEFAULT_FALLBACK_VOICE_ID

    if apply:
        for key, value in found.items():
            if value:
                os.environ[key] = value

    print(f"[SECRETS] Source: {csv_path}")
    for key in ENV_KEYS:
        present = bool(found.get(key))
        masked = _mask(found.get(key, "")) if present else "<missing>"
        print(f"[SECRETS] {key}: {'present' if present else 'missing'} {masked if present else ''}".rstrip())

    return found


def _run_cmd(args: list[str], env: dict[str, str], timeout: int = 180) -> tuple[int, str, str]:
    proc = subprocess.run(
        args,
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _start_local_api(env: dict[str, str]) -> tuple[subprocess.Popen[str] | None, bool]:
    if _port_open("127.0.0.1", 5001):
        return None, True

    code = (
        "import os,sys; "
        f"sys.path.insert(0, r'{(REPO_ROOT / 'tools').as_posix()}'); "
        "import sync_daemon as s; "
        "s.app.run(host='127.0.0.1', port=5001, debug=False, use_reloader=False)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    deadline = time.time() + 25
    while time.time() < deadline:
        if _port_open("127.0.0.1", 5001):
            return proc, True
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    return proc, False


def _check_http(url: str, timeout: int = 30) -> tuple[bool, str]:
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code == 200, f"status={r.status_code}"
    except Exception as e:
        return False, str(e)


@dataclass
class StepResult:
    name: str
    status: str
    detail: str


def smoke_all(csv_path: Path) -> int:
    env = os.environ.copy()
    secrets = bootstrap_secrets(csv_path, apply=True)
    env.update({k: v for k, v in secrets.items() if v})
    env.setdefault("PYTHONIOENCODING", "utf-8")

    results: list[StepResult] = []

    # 1. local API start
    proc, up = _start_local_api(env)
    results.append(StepResult("local_api_start", "pass" if up else "fail", "port=5001" if up else "failed to bind port 5001"))

    # 2. local endpoint checks
    ok_team, detail_team = _check_http(f"{LOCAL_BASE}/api/team")
    results.append(StepResult("local_api_team", "pass" if ok_team else "fail", detail_team))

    try:
        r = requests.get(f"{LOCAL_BASE}/api/voice-update", timeout=90)
        if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("audio/mpeg"):
            results.append(StepResult("local_voice_update", "pass", f"status=200 bytes={len(r.content)}"))
        else:
            results.append(StepResult("local_voice_update", "fail", f"status={r.status_code} type={r.headers.get('Content-Type', '')}"))
    except Exception as e:
        results.append(StepResult("local_voice_update", "fail", str(e)))

    # 3. opcheck local
    rc, out, err = _run_cmd([sys.executable, "tools/opcheck.py", "--base-url", LOCAL_BASE, "--no-burst"], env=env, timeout=180)
    if rc == 0:
        summary = "ok"
        try:
            rep = json.loads(out)
            failed = int(((rep.get("summary") or {}).get("failed")) or 0)
            total = int(((rep.get("summary") or {}).get("total")) or 0)
            summary = f"failed={failed}/{total}"
        except Exception:
            pass
        results.append(StepResult("opcheck_local", "pass", summary))
    else:
        results.append(StepResult("opcheck_local", "fail", (err or out)[-500:]))

    # 4. opcheck production
    rc, out, err = _run_cmd([sys.executable, "tools/opcheck.py", "--base-url", PROD_BASE], env=env, timeout=180)
    if rc == 0:
        status = "pass"
        detail = "ok"
        try:
            rep = json.loads(out)
            failed = int(((rep.get("summary") or {}).get("failed")) or 0)
            total = int(((rep.get("summary") or {}).get("total")) or 0)
            detail = f"failed={failed}/{total}"
            # Keep this non-blocking unless it regresses heavily.
            if failed > 1:
                status = "warn"
        except Exception:
            pass
        results.append(StepResult("opcheck_prod", status, detail))
    else:
        results.append(StepResult("opcheck_prod", "fail", (err or out)[-500:]))

    # 5. RAG indexing dry run
    rc, out, err = _run_cmd([sys.executable, "tools/index_historical_data.py", "--dry-run"], env=env, timeout=120)
    results.append(StepResult("index_dry_run", "pass" if rc == 0 else "fail", (out or err).strip()[-300:]))

    # 6. RAG live run (gated by Gemini API key, not OAuth client secret)
    runtime_gemini_key = (env.get("GEMINI_API_KEY", "").strip() or env.get("GOOGLE_API_KEY", "").strip())
    runtime_client_secret = env.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not runtime_gemini_key:
        msg = "missing GEMINI_API_KEY/GOOGLE_API_KEY"
        if runtime_client_secret and _is_oauth_client_secret(runtime_client_secret):
            msg = "Gemini OAuth client secret present, but missing Gemini API key (AIza...)"
        results.append(StepResult("index_live_run", "blocked", msg))
    else:
        rc, out, err = _run_cmd([sys.executable, "tools/index_historical_data.py"], env=env, timeout=180)
        text = (out + "\n" + err).strip()
        if rc == 0:
            results.append(StepResult("index_live_run", "pass", text[-300:]))
        elif "Missing GEMINI_API_KEY" in text or "Missing GOOGLE_API_KEY" in text:
            results.append(StepResult("index_live_run", "blocked", "missing GEMINI_API_KEY/GOOGLE_API_KEY"))
        else:
            results.append(StepResult("index_live_run", "fail", text[-500:]))

    # 7. Modal daily scout run (gated by GC creds)
    if not env.get("GC_EMAIL", "").strip() or not env.get("GC_PASSWORD", "").strip():
        results.append(StepResult("modal_daily_scout_job", "blocked", "missing GC_EMAIL/GC_PASSWORD"))
    else:
        rc, out, err = _run_cmd(
            [sys.executable, "-m", "modal", "run", "tools/modal_app.py::daily_scout_job"],
            env=env,
            timeout=300,
        )
        text = (out + "\n" + err).strip()
        if rc == 0:
            results.append(StepResult("modal_daily_scout_job", "pass", "completed"))
        elif "Missing credentials. Set GC_EMAIL and GC_PASSWORD" in text:
            results.append(StepResult("modal_daily_scout_job", "blocked", "missing GC_EMAIL/GC_PASSWORD"))
        else:
            results.append(StepResult("modal_daily_scout_job", "fail", text[-600:]))

    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()

    status_counts: dict[str, int] = {"pass": 0, "warn": 0, "blocked": 0, "fail": 0}
    for r in results:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1

    print("\n=== SMOKE MATRIX ===")
    for r in results:
        print(f"{r.status.upper():8} | {r.name:24} | {r.detail}")
    print(
        "\n=== SUMMARY ===\n"
        f"pass={status_counts['pass']} warn={status_counts['warn']} blocked={status_counts['blocked']} fail={status_counts['fail']}"
    )

    return 0 if status_counts["fail"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Runtime operator utilities.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_boot = sub.add_parser("bootstrap-secrets", help="Load session secrets from H:\\APIs.csv.")
    p_boot.add_argument("--csv", default=str(DEFAULT_APIS_CSV), help="Path to APIs CSV file.")
    p_boot.add_argument("--no-apply", action="store_true", help="Do not set process environment variables.")
    p_boot.add_argument("--emit-json", action="store_true", help="Emit raw JSON payload for wrapper scripts.")

    p_smoke = sub.add_parser("smoke-all", help="Run full runtime smoke sequence.")
    p_smoke.add_argument("--csv", default=str(DEFAULT_APIS_CSV), help="Path to APIs CSV file.")

    args = parser.parse_args()

    if args.cmd == "bootstrap-secrets":
        found = extract_secrets_from_csv(Path(args.csv))
        if found.get("ELEVENLABS_API_KEY") and not found.get("ELEVENLABS_VOICE_ID"):
            found["ELEVENLABS_VOICE_ID"] = os.getenv("ELEVENLABS_VOICE_ID", "").strip() or DEFAULT_FALLBACK_VOICE_ID
        if args.emit_json:
            print(json.dumps(found))
            return 0
        bootstrap_secrets(Path(args.csv), apply=not args.no_apply)
        return 0

    if args.cmd == "smoke-all":
        return smoke_all(Path(args.csv))

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
