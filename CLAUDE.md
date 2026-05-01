# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: Dugout — Softball Analyzer for The Sharks (PCLL)

Deterministic softball analyzer and training aid. Ingests GameChanger CSV
exports, produces per-player and per-team SWOT, generates PCLL-compliant
batting orders, and serves it through a React PWA dashboard for in-dugout use.

The repo runs as three cooperating layers:

1. **Python backend** (`tools/`) — atomic CLI scripts plus `tools/sync_daemon.py`,
   a long-running Flask app served by gunicorn on port `5000`. `sync_daemon.py`
   exposes the `/api/*` endpoints the dashboard consumes; it also owns CSV
   ingest scheduling and the GC autopull pipeline.
2. **React PWA** (`client/`) — Vite + React 19 app. Reads JSON snapshots from
   `client/public/data/sharks/` (synced at build/dev time from `data/sharks/`)
   and falls back to live `/api/*` calls proxied to `localhost:5000`.
3. **Docker / Pi deployment** (`docker-compose.sharks.yml`, `deploy/`,
   `scripts/`) — three containers (`sharks_dashboard` nginx, `sharks_api`
   gunicorn, `sharks_sync` ingest worker) plus Watchtower auto-update from
   GHCR. Production target is a Raspberry Pi reachable at
   `dugout.joelycannoli.com`.

## Rule Hierarchy

1. **Constitution** — `gemini.md`. Defines schemas, integrations, behavioral
   rules. Authoritative.
2. **Operational** — this file (`CLAUDE.md`).
3. **Guardrails** — `guardrails.md` lists confirmed failure patterns
   (SIGN-001…). Read before acting; do not repeat a SIGN.
4. **Session memory** — `project-memory/softball/` (and the duplicate root
   files `task_plan.md`, `findings.md`, `progress.md`).

## Core Commands

### Python backend

```bash
# Dev environment (creates .venv, installs requirements-dev.txt)
make install-dev

# Tests
make test                                       # full pytest run
.venv/bin/pytest tests/test_lineup_optimizer.py # one file
.venv/bin/pytest -k swot                        # by keyword
.venv/bin/pytest -m "not slow"                  # skip network/slow tests
make cov                                        # coverage (term + xml)
make cov-html                                   # coverage (htmlcov/)

# Run the API locally
make run                                        # gunicorn -b 0.0.0.0:8000 api:app
# (note: production binds sync_daemon:app on :5000 — see docker-compose)
python tools/sync_daemon.py                     # direct, dev mode

# Pipelines
python tools/gc_ingest_pipeline.py --csv <export.csv>
python tools/gc_ingest_pipeline.py --csv <export.csv> --scorebook <pdf>
python tools/lineup_optimizer.py
python tools/swot_analyzer.py
python tools/practice_gen.py
python tools/opcheck.py                         # health probe of /api/*
python tools/autopull/cli.py pull               # scheduled CSV pull (Pi)
python tools/notebooklm_sync.py
modal deploy tools/modal_app.py
```

Production runtime (`docker-compose.sharks.yml`) runs gunicorn against
`sync_daemon:app`, **not** `api:app`. The Makefile `run` target is a legacy
local convenience.

### Frontend (`client/`)

```bash
cd client
npm ci
npm run dev        # vite on 0.0.0.0; proxies /api → localhost:5000
npm run build      # runs sync:data then vite build
npm run lint       # eslint .
npm run preview
```

`predev` and `prebuild` invoke `client/scripts/sync_data.js`, which copies
`data/sharks/{team,team_merged,swot_analysis,lineups,practice_insights}.json`
into `client/public/data/sharks/`. In Docker builds set
`VITE_SKIP_DATA_SYNC=1` (data is volume-mounted at runtime).

### CI

`.github/workflows/ci.yml` runs three jobs on pushes/PRs to `main`: client
lint, client build (with `VITE_SKIP_DATA_SYNC=1`), and Python pytest with
coverage. `python -c "import py_compile..."` is the smoke gate for
`sync_daemon.py` — keep that file importable.

## Architecture

### Data flow

```
GameChanger CSV (manual export OR tools/autopull)
      ↓
tools/gc_csv_ingest.py        (parse rows → normalized stats)
      ↓
tools/gc_ingest_pipeline.py   (orchestrator: ingest → SWOT → lineups)
      ↓
data/sharks/*.json            (team.json, swot_analysis.json, lineups.json…)
      ↓                                          ↓
client/scripts/sync_data.js              tools/sync_daemon.py /api/*
      ↓                                          ↓
client/public/data/sharks/*.json         React PWA fetch
      ↓
client/src/App.jsx + components/
```

### Backend (`tools/`)

`tools/` is an atomic-script directory. Each top-level `*.py` file is either
a CLI entrypoint or a single-purpose engine. The notable ones:

- `sync_daemon.py` (~6k lines) — Flask app + background scheduler. Hosts every
  `/api/*` endpoint the dashboard hits (`/api/team`, `/api/games`,
  `/api/availability`, `/api/standings`, `/api/sync/status`, `/api/run`,
  `/api/health`, etc.) and dispatches the autopull worker. This is the
  service-of-record for production.
- `gc_ingest_pipeline.py` — chains `gc_csv_ingest` → `swot_analyzer` →
  `lineup_optimizer` → writes to `data/sharks/`.
- `swot_analyzer.py` / `lineup_optimizer.py` / `practice_gen.py` —
  formula-driven engines. Lineup formulas live in
  `architecture/lineup_rules_sop.md`; SWOT thresholds in
  `architecture/swot_analysis_sop.md`.
- `autopull/` — scheduled headless CSV download (Playwright + Gmail 2FA
  reader + LLM-adaptive locator fallback). The **only** sanctioned browser
  automation against gc.com.
