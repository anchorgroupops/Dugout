# Apex Announcer — Deep-Render & Shuffle System

**Date:** 2026-04-25  
**Status:** Approved — implementing

## Context

The Phase 1 Apex Announcer shipped with Replicate 1.7B cloud rendering and a single walk-up song per player. Phase 2 adds a two-tier render system (Pi Quick + Mac Best Quality), lossless FLAC archiving, an FFmpeg "Stadium Wrap" post-process chain, a persistent LRU shuffle engine for multiple walk-up songs, and a self-healing Mac polling worker.

---

## Render Tier Architecture

```
Request (quality=quick)
  ├─ Pi CPU < 80%  →  LocalVLLMTTS (0.6B, 4-bit quantized)
  └─ Pi CPU ≥ 80%  →  Replicate06bTTS (Cloud Mirror, same Steitzer ICL ref)

Request (quality=best)
  ├─ Mac heartbeat fresh (< 30s)  →  enqueue PENDING in SQLite
  │    Mac polls /api/announcer/render-queue every 10s
  │    Claims job → PROCESSING (prevents Pi failover)
  │    Renders Qwen3-1.7B locally → WAV
  │    FFmpeg Pass 1: WAV → FLAC 24-bit/48kHz (archive master)
  │    FFmpeg Pass 2: FLAC → Stadium Wrap chain → 192kbps MP3
  │    POST FLAC + MP3 to /api/announcer/render-complete/<job_id>
  │    Pi stores: archive/…/ts.flac + clips/…/ts.mp3
  └─ Mac offline  →  demote to quality=quick + draft_quality=true
                     auto re-render when Mac heartbeats
```

**Stadium Wrap FFmpeg filter chain (Best Quality only):**
- `compand` — broadcast hard compression (attack 10ms, decay 200ms)
- `equalizer f=150 t=l g=+4dB` — sub-bass Steitzer "boom"
- `extrastereo m=2.5` — fills the stadium soundstage

---

## Database: `data/sharks/announcer/announcer.db`

### `render_queue`
| col | type | notes |
|-----|------|-------|
| id | TEXT PK | UUID |
| player_id | TEXT | FK → roster |
| game_context | TEXT | JSON snapshot |
| quality | TEXT | `quick`\|`best` |
| status | TEXT | `PENDING`→`PROCESSING`→`COMPLETED`\|`FAILED` |
| priority | TEXT | `high` (quick) \| `normal` (best) |
| worker_id | TEXT | mac hostname when claimed |
| draft_quality | INTEGER | 1 if rendered via fallback |
| created_at | TEXT | ISO UTC |
| claimed_at | TEXT | |
| completed_at | TEXT | |
| error | TEXT | failure message |

### `player_songs`
| col | type | notes |
|-----|------|-------|
| id | INTEGER PK AUTOINCREMENT | |
| player_id | TEXT | FK → roster |
| song_url | TEXT | |
| song_label | TEXT | display name |
| play_count | INTEGER | lifetime counter |
| last_played_at | TEXT | ISO UTC, NULL = never played |

### `shuffle_state`
| col | type | notes |
|-----|------|-------|
| player_id + game_session_id | PK | |
| played_song_ids | TEXT | JSON array, resets when full cycle complete |

### `mac_heartbeat`
| col | type | notes |
|-----|------|-------|
| worker_id | TEXT PK | hostname |
| last_seen_at | TEXT | ISO UTC |

---

## Shuffle Engine — Least-Recently-Played

1. Load all songs for player, sorted by `(play_count ASC, last_played_at ASC NULLS FIRST)`
2. Filter to songs not yet played this game session
3. If all played, reset session played list (full cycle → restart)
4. Among the remaining, pick randomly from the lowest `play_count` tier
5. Increment `play_count`, set `last_played_at`, append to session state

Tie-breaking rationale: songs with the same play count are equally "fair"; randomness within the tier prevents predictable ordering.

**Pre-buffering:** `GET /api/announcer/next-songs?player_ids=A,B,C&session=S` peeks (no commit) the next song URL for up to 3 upcoming batters. The PWA calls `preload()` on these URLs during current batter's playback.

---

## New API Endpoints

| method | path | description |
|--------|------|-------------|
| GET | `/api/announcer/render-queue` | Mac polls: returns PENDING best-quality jobs |
| PATCH | `/api/announcer/render-queue/<job_id>` | Mac claims job (→ PROCESSING) |
| POST | `/api/announcer/render-complete/<job_id>` | Mac uploads FLAC + MP3 |
| POST | `/api/announcer/heartbeat` | Mac reports alive |
| GET | `/api/announcer/render-status/<player_id>` | SSE quality label stream |
| GET | `/api/announcer/songs/<player_id>` | List song pool |
| POST | `/api/announcer/songs/<player_id>` | Add song to pool |
| DELETE | `/api/announcer/songs/<player_id>/<song_id>` | Remove song |
| GET | `/api/announcer/next-songs` | Peek next song per player (no commit) |

---

## Files Modified

| file | what changes |
|------|-------------|
| `tools/announcer_db.py` | NEW — all SQLite ops (render queue, songs, shuffle, heartbeat) |
| `tools/announcer_engine.py` | + `Replicate06bTTS`, `get_quick_tts_provider()`, `archive_and_transcode()` |
| `tools/sync_daemon.py` | + 9 new route handlers + quality-aware render routing |
| `tools/announcer_api.py` | + background polling loop + Stadium Wrap + Pi upload |
| `client/nginx.conf` | + proxy rules for new announcer routes |

---

## Verification

1. `python -c "from announcer_db import init_db, pick_walkup_song; init_db(); print('DB ok')"` → DB ok
2. `curl -X POST http://pi:5000/api/announcer/heartbeat -H "Content-Type: application/json" -d '{"worker_id":"mac"}'` → `{"status":"ok"}`
3. `curl http://pi:5000/api/announcer/render-queue` → `{"jobs":[]}`
4. Add songs via POST, call `pick_walkup_song` three times — should rotate A→B→C without repeat then reset
5. Set `MAC_HEARTBEAT_MAX_AGE=0` env var, trigger best-quality render — should demote to quick + draft_quality=true
6. Start `announcer_api.py` daemon on Mac → poll loop logs `[render_worker] polling...` every 10s
