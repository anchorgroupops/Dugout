"""Announcer TTS Engine — voice synthesis for walk-up announcements.

Providers, in priority order (see _build_provider_chain):
  LocalVLLM → Replicate (only with a voice reference) → ElevenLabs → EdgeTTS →
  Kokoro → Google Cloud → Mock.  In production ElevenLabs is the one that runs.

Data stored in data/sharks/announcer/:
  - roster.json          — player announcer metadata
  - voice_selection.json — which VOICE_PROFILES entry is the team default
  - voice_samples/       — cached per-voice sample lines for the picker
  - clips/{player_id}/{timestamp}.mp3   — rendered audio (Stadium Wrap applied)
  - archive/{player_id}/{timestamp}.flac — lossless masters, best-quality only
"""
from __future__ import annotations

import io
import json
import logging
import os
import struct
import threading
import time
import wave
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")

DATA_DIR = Path(__file__).parent.parent / "data"
ANNOUNCER_DIR = DATA_DIR / "sharks" / "announcer"
CLIPS_DIR = ANNOUNCER_DIR / "clips"
ARCHIVE_DIR = ANNOUNCER_DIR / "archive"
ROSTER_FILE = ANNOUNCER_DIR / "roster.json"

class _RosterLock:
    """Re-entrant lock over roster.json that holds across threads AND processes.

    A thread lock alone is not enough: the Pi runs gunicorn with 2 workers, so
    a coach tapping Render on two players can land each request in a different
    process.  The OS file lock (flock / msvcrt) is what actually serialises them;
    the RLock makes it re-entrant, since update_player() calls load_announcer_roster()
    while already holding the lock.  Both release automatically if the process dies.
    """

    def __init__(self) -> None:
        self._thread_lock = threading.RLock()
        self._depth = 0
        self._fh = None

    def __enter__(self):
        self._thread_lock.acquire()
        if self._depth == 0:
            self._fh = self._acquire_file_lock()
        self._depth += 1
        return self

    def __exit__(self, *exc):
        self._depth -= 1
        if self._depth == 0 and self._fh is not None:
            self._release_file_lock(self._fh)
            self._fh = None
        self._thread_lock.release()

    @staticmethod
    def _acquire_file_lock():
        lock_path = ROSTER_FILE.with_suffix(".lock")
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(lock_path, "a+")
        except OSError as e:
            # Read-only filesystem — fall back to the thread lock only.
            logging.warning("[Announcer] roster lock file unavailable (%s); thread-lock only", e)
            return None
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except OSError as e:
            logging.warning("[Announcer] roster file lock failed (%s); thread-lock only", e)
            fh.close()
            return None
        return fh

    @staticmethod
    def _release_file_lock(fh) -> None:
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


# Serialises roster.json read-modify-write across concurrent renders.
_ROSTER_LOCK = _RosterLock()

# Reuse the phonetic map from sync_daemon at runtime (imported lazily to avoid circular imports)
_PHONETIC_MAP = None


def _get_phonetic_map() -> dict:
    global _PHONETIC_MAP
    if _PHONETIC_MAP is None:
        try:
            from sync_daemon import _PHONETIC_MAP as pm
            _PHONETIC_MAP = pm
        except ImportError:
            _PHONETIC_MAP = {}
    return _PHONETIC_MAP


def _apply_phonetics(text: str) -> str:
    """Replace known mispronounced names with phonetic spellings."""
    import re
    result = text
    for word, phonetic in _get_phonetic_map().items():
        if word.lower() in result.lower():
            result = re.sub(re.escape(word), phonetic, result, flags=re.IGNORECASE)
    return result


def _resolve_secret(name: str, default: str = "") -> str:
    val = os.getenv(name, "").strip()
    if val:
        return val
    try:
        from sync_daemon import _resolve_secret as rs
        return rs(name, default)
    except ImportError:
        return default


def _ensure_dirs():
    for d in (ANNOUNCER_DIR, CLIPS_DIR, ARCHIVE_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logging.warning("[Announcer] mkdir %s failed: %s", d, e)


def _atomic_write_json(path: Path, data, indent: int = 2):
    """Atomic JSON write via tempfile + rename."""
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _sanitize_player_id(raw: str) -> str:
    """Sanitize player ID to prevent path traversal. Only allow [a-z0-9_-]."""
    import re
    # Strip path separators and collapse to safe chars
    safe = re.sub(r'[^a-z0-9_-]', '', raw.lower().replace(' ', '-'))
    # Remove leading dots/dashes to prevent hidden files or relative paths
    safe = safe.lstrip('.-')
    return safe[:100] or 'unknown'


MAX_TTS_OUTPUT_BYTES = 10 * 1024 * 1024  # 10 MB cap on TTS output


def _read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return default


# ---------------------------------------------------------------------------
# TTS text sanitization
# ---------------------------------------------------------------------------

import re as _re

def _strip_markup_tags(text: str) -> str:
    """Remove custom TTS markup tags that would be spoken literally.

    Strips [breath], [pause:Xs], [pause:X.Xs] etc. and collapses extra
    whitespace.  Call this before passing script text to any provider that
    doesn't natively handle these markers.
    """
    text = _re.sub(r'\[breath\]', '', text, flags=_re.IGNORECASE)
    text = _re.sub(r'\[pause:[^\]]*\]', '', text)
    text = _re.sub(r'\(\s*(?:breath|breathe|inhale|exhale)\s*\)', '', text, flags=_re.IGNORECASE)
    text = _re.sub(r'<[^>]+>', '', text)        # strip any stray XML/SSML tags
    text = _re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def _tags_to_ssml(text: str, voice_name: str) -> str:
    """Convert custom markup tags to SSML <break> elements.

    Wraps the result in a <speak><voice> block suitable for providers
    that accept SSML (e.g. Edge TTS, Google Cloud TTS).
    """
    text = _re.sub(r'\[breath\]', '<break time="150ms"/>', text, flags=_re.IGNORECASE)
    text = _re.sub(
        r'\[pause:(\d+(?:\.\d+)?)s\]',
        lambda m: f'<break time="{int(float(m.group(1)) * 1000)}ms"/>',
        text,
    )
    text = _re.sub(r'\(\s*(?:breath|breathe|inhale|exhale)\s*\)', '<break time="150ms"/>', text, flags=_re.IGNORECASE)
    inner = _re.sub(r'\s{2,}', ' ', text).strip()
    return f'<speak><voice name="{voice_name}">{inner}</voice></speak>'


# ---------------------------------------------------------------------------
# TTS Providers
# ---------------------------------------------------------------------------

class TTSProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, voice_config: dict) -> bytes:
        """Return MP3 audio bytes for the given text."""

    @property
    @abstractmethod
    def name(self) -> str:  # pragma: no cover
        pass

    def available(self) -> bool:
        """Fast availability check (no synthesis). Override for key/package checks."""
        return True

    @property
    def max_concurrency(self) -> int:
        """How many renders this provider tolerates in parallel.

        Batch callers clamp their worker count to this.  Local providers have no
        meaningful limit; hosted ones do, and exceeding it returns 429.
        """
        return 8


