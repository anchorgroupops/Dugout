"""
Clone Jeff Steitzer's voice (Halo Reach announcer) via ElevenLabs Instant Voice Clone.

Steps:
  1. Fetches the Halo Reach soundboard page to get fresh signed URLs
  2. Downloads all 93 clips to data/jeff_voice/clips/
  3. Concatenates into one training file (if ffmpeg available) for best clone quality
  4. Uploads to ElevenLabs /v1/voices/add (or /edit to update an existing voice)
  5. Prints the voice_id — add it to .env as ELEVENLABS_VOICE_ID

Usage:
  python tools/clone_jeff.py
  python tools/clone_jeff.py --name "Jeff Steitzer - Halo"
  python tools/clone_jeff.py --skip-download          # reuse cached clips
  python tools/clone_jeff.py --update <voice_id>      # refresh existing voice
  python tools/clone_jeff.py --out-dir /tmp/jeff      # custom download dir

Requires:
  ELEVENLABS_API_KEY in .env  (or set as env var)
  pip install requests python-dotenv
  ffmpeg on PATH (optional but strongly recommended for best quality)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

BOARD_URL = "https://www.101soundboards.com/boards/76143-halo-reach-soundboard"
BASE_URL = "https://www.101soundboards.com"
ELEVENLABS_API = "https://api.elevenlabs.io/v1"
DEFAULT_OUT_DIR = Path(__file__).parent.parent / "data" / "jeff_voice" / "clips"
DEFAULT_VOICE_NAME = "Jeff Steitzer"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Step 1: Fetch sound metadata from the soundboard page
# ---------------------------------------------------------------------------

def fetch_sounds() -> list[dict]:
    """Fetch the soundboard page and extract all 93 sound objects from board_data_inline."""
    print(f"[Jeff] Fetching soundboard page: {BOARD_URL}")
    resp = requests.get(BOARD_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.text

    # The page embeds: window.board_data_inline = { ... };
    m = re.search(r"window\.board_data_inline\s*=\s*", html)
    if not m:
        raise RuntimeError(
            "[Jeff] Could not find window.board_data_inline in page source. "
            "The site may have changed its structure."
        )

    try:
        data, _ = json.JSONDecoder().raw_decode(html[m.end():])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"[Jeff] Failed to parse board_data_inline JSON: {e}")

    sounds = data.get("sounds", [])
    print(f"[Jeff] Found {len(sounds)} clips on the board.")
    return sounds


# ---------------------------------------------------------------------------
# Step 2: Download clips
# ---------------------------------------------------------------------------

def download_clips(sounds: list[dict], out_dir: Path) -> list[Path]:
    """Download all sound clips. Returns list of successfully downloaded paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    session = requests.Session()
    session.headers.update(HEADERS)

    for i, sound in enumerate(sounds, 1):
        sid = sound.get("id")
        transcript = sound.get("sound_transcript", f"clip_{sid}")
        safe_name = re.sub(r"[^\w\-]", "_", transcript.lower())
        out_path = out_dir / f"{sid}_{safe_name}.mp3"

        if out_path.exists() and out_path.stat().st_size > 1000:
            print(f"[Jeff] [{i:02d}/{len(sounds)}] Cached: {out_path.name}")
            downloaded.append(out_path)
            continue

        # Prefer file_url (direct CDN, no redirect); fallback to download_url
        file_url = sound.get("sound_file_url", "")
        if file_url and not file_url.startswith("http"):
            file_url = BASE_URL + file_url
        download_url = sound.get("download_url", "")
        if download_url and not download_url.startswith("http"):
            download_url = BASE_URL + download_url

        url = file_url or download_url
        if not url:
            print(f"[Jeff] [{i:02d}/{len(sounds)}] SKIP {transcript}: no URL")
            continue

        try:
            r = session.get(url, timeout=20, allow_redirects=True)
            r.raise_for_status()
            content = r.content
            if len(content) < 500:
                print(f"[Jeff] [{i:02d}/{len(sounds)}] WARN {transcript}: tiny response ({len(content)}b), skipping")
                continue
            out_path.write_bytes(content)
            duration_s = sound.get("sound_duration", 0) / 1000
            print(f"[Jeff] [{i:02d}/{len(sounds)}] OK {transcript} ({duration_s:.1f}s, {len(content)//1024}KB)")
            downloaded.append(out_path)
        except Exception as e:
            print(f"[Jeff] [{i:02d}/{len(sounds)}] ERROR {transcript}: {e}")

        time.sleep(0.3)  # polite rate limit

    print(f"[Jeff] Downloaded {len(downloaded)}/{len(sounds)} clips to {out_dir}")
    return downloaded


# ---------------------------------------------------------------------------
# Step 3: Concatenate with ffmpeg (best quality for IVC)
# ---------------------------------------------------------------------------

