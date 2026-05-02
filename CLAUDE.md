# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Dugout is a deterministic softball analyzer for **The Sharks** (PCLL). It ingests
GameChanger CSV exports, runs formula-driven SWOT and lineup engines, and serves
the results through a React PWA dashboard used in-dugout. The Constitution
(`gemini.md`) defines schemas and behavioral rules; `guardrails.md` is the
running log of confirmed failure patterns (SIGNs).

---

## Commands

### Setup

```bash
make install-dev          # creates .venv, installs requirements-dev.txt
cd client && npm ci       # frontend deps
```

### Test (Python)

```bash
make test                                       # full pytest run
.venv/bin/pytest tests/test_lineup_optimizer.py # one file
.venv/bin/pytest -k swot                        # by keyword
.venv/bin/pytest -m "not slow"                  # skip network/slow tests
make cov                                        # coverage (term + xml)
make cov-html                                   # coverage (htmlcov/)
```

`pytest.ini` declares the `slow` and `property` markers; `tests/conftest.py`
prepends the repo root and `tools/` to `sys.path` so backend modules import
without a package install.

### Lint / build (frontend, in `client/`)

```bash
npm run lint              # eslint .
npm run build             # runs `sync:data` then `vite build`
npm run preview           # serve the built bundle
VITE_SKIP_DATA_SYNC=1 npm run build   # Docker build path; data is volume-mounted at runtime
```

`predev` and `prebuild` invoke `client/scripts/sync_data.js`, which copies
`data/sharks/{team,team_merged,swot_analysis,lineups,practice_insights}.json`
into `client/public/data/sharks/`. Forgetting this is the most common dev-loop
break: the PWA boots against stale snapshots until the script reruns.

### Run locally

```bash
npm run dev               # Vite on 0.0.0.0; proxies /api → http://localhost:5000
python tools/sync_daemon.py   # dev Flask app, exposes /api/* on :5000
make run                  # ⚠ legacy: gunicorn api:app on :8000 — NOT what production runs
```

Production binds `gunicorn ... sync_daemon:app` on `:5000` (see
`docker-compose.sharks.yml`). The Makefile `run` target predates the daemon
and is kept only as a local convenience — don't use it to reproduce prod
behavior.

### Ingest / pipelines

```bash
python tools/gc_ingest_pipeline.py --csv <export.csv>
python tools/gc_ingest_pipeline.py --csv <export.csv> --scorebook <pdf>
python tools/lineup_optimizer.py
python tools/swot_analyzer.py
python tools/practice_gen.py
python tools/opcheck.py                   # health probe of /api/* (default: dugout.joelycannoli.com)
python tools/autopull/cli.py pull         # scheduled CSV pull (Pi)
python tools/notebooklm_sync.py
modal deploy tools/modal_app.py
```

### Deploy

```bash
docker compose -f docker-compose.sharks.yml up -d   # Pi: 4-container stack
docker compose -f docker-compose.sharks.yml build   # local image build
```

`.github/workflows/build-deploy.yml` builds and pushes multi-arch
(`linux/arm64`, `linux/amd64`) images to `ghcr.io/anchorgroupops/sharks-{dashboard,api}`
on every push to `main`. Watchtower polls GHCR every 60 s and rolls the
running containers on the Pi.

### CI smoke commands

What `.github/workflows/ci.yml` runs on each PR — reproduce locally before
pushing:

```bash
# lint job
cd client && npm ci && npm run lint

# build job
cd client && npm ci && VITE_SKIP_DATA_SYNC=1 npm run build

# python-check job
pip install -r requirements-dev.txt
python -c "import py_compile; py_compile.compile('tools/sync_daemon.py', doraise=True)"
pytest --cov=. --cov-config=.coveragerc --cov-report=term-missing --cov-report=xml
```

The `py_compile` line is the hard smoke gate on `sync_daemon.py` (~6k lines) —
keep it importable.

---

## Self-Improvement Loop (Modify-Verify-Harvest)

From `gemini.md`. Every non-trivial change:

1. **Modify** one file or logic block.
2. **Verify** with a deterministic command — `pytest`, `python tools/opcheck.py`,
   `npm run lint`, or `npm run build`. Pass/fail only; no subjective judgement.
3. **Harvest** — if green, commit and append one line to `progress.md`. If red,
   log the failure as a new SIGN in `guardrails.md` and reset.