class LocalVLLMTTS(TTSProvider):
    """Local FastAPI TTS service (announcer_api.py) for on-device inference."""

    @property
    def name(self) -> str:
        return "local_vllm"

    def synthesize(self, text: str, voice_config: dict) -> bytes:
        base_url = os.getenv("LOCAL_TTS_URL", "").rstrip("/")
        if not base_url:
            raise RuntimeError("LOCAL_TTS_URL not set")
        payload = {
            "text": text,
            "voice_design": {
                "pitch": -2.0,
                "energy": 1.3,
                "speaking_rate": 0.92,
                "emotion_exaggeration": 0.85,
                "speaker_style": "announcer",
            },
            "reference_audio_url": voice_config.get("reference_audio_url", ""),
            "reference_transcript": voice_config.get("reference_transcript", ""),
        }
        resp = requests.post(f"{base_url}/synthesize", json=payload, timeout=15, stream=True)
        if resp.status_code != 200:
            raise RuntimeError(f"Local TTS returned {resp.status_code}: {resp.text[:200]}")
        return resp.content


class ReplicateTTS(TTSProvider):
    """Qwen2.5-TTS-3B via Replicate API — Best Quality renderer."""

    # Configurable via REPLICATE_BEST_MODEL_ID env var to allow easy upgrades
    _DEFAULT_MODEL_SLUG = "qwen/qwen2.5-tts-3b"

    @property
    def _api_url(self) -> str:
        slug = os.getenv("REPLICATE_BEST_MODEL_ID", self._DEFAULT_MODEL_SLUG)
        return f"https://api.replicate.com/v1/models/{slug}/predictions"

    API_URL = ""  # unused — _api_url property takes precedence
    POLL_INTERVAL = 2.0
    MAX_POLL_SECONDS = 120

    @property
    def name(self) -> str:
        return "replicate_qwen25_tts_3b"

    def synthesize(self, text: str, voice_config: dict) -> bytes:
        token = _resolve_secret("REPLICATE_API_TOKEN")
        if not token:
            raise RuntimeError("REPLICATE_API_TOKEN not set")

        ref_audio = voice_config.get("reference_audio_url", "")
        ref_text = voice_config.get("reference_transcript", "")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "wait",
        }

        # Qwen2.5-TTS-3B supports voice_instruction for style steering
        input_payload: dict = {
            "text": text,
            "voice_instruction": STEITZER_VOICE_INSTRUCTION,
            "language": "en",
        }
        # Include ICL clone params when a reference clip is configured
        if ref_audio and ref_text:
            input_payload["mode"] = "clone"
            input_payload["reference_audio"] = ref_audio
            input_payload["reference_text"] = ref_text
        else:
            input_payload["mode"] = "design"

        payload = {"input": input_payload}

        resp = requests.post(self._api_url, json=payload, headers=headers, timeout=90)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Replicate returned {resp.status_code}: {resp.text[:300]}")

        result = resp.json()
        status = result.get("status", "")

        # If Prefer: wait worked, we get completed immediately
        if status == "succeeded":
            return self._download_output(result)

        # Otherwise poll for completion
        poll_url = result.get("urls", {}).get("get", "")
        if not poll_url:
            raise RuntimeError("No poll URL in Replicate response")

        start = time.monotonic()
        while time.monotonic() - start < self.MAX_POLL_SECONDS:
            time.sleep(self.POLL_INTERVAL)
            poll_resp = requests.get(poll_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
            poll_data = poll_resp.json()
            poll_status = poll_data.get("status", "")
            if poll_status == "succeeded":
                return self._download_output(poll_data)
            if poll_status in ("failed", "canceled"):
                err = poll_data.get("error", "Unknown error")
                raise RuntimeError(f"Replicate prediction failed: {err}")

        raise RuntimeError(f"Replicate prediction timed out after {self.MAX_POLL_SECONDS}s")

    def _download_output(self, result: dict) -> bytes:
        output = result.get("output")
        if not output:
            raise RuntimeError("Replicate returned no output")
        # Output can be a URL string or a list with one URL
        url = output if isinstance(output, str) else output[0]
        resp = requests.get(url, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to download audio from Replicate: {resp.status_code}")
        return resp.content


class Replicate06bTTS(ReplicateTTS):
    """Qwen3-TTS-0.6B via Replicate — Cloud Mirror for Quick Render failover.

    Uses *identical* ICL clone parameters (same Steitzer reference audio + transcript)
    so Quick Render fallback audio is indistinguishable in vocal character from Best Quality.
    Only the model size differs: 0.6B is faster and cheaper, not weaker in voice consistency.
    """

    # Override with the 0.6B model endpoint.  Configurable via REPLICATE_06B_MODEL_ID
    # in case Replicate renames the model slug.
    @property
    def _api_url(self) -> str:
        slug = os.getenv(
            "REPLICATE_06B_MODEL_ID",
            "qwen/qwen3-tts-0.6b-voicedesign",
        )
        return f"https://api.replicate.com/v1/models/{slug}/predictions"

    MAX_POLL_SECONDS = 30  # 0.6B is faster than 3B

    @property
    def name(self) -> str:
        return "replicate_qwen3_tts_0.6b"


# Deep, resonant male voice used for the stadium announcer.  "Brian" is a premade
# ElevenLabs voice, so it works on the free tier — library/professional voices
# return HTTP 402 without a paid plan.  Measured median F0 137 Hz (vs 167 Hz for
# "Adam"), the deepest premade option on the account.
# The previous default, EXAVITQu4vr4xnSDxMaL, is "Sarah" — a young female voice.
ANNOUNCER_ELEVENLABS_VOICE_ID = "nPczCjzI2devNBz1zQrb"


class ElevenLabsTTS(TTSProvider):
    """ElevenLabs TTS — reuses existing integration pattern."""

    # Free and starter plans allow 2 requests in parallel; more returns 429.
    _MAX_CONCURRENCY = int(os.getenv("ELEVENLABS_MAX_CONCURRENCY", "2"))
    _MAX_ATTEMPTS = 4

    @property
    def name(self) -> str:
        return "elevenlabs"

    @property
    def max_concurrency(self) -> int:
        return max(1, self._MAX_CONCURRENCY)

    def synthesize(self, text: str, voice_config: dict) -> bytes:
        api_key = _resolve_secret("ELEVENLABS_API_KEY")
        voice_id = (
            voice_config.get("elevenlabs_voice_id", "")
            or _resolve_secret("ELEVENLABS_VOICE_ID")
            or os.getenv("ELEVENLABS_DEFAULT_VOICE_ID", "").strip()
            or ANNOUNCER_ELEVENLABS_VOICE_ID
        )
        model_id = (
            voice_config.get("model_id")
            or os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
        )

        if not api_key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        payload = {
            "text": text,
            "model_id": model_id,
            # Announcer delivery: low-ish stability + high style gives the dramatic
            # swing the Halo-style read needs.  0.20 was low enough that repeat
            # renders of the same player drifted in character; 0.30 holds.
            "voice_settings": voice_config.get("voice_settings") or {
                "stability": 0.30,
                "similarity_boost": 0.85,
                "style": 0.75,
                "use_speaker_boost": True,
            },
        }
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        }
        # Retry the transient failures — a rate-limit or a 5xx mid-batch used to
        # abandon that player with no clip at all.
        for attempt in range(1, self._MAX_ATTEMPTS + 1):
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            if resp.status_code == 200:
                return resp.content
            if resp.status_code not in (429, 500, 502, 503, 504) or attempt == self._MAX_ATTEMPTS:
                raise RuntimeError(f"ElevenLabs returned {resp.status_code}: {resp.text[:300]}")
            delay = float(resp.headers.get("retry-after") or 2 ** attempt)
            logging.warning("[Announcer] ElevenLabs %s (attempt %d/%d) — retrying in %.1fs",
                            resp.status_code, attempt, self._MAX_ATTEMPTS, delay)
            time.sleep(delay)
        raise RuntimeError("ElevenLabs: exhausted retries")  # pragma: no cover


class EdgeTTSProvider(TTSProvider):
    """Microsoft Edge TTS via edge-tts package — free, no API key, neural voices.

    Install: pip install edge-tts
    Voices tried in order: en-US-GuyNeural (deep), en-US-DavisNeural (clear male).
    Supports SSML pause markup natively.
    """

    _VOICES = ["en-US-GuyNeural", "en-US-DavisNeural", "en-US-ChristopherNeural"]

    @property
    def name(self) -> str:
        return "edge_tts"

    def available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            return False

    def synthesize(self, text: str, voice_config: dict) -> bytes:
        try:
            import edge_tts
            import asyncio
        except ImportError:
            raise RuntimeError("edge-tts not installed. Run: pip install edge-tts")

        voice = voice_config.get("edge_tts_voice", self._VOICES[0])
        # Convert markup to SSML for natural pausing
        ssml = _tags_to_ssml(text, voice)

        async def _fetch() -> bytes:
            buf = io.BytesIO()
            communicate = edge_tts.Communicate(ssml, voice)
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            return buf.getvalue()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, _fetch())
                    return future.result(timeout=30)
            return loop.run_until_complete(_fetch())
        except RuntimeError:
            return asyncio.run(_fetch())


