import os
import json
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
        "pyotp",
        "pinecone>=5.0,<6",
        "google-generativeai>=0.8,<1",
        "fastapi[standard]",
    )
    .run_commands("playwright install --with-deps chromium")
    .add_local_dir(".", remote_path="/app", ignore=["node_modules", "data", "client/node_modules", "client/dist", ".git"])
)

# Named Modal secret for GC auth credentials (GC_TOTP_SECRET, GC_PASSWORD, etc.)
try:
    _sharks_auth_secret = modal.Secret.from_name("softball-sharks-auth")
except Exception:
    _sharks_auth_secret = None

tts_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch==2.3.1",
        "torchaudio==2.3.1",
        "transformers>=4.45.0",
        "soundfile",
        "numpy",
        "scipy",
    )
)


def _runtime_secret() -> modal.Secret:
    payload = {}
    for key in (
        "GC_EMAIL",
        "GC_PASSWORD",
        "GC_TOTP_SECRET",
        "GC_TEAM_ID",
        "GC_SEASON_SLUG",
        "GC_ORG_IDS",
        "GC_SESSION_COOKIES",
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


def _build_voice_script(sharks_dir: str) -> str:
    """Build a 30-45 second sports radio announcement from team data."""
    team_file = Path(sharks_dir) / "team_enriched.json"
    if not team_file.exists():
        team_file = Path(sharks_dir) / "team.json"
    if not team_file.exists():
        return ""

    try:
        team = json.loads(team_file.read_text())
    except Exception:
        return ""

    team_name = team.get("team_name", "The Sharks")
    record = team.get("record", "0-0")
    roster = team.get("roster", [])

    # Top 3 hitters by AVG
    hitters = []
    for p in roster:
        bat = p.get("batting") or {}
        avg = float(bat.get("avg", 0) or 0)
        name = p.get("name") or f"{p.get('first', '')} {p.get('last', '')}".strip()
        if avg > 0 and name:
            hitters.append((name, avg))
    hitters.sort(key=lambda x: x[1], reverse=True)
    top3 = hitters[:3]

    hitter_text = ""
    if top3:
        parts = [f"{name} batting {avg:.3f}" for name, avg in top3]
        hitter_text = f"Leading the charge at the plate: {', '.join(parts)}."

    # Next game from schedule
    sched_file = Path(sharks_dir) / "schedule_manual.json"
    next_game_text = ""
    if sched_file.exists():
        try:
            sched = json.loads(sched_file.read_text())
            from datetime import datetime
            from zoneinfo import ZoneInfo
            today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
            upcoming = [g for g in (sched.get("upcoming") or []) if str(g.get("date", "")) >= today]
            if upcoming:
                g = upcoming[0]
                opp = g.get("opponent", "their next opponent")
                ha = "at home" if g.get("home_away") == "home" else "on the road"
                next_game_text = f"Next up, the Sharks take on the {opp} {ha}."
        except Exception:
            pass

    script = (
        f"Hey Sharks fans! Here's your latest team update. "
        f"{team_name} are {record} this season. "
        f"{hitter_text} "
        f"{next_game_text} "
        f"Let's go Sharks!"
    )
    return script.strip()


@app.function(
    image=tts_image,
    gpu="T4",
    volumes={VOLUME_MOUNT: SESSION_VOLUME},
    timeout=300,
    memory=8192,
)
def generate_voice_update(script_text: str, output_path: str = "/vol/softball-gc/sharks/voice_update.mp3"):
    """Generate TTS audio using Qwen3-TTS on Modal GPU."""
    import torch
    import soundfile as sf
    from transformers import AutoTokenizer, AutoModelForCausalLM

    if not script_text.strip():
        return {"status": "skipped", "reason": "empty script"}

    model_id = "Qwen/Qwen3-TTS"
    print(f"[TTS] Loading model {model_id}...")
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_id, torch_dtype=torch.float16, trust_remote_code=True
    ).to("cuda")

    print(f"[TTS] Generating speech for {len(script_text)} chars...")
    inputs = tokenizer(script_text, return_tensors="pt").to("cuda")
    with torch.no_grad():
        output = model.generate(**inputs, do_sample=True, temperature=0.7, max_new_tokens=4096)

    # Decode audio from model output
    audio_tokens = output[0][inputs["input_ids"].shape[-1]:]
    audio_np = audio_tokens.cpu().float().numpy()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(output_path, audio_np, samplerate=24000)
    print(f"[TTS] Saved to {output_path} ({Path(output_path).stat().st_size} bytes)")
    return {"status": "ok", "path": output_path}