def concat_clips(clips: list[Path], out_dir: Path) -> Path | None:
    """Concatenate all clips into a single MP3 using ffmpeg. Returns path or None."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, timeout=5
        )
        if result.returncode != 0:
            raise FileNotFoundError
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("[Jeff] ffmpeg not found — will upload individual clips instead of combined file.")
        return None

    concat_list = out_dir.parent / "concat_list.txt"
    combined = out_dir.parent / "jeff_combined.mp3"

    # Sort by duration (longest first) then by filename for determinism
    sorted_clips = sorted(clips, key=lambda p: int(p.stem.split("_")[0]))

    with open(concat_list, "w", encoding="utf-8") as f:
        for clip in sorted_clips:
            f.write(f"file '{clip.resolve()}'\n")

    print(f"[Jeff] Concatenating {len(sorted_clips)} clips → {combined.name} ...")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c:a", "libmp3lame", "-q:a", "2",  # ~190 kbps VBR, re-encode for clean stream
                str(combined),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        size_kb = combined.stat().st_size // 1024
        print(f"[Jeff] Combined file: {combined} ({size_kb} KB)")
        return combined
    except subprocess.CalledProcessError as e:
        print(f"[Jeff] ffmpeg concat failed: {e.stderr.decode()[:200]}")
        return None


# ---------------------------------------------------------------------------
# Step 4: Upload to ElevenLabs
# ---------------------------------------------------------------------------

def upload_voice(
    audio_files: list[Path],
    voice_name: str,
    api_key: str,
    existing_voice_id: str | None = None,
) -> str:
    """Create or update an ElevenLabs Instant Voice Clone. Returns voice_id."""
    if not audio_files:
        raise ValueError("[Jeff] No audio files to upload.")

    # IVC supports up to 25 files. If we have more, pick the 25 largest (most audio data).
    if len(audio_files) > 25:
        audio_files = sorted(audio_files, key=lambda p: p.stat().st_size, reverse=True)[:25]
        print(f"[Jeff] Using top 25 largest clips for IVC (max supported).")

    if existing_voice_id:
        url = f"{ELEVENLABS_API}/voices/{existing_voice_id}/edit"
        method = "POST"
        print(f"[Jeff] Updating existing voice {existing_voice_id} ...")
    else:
        url = f"{ELEVENLABS_API}/voices/add"
        method = "POST"
        print(f"[Jeff] Creating new voice clone '{voice_name}' ...")

    headers = {"xi-api-key": api_key}
    data = {
        "name": voice_name,
        "description": (
            "Jeff Steitzer — Halo Reach multiplayer announcer. "
            "Voice cloned from 101soundboards.com for The Sharks softball team walk-up announcements."
        ),
    }

    file_handles = []
    try:
        files = []
        for p in audio_files:
            fh = open(p, "rb")
            file_handles.append(fh)
            files.append(("files", (p.name, fh, "audio/mpeg")))

        print(f"[Jeff] Uploading {len(files)} file(s) to ElevenLabs ...")
        resp = requests.post(url, headers=headers, data=data, files=files, timeout=180)

        if resp.status_code == 422:
            print(f"[Jeff] ElevenLabs 422: {resp.text}")
            raise RuntimeError(f"ElevenLabs rejected the upload: {resp.text}")
        resp.raise_for_status()

    finally:
        for fh in file_handles:
            fh.close()

    result = resp.json()
    voice_id = result.get("voice_id")
    if not voice_id:
        raise RuntimeError(f"[Jeff] No voice_id in ElevenLabs response: {result}")

    print(f"\n[Jeff] Voice clone created successfully!")
    print(f"[Jeff] voice_id: {voice_id}")
    return voice_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Clone Jeff Steitzer's voice from Halo Reach soundboard → ElevenLabs"
    )
    parser.add_argument("--name", default=DEFAULT_VOICE_NAME, help="Voice name in ElevenLabs")
    parser.add_argument("--skip-download", action="store_true", help="Reuse already-downloaded clips")
    parser.add_argument("--update", metavar="VOICE_ID", default=None, help="Update existing ElevenLabs voice ID")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Directory for downloaded clips")
    parser.add_argument("--no-concat", action="store_true", help="Skip ffmpeg concat, upload individual clips")
    args = parser.parse_args()

    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        print("[Jeff] ERROR: ELEVENLABS_API_KEY not set in .env or environment.")
        sys.exit(1)

    out_dir = Path(args.out_dir)

    # 1. Fetch sound metadata
    if args.skip_download:
        clips = sorted(out_dir.glob("*.mp3"))
        if not clips:
            print(f"[Jeff] --skip-download: no .mp3 files found in {out_dir}. Run without this flag first.")
            sys.exit(1)
        print(f"[Jeff] Using {len(clips)} cached clips from {out_dir}")
    else:
        sounds = fetch_sounds()
        clips = download_clips(sounds, out_dir)

    if not clips:
        print("[Jeff] ERROR: No clips available to upload.")
        sys.exit(1)

    # 2. Concatenate (preferred — gives ElevenLabs the full 3 min of audio as one stream)
    combined = None
    if not args.no_concat:
        combined = concat_clips(clips, out_dir)

    upload_files = [combined] if combined else clips

    # 3. Upload to ElevenLabs
    voice_id = upload_voice(
        audio_files=upload_files,
        voice_name=args.name,
        api_key=api_key,
        existing_voice_id=args.update,
    )

    # 4. Print instructions
    env_file = Path(__file__).parent.parent / ".env"
    print()
    print("=" * 60)
    print("NEXT STEP — add this to your .env file on the Pi:")
    print(f"  ELEVENLABS_VOICE_ID={voice_id}")
    print()
    if env_file.exists():
        existing = env_file.read_text(encoding="utf-8")
        if "ELEVENLABS_VOICE_ID" not in existing:
            print(f"(Appending automatically to {env_file} ...)")
            with open(env_file, "a", encoding="utf-8") as f:
                f.write(f"\nELEVENLABS_VOICE_ID={voice_id}\n")
            print("Done. Restart the sharks_api container to pick it up.")
        else:
            print(f"NOTE: ELEVENLABS_VOICE_ID already in .env — update it manually to: {voice_id}")
    print("=" * 60)


if __name__ == "__main__":
    main()