class KokoroTTSProvider(TTSProvider):
    """Kokoro-82M via kokoro-onnx — local, MIT license, ARM64-compatible, no GPU needed.

    Install: pip install kokoro-onnx
    Model auto-downloads (~300 MB) on first use.
    Voice: am_adam (deep American male announcer).
    """

    _VOICE = "am_adam"

    @property
    def name(self) -> str:
        return "kokoro_onnx"

    def available(self) -> bool:
        try:
            import kokoro_onnx  # noqa: F401
            return True
        except ImportError:
            return False

    def _to_mp3(self, samples, sample_rate: int) -> bytes:
        """Convert numpy float32 samples to MP3 bytes via ffmpeg, or WAV fallback."""
        import subprocess
        import tempfile
        import numpy as np

        samples_int16 = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
            tmp_wav_path = Path(tmp_wav.name)
        with wave.open(str(tmp_wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(samples_int16.tobytes())

        mp3_path = tmp_wav_path.with_suffix(".mp3")
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(tmp_wav_path),
                 "-codec:a", "libmp3lame", "-q:a", "2", str(mp3_path)],
                capture_output=True, timeout=30,
            )
            if result.returncode == 0 and mp3_path.exists():
                mp3_bytes = mp3_path.read_bytes()
                return mp3_bytes
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        finally:
            for p in (tmp_wav_path, mp3_path):
                try:
                    p.unlink()
                except OSError:
                    pass

        # ffmpeg unavailable — return raw WAV bytes
        return tmp_wav_path.read_bytes() if tmp_wav_path.exists() else b""

    def synthesize(self, text: str, voice_config: dict) -> bytes:
        try:
            from kokoro_onnx import Kokoro
        except ImportError:
            raise RuntimeError("kokoro-onnx not installed. Run: pip install kokoro-onnx")

        clean = _strip_markup_tags(text)
        voice = voice_config.get("kokoro_voice", self._VOICE)
        speed = float(voice_config.get("kokoro_speed", 0.9))

        kokoro = Kokoro.from_pretrained()
        samples, sample_rate = kokoro.create(clean, voice=voice, speed=speed, lang="en-us")
        return self._to_mp3(samples, sample_rate)


