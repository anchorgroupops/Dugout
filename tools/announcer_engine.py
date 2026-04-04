"""Announcer TTS Engine — dual-provider voice synthesis for walk-up announcements.

Providers:
  1. Replicate Qwen3-TTS (clone mode) — primary if REPLICATE_API_TOKEN is set
  2. ElevenLabs — fallback using existing integration
  3. Mock — silent placeholder when no API keys configured (dev/testing)

Data stored in data/sharks/announcer/:
  - roster.json       — player announcer metadata
  - voice_profiles.json — reference voice configs
  - clips/{player_id}/{timestamp}.mp3 — rendered audio
"""
from __future__ import annotations

import io
import json
import logging
import os
import struct
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
ROSTER_FILE = ANNOUNCER_DIR / "roster.json"
VOICE_PROFILES_FILE = ANNOUNCER_DIR / "voice_profiles.json"

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
    ANNOUNCER_DIR.mkdir(parents=True, exist_ok=True)
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)


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
# TTS Providers
# ---------------------------------------------------------------------------

class TTSProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, voice_config: dict) -> bytes:
        """Return MP3 audio bytes for the given text."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass


class ReplicateTTS(TTSProvider):
    """Qwen3-TTS via Replicate API in clone mode."""

    API_URL = "https://api.replicate.com/v1/models/qwen/qwen3-tts/predictions"
    POLL_INTERVAL = 2.0
    MAX_POLL_SECONDS = 120

    @property
    def name(self) -> str:
        return "replicate_qwen3_tts"

    def synthesize(self, text: str, voice_config: dict) -> bytes:
        token = _resolve_secret("REPLICATE_API_TOKEN")
        if not token:
            raise RuntimeError("REPLICATE_API_TOKEN not set")

        ref_audio = voice_config.get("reference_audio_url", "")
        ref_text = voice_config.get("reference_transcript", "")
        if not ref_audio or not ref_text:
            raise RuntimeError("Voice profile missing reference_audio_url or reference_transcript")

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
            }
        }

        resp = requests.post(self.API_URL, json=payload, headers=headers, timeout=90)
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


class ElevenLabsTTS(TTSProvider):
    """ElevenLabs TTS — reuses existing integration pattern."""

    @property
    def name(self) -> str:
        return "elevenlabs"

    def synthesize(self, text: str, voice_config: dict) -> bytes:
        api_key = _resolve_secret("ELEVENLABS_API_KEY")
        voice_id = (
            voice_config.get("elevenlabs_voice_id", "")
            or _resolve_secret("ELEVENLABS_VOICE_ID")
            or os.getenv("ELEVENLABS_DEFAULT_VOICE_ID", "").strip()
            or "EXAVITQu4vr4xnSDxMaL"  # default fallback
        )
        model_id = os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")

        if not api_key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": 0.20,
                "similarity_boost": 0.90,
                "style": 0.70,
                "use_speaker_boost": True,
            },
        }
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"ElevenLabs returned {resp.status_code}: {resp.text[:300]}")
        return resp.content


class MockTTS(TTSProvider):
    """Generates a silent 2-second MP3-like WAV for testing without API keys."""

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


def get_tts_provider() -> TTSProvider:
    """Return the best available TTS provider."""
    if _resolve_secret("REPLICATE_API_TOKEN"):
        return ReplicateTTS()
    if _resolve_secret("ELEVENLABS_API_KEY"):
        return ElevenLabsTTS()
    logging.info("[Announcer] No TTS API keys configured — using mock provider")
    return MockTTS()


# ---------------------------------------------------------------------------
# Voice Profiles
# ---------------------------------------------------------------------------

DEFAULT_VOICE_PROFILE = {
    "id": "default-steitzer",
    "name": "Jeff Steitzer (Stadium Announcer)",
    "reference_audio_url": os.getenv("ANNOUNCER_VOICE_REF_URL", ""),
    "reference_transcript": os.getenv("ANNOUNCER_VOICE_REF_TEXT", "Now batting, number seven, Sophia!"),
    "description": "Classic booming stadium announcer voice",
    "is_default": True,
}


def load_voice_profiles() -> list[dict]:
    profiles = _read_json(VOICE_PROFILES_FILE, default=None)
    if isinstance(profiles, list) and profiles:
        return profiles
    return [DEFAULT_VOICE_PROFILE]


def get_default_voice_profile() -> dict:
    for p in load_voice_profiles():
        if p.get("is_default"):
            return p
    return DEFAULT_VOICE_PROFILE


# ---------------------------------------------------------------------------
# Announcer Roster
# ---------------------------------------------------------------------------

def _number_to_word(num: str) -> str:
    """Convert jersey number string to spoken word for announcements."""
    words = {
        "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
        "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
        "10": "ten", "11": "eleven", "12": "twelve", "13": "thirteen",
        "14": "fourteen", "15": "fifteen", "16": "sixteen", "17": "seventeen",
        "18": "eighteen", "19": "nineteen", "20": "twenty",
        "21": "twenty-one", "22": "twenty-two", "23": "twenty-three",
        "24": "twenty-four", "25": "twenty-five", "26": "twenty-six",
        "27": "twenty-seven", "28": "twenty-eight", "29": "twenty-nine",
        "30": "thirty", "31": "thirty-one", "32": "thirty-two",
        "33": "thirty-three", "34": "thirty-four", "35": "thirty-five",
        "99": "ninety-nine", "00": "double-zero",
    }
    return words.get(str(num).strip(), str(num))


def build_announcement_text(player: dict) -> str:
    """Build the TTS announcement text for a player."""
    first = (player.get("first") or "").strip()
    last = (player.get("last") or "").strip()
    number = str(player.get("number") or "").strip()
    phonetic_hint = (player.get("phonetic_hint") or "").strip()
    tts_instruction = (player.get("tts_instruction") or "").strip()

    name = phonetic_hint if phonetic_hint else f"{first} {last}"
    name = _apply_phonetics(name)
    num_word = _number_to_word(number)

    base = f"Now batting, number {num_word}, {name}!"
    if tts_instruction:
        base = f"{tts_instruction}. {base}"
    return base


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

        player_id = f"{number}-{first}-{last}".lower().replace(" ", "-")
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


def load_announcer_roster() -> list[dict]:
    """Load announcer roster, bootstrapping from team.json if needed."""
    _ensure_dirs()
    roster = _read_json(ROSTER_FILE, default=None)
    if isinstance(roster, list) and roster:
        return roster

    # Bootstrap from team data
    roster = _bootstrap_roster_from_team()
    if roster:
        _atomic_write_json(ROSTER_FILE, roster)
        logging.info("[Announcer] Bootstrapped roster with %d players", len(roster))
    return roster


def save_announcer_roster(roster: list[dict]):
    _ensure_dirs()
    _atomic_write_json(ROSTER_FILE, roster)


def get_player_by_id(player_id: str) -> dict | None:
    for p in load_announcer_roster():
        if p.get("id") == player_id:
            return p
    return None


def update_player(player_id: str, updates: dict) -> dict | None:
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

def render_player_audio(player_id: str) -> dict:
    """Render TTS audio for a single player. Returns updated player dict."""
    player = get_player_by_id(player_id)
    if not player:
        raise ValueError(f"Player not found: {player_id}")

    update_player(player_id, {"status": "rendering", "error_message": ""})

    try:
        provider = get_tts_provider()
        voice = get_default_voice_profile()
        text = build_announcement_text(player)
        audio_bytes = provider.synthesize(text, voice)

        # Save clip
        ts = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
        player_clip_dir = CLIPS_DIR / player_id
        player_clip_dir.mkdir(parents=True, exist_ok=True)
        clip_path = player_clip_dir / f"{ts}.mp3"
        clip_path.write_bytes(audio_bytes)

        # Build URL path (served by nginx or Flask)
        clip_url = f"/announcer-clips/{player_id}/{ts}.mp3"

        updated = update_player(player_id, {
            "status": "ready",
            "announcer_audio_url": clip_url,
            "rendered_at": datetime.now(ET).isoformat(),
            "error_message": "",
        })
        logging.info("[Announcer] Rendered %s via %s (%d bytes)", player_id, provider.name, len(audio_bytes))
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
