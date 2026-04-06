"""
Modal app for softball-strategy-sharks.

Only GPU tasks (voice generation) run here. GC scraping and data analysis
run exclusively on the Pi's sync_daemon to avoid 2FA email spam from
Modal's rotating IPs.
"""
import json
from pathlib import Path

import modal
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

app = modal.App("softball-strategy-sharks")

SESSION_VOLUME = modal.Volume.from_name("softball-gc-session", create_if_missing=True)
VOLUME_MOUNT = "/vol/softball-gc"

# Minimal image — no Playwright or scraping deps needed (Pi handles that)
sharks_image = (
    modal.Image.debian_slim()
    .pip_install("python-dotenv", "fastapi[standard]")
)

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
        bat = p.get("batting") or p
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

    # TODO: Qwen3-TTS output requires model-specific audio decoding (codec/vocoder),
    # not raw token-to-float conversion. This may produce garbled/silent output.
    # Fix: use the model's decode_audio() API or switch to a known-working TTS model.
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
    timeout=600,
)
def daily_scout_job():
    """Daily voice update generation (GPU).

    GC scraping + analysis runs on the Pi's sync_daemon — not here.
    This prevents 2FA email spam from Modal's rotating IPs.
    """
    print("[Modal] Daily voice update job started.")
    sharks_dir = str(Path(VOLUME_MOUNT) / "sharks")
    script = _build_voice_script(sharks_dir)
    if script:
        print("[Modal] Generating voice update (GPU)...")
        result = generate_voice_update.remote(script)
        SESSION_VOLUME.commit()
        print(f"[Modal] Voice update complete: {result}")
        return {"status": "ok", "voice": result}
    print("[Modal] No team data for voice script — skipping.")
    return {"status": "skipped", "reason": "no_team_data"}


@app.function(image=sharks_image, volumes={VOLUME_MOUNT: SESSION_VOLUME}, timeout=600)
@modal.fastapi_endpoint(method="POST")
def manual_sync():
    """Manual trigger via Webhook (POST). Generates voice update only."""
    daily_scout_job.spawn()
    return {"status": "triggered", "message": "Voice generation started in background."}


@app.function(image=sharks_image, volumes={VOLUME_MOUNT: SESSION_VOLUME}, timeout=600)
def trigger_immediate_refresh():
    """Internal manual trigger."""
    return daily_scout_job.remote()


@app.local_entrypoint()
def main():
    print("Launching voice update generation...")
    result = trigger_immediate_refresh.remote()
    print(result)