class GoogleCloudTTSProvider(TTSProvider):
    """Google Cloud TTS — free tier: 1M Neural2 chars/month, 4M Standard chars/month.

    Requires GOOGLE_API_KEY or GOOGLE_APPLICATION_CREDENTIALS in env.
    Voice: en-US-Neural2-J (deep male, announcer-adjacent).
    Install: pip install google-cloud-texttospeech
    """

    _VOICE_NAME = "en-US-Neural2-J"
    _LANGUAGE = "en-US"

    @property
    def name(self) -> str:
        return "google_cloud_tts"

    def available(self) -> bool:
        try:
            from google.cloud import texttospeech  # noqa: F401
            return bool(
                os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
                or _resolve_secret("GOOGLE_API_KEY")
            )
        except ImportError:
            return False

    def synthesize(self, text: str, voice_config: dict) -> bytes:
        try:
            from google.cloud import texttospeech
        except ImportError:
            raise RuntimeError(
                "google-cloud-texttospeech not installed. Run: pip install google-cloud-texttospeech"
            )

        api_key = _resolve_secret("GOOGLE_API_KEY")
        client_kwargs = {}
        if api_key and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip():
            from google.api_core.gapic_v1.client_info import ClientInfo
            client_kwargs["client_options"] = {"api_key": api_key}

        client = texttospeech.TextToSpeechClient(**client_kwargs)

        voice_name = voice_config.get("google_tts_voice", self._VOICE_NAME)
        clean = _strip_markup_tags(text)

        synthesis_input = texttospeech.SynthesisInput(text=clean)
        voice = texttospeech.VoiceSelectionParams(
            language_code=self._LANGUAGE,
            name=voice_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=0.90,
            pitch=-2.0,
        )

        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        return response.audio_content


class MockTTS(TTSProvider):
    """Generates a silent 2-second WAV for testing without API keys."""

    @property
    def name(self) -> str:
        return "mock"

    def synthesize(self, text: str, voice_config: dict) -> bytes:
        buf = io.BytesIO()
        sample_rate = 22050
        duration = 2
        n_samples = sample_rate * duration
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(struct.pack(f"<{n_samples}h", *([0] * n_samples)))
        return buf.getvalue()


def _has_replicate_voice_ref() -> bool:
    """True only when REPLICATE_API_TOKEN + ANNOUNCER_VOICE_REF_URL are both set."""
    return bool(
        _resolve_secret("REPLICATE_API_TOKEN") and
        os.getenv("ANNOUNCER_VOICE_REF_URL", "").strip()
    )


# Ordered provider registry — probed top-to-bottom at render time.
# Best Quality chain (Mac/cloud):  LocalVLLM → Replicate3B → ElevenLabs → EdgeTTS → Kokoro → GoogleCloud → Mock
# Quick chain (Pi-side):           LocalVLLM → Replicate0.6B → ElevenLabs → EdgeTTS → Kokoro → GoogleCloud → Mock
#
# ElevenLabs sits above EdgeTTS because it is the only key-free-of-Replicate path
# that actually delivers the stadium-announcer read.  EdgeTTS/Kokoro/GoogleCloud
# accept no style steering, so they produce a flat neutral narration — fine as a
# fallback, wrong as the default.

def _build_provider_chain(quick: bool = False) -> list[TTSProvider]:
    chain: list[TTSProvider] = []
    if os.getenv("LOCAL_TTS_URL", "").strip():
        chain.append(LocalVLLMTTS())
    if _has_replicate_voice_ref():
        chain.append(Replicate06bTTS() if quick else ReplicateTTS())
    if _resolve_secret("ELEVENLABS_API_KEY"):
        chain.append(ElevenLabsTTS())
    chain.append(EdgeTTSProvider())
    chain.append(KokoroTTSProvider())
    chain.append(GoogleCloudTTSProvider())
    chain.append(MockTTS())
    return chain


def probe_tts_providers() -> list[dict]:
    """Test every provider in the chain and return their availability status.

    Each entry: {name, available, selected, reason}
    The first available provider is marked selected=True.
    This is the source of truth for GET /api/announcer/tts-probe.
    """
    chain = _build_provider_chain(quick=False)
    results = []
    selected = False
    for p in chain:
        try:
            ok = p.available()
            reason = "ok" if ok else "not configured"
        except Exception as e:
            ok = False
            reason = str(e)[:120]
        entry = {"name": p.name, "available": ok, "selected": False, "reason": reason}
        if ok and not selected:
            entry["selected"] = True
            selected = True
        results.append(entry)
    return results


def get_tts_provider() -> TTSProvider:
    """Return the best available TTS provider for Best Quality renders.

    Walks the provider chain in priority order and returns the first available one.
    Priority: LocalVLLM → Replicate 3B → ElevenLabs → EdgeTTS → Kokoro → GoogleCloud → Mock
    """
    for provider in _build_provider_chain(quick=False):
        if provider.available():
            logging.info("[Announcer] TTS provider selected: %s", provider.name)
            return provider
    return MockTTS()


def get_quick_tts_provider() -> TTSProvider:
    """Return provider for Quick Render (Pi-side, speed-optimised).

    Priority: LocalVLLM → Replicate 0.6B → ElevenLabs → EdgeTTS → Kokoro → GoogleCloud → Mock
    """
    for provider in _build_provider_chain(quick=True):
        if provider.available():
            logging.info("[Announcer] Quick TTS provider selected: %s", provider.name)
            return provider
    return MockTTS()


