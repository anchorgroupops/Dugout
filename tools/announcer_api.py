"""Apex Announcer — Local FastAPI TTS Service.

Serves Qwen3-TTS-1.7B-VoiceDesign inference locally on MacBook Pro (MPS)
or Raspberry Pi 5 (CPU). Falls back to Replicate cloud API if no local
model is available.

Inference mode selected by env vars:
  USE_VLLM=1        → vLLM AsyncLLMEngine (requires CUDA)
  USE_TRANSFORMERS=1 → HuggingFace transformers pipeline (MPS / CPU)
  (neither)          → Proxy to Replicate (requires REPLICATE_API_TOKEN)

Start:
  uvicorn announcer_api:app --host 0.0.0.0 --port 8765 --workers 1

Then set in .env:
  LOCAL_TTS_URL=http://localhost:8765
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import socket
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import AsyncGenerator

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).parent.parent / ".env", override=False)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
log = logging.getLogger("announcer_api")

MODEL_ID = "Qwen/Qwen3-TTS-1.7B-VoiceDesign"

# ---------------------------------------------------------------------------
# Render worker config
# ---------------------------------------------------------------------------

# URL of the Pi's Flask API (sync_daemon.py) — use Tailscale IP for direct access
PI_API_URL = os.getenv("PI_API_URL", "").rstrip("/")
WORKER_ID = os.getenv("WORKER_ID", socket.gethostname())
WORKER_VERSION = "2.0.0"
POLL_INTERVAL_SECONDS = int(os.getenv("RENDER_POLL_INTERVAL", "10"))
HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("HEARTBEAT_INTERVAL", "30"))
_pipeline = None
_vllm_engine = None
_model_loaded = False
_active_provider = "none"

app = FastAPI(title="Apex Announcer TTS", version="1.0.0")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class VoiceDesignParams(BaseModel):
    pitch: float = Field(-2.0, ge=-12.0, le=12.0, description="Pitch shift in semitones")
    energy: float = Field(1.3, ge=0.5, le=3.0, description="Amplitude/energy scale")
    speaking_rate: float = Field(0.92, ge=0.5, le=2.0, description="Speaking rate multiplier")
    emotion_exaggeration: float = Field(0.85, ge=0.0, le=1.0, description="Halo 'Voice of God' intensity")
    speaker_style: str = Field("announcer", description="Style hint for VoiceDesign conditioning")


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000, description="Text to synthesize (supports [breath], [pause:Xs] tags)")
    voice_design: VoiceDesignParams = Field(default_factory=VoiceDesignParams)
    reference_audio_url: str = Field("", description="URL to 5-10s Jeff Steitzer reference clip for ICL clone mode")
    reference_transcript: str = Field("", description="Transcript of the reference clip")


# ---------------------------------------------------------------------------
# Model loading (lazy)
# ---------------------------------------------------------------------------

def _load_transformers_pipeline():
    global _pipeline, _model_loaded, _active_provider
    try:
        import torch
        from transformers import pipeline as hf_pipeline

        device = (
            "mps" if torch.backends.mps.is_available()
            else "cuda" if torch.cuda.is_available()
            else "cpu"
        )
        log.info("Loading %s on device=%s", MODEL_ID, device)
        _pipeline = hf_pipeline(
            "text-to-speech",
            model=MODEL_ID,
            device=device,
        )
        _model_loaded = True
        _active_provider = f"transformers:{device}"
        log.info("Model loaded successfully on %s", device)
    except Exception as exc:
        log.warning("transformers load failed: %s — will proxy to Replicate", exc)
        _active_provider = "replicate_proxy"


async def _load_vllm_engine():
    global _vllm_engine, _model_loaded, _active_provider
    try:
        from vllm import AsyncLLMEngine, AsyncEngineArgs

        args = AsyncEngineArgs(model=MODEL_ID, dtype="float16", max_model_len=2048)
        _vllm_engine = AsyncLLMEngine.from_engine_args(args)
        _model_loaded = True
        _active_provider = "vllm"
        log.info("vLLM engine loaded for %s", MODEL_ID)
    except Exception as exc:
        log.warning("vLLM load failed: %s — falling back to transformers", exc)
        _load_transformers_pipeline()


@app.on_event("startup")
async def startup():
    use_vllm = os.getenv("USE_VLLM", "").lower() in ("1", "true", "yes")
    use_transformers = os.getenv("USE_TRANSFORMERS", "").lower() in ("1", "true", "yes")

    if use_vllm:
        await _load_vllm_engine()
    elif use_transformers:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _load_transformers_pipeline)
    else:
        log.info("No local model requested — proxying to Replicate")
        global _active_provider
        _active_provider = "replicate_proxy"

    # Launch render worker + heartbeat tasks if Pi API URL is configured
    asyncio.create_task(_heartbeat_loop())
    asyncio.create_task(_render_worker_loop())


# ---------------------------------------------------------------------------
# Synthesis helpers
# ---------------------------------------------------------------------------

def _synth_transformers(text: str, vd: VoiceDesignParams) -> bytes:
    result = _pipeline(text, forward_params={
        "pitch_shift": vd.pitch,
        "energy_scale": vd.energy,
        "speaking_rate": vd.speaking_rate,
    })
    audio_array = result["audio"]
    sampling_rate = result.get("sampling_rate", 22050)

    buf = io.BytesIO()
    import numpy as np
    pcm = (audio_array * 32767).astype(np.int16)
    n = len(pcm)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sampling_rate)
        wf.writeframes(struct.pack(f"<{n}h", *pcm.tolist()))
    return buf.getvalue()


def _synth_replicate(text: str, vd: VoiceDesignParams, ref_audio: str, ref_text: str) -> bytes:
    token = os.getenv("REPLICATE_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN not set and no local model available")

    if not ref_audio or not ref_text:
        raise RuntimeError("reference_audio_url and reference_transcript required for Replicate clone mode")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "wait",
    }
    payload = {
        "input": {
            "mode": "clone",
            "text": text,
            "reference_audio": ref_audio,
            "reference_text": ref_text,
            "language": "en",
            "voice_design": {
                "pitch": vd.pitch,
                "energy": vd.energy,
                "speaking_rate": vd.speaking_rate,
            },
            "emotion_exaggeration": vd.emotion_exaggeration,
        }
    }
    resp = requests.post(
        "https://api.replicate.com/v1/models/qwen/qwen3-tts-1.7b-voicedesign/predictions",
        json=payload,
        headers=headers,
        timeout=90,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Replicate {resp.status_code}: {resp.text[:300]}")

    result = resp.json()
    if result.get("status") == "succeeded":
        output = result.get("output")
    else:
        poll_url = result.get("urls", {}).get("get", "")
        if not poll_url:
            raise RuntimeError("No poll URL in Replicate response")
        import time
        start = time.monotonic()
        while time.monotonic() - start < 120:
            time.sleep(2)
            pr = requests.get(poll_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
            pd = pr.json()
            if pd.get("status") == "succeeded":
                output = pd.get("output")
                break
            if pd.get("status") in ("failed", "canceled"):
                raise RuntimeError(f"Replicate failed: {pd.get('error', 'unknown')}")
        else:
            raise RuntimeError("Replicate timed out")

    url = output if isinstance(output, str) else output[0]
    audio_resp = requests.get(url, timeout=60)
    if audio_resp.status_code != 200:
        raise RuntimeError(f"Failed to download Replicate audio: {audio_resp.status_code}")
    return audio_resp.content


def _make_silent_wav(duration_secs: int = 2) -> bytes:
    buf = io.BytesIO()
    sample_rate = 22050
    n = sample_rate * duration_secs
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{n}h", *([0] * n)))
    return buf.getvalue()


async def _synthesize_async(req: SynthesizeRequest) -> bytes:
    loop = asyncio.get_event_loop()

    if _pipeline is not None:
        return await loop.run_in_executor(
            None, _synth_transformers, req.text, req.voice_design
        )

    if _active_provider == "replicate_proxy" or not _model_loaded:
        return await loop.run_in_executor(
            None,
            _synth_replicate,
            req.text,
            req.voice_design,
            req.reference_audio_url,
            req.reference_transcript,
        )

    return _make_silent_wav()


async def _stream_audio(audio_bytes: bytes, chunk_size: int = 4096) -> AsyncGenerator[bytes, None]:
    for i in range(0, len(audio_bytes), chunk_size):
        yield audio_bytes[i : i + chunk_size]
        await asyncio.sleep(0)  # yield control so first chunk arrives fast


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "provider": _active_provider,
        "model_loaded": _model_loaded,
        "model_id": MODEL_ID,
    }


@app.post("/synthesize")
async def synthesize(req: SynthesizeRequest):
    """Synthesize speech and stream MP3/WAV bytes.

    Uses the Qwen3-TTS-1.7B-VoiceDesign model locally (transformers/vLLM) or
    proxies to Replicate if no local model is configured.
    """
    try:
        audio_bytes = await _synthesize_async(req)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        log.exception("Synthesis error: %s", exc)
        raise HTTPException(status_code=500, detail="Synthesis failed")

    content_type = "audio/mpeg" if audio_bytes[:3] == b"ID3" or audio_bytes[:2] == b"\xff\xfb" else "audio/wav"

    return StreamingResponse(
        _stream_audio(audio_bytes),
        media_type=content_type,
        headers={
            "X-Provider": _active_provider,
            "Cache-Control": "no-store",
        },
    )


# ---------------------------------------------------------------------------
# Stadium Wrap — FFmpeg post-processing chain
# ---------------------------------------------------------------------------

def _run_stadium_wrap(audio_bytes: bytes) -> tuple[bytes, bytes]:
    """Apply the Stadium Wrap FFmpeg chain to raw audio bytes.

    Two-pass production:
      Pass 1 — WAV/MP3 → FLAC master (24-bit / 48kHz)
      Pass 2 — FLAC → compand + lowshelf +4dB @ 150Hz + extrastereo → 192kbps MP3

    Returns (flac_bytes, mp3_bytes).
    Raises RuntimeError if FFmpeg is not in PATH or a pass fails.
    """
    is_mp3 = audio_bytes[:3] == b"ID3" or (
        len(audio_bytes) >= 2 and audio_bytes[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
    )
    in_suffix = ".mp3" if is_mp3 else ".wav"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        input_path = tmp / f"input{in_suffix}"
        flac_path = tmp / "master.flac"
        mp3_path = tmp / "proxy.mp3"

        input_path.write_bytes(audio_bytes)

        # Pass 1: → FLAC 24-bit/48kHz
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(input_path),
             "-ar", "48000", "-c:a", "flac", "-sample_fmt", "s32",
             str(flac_path)],
            capture_output=True, timeout=60,
        )
        if r.returncode != 0:
            raise RuntimeError(f"Stadium Wrap Pass 1 failed: {r.stderr.decode(errors='replace')[:300]}")

        # Pass 2: Stadium Wrap → 192kbps MP3
        # compand → vocal boom → split → slapback/reverb → 80/20 wet/dry mix → stereo widen
        filtergraph = (
            "[0:a]"
            "compand=attacks=0.01:decays=0.2"
            ":points=-80/-80|-45/-30|-27/-20|0/-13:gain=6,"
            "equalizer=f=150:t=l:width_type=o:width=2:g=4"
            "[processed];"
            "[processed]asplit=2[dry][wet];"
            "[wet]aecho=0.8:1.0:50|75|100:0.4|0.3|0.2[rev];"
            "[dry][rev]amix=inputs=2:weights=0.8:0.2,"
            "extrastereo=m=2.5[out]"
        )
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(flac_path),
             "-filter_complex", filtergraph,
             "-map", "[out]",
             "-ar", "48000", "-ac", "2",
             "-c:a", "libmp3lame", "-q:a", "2",
             str(mp3_path)],
            capture_output=True, timeout=60,
        )
        if r.returncode != 0:
            raise RuntimeError(f"Stadium Wrap Pass 2 failed: {r.stderr.decode(errors='replace')[:300]}")

        return flac_path.read_bytes(), mp3_path.read_bytes()


# ---------------------------------------------------------------------------
# Pi API helpers
# ---------------------------------------------------------------------------

def _pi_claim_job(job_id: str) -> bool:
    """Mark job PROCESSING on Pi so failover doesn't fire."""
    if not PI_API_URL:
        return False
    try:
        resp = requests.patch(
            f"{PI_API_URL}/api/announcer/render-queue/{job_id}",
            json={"worker_id": WORKER_ID, "status": "PROCESSING"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as exc:
        log.warning("[render_worker] claim job %s failed: %s", job_id, exc)
        return False


def _pi_upload_complete(job_id: str, flac_bytes: bytes, mp3_bytes: bytes) -> bool:
    """Upload FLAC master + MP3 proxy to Pi render-complete endpoint."""
    if not PI_API_URL:
        return False
    try:
        resp = requests.post(
            f"{PI_API_URL}/api/announcer/render-complete/{job_id}",
            files={
                "mp3": ("proxy.mp3", mp3_bytes, "audio/mpeg"),
                "flac": ("master.flac", flac_bytes, "audio/flac"),
            },
            timeout=120,
        )
        return resp.status_code == 200
    except Exception as exc:
        log.warning("[render_worker] upload complete for %s failed: %s", job_id, exc)
        return False


def _pi_mark_failed(job_id: str, error: str) -> None:
    if not PI_API_URL:
        return
    try:
        requests.patch(
            f"{PI_API_URL}/api/announcer/render-queue/{job_id}",
            json={"status": "FAILED", "error": error[:300]},
            timeout=10,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Background tasks — heartbeat + render worker
# ---------------------------------------------------------------------------

async def _heartbeat_loop() -> None:
    """Send heartbeat to Pi every HEARTBEAT_INTERVAL_SECONDS."""
    if not PI_API_URL:
        log.info("[heartbeat] PI_API_URL not set — heartbeat disabled")
        return

    while True:
        try:
            resp = requests.post(
                f"{PI_API_URL}/api/announcer/heartbeat",
                json={"worker_id": WORKER_ID, "version": WORKER_VERSION},
                timeout=5,
            )
            if resp.status_code != 200:
                log.warning("[heartbeat] unexpected status %s", resp.status_code)
        except Exception as exc:
            log.warning("[heartbeat] failed: %s", exc)
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


async def _render_worker_loop() -> None:
    """Poll Pi for PENDING best-quality jobs and execute them locally."""
    if not PI_API_URL:
        log.info("[render_worker] PI_API_URL not set — render worker disabled")
        return

    log.info("[render_worker] Starting — polling %s every %ds", PI_API_URL, POLL_INTERVAL_SECONDS)

    while True:
        try:
            resp = requests.get(
                f"{PI_API_URL}/api/announcer/render-queue",
                timeout=10,
            )
            if resp.status_code != 200:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            jobs = resp.json().get("jobs", [])
            if not jobs:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            job = jobs[0]
            job_id = job["id"]
            player_id = job["player_id"]
            game_context = job.get("game_context") or {}
            if isinstance(game_context, str):
                import json as _json
                game_context = _json.loads(game_context) if game_context else {}

            log.info("[render_worker] Claimed job %s (player=%s)", job_id, player_id)
            _pi_claim_job(job_id)

            try:
                # Synthesize with 1.7B model
                from announcer_engine import (
                    build_announcement_text, get_player_by_id,
                    get_tts_provider, get_default_voice_profile,
                )
                player = get_player_by_id(player_id)
                if not player:
                    raise ValueError(f"Player not found: {player_id}")

                text = build_announcement_text(player, game_context)
                provider = get_tts_provider()
                voice = get_default_voice_profile()

                loop = asyncio.get_event_loop()
                audio_bytes = await loop.run_in_executor(
                    None, provider.synthesize, text, voice
                )

                # Stadium Wrap
                flac_bytes, mp3_bytes = await loop.run_in_executor(
                    None, _run_stadium_wrap, audio_bytes
                )
                log.info(
                    "[render_worker] Stadium Wrap complete for %s: FLAC %dkB MP3 %dkB",
                    player_id, len(flac_bytes) // 1024, len(mp3_bytes) // 1024,
                )

                # Upload to Pi
                ok = await loop.run_in_executor(
                    None, _pi_upload_complete, job_id, flac_bytes, mp3_bytes
                )
                if not ok:
                    log.warning("[render_worker] upload failed for job %s", job_id)

            except Exception as exc:
                log.error("[render_worker] job %s failed: %s", job_id, exc)
                _pi_mark_failed(job_id, str(exc))

        except Exception as exc:
            log.warning("[render_worker] poll error: %s", exc)

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("TTS_PORT", "8765"))
    log.info("Starting Apex Announcer TTS on :%d", port)
    uvicorn.run("announcer_api:app", host="0.0.0.0", port=port, workers=1)
