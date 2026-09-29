"""Coach-supplied audio for the announcer, and the manual batting order.

- Uploaded walk-up songs:  data/music/clips/<player>/<slug>-<8 hex>.mp3
                           served at /audio/music/<player>/<file>
- Uploaded calls:          data/sharks/announcer/clips/<player>/upload-<8 hex>.mp3
                           served at /announcer-clips/<player>/<file>
- Soundboard:              data/sharks/announcer/soundboard/<file>, listed in
                           data/sharks/announcer/soundboard.json, served at
                           /audio/soundboard/<file>
- Batting order:           data/sharks/announcer/batting_order.json

With FFmpeg on the box every upload is decoded, loudness-normalised
(`loudnorm`) and re-encoded to 128 kbps MP3 with its channel count kept; a
file FFmpeg can't decode is refused (422). Without FFmpeg the bytes are
stored as they came, under the extension their header says they are.

The six built-in soundboard effects are synthesised by FFmpeg from
oscillators and noise (no recorded or licensed audio), once, on the first
soundboard listing. Filters used exist in FFmpeg 4.4 (the Pi image); `amix`
is avoided on purpose (SIGN-012).
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import announcer_engine as ae
import music_ingest as mi

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
# Below gunicorn's 90 s worker timeout (docker-compose.sharks.yml).
FFMPEG_TIMEOUT_S = 75
SONG_LUFS = -14.0   # matches music_ingest.LUFS_TARGET
CALL_LUFS = -16.0   # matches the Stadium Wrap's loudnorm target
EFFECT_LUFS = -14.0

SOUNDBOARD_DIR = ae.ANNOUNCER_DIR / "soundboard"
SOUNDBOARD_FILE = ae.ANNOUNCER_DIR / "soundboard.json"
BATTING_ORDER_FILE = ae.ANNOUNCER_DIR / "batting_order.json"
MAX_SOUNDS = 24
SOUND_LABEL_MAX = 24
SONG_LABEL_MAX = 80
MAX_ORDER = 60

AUDIO_FILE_RE = re.compile(r"^[A-Za-z0-9_-]+\.(mp3|wav|m4a)$")
MIMETYPES = {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4", "ogg": "audio/ogg"}


class UploadError(Exception):
    """A refused upload: `code` is the API error, `status` the HTTP status."""

    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.code = code
        self.status = status


def sniff_audio(head: bytes) -> str | None:
    """'mp3' | 'wav' | 'm4a' from a file's first bytes, else None."""
    if head[:3] == b"ID3":
        return "mp3"
    # MPEG audio frame sync; layer bits 00 are reserved (that's AAC ADTS).
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0 and (head[1] & 0x06):
        return "mp3"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[4:8] == b"ftyp":
        return "m4a"
    return None


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def mimetype_for(filename: str) -> str:
    return MIMETYPES.get(filename.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def clean_label(raw: str, max_len: int) -> str:
    """A display label: printable, single-spaced, trimmed to max_len."""
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(raw or ""))
    return re.sub(r"\s+", " ", s).strip()[:max_len].strip()


def label_from_filename(filename: str, max_len: int) -> str:
    stem = Path(str(filename or "")).stem.replace("_", " ")
    return clean_label(stem, max_len)


def _unique_stem(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


def _run_ffmpeg(args: list[str]) -> bool:
    try:
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", *args],
                              capture_output=True, timeout=FFMPEG_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError) as e:
        logging.warning("[Announcer] ffmpeg failed: %s", e)
        return False
    if proc.returncode != 0:
        logging.warning("[Announcer] ffmpeg exit %s: %s", proc.returncode,
                        (proc.stderr or b"")[-300:].decode("utf-8", "replace"))
    return proc.returncode == 0


def store_audio(data: bytes, dest_dir: Path, stem: str, *, lufs: float) -> str:
    """Validate, normalise and file one uploaded audio file. Returns the filename.

    Raises UploadError: 413 file_too_large, 415 unsupported_audio,
    422 audio_unreadable (FFmpeg present but could not decode it).
    """
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError("file_too_large", 413)
    kind = sniff_audio(data[:16])
    if not kind:
        raise UploadError("unsupported_audio", 415)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if not ffmpeg_available():
        name = f"{stem}.{kind}"
        _atomic_write_bytes(dest_dir / name, data)
        return name
    name = f"{stem}.mp3"
    # Temp dir beside the destination so the final rename is atomic, and a
    # real file for the input: many .m4a files (iPhone Voice Memos) keep the
    # index at the end and can't be decoded from a pipe.
    with tempfile.TemporaryDirectory(dir=str(dest_dir), prefix=".upload-") as tmp:
        src = Path(tmp) / f"in.{kind}"
        out = Path(tmp) / "out.mp3"
        src.write_bytes(data)
        ok = _run_ffmpeg([
            "-i", str(src), "-vn", "-map_metadata", "-1",
            # Single-pass loudnorm works at 192 kHz internally; -ar brings it back.
            "-af", f"loudnorm=I={lufs}:TP=-1.5:LRA=11",
            "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "128k", str(out),
        ])
        if not ok or not out.is_file() or out.stat().st_size == 0:
            raise UploadError("audio_unreadable", 422)
        os.replace(out, dest_dir / name)
    return name


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── Songs and calls ────────────────────────────────────────────────────────