def check_provider_health() -> dict:
    """Liveness check for each TTS provider. Used by /api/announcer/provider-health."""
    import requests as _req
    probe = probe_tts_providers()
    results = {p["name"]: p["available"] for p in probe}
    results["selected"] = next((p["name"] for p in probe if p.get("selected")), "mock")

    # Deep ping for network providers
    local_url = os.getenv("LOCAL_TTS_URL", "").strip()
    if local_url:
        try:
            r = _req.get(f"{local_url}/health", timeout=3)
            results["local_tts_ping"] = r.status_code == 200
        except Exception:
            results["local_tts_ping"] = False

    replicate_token = _resolve_secret("REPLICATE_API_TOKEN")
    if replicate_token:
        try:
            r = _req.get(
                "https://api.replicate.com/v1/account",
                headers={"Authorization": f"Bearer {replicate_token}"},
                timeout=5,
            )
            results["replicate_ping"] = r.status_code == 200
        except Exception:
            results["replicate_ping"] = False

    el_key = _resolve_secret("ELEVENLABS_API_KEY")
    if el_key:
        try:
            r = _req.get(
                "https://api.elevenlabs.io/v1/user",
                headers={"xi-api-key": el_key},
                timeout=5,
            )
            results["elevenlabs_ping"] = r.status_code == 200
        except Exception:
            results["elevenlabs_ping"] = False

    return results


# ---------------------------------------------------------------------------
# Voice Profiles
# ---------------------------------------------------------------------------

# All premade ElevenLabs voices.  The account is on the free tier, where designed
# voices (HTTP 403) and cloning (402) are unavailable — and cloning the real Halo
# actor would be off the table regardless.  "Halo Announcer" is the closest
# legitimate match to that delivery: the deepest premade voice, the model/settings
# with the widest measured pitch swing (182 Hz range on multilingual_v2 vs 67 on
# v3), a two-semitone drop in the stadium chain, and the scripted cadence.
VOICE_PROFILES: list[dict] = [
    {
        "id": "halo", "name": "Halo Announcer",
        "tagline": "Deep, booming, larger than life — the default",
        "elevenlabs_voice_id": "nPczCjzI2devNBz1zQrb", "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.30, "similarity_boost": 0.85, "style": 0.75, "use_speaker_boost": True},
        "pitch_semitones": -2.0,
    },
    {
        "id": "brian", "name": "Brian",
        "tagline": "Deep and resonant, straight read",
        "elevenlabs_voice_id": "nPczCjzI2devNBz1zQrb", "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.85, "style": 0.45, "use_speaker_boost": True},
        "pitch_semitones": 0.0,
    },
    {
        "id": "callum", "name": "Callum",
        "tagline": "Gravel and grit",
        "elevenlabs_voice_id": "N2lVS1w4EtoT3dr4eOWO", "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.35, "similarity_boost": 0.85, "style": 0.65, "use_speaker_boost": True},
        "pitch_semitones": 0.0,
    },
    {
        "id": "george", "name": "George",
        "tagline": "Warm storyteller",
        "elevenlabs_voice_id": "JBFqnCBsd6RMkjVDRZzb", "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.40, "similarity_boost": 0.85, "style": 0.55, "use_speaker_boost": True},
        "pitch_semitones": 0.0,
    },
    {
        "id": "adam", "name": "Adam",
        "tagline": "Classic PA announcer",
        "elevenlabs_voice_id": "pNInz6obpgDQGcFmaJgB", "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.40, "similarity_boost": 0.85, "style": 0.60, "use_speaker_boost": True},
        "pitch_semitones": 0.0,
    },
]

VOICE_SELECTION_FILE = ANNOUNCER_DIR / "voice_selection.json"
VOICE_SAMPLES_DIR = ANNOUNCER_DIR / "voice_samples"
VOICE_SAMPLE_TEXT = (
    "[breath] Now batting for your Sharks... [pause:0.4s] "
    "NUMBEEEER seven... [pause:0.3s] your leadoff hitter!"
)


def get_voice_profile(profile_id: str | None) -> dict | None:
    for p in VOICE_PROFILES:
        if p["id"] == profile_id:
            return p
    return None


def get_default_voice_profile_id() -> str:
    sel = _read_json(VOICE_SELECTION_FILE, default=None)
    pid = sel.get("default_profile_id") if isinstance(sel, dict) else None
    return pid if get_voice_profile(pid) else VOICE_PROFILES[0]["id"]


def load_voice_profiles() -> list[dict]:
    default_id = get_default_voice_profile_id()
    return [{**p, "is_default": p["id"] == default_id} for p in VOICE_PROFILES]


def get_default_voice_profile() -> dict:
    return get_voice_profile(get_default_voice_profile_id()) or VOICE_PROFILES[0]


def set_default_voice_profile(profile_id: str) -> dict:
    profile = get_voice_profile(profile_id)
    if not profile:
        raise ValueError(f"Unknown voice profile: {profile_id}")
    _ensure_dirs()
    _atomic_write_json(VOICE_SELECTION_FILE, {"default_profile_id": profile_id})
    return profile


def resolve_voice_profile(player: dict) -> dict:
    """Per-player override if set, else the team default."""
    return get_voice_profile(player.get("voice_profile_id")) or get_default_voice_profile()


