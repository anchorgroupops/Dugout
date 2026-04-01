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
        "playwright==1.49.0",
        "python-dotenv",
        "requests",
        "pinecone",
        "google-generativeai",
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


def _run_step(label: str, args: list[str], env: dict[str, str]) -> None:
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
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {proc.returncode}")
    print(f"[Modal] Completed step: {label}")


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

    env = os.environ.copy()
    env["GC_AUTH_FILE"] = str(auth_file)
    env["GC_PLAYWRIGHT_CONTEXT_DIR"] = str(profile_dir)
    env.setdefault("PYTHONUNBUFFERED", "1")

    _run_step("GameChanger scrape", ["python", "tools/gc_scraper.py"], env=env)
    _run_step("SWOT analysis", ["python", "tools/swot_analyzer.py"], env=env)
    _run_step("NotebookLM payload sync", ["python", "tools/notebooklm_sync.py"], env=env)
    _run_step("RAG Memory sync", ["python", "tools/memory_engine.py", "sync"], env=env)

    SESSION_VOLUME.commit()
    print("[Modal] Daily scouting job finished.")
    return {"status": "ok"}


@app.function(
    image=sharks_image,
    schedule=modal.Cron("0 23 * * *"),  # Nightly at 11PM ET
    volumes={VOLUME_MOUNT: SESSION_VOLUME},
    secrets=[_runtime_secret()],
    timeout=60 * 60,  # 60 min — full pipeline is heavier than daily scout
)
def night_shift_job():
    """
    Night Shift — autonomous overnight coworker.
    Runs the full heavy-lift pipeline: league scrape, SWOT, lineups,
    practice plans, sync, reconciliation, and morning briefing.
    """
    print("[Modal] Night Shift started.")

    auth_dir = Path(VOLUME_MOUNT) / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    auth_file = auth_dir / "auth.json"
    profile_dir = auth_dir / "playwright-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["GC_AUTH_FILE"] = str(auth_file)
    env["GC_PLAYWRIGHT_CONTEXT_DIR"] = str(profile_dir)
    env.setdefault("PYTHONUNBUFFERED", "1")

    _run_step("Night Shift Pipeline", ["python", "tools/night_shift.py"], env=env)

    SESSION_VOLUME.commit()
    print("[Modal] Night Shift finished.")
    return {"status": "ok", "job": "night_shift"}


@app.function(image=sharks_image, volumes={VOLUME_MOUNT: SESSION_VOLUME}, secrets=[_runtime_secret()], timeout=60 * 45)
@modal.web_endpoint(method="POST")
def manual_sync():
    """Manual trigger via Webhook (POST)."""
    daily_scout_job.spawn()
    return {"status": "triggered", "message": "Scouting job started in background."}


@app.function(image=sharks_image, volumes={VOLUME_MOUNT: SESSION_VOLUME}, secrets=[_runtime_secret()], timeout=60 * 60)
@modal.web_endpoint(method="POST")
def manual_night_shift():
    """Manual Night Shift trigger via Webhook (POST)."""
    night_shift_job.spawn()
    return {"status": "triggered", "message": "Night Shift started in background."}


@app.function(image=sharks_image, volumes={VOLUME_MOUNT: SESSION_VOLUME}, secrets=[_runtime_secret()], timeout=60 * 45)
def trigger_immediate_refresh():
    """Internal manual trigger."""
    return daily_scout_job.remote()


@app.local_entrypoint()
def main():
    print("Launching manual Modal refresh...")
    result = trigger_immediate_refresh.remote()
    print(result)