For stuck loops: `tools/ralph.sh <verify_cmd> [max_iterations]` runs the cycle
automatically and logs each pass to `progress.md`. It exits on the first green
verify or after `max_iterations` with a manual-review flag.

If a rule in `gemini.md` contradicts observed code, propose a diff to the user
before editing the Constitution. Never silently mutate it.

---

## Architecture (appendix)

Three cooperating layers:

1. **Python backend** (`tools/`) — atomic CLI scripts plus
   `tools/sync_daemon.py`, the Flask app gunicorn serves on `:5000`. Hosts
   every `/api/*` endpoint the dashboard hits (`/api/team`, `/api/games`,
   `/api/availability`, `/api/standings`, `/api/sync/status`, `/api/run`,
   `/api/health`) and dispatches the autopull worker.
2. **React PWA** (`client/`) — Vite + React 19. Reads JSON snapshots from
   `client/public/data/sharks/` (synced at build/dev time) and falls back to
   live `/api/*` calls proxied to `localhost:5000`.
3. **Docker / Pi deployment** — `docker-compose.sharks.yml` runs four
   containers: `sharks_dashboard` (nginx, port `127.0.0.1:3000:8080`),
   `sharks_api` (gunicorn `sync_daemon:app` on `:5000`), `sharks_sync` (same
   image with `RUN_API_SERVER=0`, background ingest), and `watchtower` (GHCR
   poller). The two Python services share `./data` and `./logs` bind mounts,
   so the API serves whatever the sync worker just wrote. Production target:
   Raspberry Pi at `dugout.joelycannoli.com`.

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

Atomic-script directory; each top-level `*.py` is either a CLI entrypoint or a
single-purpose engine. Notable modules:

- `sync_daemon.py` — Flask app + background scheduler; production
  service-of-record.
- `gc_ingest_pipeline.py` — chains `gc_csv_ingest` → `swot_analyzer` →
  `lineup_optimizer` → writes to `data/sharks/`.
- `swot_analyzer.py` / `lineup_optimizer.py` / `practice_gen.py` —
  formula-driven engines. Formulas live in `architecture/swot_analysis_sop.md`
  and `architecture/lineup_rules_sop.md`, not in code comments.
- `autopull/` — scheduled headless CSV download (Playwright + Gmail 2FA reader
  + LLM-adaptive locator fallback). The only sanctioned browser automation
  against gc.com.
- `team_registry.py` + `config/teams.yaml` — multi-team source-of-truth.
  Adding a team is a YAML append, not a code branch.
- `announcer_*.py` — walk-up music + TTS (ElevenLabs / Replicate / Edge TTS /
  Kokoro fallback chain) for in-game announcer mode.

Many `tools/gc_*.py` files (`gc_har_capture`, `gc_pbp_scraper`,
`gc_full_scraper`, `gc_player_scraper`, etc.) are diagnostic captures
deprecated by the CSV-first policy and excluded from coverage in
`.coveragerc`.

### Frontend (`client/src/`)

- `App.jsx` is the shell: tab routing, sync progress bar, online/offline
  badge, install prompt, data hydration. Heavy components are
  `lazyWithRetry`-loaded (chunk hash invalidation falls back to reload).
- `components/` — one file per dashboard tab (`Roster`, `Lineup`,
  `Scoreboard`, `Swot`, `Games`, `League`, `Practice`, `Scouting`,
  `Announcer`, `OpponentFieldMap`, `RosterManager`).
- `utils/` — `apiClient.js` (fetch backoff), `usePWAInstall.js`,
  `useOnlineStatus.js`, `lazyWithRetry.js`, `usePrebuffer.js` (announcer
  audio), `audioController.js`, `formatDate.js`.
- `services/SpotifyService.js` — walk-up music integration.
- `client/ios/` — Capacitor wrapper for the iOS build.

### PWA / Service Worker

`client/vite.config.js` configures `vite-plugin-pwa` with
`registerType: 'autoUpdate'` and **manual** `injectRegister: null`
(registration is wrapped in `main.jsx` to clean stale SWs). Workbox
strategies:

- JS/CSS chunks → `NetworkFirst` (3 s timeout) — prevents stale-hash
  cascades after a deploy.
- Images / fonts → `CacheFirst`.
- `/announcer-clips/`, `/audio/music/`, `/audio/walkup/` → `CacheFirst` with
  range-request support; clips are immutable per slug.
- `/api/*` and `*.json` → `NetworkFirst` (5 s timeout, 24 h cache).