def render_voice_sample(profile_id: str) -> Path:
    """Render (once) a short sample line in the given voice, through the full
    stadium chain so it sounds like a real clip.  Cached on disk."""
    profile = get_voice_profile(profile_id)
    if not profile:
        raise ValueError(f"Unknown voice profile: {profile_id}")
    VOICE_SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    out = VOICE_SAMPLES_DIR / f"{profile_id}.mp3"
    if out.exists() and out.stat().st_size > 1000:
        return out
    provider = get_tts_provider()
    text = VOICE_SAMPLE_TEXT if isinstance(provider, EdgeTTSProvider) else _strip_markup_tags(VOICE_SAMPLE_TEXT)
    audio = provider.synthesize(text, profile)
    try:
        archive_and_transcode(audio, f"sample-{profile_id}", archive=False,
                              pitch_semitones=float(profile.get("pitch_semitones") or 0.0),
                              out_mp3=out)
    except Exception as e:
        logging.warning("[Announcer] sample wrap failed (%s) — saving raw", e)
        out.write_bytes(audio)
    return out


# ---------------------------------------------------------------------------
# Announcer Roster
# ---------------------------------------------------------------------------

_ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven",
         "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
         "fifteen", "sixteen", "seventeen", "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty",
         "sixty", "seventy", "eighty", "ninety")


def _number_to_word(num: str) -> str:
    """Convert a jersey number to the words an announcer would say.

    Jersey numbers run 0-99, and "00" is a distinct jersey from "0", so the
    leading-zero form is spoken as "double-zero".  Anything that is not a
    plain number (blank, "TBD") is returned unchanged for the caller to handle.
    """
    raw = str(num).strip()
    if not raw.isdigit():
        return raw
    if raw == "00":
        return "double-zero"
    n = int(raw)
    if n >= 100:
        return raw
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] if ones == 0 else f"{_TENS[tens]}-{_ONES[ones]}"


_HALO_SCRIPTS: dict[str, str] = {
    "triple_rbi":    "Hat trick! Three runs batted in!",
    "quad_rbi":      "Grand Slam Hero! Four RBI!",
    "3_strikeouts":  "Strikeout artist! Three up, three down!",
    "4_strikeouts":  "She is ON FIRE! Four strikeouts!",
    "5_strikeouts":  "UNTOUCHABLE! Five strikeouts!",
    "grand_slam":    "Grand. Slam. QUEEN!",
    "cycle":         "PERFECTION! She hit for the cycle!",
}

# Ballpark DJ reads "Now batting for the Savannah Seadogs..."; same idea here.
ANNOUNCER_TEAM_PHRASE = os.getenv("ANNOUNCER_TEAM_PHRASE", "").strip() or "your Sharks"

STEITZER_VOICE_INSTRUCTION = (
    "Speak like Jeff Steitzer, the iconic Halo video game announcer. "
    "Use a deep, booming, dramatic stadium announcer voice with elongated emphasis on key words. "
    "Draw out 'Now batting' with gravitas, pause before the number, then announce the name "
    "with rising energy and excitement. This is for a youth softball game — keep it celebratory and fun."
)


def build_situational_announcement(player: dict, game_context: dict | None = None) -> str:
    """Build a game-state-aware TTS script with Halo-style achievements.

    game_context shape:
      {"inning": int, "outs": int, "bases": [bool, bool, bool],
       "score_us": int, "score_them": int, "achievement": str|None}
    """
    first = (player.get("first") or "").strip()
    last = (player.get("last") or "").strip()
    number = str(player.get("number") or "").strip()
    phonetic_hint = (player.get("phonetic_hint") or "").strip()
    tts_instruction = (player.get("tts_instruction") or "").strip()

    name = phonetic_hint if phonetic_hint else f"{first} {last}".strip()
    name = _apply_phonetics(name)
    num_word = _number_to_word(number)

    ctx = game_context or {}
    achievement = ctx.get("achievement") or ""
    bases = ctx.get("bases") or [False, False, False]
    outs = int(ctx.get("outs") or 0)
    score_us = int(ctx.get("score_us") or 0)
    score_them = int(ctx.get("score_them") or 0)
    bases_loaded = all(bases[:3]) if len(bases) >= 3 else False
    high_stakes = bases_loaded and outs >= 2
    trailing = score_them > score_us

    if achievement and achievement in _HALO_SCRIPTS:
        halo_call = _HALO_SCRIPTS[achievement]
        script = f"[breath] {halo_call} [pause:0.5s] That's number {num_word}... {name}!"
    elif high_stakes:
        urgency = "with the game on the line" if trailing else "with the bases loaded"
        script = (
            f"[breath] NOW BATTING for {ANNOUNCER_TEAM_PHRASE}... [pause:0.5s] {urgency}... "
            f"[pause:0.4s] NUMBEEEER {num_word}... [pause:0.3s] {name}!"
        )
    elif bases_loaded:
        script = (
            f"[breath] Bases loaded... [pause:0.4s] "
            f"NOW batting for {ANNOUNCER_TEAM_PHRASE}... [pause:0.3s] NUMBEEEER {num_word}... [pause:0.3s] {name}!"
        )
    else:
        script = (
            f"[breath] Now batting for {ANNOUNCER_TEAM_PHRASE}... [pause:0.4s] "
            f"NUMBEEEER {num_word}... [pause:0.3s] {name}!"
        )

    if tts_instruction and not achievement:
        script = f"{tts_instruction}. {script}"

    return script


def build_announcement_text(player: dict, game_context: dict | None = None) -> str:
    """Build the TTS announcement text for a player.

    Delegates to build_situational_announcement when game_context is provided.
    """
    return build_situational_announcement(player, game_context)


def _bootstrap_roster_from_team() -> list[dict]:
    """Create initial announcer roster from existing team.json data."""
    team_files = [
        DATA_DIR / "sharks" / "team_enriched.json",
        DATA_DIR / "sharks" / "team_merged.json",
        DATA_DIR / "sharks" / "team.json",
    ]
    team = None
    for tf in team_files:
        if tf.exists():
            team = _read_json(tf)
            break

    if not isinstance(team, dict):
        return []

    roster = team.get("roster", [])
    if not isinstance(roster, list):
        return []

    announcer_roster = []
    for p in roster:
        if not isinstance(p, dict):
            continue
        first = (p.get("first") or "").strip()
        last = (p.get("last") or "").strip()
        number = str(p.get("number") or "").strip()
        if not first:
            continue

        player_id = _sanitize_player_id(f"{number}-{first}-{last}")
        entry = {
            "id": player_id,
            "first": first,
            "last": last,
            "number": number,
            "phonetic_hint": "",
            "tts_instruction": "",
            "walkup_song_url": "",
            "intro_timestamp": 5.0,
            "announcer_audio_url": "",
            "status": "pending",
            "is_active": True,
            "rendered_at": "",
            "error_message": "",
        }
        announcer_roster.append(entry)

    return announcer_roster


