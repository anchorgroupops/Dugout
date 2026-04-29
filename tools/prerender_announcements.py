"""
Pre-render walk-up announcements for all active players.

Probes TTS providers at startup, selects the best available one, then
batch-generates MP3 clips for the whole roster and caches them on disk.
Cached clips are served directly by the Flask app — no live TTS call
during the game.

Usage:
  python tools/prerender_announcements.py                   # all pending players
  python tools/prerender_announcements.py --all             # re-render everyone
  python tools/prerender_announcements.py --player 7-sofia  # single player by ID
  python tools/prerender_announcements.py --dry-run         # show plan, no audio
  python tools/prerender_announcements.py --probe           # show provider status only

Options:
  --all         Re-render even players already marked ready
  --player ID   Render one specific player (by announcer roster ID)
  --dry-run     Print what would be rendered without calling TTS
  --probe       Show TTS provider probe results and exit
  --quality     best | quick  (default: best)
  --concurrency N  Parallel renders (default: 1, safe for Pi; use 2-4 on PC)

Requires:
  - data/sharks/announcer/roster.json (bootstrapped from team.json if missing)
  - At least one TTS provider configured (edge-tts covers the no-key case)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Allow running from repo root or tools/ directory
_TOOLS = Path(__file__).resolve().parent
_REPO = _TOOLS.parent
sys.path.insert(0, str(_TOOLS))

from dotenv import load_dotenv
load_dotenv(_REPO / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("prerender")


def _print_probe(providers: list[dict]):
    print("\nTTS Provider Probe:")
    print(f"  {'PROVIDER':<22} {'AVAILABLE':<10} {'SELECTED':<9} REASON")
    print("  " + "-" * 62)
    for p in providers:
        avail = "YES" if p["available"] else "no"
        sel = "<-- selected" if p.get("selected") else ""
        print(f"  {p['name']:<22} {avail:<10} {sel:<9} {p.get('reason', '')}")
    print()


def probe_and_show() -> list[dict]:
    from announcer_engine import probe_tts_providers
    providers = probe_tts_providers()
    _print_probe(providers)
    return providers


def _render_one(player: dict, quality: str, dry_run: bool) -> dict:
    pid = player["id"]
    name = f"{player.get('first', '')} {player.get('last', '')}".strip()
    number = player.get("number", "?")

    if dry_run:
        log.info("[DRY-RUN] Would render: #%s %s (id=%s)", number, name, pid)
        return {"player_id": pid, "status": "dry_run"}

    try:
        from announcer_engine import render_player_audio
        updated = render_player_audio(pid, game_context=None, quality=quality)
        clip_url = updated.get("announcer_audio_url", "")
        log.info("[OK] #%s %-20s → %s", number, name, clip_url)
        return {"player_id": pid, "status": "ok", "clip_url": clip_url}
    except Exception as e:
        log.error("[FAIL] #%s %s: %s", number, name, e)
        return {"player_id": pid, "status": "error", "error": str(e)[:200]}


def main():
    parser = argparse.ArgumentParser(description="Pre-render walk-up announcements")
    parser.add_argument("--all", action="store_true", help="Re-render even ready players")
    parser.add_argument("--player", metavar="ID", help="Render one specific player by roster ID")
    parser.add_argument("--dry-run", action="store_true", help="Print plan, no audio")
    parser.add_argument("--probe", action="store_true", help="Show TTS provider probe and exit")
    parser.add_argument("--quality", choices=["best", "quick"], default="best")
    parser.add_argument("--concurrency", type=int, default=1, metavar="N")
    args = parser.parse_args()

    # Always show probe results
    providers = probe_and_show()
    if args.probe:
        return

    selected = next((p for p in providers if p.get("selected")), None)
    if not selected:
        log.error("No TTS provider available. Install edge-tts: pip install edge-tts")
        sys.exit(1)
    if selected["name"] == "mock":
        log.warning("Only mock TTS available — output will be silent. Install edge-tts for real audio.")

    log.info("Using provider: %s (quality=%s)", selected["name"], args.quality)

    # Load roster
    from announcer_engine import load_announcer_roster
    roster = load_announcer_roster()
    active = [p for p in roster if p.get("is_active", True)]

    if args.player:
        targets = [p for p in active if p["id"] == args.player]
        if not targets:
            log.error("Player not found: %s", args.player)
            log.info("Available IDs: %s", [p["id"] for p in active])
            sys.exit(1)
    elif args.all:
        targets = active
    else:
        targets = [p for p in active if p.get("status") != "ready"]

    if not targets:
        log.info("Nothing to render — all active players are already ready.")
        log.info("Use --all to re-render everyone.")
        return

    log.info("Rendering %d player(s)...", len(targets))
    t0 = time.monotonic()
    results = []

    if args.concurrency > 1:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {pool.submit(_render_one, p, args.quality, args.dry_run): p for p in targets}
            for future in as_completed(futures):
                results.append(future.result())
    else:
        for p in targets:
            results.append(_render_one(p, args.quality, args.dry_run))

    elapsed = time.monotonic() - t0
    ok = sum(1 for r in results if r["status"] in ("ok", "dry_run"))
    failed = sum(1 for r in results if r["status"] == "error")

    print(f"\nDone in {elapsed:.1f}s — {ok} succeeded, {failed} failed")
    if failed:
        errors = [r for r in results if r["status"] == "error"]
        for e in errors:
            print(f"  FAIL {e['player_id']}: {e.get('error', '')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