def save_song_upload(player_id: str, filename: str, data: bytes, label: str = "") -> dict:
    """File an uploaded walk-up song. Returns the roster song entry (not yet saved)."""
    safe = ae._sanitize_player_id(player_id)
    title = clean_label(label, SONG_LABEL_MAX) or label_from_filename(filename, SONG_LABEL_MAX) or "Walk-up song"
    stem = _unique_stem(mi._slugify(title, 40))
    name = store_audio(data, mi.CLIPS_DIR / safe, stem, lufs=SONG_LUFS)
    return {"id": secrets.token_hex(4), "url": f"/audio/music/{safe}/{name}", "start": 0.0, "label": title}


def save_call_upload(player_id: str, data: bytes) -> str:
    """File an uploaded, pre-recorded call. Returns its clip URL."""
    safe = ae._sanitize_player_id(player_id)
    name = store_audio(data, ae.CLIPS_DIR / safe, _unique_stem("upload"), lufs=CALL_LUFS)
    return f"/announcer-clips/{safe}/{name}"


# ── Soundboard ─────────────────────────────────────────────────────────────

# (id, label, seconds, lavfi graph producing [out]). {d} is the duration.
_CHARGE = [(392.0, 0.14), (523.25, 0.14), (659.25, 0.14), (783.99, 0.34), (659.25, 0.14), (783.99, 0.7)]


def _charge_graph() -> str:
    notes = []
    for i, (f, dur) in enumerate(_CHARGE):
        organ = (f"(sin(2*PI*{f}*t)+0.5*sin(4*PI*{f}*t)+0.25*sin(6*PI*{f}*t))*0.9"
                 f"*min(1,t*80)*min(1,({dur}-t)*30)")
        notes.append(f"aevalsrc='{organ}':s=44100:d={dur}[n{i}]")
    joined = "".join(f"[n{i}]" for i in range(len(_CHARGE)))
    return ";".join(notes) + f";{joined}concat=n={len(_CHARGE)}:v=0:a=1,aecho=0.6:0.5:60:0.25[out]"


BUILTIN_SOUNDS = [
    ("air-horn", "Air horn", 1.6,
     "aevalsrc='0.22*((gt(sin(2*PI*233*t),0)*2-1)+(gt(sin(2*PI*294*t),0)*2-1)+0.6*(gt(sin(2*PI*349*t),0)*2-1))"
     "*min(1,t*25)*min(1,(1.6-t)*6)':s=44100:d=1.6,lowpass=f=2600,highpass=f=150[out]"),
    ("charge", "Charge!", 1.6, _charge_graph()),
    ("drum-roll", "Drum roll", 2.4,
     "anoisesrc=d=2.4:c=white:r=44100:a=0.8:s=7,"
     "aeval='val(0)*if(lt(t,1.9),(0.25+0.75*t/1.9)*exp(-mod(t,0.045)*70),1.3*exp(-(t-1.9)*7))',"
     "highpass=f=180,lowpass=f=6000[out]"),
    ("cowbell", "Cowbell", 1.0,
     "aevalsrc='0.85*((gt(sin(2*PI*540*t),0)-0.5)+(gt(sin(2*PI*800*t),0)-0.5))"
     "*if(lt(t,0.28),exp(-t*14),exp(-(t-0.28)*9))':s=44100:d=1.0,highpass=f=400,lowpass=f=4000[out]"),
    ("whistle", "Whistle", 0.9,
     "aevalsrc='0.45*sin(2*PI*2800*t+3*sin(2*PI*28*t))*min(1,t*40)*min(1,(0.9-t)*12)':s=44100:d=0.9[out]"),
    ("crowd", "Crowd cheer", 3.0,
     "anoisesrc=d=3:c=pink:r=44100:a=0.9:s=11,"
     "aeval='val(0)*min(1,t*1.6)*min(1,(3-t)*1.2)*(0.75+0.15*sin(2*PI*1.3*t)+0.1*sin(2*PI*3.1*t))',"
     "highpass=f=300,lowpass=f=3500,volume=1.8[out]"),
]
BUILTIN_VERSION = 1  # bump when a graph changes: the service worker caches by URL for a year
BUILTIN_IDS = {b[0] for b in BUILTIN_SOUNDS}


def builtin_filename(sound_id: str) -> str:
    return f"builtin-{sound_id}-v{BUILTIN_VERSION}.mp3"


def _render_builtin(sound_id: str, graph: str) -> bool:
    SOUNDBOARD_DIR.mkdir(parents=True, exist_ok=True)
    dest = SOUNDBOARD_DIR / builtin_filename(sound_id)
    with tempfile.TemporaryDirectory(dir=str(SOUNDBOARD_DIR), prefix=".render-") as tmp:
        out = Path(tmp) / "out.mp3"
        ok = _run_ffmpeg(["-filter_complex", f"{graph};[out]alimiter=limit=0.9[final]", "-map", "[final]",
                          "-ac", "1", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "128k", str(out)])
        if not ok or not out.is_file() or out.stat().st_size == 0:
            return False
        os.replace(out, dest)  # two workers may race on the first listing; last rename wins, same bytes
    return True