def reconcile_roster_with_team(roster: list[dict]) -> tuple[list[dict], bool]:
    """Fold current team.json membership into an existing announcer roster.

    Returns (roster, changed).  Players on the team but missing from the roster
    are appended as pending; players no longer on the team are deactivated
    rather than deleted, so their phonetic hints, walk-up song and rendered
    clips survive if they come back.  Everything else is left alone — this must
    never clobber a hand-edited phonetic_hint or a rendered clip URL.
    """
    team_roster = _bootstrap_roster_from_team()
    if not team_roster:
        return roster, False          # no team data — leave the roster untouched

    team_ids = {p["id"] for p in team_roster}
    existing = {p.get("id") for p in roster}
    changed = False

    for player in team_roster:
        if player["id"] not in existing:
            roster.append(player)
            changed = True
            logging.info("[Announcer] Added new player to roster: %s", player["id"])

    for player in roster:
        on_team = player.get("id") in team_ids
        if player.get("is_active", True) != on_team:
            player["is_active"] = on_team
            changed = True
            logging.info("[Announcer] %s player %s",
                         "Reactivated" if on_team else "Deactivated", player.get("id"))

    return roster, changed


def load_announcer_roster() -> list[dict]:
    """Load the announcer roster, reconciling it against current team.json.

    The roster used to be bootstrapped once and never revisited, so a mid-season
    signing never got an announcement and players who left kept theirs.
    """
    try:
        _ensure_dirs()
    except OSError as e:
        logging.warning("[Announcer] Could not create announcer dirs: %s", e)

    roster = _read_json(ROSTER_FILE, default=None)
    if isinstance(roster, list) and roster:
        roster, changed = reconcile_roster_with_team(roster)
        if changed:
            # Re-read under the lock so this write can't clobber a status update
            # that another worker landed between our read and now.
            with _ROSTER_LOCK:
                fresh = _read_json(ROSTER_FILE, default=None)
                roster, _ = reconcile_roster_with_team(fresh if isinstance(fresh, list) else roster)
                try:
                    _atomic_write_json(ROSTER_FILE, roster)
                except OSError as e:
                    logging.warning("[Announcer] Could not persist reconciled roster: %s", e)
        return roster

    # Bootstrap from team data
    roster = _bootstrap_roster_from_team()
    if roster:
        try:
            _atomic_write_json(ROSTER_FILE, roster)
            logging.info("[Announcer] Bootstrapped roster with %d players", len(roster))
        except OSError as e:
            logging.warning("[Announcer] Could not persist bootstrapped roster (permission issue): %s", e)
    return roster or []


def save_announcer_roster(roster: list[dict]):
    _ensure_dirs()
    _atomic_write_json(ROSTER_FILE, roster)


def get_player_by_id(player_id: str) -> dict | None:
    for p in load_announcer_roster():
        if p.get("id") == player_id:
            return p
    return None


def update_player(player_id: str, updates: dict) -> dict | None:
    """Apply updates to one player and persist the roster.

    Holds _ROSTER_LOCK across the read-modify-write: prerender runs renders on a
    thread pool (--concurrency 2-4), and without the lock two threads finishing
    together would each write back a roster built before the other's update,
    silently dropping one player's status and clip URL.
    """
    with _ROSTER_LOCK:
        roster = load_announcer_roster()
        for i, p in enumerate(roster):
            if p.get("id") == player_id:
                roster[i].update(updates)
                save_announcer_roster(roster)
                return roster[i]
    return None


# ---------------------------------------------------------------------------
# Render Operations
# ---------------------------------------------------------------------------