- `team_registry.py` + `config/teams.yaml` — multi-team source-of-truth.
  Adding a team means appending a YAML entry, not branching code.
- `announcer_*.py` — walk-up music + TTS (ElevenLabs / Replicate / Edge TTS
  / Kokoro fallback chain) for in-game announcer mode.

Many `tools/gc_*.py` files (`gc_har_capture`, `gc_pbp_scraper`,
`gc_full_scraper`, `gc_player_scraper`, etc.) are diagnostic captures and
**deprecated** by the CSV-first policy. They're excluded from coverage in
`.coveragerc`. Don't add new variants — see SIGN-005.

### Frontend (`client/src/`)

- `App.jsx` is the shell: tab routing, sync progress bar, online/offline
  badge, install prompt, data hydration. Heavy components are
  `lazyWithRetry`-loaded (chunk hash invalidation falls back to reload).
- `components/` — one file per dashboard tab (`Roster`, `Lineup`,
  `Scoreboard`, `Swot`, `Games`, `League`, `Practice`, `Scouting`,
  `Announcer`, `OpponentFieldMap`, `RosterManager`).
- `utils/` — data-fetch backoff (`apiClient.js`), audio prebuffering for the
  announcer, PWA install/online hooks, lazy-load retry helper.
- `services/SpotifyService.js` — walk-up music integration.

### PWA / Service Worker

`vite-plugin-pwa` is configured in `client/vite.config.js` with `registerType:
'autoUpdate'` and **manual** `injectRegister: null` (registration is wrapped
in `main.jsx` so we can clean stale SWs). Workbox strategies:

- JS/CSS chunks → `NetworkFirst` (3s timeout) — prevents stale-hash
  cascades after a deploy.
- Images/fonts → `CacheFirst`.
- `/announcer-clips/`, `/audio/music/`, `/audio/walkup/` → `CacheFirst` with
  range-request support; clips are immutable per slug.
- `/api/*` and `*.json` → `NetworkFirst` (5s timeout, 24h cache).

If you change caching, also verify `dist/manifest.webmanifest` exists after
`npm run build` (SIGN-002).

### Deployment

`docker-compose.sharks.yml` defines four services:

| Service | Image | Role |
|---|---|---|
| `sharks_dashboard` | `ghcr.io/anchorgroupops/sharks-dashboard` | nginx serving Vite build, port `127.0.0.1:3000:8080` |
| `sharks_api` | `ghcr.io/anchorgroupops/sharks-api` | gunicorn `sync_daemon:app` on `:5000` |
| `sharks_sync` | same image, `RUN_API_SERVER=0` | background ingest worker |
| `watchtower` | `containrrr/watchtower` | polls GHCR every 60s for new images |

Both Python services share `./data` and `./logs` bind mounts, so the API
serves whatever the sync worker has just written. `.github/workflows/build-deploy.yml`
builds + pushes multi-arch (`linux/arm64`, `linux/amd64`) images to GHCR on
every push to `main`; Watchtower then rolls them on the Pi.

## Conventions

- **CSV-first.** GameChanger CSV exports are the only sanctioned data source.
  Browser automation is permitted **only** in `tools/autopull/` for the
  single CSV-download click. No live-page scraping, no play-by-play
  scraping, no opponent-stat scraping beyond CSV.
- **Read-only on gc.com.** Never POST/PUT/DELETE. A button click in the UI
  is not authorization — explicit user Q&A is required.
- **Data separation.** Sharks → `data/sharks/`, opponents → `data/opponents/`.
  Never share a JSON file between the two (SIGN-006).
- **Deterministic outputs.** SWOT and lineup logic must be formula-driven
  (see `architecture/swot_analysis_sop.md` and `architecture/lineup_rules_sop.md`).
  No vibes-based bucketing.
- **Cross-platform paths.** Use `pathlib.Path` and env vars. Hardcoded
  Windows drive letters break Pi/Linux deploys (SIGN-004).
- **One scraper per function.** Audit `tools/` before adding a new
  `gc_*` file — consolidate into existing engines (SIGN-005).
- **Mobile-first UI.** Every component is exercised on a phone in the
  dugout. Test responsive breakpoints; the iOS Capacitor wrapper lives in
  `client/ios/`.
- **PCLL compliance.** Lineups must satisfy mandatory-play rules:
  every rostered player gets ≥1 AB and ≥6 consecutive defensive outs;
  continuous batting order. Validation belongs in `lineup_optimizer.py`.

## Things that DO NOT belong in this repo

- NotebookLM Librarian application code (`api.py`, `batch_sync.py`,
  `run_dashboard.py` for the Librarian project). The Librarian is a
  separate project; this repo only consumes its sync output via
  `tools/notebooklm_sync.py`.
- YouTube/web-crawling fetchers unrelated to softball (the walk-up music
  `yt-dlp` flow is the sole exception).
- BlueStacks / Frida / ADB tools. Playwright handles GC automation.
- Hardcoded Windows paths (`H:\Repos\...`, `C:\...`).
- Duplicate scraper variants — consolidate, don't fork.

## Self-Improvement Loop (Modify-Verify-Harvest)

From `gemini.md`. Every non-trivial change:

1. **Modify** one file or logic block.
2. **Verify** with a deterministic command (`pytest`, `python tools/opcheck.py`,
   `npm run lint`, `npm run build`). Pass/fail only.
3. **Harvest** — if green, commit and append one line to `progress.md`. If
   red, log the failure as a new SIGN in `guardrails.md` and reset.

For stuck loops: `tools/ralph.sh <verify_cmd> [max_iterations]` runs the
cycle automatically and logs each pass to `progress.md`.

If a rule in `gemini.md` contradicts observed code, propose a diff to the
user before editing the Constitution. Never silently mutate it.