def ensure_builtin_sounds() -> list[dict]:
    """The built-in effects that exist on disk, rendering any that are missing."""
    out = []
    for sound_id, label, _secs, graph in BUILTIN_SOUNDS:
        name = builtin_filename(sound_id)
        if not (SOUNDBOARD_DIR / name).is_file():
            if not ffmpeg_available() or not _render_builtin(sound_id, graph):
                continue
        out.append({"id": sound_id, "label": label, "url": f"/audio/soundboard/{name}", "builtin": True})
    return out


def _read_uploaded_sounds() -> list[dict]:
    try:
        data = json.loads(SOUNDBOARD_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [s for s in data if isinstance(s, dict) and s.get("id") and s.get("url")] if isinstance(data, list) else []


def list_sounds() -> list[dict]:
    uploaded = [{**s, "builtin": False} for s in _read_uploaded_sounds()]
    return ensure_builtin_sounds() + uploaded


def add_sound(filename: str, data: bytes, label: str = "") -> dict:
    """File an uploaded effect and append it to soundboard.json."""
    title = clean_label(label, SOUND_LABEL_MAX) or label_from_filename(filename, SOUND_LABEL_MAX) or "Sound"
    # _ROSTER_LOCK is a cross-process file lock; reusing it keeps two workers
    # from interleaving read-modify-writes of soundboard.json.
    with ae._ROSTER_LOCK:
        if len(_read_uploaded_sounds()) >= MAX_SOUNDS:
            raise UploadError("sounds_full", 409)
    stem = _unique_stem(mi._slugify(title, 30))
    name = store_audio(data, SOUNDBOARD_DIR, stem, lufs=EFFECT_LUFS)
    entry = {"id": stem, "label": title, "url": f"/audio/soundboard/{name}",
             "added_at": datetime.now(ae.ET).isoformat()}
    with ae._ROSTER_LOCK:
        sounds = _read_uploaded_sounds()
        if len(sounds) >= MAX_SOUNDS:
            # Lost the race to another upload while ffmpeg ran: drop the file.
            (SOUNDBOARD_DIR / name).unlink(missing_ok=True)
            raise UploadError("sounds_full", 409)
        sounds.append(entry)
        ae._atomic_write_json(SOUNDBOARD_FILE, sounds)
    return {**entry, "builtin": False}


def remove_sound(sound_id: str) -> None:
    """Delete an uploaded effect. Raises UploadError for built-ins or unknown ids."""
    if sound_id in BUILTIN_IDS:
        raise UploadError("builtin_sound", 400)
    with ae._ROSTER_LOCK:
        sounds = _read_uploaded_sounds()
        entry = next((s for s in sounds if s.get("id") == sound_id), None)
        if not entry:
            raise UploadError("sound_not_found", 404)
        ae._atomic_write_json(SOUNDBOARD_FILE, [s for s in sounds if s is not entry])
    name = str(entry.get("url", "")).rsplit("/", 1)[-1]
    if AUDIO_FILE_RE.match(name):
        try:
            (SOUNDBOARD_DIR / name).unlink()
        except OSError:
            pass


def soundboard_path(filename: str) -> Path | None:
    """On-disk file for /audio/soundboard/<filename>, or None (bad name, missing)."""
    if not AUDIO_FILE_RE.match(filename or ""):
        return None
    target = (SOUNDBOARD_DIR / filename).resolve()
    try:
        target.relative_to(SOUNDBOARD_DIR.resolve())
    except ValueError:
        return None
    return target if target.is_file() else None


# ── Manual batting order ───────────────────────────────────────────────────

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def read_batting_order() -> dict | None:
    try:
        data = json.loads(BATTING_ORDER_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    order = data.get("order") if isinstance(data, dict) else None
    if not isinstance(order, list) or not order:
        return None
    return {"order": [str(x) for x in order if isinstance(x, str)], "updated_at": data.get("updated_at") or ""}


def save_batting_order(order, active_ids: list[str]) -> dict:
    """Store the coach's order over the active roster (`active_ids`, roster order).

    Unknown, inactive and repeated ids are dropped; active players the order
    doesn't name are appended in roster order. An order naming no active
    player is refused.
    """
    if not isinstance(order, list) or len(order) > MAX_ORDER or not all(isinstance(x, str) and _ID_RE.match(x) for x in order):
        raise UploadError("order_invalid", 400)
    active = set(active_ids)
    seen, clean = set(), []
    for pid in order:
        if pid not in seen and pid in active:
            seen.add(pid)
            clean.append(pid)
    if not clean:
        raise UploadError("order_invalid", 400)
    clean += [pid for pid in active_ids if pid not in seen]
    record = {"order": clean, "updated_at": datetime.now(ae.ET).isoformat()}
    ae._atomic_write_json(BATTING_ORDER_FILE, record)
    return record


def clear_batting_order() -> bool:
    try:
        BATTING_ORDER_FILE.unlink()
        return True
    except FileNotFoundError:
        return False
