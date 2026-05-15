"""Apex Music Fetcher — local-file scan + yt-dlp ingest pipeline.

Sourcing:
  - Local: scan_local_files(player_id) indexes data/music/raw/{player_id}/*.{mp3,wav,m4a}
  - URL:   ingest_url(...) downloads via yt-dlp and produces a normalized hook clip.

Hook trim:
  Default 18s window starting at `hook_start_ms` (or detected peak energy if not
  provided). Hook is silenced 50ms at edges to avoid clicks.

Normalization:
  Two-pass ffmpeg `loudnorm` to integrated loudness -14 LUFS, true-peak -1.5 dBTP,
  loudness range 11. Matches Spotify / Apple Music ingest target so songs play
  at consistent volume relative to TTS bumpers.

Storage:
  data/music/raw/{player_id}/{slug}.{ext}      — original (or yt-dlp output)
  data/music/clips/{player_id}/{slug}-hook.mp3 — normalized 18s hook served to PWA
  URL the PWA fetches: /audio/music/{player_id}/{slug}-hook.mp3
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

log = logging.getLogger("music_ingest")

PROJECT_ROOT = Path(__file__).parent.parent
MUSIC_DIR = PROJECT_ROOT / "data" / "music"
RAW_DIR = MUSIC_DIR / "raw"
CLIPS_DIR = MUSIC_DIR / "clips"

DEFAULT_HOOK_DURATION_S = 18
LUFS_TARGET = -14.0
TRUE_PEAK_TARGET = -1.5
LRA_TARGET = 11.0

_VALID_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}


def _ensure_dirs(player_id: str) -> tuple[Path, Path]:
    raw = RAW_DIR / player_id
    clips = CLIPS_DIR / player_id
    raw.mkdir(parents=True, exist_ok=True)
    clips.mkdir(parents=True, exist_ok=True)
    return raw, clips


def _slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", text or "").strip("-").lower()
    return (s or "track")[:max_len]


def _ffprobe_duration_ms(path: Path) -> int | None:
    """Return media duration in ms via ffprobe, or None on failure."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=20, check=True,
        )
        data = json.loads(out.stdout or "{}")
        dur = float((data.get("format") or {}).get("duration") or 0)
        return int(dur * 1000) if dur > 0 else None
    except Exception as e:
        log.debug("ffprobe failed for %s: %s", path, e)
        return None


