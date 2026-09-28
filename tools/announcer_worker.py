"""Announcer render worker — Qwen3-TTS on any machine with a decent GPU.

Outbound-only: polls the Pi for jobs, synthesises locally, uploads raw WAV.
It opens no port, so it is safe to run on the Mac on demand. The Pi composes
each job's script and voice direction, so the worker needs no roster data and
no FFmpeg (the Pi applies the Stadium Wrap).

Backends (picked automatically):
  Apple Silicon → mlx-audio   (pip install mlx-audio soundfile)
  NVIDIA CUDA   → qwen-tts    (pip install qwen-tts soundfile)

Env:
  PI_API_URL          https://dugout.joelycannoli.com   (required)
  DUGOUT_WRITE_TOKEN  shared write token                (required)
  DUGOUT_ORIGIN       Origin header, default = PI_API_URL
  WORKER_ID           default = hostname
  QWEN_TTS_MODEL      override the model repo id

Run:
  python tools/announcer_worker.py            # poll forever
  python tools/announcer_worker.py --once "Now batting, number twelve"   # local test → out.wav
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import platform
import socket
import sys
import time

import requests

log = logging.getLogger("announcer_worker")

WORKER_VERSION = "3.0.0"
POLL_INTERVAL_SECONDS = int(os.getenv("RENDER_POLL_INTERVAL", "5"))
HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("HEARTBEAT_INTERVAL", "30"))
MLX_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit"
CUDA_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
DEFAULT_INSTRUCT = ("A booming, deep male stadium announcer. Slow and dramatic with big "
                    "crowd energy, drawing out the player's name.")


# ---------------------------------------------------------------------------
# Synthesis backends
# ---------------------------------------------------------------------------

class Qwen3Backend:
    """Loads Qwen3-TTS VoiceDesign once; synthesize() returns WAV bytes."""

    def __init__(self) -> None:
        if sys.platform == "darwin" and platform.machine() == "arm64":
            from mlx_audio.tts.utils import load_model
            self.name = "qwen3-mlx"
            self._model = load_model(os.getenv("QWEN_TTS_MODEL", MLX_MODEL))
            self.sample_rate = self._model.sample_rate
        else:
            import torch
            from qwen_tts import Qwen3TTSModel
            if not torch.cuda.is_available():
                raise RuntimeError("No Apple Silicon or CUDA GPU — this worker needs one")
            self.name = "qwen3-cuda"
            self._model = Qwen3TTSModel.from_pretrained(
                os.getenv("QWEN_TTS_MODEL", CUDA_MODEL),
                device_map="cuda:0", dtype=torch.bfloat16,
            )
            self.sample_rate = None
        log.info("Loaded %s", self.name)

    def synthesize(self, text: str, instruct: str) -> bytes:
        import numpy as np
        import soundfile as sf

        if self.name == "qwen3-mlx":
            chunks = self._model.generate_voice_design(text=text, language="English", instruct=instruct)
            audio = np.concatenate([np.array(c.audio) for c in chunks])
            sr = self.sample_rate
        else:
            wavs, sr = self._model.generate_voice_design(text=text, language="English", instruct=instruct)
            audio = wavs[0]
        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="WAV")
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Pi client
# ---------------------------------------------------------------------------

class PiClient:
    def __init__(self, base_url: str, token: str, origin: str, worker_id: str) -> None:
        self.base = base_url.rstrip("/")
        self.worker_id = worker_id
        # Origin satisfies the Pi's JSON write guard; the token satisfies the
        # write-token gate. Missing either used to 403/401 every worker call.
        self.headers = {"Origin": origin, "X-Dugout-Token": token}

    def heartbeat(self) -> None:
        requests.post(f"{self.base}/api/announcer/heartbeat", headers=self.headers,
                      json={"worker_id": self.worker_id, "version": WORKER_VERSION},
                      timeout=5).raise_for_status()

    def pending_jobs(self) -> list[dict]:
        r = requests.get(f"{self.base}/api/announcer/render-queue", headers=self.headers, timeout=10)
        r.raise_for_status()
        return r.json().get("jobs", [])

    def set_status(self, job_id: str, status: str, error: str = "") -> None:
        body = {"worker_id": self.worker_id, "status": status}
        if error:
            body["error"] = error[:300]
        requests.patch(f"{self.base}/api/announcer/render-queue/{job_id}",
                       headers=self.headers, json=body, timeout=10).raise_for_status()

    def upload(self, job_id: str, wav: bytes) -> None:
        requests.post(f"{self.base}/api/announcer/render-complete/{job_id}", headers=self.headers,
                      files={"audio": ("render.wav", wav, "audio/wav")},
                      timeout=120).raise_for_status()


def run_job(pi: PiClient, backend: Qwen3Backend, job: dict) -> None:
    job_id = job["id"]
    text = (job.get("text") or "").strip()
    if not text:
        # Queued before jobs carried a script; rendering it would mean guessing
        # at a roster this machine doesn't have.
        pi.set_status(job_id, "FAILED", "legacy job without a script — re-render from the Announcer")
        return
    try:
        pi.set_status(job_id, "PROCESSING")
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 409:
            return  # another worker got it first
        raise
    try:
        t = time.time()
        wav = backend.synthesize(text, job.get("instruct") or DEFAULT_INSTRUCT)
        pi.upload(job_id, wav)
        log.info("Job %s (%s) done in %.1fs", job_id, job.get("kind") or "player", time.time() - t)
    except Exception as exc:
        log.error("Job %s failed: %s", job_id, exc)
        pi.set_status(job_id, "FAILED", str(exc))


def serve(pi: PiClient, backend: Qwen3Backend) -> None:
    log.info("Worker %s polling %s every %ds", pi.worker_id, pi.base, POLL_INTERVAL_SECONDS)
    last_beat = 0.0
    while True:
        try:
            if time.time() - last_beat >= HEARTBEAT_INTERVAL_SECONDS:
                pi.heartbeat()
                last_beat = time.time()
            for job in pi.pending_jobs():
                run_job(pi, backend, job)
                pi.heartbeat()
                last_beat = time.time()
        except Exception as exc:
            log.warning("Poll error: %s", exc)
        time.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", metavar="TEXT", help="render TEXT locally to --out and exit")
    ap.add_argument("--instruct", default=DEFAULT_INSTRUCT)
    ap.add_argument("--out", default="out.wav")
    args = ap.parse_args()

    backend = Qwen3Backend()
    if args.once:
        with open(args.out, "wb") as f:
            f.write(backend.synthesize(args.once, args.instruct))
        print(args.out)
        return

    base = os.getenv("PI_API_URL", "").strip()
    token = os.getenv("DUGOUT_WRITE_TOKEN", "").strip()
    if not base or not token:
        sys.exit("PI_API_URL and DUGOUT_WRITE_TOKEN must be set")
    serve(PiClient(base, token, os.getenv("DUGOUT_ORIGIN", base).rstrip("/"),
                   os.getenv("WORKER_ID", socket.gethostname())), backend)


if __name__ == "__main__":
    main()