@app.function(
    image=sharks_image,
    schedule=modal.Cron("0 6 * * *"),
    volumes={VOLUME_MOUNT: SESSION_VOLUME},
    secrets=[s for s in [_runtime_secret(), _sharks_auth_secret] if s],
    timeout=60 * 45,
)
def daily_scout_job():
    """
    Daily orchestration:
      1) Scrape latest GC data
      2) Recompute SWOT outputs
      3) Prepare NotebookLM sync payload
      4) Generate voice update (GPU)

    Uses persistent Playwright auth/context in Modal Volume to avoid repeated logins.
    Each step is wrapped in try/except so a single failure doesn't abort the pipeline.
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
    # Hardcoded GC team config fallbacks
    env.setdefault("GC_TEAM_ID", "NuGgx6WvP7TO")
    env.setdefault("GC_SEASON_SLUG", "2026-spring-sharks")

    # Auth: prefer TOTP, then session cookies, then email/password
    gc_totp = env.get("GC_TOTP_SECRET", "").strip()
    gc_cookies = env.get("GC_SESSION_COOKIES", "").strip()
    gc_email = env.get("GC_EMAIL", "").strip()
    gc_password = env.get("GC_PASSWORD", "").strip()
    if gc_totp:
        print("[Modal] GC_TOTP_SECRET available — will generate fresh TOTP codes for 2FA.")
    elif gc_cookies:
        print("[Modal] GC_SESSION_COOKIES available — will use cookie injection.")
    elif gc_email and gc_password:
        print("[Modal] Using GC_EMAIL/GC_PASSWORD for login (may trigger 2FA).")
    else:
        print("[Modal] WARNING: No GC auth configured. GC scrape will be skipped.")

    # Check for auth cooldown file (persisted in volume) — avoid 2FA spam
    skip_gc = False
    if cooldown_file.exists():
        try:
            cd = json.loads(cooldown_file.read_text())
            until_ts = cd.get("until", 0)
            now_ts = __import__("time").time()
            if now_ts < until_ts:
                remaining_min = int((until_ts - now_ts) / 60)
                print(f"[Modal] Auth cooldown active — skipping GC scrape for {remaining_min}m")
                skip_gc = True
        except Exception as e:
            print(f"[Modal] Could not read cooldown file: {e}")

    results = {}

    # Step 1: GC scrape
    if skip_gc:
        results["gc_scrape"] = "skipped_cooldown"
    else:
        gc_ok = _run_step("GameChanger scrape", ["python", "tools/gc_scraper.py"], env=env, optional=True)
        results["gc_scrape"] = "ok" if gc_ok else "failed"
        if not gc_ok:
            print("[Modal] GC scrape failed — analysis steps will use cached data.")

    # Step 2: SWOT analysis
    swot_ok = _run_step("SWOT analysis", ["python", "tools/swot_analyzer.py"], env=env, optional=True)
    results["swot"] = "ok" if swot_ok else "failed"

    # Step 3: NotebookLM sync
    nb_ok = _run_step("NotebookLM payload sync", ["python", "tools/notebooklm_sync.py"], env=env, optional=True)
    results["notebooklm"] = "ok" if nb_ok else "failed"

    # Step 4: RAG memory sync
    rag_ok = _run_step("RAG Memory sync", ["python", "tools/memory_engine.py", "sync"], env=env, optional=True)
    results["rag"] = "ok" if rag_ok else "failed"

    # Step 5: Voice update (runs on GPU via separate function)
    try:
        sharks_dir = str(Path(VOLUME_MOUNT) / "sharks")
        script = _build_voice_script(sharks_dir)
        if script:
            print("[Modal] Spawning voice update generation (GPU)...")
            generate_voice_update.spawn(script)
            results["voice"] = "spawned"
        else:
            results["voice"] = "skipped_no_data"
    except Exception as e:
        print(f"[Modal] Voice generation spawn failed: {e}")
        results["voice"] = "failed"

    SESSION_VOLUME.commit()
    print(f"[Modal] Daily scouting job finished. Results: {results}")
    return {"status": "ok", "steps": results}


@app.function(image=sharks_image, volumes={VOLUME_MOUNT: SESSION_VOLUME}, secrets=[s for s in [_runtime_secret(), _sharks_auth_secret] if s], timeout=60 * 45)
@modal.fastapi_endpoint(method="POST")
def manual_sync():
    """Manual trigger via Webhook (POST)."""
    daily_scout_job.spawn()
    return {"status": "triggered", "message": "Scouting job started in background."}


@app.function(image=sharks_image, volumes={VOLUME_MOUNT: SESSION_VOLUME}, secrets=[s for s in [_runtime_secret(), _sharks_auth_secret] if s], timeout=60 * 45)
def trigger_immediate_refresh():
    """Internal manual trigger."""
    return daily_scout_job.remote()


@app.local_entrypoint()
def main():
    print("Launching manual Modal refresh...")
    result = trigger_immediate_refresh.remote()
    print(result)
