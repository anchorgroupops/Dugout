import os
import subprocess
from pathlib import Path

import modal
from dotenv import load_dotenv

# Load .env so _runtime_secret() has credentials at deploy time
load_dotenv(Path(__file__).parent.parent / ".env")

app = modal.App("softball-strategy-sharks")

SESSION_VOLUME = modal.Volume.from_name("softball-gc-session", create_if_missing=True)
VOLUME_MOUNT = "/vol/softball-gc"

sharks_image = (
    modal.Image.debian_slim()
    .pip_install(
        "playwright==1.42.0",  # keep in sync with requirements.txt
        "python-dotenv",
        "requests",
        "pinecone>=5.0,<6",
        "google-generativeai>=0.8,<1",
        "fastapi[standard]",
    )
    .run_commands("playwright install --with-deps chromium")
    .add_local_dir(".", remote_path="/app", ignore=["node_modules", "data", "client/node_modules", "client/dist", ".git"])
)


def _runtime_secret() -> modal.Secret:
    payload = {}
    for key in (
        "GC_EMAIL",
        "GC_PASSWORD",
        "GC_TEAM_ID",
        "GC_SEASON_SLUG",
        "GC_ORG_IDS",
        "PINECONE_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID",
    ):
        val = os.getenv(key, "").strip()
        if val:
            payload[key] = val
    if not payload:
        payload["SOFTBALL_RUNTIME"] = "1"
    return modal.Secret.from_dict(payload)


def _run_step(label: str, args: list[str], env: dict[str, str], optional: bool = False) -> bool:
    """Run a subprocess step. Returns True on success, False on failure if optional=True.
    Raises RuntimeError on failure if optional=False."""
    print(f"[Modal] Starting step: {label}")
    proc = subprocess.run(
        args,
        cwd="/app",
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.stdout:
        print(proc.stdout[-8000:] if len(proc.stdout) > 8000 else proc.stdout)
    if proc.stderr:
        print(proc.stderr[-4000:] if len(proc.stderr) > 4000 else proc.stderr)
    if proc.returncode != 0:
        msg = f"{label} failed with exit code {proc.returncode}"
        if optional:
            print(f"[Modal] WARNING: {msg} (continuing)")
            return False
        raise RuntimeError(msg)
    print(f"[Modal] Completed step: {label}")
    return True


@app.function(
    image=sharks_image,
    schedule=modal.Cron("0 6 * * *"),
    volumes={VOLUME_MOUNT: SESSION_VOLUME},
    secrets=[_runtime_secret()],
    timeout=60 * 45,
)
def daily_scout_job():
    """
    Daily orchestration:
      1) Scrape latest GC data
      2) Recompute SWOT outputs
      3) Prepare NotebookLM sync payload

    Uses persistent Playwright auth/context in Modal Volume to avoid repeated logins.
    """
    print("[Modal] Daily scouting job started.")

    auth_dir = Path(VOLUME_MOUNT) / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    auth_file = auth_dir / "auth.json"
    profile_dir = auth_dir / "playwright-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    # Point cooldown file to the persistent volume so it survives between Modal runs
    cooldown_file = auth_dir / ".auth_cooldown"

    env = os.environ.copy()
    env["GC_AUTH_FILE"] = str(auth_file)
    env["GC_PLAYWRIGHT_CONTEXT_DIR"] = str(profile_dir)
    env["GC_AUTH_COOLDOWN_FILE"] = str(cooldown_file)
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("AUTH_COOLDOWN_HOURS", "4")

    # Validate credentials before attempting scrape to surface missing secrets clearly
    gc_email = env.get("GC_EMAIL", "").strip()
    gc_password = env.get("GC_PASSWORD", "").strip()
    if not gc_email or not gc_password:
        raise RuntimeError(
            "[Modal] GC_EMAIL or GC_PASSWORD not set. "
            "Add them as Modal secrets: modal secret create sharks-gc GC_EMAIL=... GC_PASSWORD=..."
        )

    # Check for auth cooldown file (persisted in volume) — avoid 2FA spam
    if cooldown_file.exists():
        try:
            import json as _json
            cd = _json.loads(cooldown_file.read_text())
            until_ts = cd.get("until", 0)
            now_ts = __import__("time").time()
            if now_ts < until_ts:
                remaining_min = int((until_ts - now_ts) / 60)
                print(f"[Modal] Auth cooldown active — skipping GC scrape for {remaining_min}m to prevent 2FA spam.")
                # Still run analysis steps on existing data
                _run_step("SWOT analysis", ["python", "tools/swot_analyzer.py"], env=env, optional=True)
                _run_step("NotebookLM payload sync", ["python", "tools/notebooklm_sync.py"], env=env, optional=True)
                SESSION_VOLUME.commit()
                return {"status": "skipped_gc", "reason": "auth_cooldown", "remaining_min": remaining_min}
        except Exception as e:
            print(f"[Modal] Could not read cooldown file: {e}")

    gc_ok = _run_step("GameChanger scrape", ["python", "tools/gc_scraper.py"], env=env, optional=True)
    if not gc_ok:
        print("[Modal] GC scrape failed — analysis steps will use cached data.")

    _run_step("SWOT analysis", ["python", "tools/swot_analyzer.py"], env=env, optional=True)
    _run_step("NotebookLM payload sync", ["python", "tools/notebooklm_sync.py"], env=env, optional=True)
    _run_step("RAG Memory sync", ["python", "tools/memory_engine.py", "sync"], env=env, optional=True)

    SESSION_VOLUME.commit()
    print("[Modal] Daily scouting job finished.")
    return {"status": "ok" if gc_ok else "partial", "gc_scrape": "ok" if gc_ok else "failed"}


@app.function(image=sharks_image, volumes={VOLUME_MOUNT: SESSION_VOLUME}, secrets=[_runtime_secret()], timeout=60 * 45)
@modal.web_endpoint(method="POST")
def manual_sync():
    """Manual trigger via Webhook (POST)."""
    daily_scout_job.spawn()
    return {"status": "triggered", "message": "Scouting job started in background."}


@app.function(image=sharks_image, volumes={VOLUME_MOUNT: SESSION_VOLUME}, secrets=[_runtime_secret()], timeout=60 * 45)
def trigger_immediate_refresh():
    """Internal manual trigger."""
    return daily_scout_job.remote()


@app.local_entrypoint()
def main():
    print("Launching manual Modal refresh...")
    result = trigger_immediate_refresh.remote()
    print(result)
