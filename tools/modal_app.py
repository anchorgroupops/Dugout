"""
Modal app for softball-strategy-sharks.

Voice generation (daily team update) runs here using EdgeTTS — free Microsoft
Neural voices, no API key, pure HTTP (no GPU needed).
GC scraping and game analysis run exclusively on the Pi's sync_daemon to avoid
2FA email spam from Modal's rotating IPs.
"""
import json
from pathlib import Path

import modal
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

app = modal.App("softball-strategy-sharks")

SESSION_VOLUME = modal.Volume.from_name("softball-gc-session", create_if_missing=True)
VOLUME_MOUNT = "/vol/softball-gc"

# Single image for all functions — EdgeTTS is pure HTTP, no GPU or torch needed.
sharks_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("python-dotenv", "fastapi[standard]", "edge-tts>=6.1.9")
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
                next_game_text = f"Next up, the Sharks take on {opp} {ha}."
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
    image=sharks_image,
    volumes={VOLUME_MOUNT: SESSION_VOLUME},
    timeout=120,
)
def generate_voice_update(script_text: str, output_path: str = "/vol/softball-gc/sharks/voice_update.mp3"):
    """Generate TTS audio using EdgeTTS (Microsoft Neural voices, free, no GPU)."""
    import asyncio
    import edge_tts

    if not script_text.strip():
        return {"status": "skipped", "reason": "empty script"}

    voice = "en-US-GuyNeural"
    print(f"[TTS] Generating {len(script_text)} chars via EdgeTTS ({voice})...")

    async def _synthesize():
        communicate = edge_tts.Communicate(script_text, voice)
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)

    audio_bytes = asyncio.run(_synthesize())
    if not audio_bytes:
        return {"status": "error", "reason": "edge_tts returned empty audio"}

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio_bytes)
    print(f"[TTS] Saved {len(audio_bytes)} bytes to {output_path}")
    SESSION_VOLUME.commit()
    return {"status": "ok", "path": output_path, "bytes": len(audio_bytes)}


@app.function(
    image=sharks_image,
    schedule=modal.Cron("0 6 * * *"),
    volumes={VOLUME_MOUNT: SESSION_VOLUME},
    timeout=180,
)
def daily_scout_job():
    """Daily voice update — reads team data from volume, generates EdgeTTS MP3.

    GC scraping + analysis runs on the Pi's sync_daemon — not here.
    """
    print("[Modal] Daily voice update job started.")
    sharks_dir = str(Path(VOLUME_MOUNT) / "sharks")
    script = _build_voice_script(sharks_dir)
    if script:
        print("[Modal] Generating voice update via EdgeTTS...")
        result = generate_voice_update.remote(script)
        print(f"[Modal] Voice update complete: {result}")
        return {"status": "ok", "voice": result}
    print("[Modal] No team data in volume — skipping.")
    return {"status": "skipped", "reason": "no_team_data"}


@app.function(image=sharks_image, volumes={VOLUME_MOUNT: SESSION_VOLUME}, timeout=180)
@modal.fastapi_endpoint(method="POST")
def manual_sync(request: dict = None):
    """Manual trigger via Webhook (POST).

    Accepts optional JSON body: {"script": "...voice script text..."}
    """
    script = (request or {}).get("script", "").strip() if request else ""
    if not script:
        sharks_dir = str(Path(VOLUME_MOUNT) / "sharks")
        script = _build_voice_script(sharks_dir)
    if script:
        generate_voice_update.spawn(script)
        return {"status": "triggered", "message": "Voice generation started in background."}
    return {"status": "skipped", "reason": "no_script_or_team_data"}


@app.function(image=sharks_image, volumes={VOLUME_MOUNT: SESSION_VOLUME}, timeout=180)
def trigger_immediate_refresh():
    """Internal manual trigger."""
    return daily_scout_job.remote()


@app.local_entrypoint()
def main():
    print("Launching voice update generation...")
    result = trigger_immediate_refresh.remote()
    print(result)
