# Dugout tablet — data contract

`GET /api/live/tablet`. Team-password session required, like every other `/api` read. The tablet polls this endpoint every 5 s while the screen is visible.

The payload is built by `tools/live_tablet.build_tablet_payload`. A real example generated from the test fixture is in `client/src/components/live-tablet/sample_payload.json`.

```jsonc
{
  "status": "idle" | "starting" | "live" | "stale" | "error",
  "armed": true,                       // live polling switched on
  "armed_until": "2026-10-11T23:30:00+00:00" | null,
  "updated_at": "…iso…" | null,        // when GC data was last fetched
  "age_s": 5 | null,
  "error": null | "gc_http_403" | "no_game_found" | …,  // short code, never a message from GC
  "field": {"width": 320, "height": 320, "home": [160, 292]},
  "game": null | {
    "opponent": "Riptide Rebels",
    "sharks_home": false,
    "inning": 3, "half": "top" | "bottom",
    "outs": 0, "balls": 2, "strikes": 1,
    "score": {"sharks": 7, "opponent": 13},
    "sharks_batting": false,
    "bases": {"1": Player | null, "2": Player | null, "3": Player | null},
    "pitcher": Player | null,
    "last_play": "Walk"
  },
  "batter": null | BatterCard,
  "on_deck": null | BatterCard
}

Player = {"id": "…", "name": "First Last", "number": "7" | "", "team": "sharks" | "opponent" | null}

BatterCard = Player + {
  "today":   [{"inning": 1, "result": "Walk"}],          // this game, in order
  "history": {"games": 2, "pa": 5, "hits": 2, "in_play": 3},
  "spray":   [{"x": 211, "y": 138, "result": "Single", "hit": true,
               "play_type": "fly_ball" | "ground_ball" | "hard_ground_ball" | "line_drive" | …,
               "today": true, "date": "2026-10-11"}]
}
```

**Status meanings**

| Status | Meaning |
|---|---|
| `idle` | Not armed. `game` may still hold the last game (up to 6 h old) as a final. |
| `starting` | Armed, but no data has arrived since arming. |
| `live` | Data is 60 s old or less. |
| `stale` | Data is older than 60 s. |
| `error` | The worker hit a GC failure and stopped polling. It fails closed. |

**Spray coordinates** use GameChanger's field frame:

- The frame is roughly 320 × 320, with home plate at `field.home`, bottom centre.
- Smaller x is the third-base / left-field side.
- The foul lines run at 45° from home.
- A point marks where the fielder made the play, not where the ball landed.

**Write endpoints** take the team session plus the write token (`X-Dugout-Token`). Both are rate-limited by the existing mutating-request limiter.

- `POST /api/live/arm` with body `{"hours": 3}` (clamped to 0.25–4) starts polling. It returns `{"armed": true, "armed_until": …}`.
- `POST /api/live/disarm` stops polling.

**`GET /api/live/status`** needs no auth, so the Pi can be checked with curl. It returns counts and codes only: `armed`, `armed_until`, `last_poll_at`, `last_poll_age_s`, `last_http`, `events_seen`, `phase`, `error`.