def archive_and_transcode(audio_bytes: bytes, player_id: str,
                          archive: bool = True, pitch_semitones: float = 0.0,
                          out_mp3: Path | None = None) -> tuple[Path | None, Path]:
    """Run the Stadium Wrap and write the MP3; optionally keep a FLAC master.

    FFmpeg Stadium Wrap chain (Best Quality):
      compand      → broadcast hard compression (attack 10ms, decay 200ms)
      equalizer    → +4dB low shelf at 150 Hz (Steitzer sub-bass boom)
      extrastereo  → m=2.5 stereo widening (fills the stadium)

    Returns (flac_path or None, mp3_path). Raises RuntimeError if FFmpeg is not in PATH.
    """
    import subprocess
    import tempfile

    ts = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
    safe_id = _sanitize_player_id(player_id)

    if out_mp3 is not None:
        mp3_path = out_mp3
    else:
        clips_player_dir = CLIPS_DIR / safe_id
        clips_player_dir.mkdir(parents=True, exist_ok=True)
        mp3_path = clips_player_dir / f"{ts}.mp3"

    flac_path: Path | None = None
    if archive:
        archive_player_dir = ARCHIVE_DIR / safe_id
        archive_player_dir.mkdir(parents=True, exist_ok=True)
        flac_path = archive_player_dir / f"{ts}.flac"

    # Detect input format from magic bytes
    is_mp3 = audio_bytes[:3] == b"ID3" or (len(audio_bytes) >= 2 and audio_bytes[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"))
    suffix = ".mp3" if is_mp3 else ".wav"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = Path(tmp.name)

    try:
        # Pass 1 (best only) — encode to 24-bit/48kHz FLAC archive master
        if archive:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(tmp_path),
                 "-ar", "48000", "-c:a", "flac", "-sample_fmt", "s32",
                 str(flac_path)],
                capture_output=True, timeout=60,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"FFmpeg FLAC encode failed: {result.stderr.decode(errors='replace')[:300]}"
                )
        wrap_input = flac_path if archive else tmp_path

        # Pass 2 — Stadium Wrap filter chain → 192kbps MP3
        # Splits signal: dry path + reverb path, mixed 80/20
        # NOTE: two syntax errors used to live in this graph and made every
        # "best" render fall through to the raw-bytes path below:
        #   - `equalizer=...:t=l` — `t` is an alias for `width_type`, whose legal
        #     values are h/q/o/s/k.  There is no `l`, and `equalizer` is a peaking
        #     filter anyway; a low shelf is the `bass` filter.
        #   - `amix=...:weights=0.8:0.2` — `weights` takes one space-separated
        #     string, so the `:0.2` was parsed as a second option name.
        # Pitch drop (Halo profile): resample trick, then restore tempo.  Core
        # filters only — rubberband is not in the Pi's ffmpeg build.
        pitch = ""
        if pitch_semitones:
            ratio = 2 ** (pitch_semitones / 12.0)
            pitch = f"aresample=48000,asetrate={int(48000 * ratio)},aresample=48000,atempo={1 / ratio:.4f},"
        filtergraph = (
            "[0:a]" + pitch +
            "compand=attacks=0.01:decays=0.2"
            ":points=-80/-80|-45/-30|-27/-20|0/-13:gain=6,"
            "bass=f=150:width_type=o:width=2:g=4"
            "[processed];"
            "[processed]asplit=2[dry][wet];"
            "[wet]aecho=0.8:1.0:50|75|100:0.4|0.3|0.2[rev];"
            "[dry][rev]amix=inputs=2:weights=0.8 0.2,"
            "extrastereo=m=2.5[out]"
        )
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(wrap_input),
             "-filter_complex", filtergraph,
             "-map", "[out]",
             "-ar", "48000", "-ac", "2",
             "-c:a", "libmp3lame", "-q:a", "2",
             str(mp3_path)],
            capture_output=True, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg Stadium Wrap failed: {result.stderr.decode(errors='replace')[:300]}"
            )
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    logging.info(
        "[Announcer] archive_and_transcode: %s → %s MP3 %dkB",
        player_id,
        f"FLAC {flac_path.stat().st_size // 1024}kB +" if flac_path else "(no archive)",
        mp3_path.stat().st_size // 1024,
    )
    return flac_path, mp3_path


def render_player_audio(player_id: str, game_context: dict | None = None,
                        quality: str = "best") -> dict:
    """Render TTS audio for a single player. Returns updated player dict."""
    player = get_player_by_id(player_id)
    if not player:
        raise ValueError(f"Player not found: {player_id}")

    update_player(player_id, {"status": "rendering", "error_message": ""})

    try:
        provider = get_quick_tts_provider() if quality == "quick" else get_tts_provider()
        voice = resolve_voice_profile(player)
        raw_text = build_announcement_text(player, game_context)
        # EdgeTTS handles SSML natively; all others receive stripped plain text.
        # This prevents [breath] / [pause:Xs] from being spoken literally.
        text = raw_text if isinstance(provider, EdgeTTSProvider) else _strip_markup_tags(raw_text)
        audio_bytes = provider.synthesize(text, voice)

        if len(audio_bytes) > MAX_TTS_OUTPUT_BYTES:
            raise RuntimeError(f"TTS output too large ({len(audio_bytes)} bytes, max {MAX_TTS_OUTPUT_BYTES})")

        # Stadium Wrap on every render; the FLAC archive master is best-only.
        # Quick used to skip the wrap entirely — and on the Pi, quick is the
        # only path a coach's Render button can take, so live clips were flat.
        safe_id = _sanitize_player_id(player_id)
        try:
            _, mp3_path = archive_and_transcode(
                audio_bytes, player_id, archive=(quality == "best"),
                pitch_semitones=float(voice.get("pitch_semitones") or 0.0))
            clip_url = f"/announcer-clips/{safe_id}/{mp3_path.name}"
        except Exception as e:
            # FFmpeg not available (e.g., dev environment) — fall back to raw MP3
            logging.warning("[Announcer] archive_and_transcode failed (%s) — saving raw bytes", e)
            ts = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
            player_clip_dir = CLIPS_DIR / safe_id
            player_clip_dir.mkdir(parents=True, exist_ok=True)
            clip_path = player_clip_dir / f"{ts}.mp3"
            clip_path.write_bytes(audio_bytes)
            clip_url = f"/announcer-clips/{safe_id}/{ts}.mp3"

        updated = update_player(player_id, {
            "status": "ready",
            "announcer_audio_url": clip_url,
            "rendered_at": datetime.now(ET).isoformat(),
            "render_quality": quality,
            "voice_rendered": voice["id"],
            "error_message": "",
        })
        logging.info("[Announcer] Rendered %s via %s (%d bytes, quality=%s)",
                     player_id, provider.name, len(audio_bytes), quality)
        return updated or player

    except Exception as e:
        logging.error("[Announcer] Render failed for %s: %s", player_id, e)
        update_player(player_id, {
            "status": "error",
            "error_message": str(e)[:500],
        })
        raise


def render_all_pending() -> dict:
    """Render audio for all active players with status != ready. Returns summary."""
    roster = load_announcer_roster()
    active = [p for p in roster if p.get("is_active") and p.get("status") != "ready"]
    results = {"total": len(active), "success": 0, "failed": 0, "errors": []}

    for p in active:
        try:
            render_player_audio(p["id"])
            results["success"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({"player_id": p["id"], "error": str(e)[:200]})

    return results


def get_roster_stats() -> dict:
    """Return summary counts of roster statuses."""
    roster = load_announcer_roster()
    active = [p for p in roster if p.get("is_active")]
    return {
        "total": len(active),
        "ready": sum(1 for p in active if p.get("status") == "ready"),
        "pending": sum(1 for p in active if p.get("status") in ("pending", "rendering")),
        "error": sum(1 for p in active if p.get("status") == "error"),
    }