def _detect_hook_start_ms(path: Path, scan_after_ms: int = 15_000) -> int:
    """Heuristic peak-energy hook detection.

    Strategy: ffmpeg `astats` on 1-second windows after `scan_after_ms`,
    pick the window with highest RMS. Falls back to scan_after_ms on error.

    This is a deliberately cheap heuristic — Spotify audio-features already
    provides `optimal_start_ms` for tracks ingested via the wizard. This
    detector only runs for raw URL ingests where no Spotify hint exists.
    """
    try:
        # ffmpeg's `astats` emits per-frame RMS in stderr. We run with -af
        # `astats=metadata=1:reset=1` and `-f null -`, then parse RMS lines.
        # For speed, we resample to mono 22.05kHz and chunk at 1s windows.
        cmd = [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
            "-ss", f"{scan_after_ms / 1000:.3f}",
            "-t", "60",
            "-af", "aresample=22050,aformat=channel_layouts=mono,astats=metadata=1:reset=1:length=1.0",
            "-f", "null", "-",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        rms_lines = [l for l in proc.stderr.splitlines() if "RMS_level" in l and "Overall" not in l]
        if not rms_lines:
            return scan_after_ms

        levels: list[float] = []
        for line in rms_lines:
            m = re.search(r"RMS_level=(-?[\d.]+|-inf)", line)
            if not m:
                continue
            v = m.group(1)
            levels.append(-120.0 if v == "-inf" else float(v))

        if not levels:
            return scan_after_ms
        peak_idx = max(range(len(levels)), key=lambda i: levels[i])
        return scan_after_ms + (peak_idx * 1000)
    except Exception as e:
        log.debug("Hook detection failed for %s: %s — using fallback offset", path, e)
        return scan_after_ms


def _normalize_to_hook(src: Path, dst: Path, *, hook_start_ms: int,
                      hook_duration_s: int = DEFAULT_HOOK_DURATION_S) -> dict:
    """Trim src to hook window and apply -14 LUFS loudnorm. Writes dst (mp3).

    Returns metadata: {"normalized_lufs", "duration_ms"}.
    Two-pass loudnorm: first pass measures, second pass applies the linear
    correction so output hits the target precisely.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    ss = max(0, hook_start_ms) / 1000.0

    # Pass 1: measure
    measure_filter = (
        f"loudnorm=I={LUFS_TARGET}:LRA={LRA_TARGET}:TP={TRUE_PEAK_TARGET}:print_format=json"
    )
    pass1 = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src),
         "-ss", f"{ss:.3f}", "-t", str(hook_duration_s),
         "-af", measure_filter, "-f", "null", "-"],
        capture_output=True, text=True, timeout=120,
    )
    stats: dict = {}
    try:
        # ffmpeg prints the JSON at the end of stderr — find the last { ... }
        m = re.search(r"\{[\s\S]+?\}\s*$", pass1.stderr)
        if m:
            stats = json.loads(m.group(0))
    except Exception:
        stats = {}

    # Pass 2: apply
    if stats and all(k in stats for k in ("input_i", "input_lra", "input_tp", "input_thresh", "target_offset")):
        apply_filter = (
            f"loudnorm=I={LUFS_TARGET}:LRA={LRA_TARGET}:TP={TRUE_PEAK_TARGET}:"
            f"measured_I={stats['input_i']}:measured_LRA={stats['input_lra']}:"
            f"measured_TP={stats['input_tp']}:measured_thresh={stats['input_thresh']}:"
            f"offset={stats['target_offset']}:linear=true:print_format=summary"
        )
    else:
        # Fallback: single-pass dynamic loudnorm. Less precise but still hits
        # the target ~within ±0.5 LUFS, which is fine for game-day use.
        apply_filter = f"loudnorm=I={LUFS_TARGET}:LRA={LRA_TARGET}:TP={TRUE_PEAK_TARGET}"

    # 50ms fade in/out at edges to prevent clicks
    fade = f"afade=t=in:st=0:d=0.05,afade=t=out:st={hook_duration_s - 0.05}:d=0.05"

    pass2 = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(src),
         "-ss", f"{ss:.3f}", "-t", str(hook_duration_s),
         "-af", f"{apply_filter},{fade}",
         "-c:a", "libmp3lame", "-b:a", "192k", str(dst)],
        capture_output=True, text=True, timeout=180,
    )
    if pass2.returncode != 0:
        log.error("Loudnorm pass 2 failed: %s", pass2.stderr[-500:])
        raise RuntimeError("ffmpeg loudnorm pass 2 failed")

    out_duration_ms = _ffprobe_duration_ms(dst) or (hook_duration_s * 1000)
    out_lufs = float(stats.get("output_i") or LUFS_TARGET)
    return {"normalized_lufs": out_lufs, "duration_ms": out_duration_ms}


def _file_to_url(player_id: str, filename: str) -> str:
    """Return the PWA-facing URL for a normalized hook file."""
    return f"/audio/music/{player_id}/{filename}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_local_files(player_id: str) -> list[dict]:
    """Index every supported audio file in data/music/raw/{player_id}/.

    For each new file, produce a normalized hook clip and register it with the
    announcer DB. Idempotent — files already registered are skipped.

    Returns a list of {song_id, file_path, label, normalized_lufs, duration_ms}
    for every entry in the player's pool after the scan.
    """
    raw_dir, clips_dir = _ensure_dirs(player_id)
    import announcer_db as adb
    adb.init_db()

    existing = {(s.get("file_path") or "").lower(): s for s in adb.get_player_songs(player_id)}
    out: list[dict] = []

    for src in sorted(raw_dir.iterdir()):
        if not src.is_file() or src.suffix.lower() not in _VALID_EXTS:
            continue

        slug = _slugify(src.stem)
        hook_filename = f"{slug}-hook.mp3"
        hook_url = _file_to_url(player_id, hook_filename)
        hook_dst = clips_dir / hook_filename

        if hook_url.lower() in existing and hook_dst.exists():
            out.append({
                "song_id": existing[hook_url.lower()].get("id"),
                "file_path": hook_url,
                "label": existing[hook_url.lower()].get("song_label") or src.stem,
                "skipped": True,
            })
            continue

        try:
            start_ms = _detect_hook_start_ms(src)
            meta = _normalize_to_hook(src, hook_dst, hook_start_ms=start_ms)
        except Exception as e:
            log.error("[music_ingest] Failed to normalize %s: %s", src.name, e)
            continue

        # Register: song_url stores the user-friendly source filename so the
        # PWA can show "from: foo.mp3"; file_path stores the URL the PWA
        # actually fetches.
        adb.add_player_song(
            player_id=player_id,
            song_url=f"local:{src.name}",
            song_label=src.stem,
            source="local",
            source_id=src.name,
            optimal_start_ms=start_ms,
            duration_ms=meta["duration_ms"],
            file_path=hook_url,
            normalized_lufs=meta["normalized_lufs"],
        )
        out.append({
            "file_path": hook_url,
            "label": src.stem,
            "normalized_lufs": meta["normalized_lufs"],
            "duration_ms": meta["duration_ms"],
        })

    return out


def ingest_url(player_id: str, url: str, *,
               hook_start_ms: int | None = None,
               hook_duration_s: int = DEFAULT_HOOK_DURATION_S,
               label: str | None = None) -> dict:
    """Download `url` via yt-dlp and produce a normalized hook clip.

    Returns {song_id, file_path, label, duration_ms, normalized_lufs}.
    Blocks until the hook clip is on disk. Caller (HTTP route) is expected
    to run this inside a background thread.
    """
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError("yt_dlp_not_installed: pip install yt-dlp") from e

    raw_dir, clips_dir = _ensure_dirs(player_id)
    import announcer_db as adb
    adb.init_db()

    # First do a metadata-only fetch so we have a stable slug + duration.
    info_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(info_opts) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    title = (info.get("title") or label or "track").strip()
    slug = _slugify(title)
    raw_path = raw_dir / f"{slug}.mp3"

    if not raw_path.exists():
        ydl_opts = {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "outtmpl": str(raw_dir / f"{slug}.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    if not raw_path.exists() or raw_path.stat().st_size < 10_000:
        raise RuntimeError("yt-dlp output missing or too small — ffmpeg may be unavailable")

    if hook_start_ms is None:
        hook_start_ms = _detect_hook_start_ms(raw_path)

    hook_filename = f"{slug}-hook.mp3"
    hook_dst = clips_dir / hook_filename
    meta = _normalize_to_hook(raw_path, hook_dst,
                              hook_start_ms=hook_start_ms,
                              hook_duration_s=hook_duration_s)
    hook_url = _file_to_url(player_id, hook_filename)

    pool = adb.add_player_song(
        player_id=player_id,
        song_url=url,
        song_label=label or title,
        source="url",
        source_id=info.get("id"),
        optimal_start_ms=hook_start_ms,
        duration_ms=meta["duration_ms"],
        file_path=hook_url,
        normalized_lufs=meta["normalized_lufs"],
    )
    # Find the row we just inserted (or the existing one — INSERT OR IGNORE).
    matching = [s for s in pool if (s.get("file_path") or "").lower() == hook_url.lower()]
    if matching:
        row = matching[0]
        # If the row pre-existed without a file_path, attach it now.
        if not row.get("file_path"):
            adb.update_player_song_file(
                row["id"], hook_url,
                bpm=None, bpm_offset_ms=0,
                normalized_lufs=meta["normalized_lufs"],
                duration_ms=meta["duration_ms"],
            )
        song_id = row["id"]
    else:
        song_id = None

    return {
        "song_id": song_id,
        "file_path": hook_url,
        "label": label or title,
        "duration_ms": meta["duration_ms"],
        "normalized_lufs": meta["normalized_lufs"],
        "hook_start_ms": hook_start_ms,
    }


def serve_music_path(player_id: str, filename: str) -> Path | None:
    """Resolve the on-disk path for an /audio/music/<player_id>/<filename> request.

    Returns None if the path escapes CLIPS_DIR (path traversal guard).
    """
    if not re.match(r"^[A-Za-z0-9_-]+\.(mp3|m4a|ogg)$", filename):
        return None
    if not re.match(r"^[A-Za-z0-9_-]+$", player_id):
        return None
    target = (CLIPS_DIR / player_id / filename).resolve()
    base = CLIPS_DIR.resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target if target.is_file() else None


def ffmpeg_available() -> bool:
    """Quick check that ffmpeg + ffprobe are on PATH."""
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def has_yt_dlp() -> bool:
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return False
