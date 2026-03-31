# CLAUDE.md — Dugout (Sharks Softball Dashboard)

## Project Goal
Deterministic softball analyzer and training aid for **The Sharks** (PCLL). Maximize win probability through GameChanger data scraping, SWOT analysis, and lineup optimization.

**Live at**: https://dugout.joelycannoli.com

## Architecture
- **Client**: React 19 + Vite 7 + PWA (installable) + Capacitor (iOS)
- **API**: Python Flask via Gunicorn (sync_daemon.py)
- **Data Pipeline**: GameChanger scraping → stats normalization → SWOT/Lineup/Matchup
- **Deploy**: GitHub Actions → GHCR → Watchtower auto-pull on Raspberry Pi
- **Domain**: dugout.joelycannoli.com → Cloudflare tunnel → Pi:3000

## Core Commands
- **Dev (frontend)**: `cd client && npm run dev` (port 5173)
- **Dev (API)**: `cd tools && python sync_daemon.py` (port 5000)
- **Build**: `cd client && npm run build`
- **Lint**: `cd client && npx eslint src/`
- **Deploy**: Push to `main` — GitHub Actions builds images, Watchtower auto-pulls
- **Run Scraper**: `python tools/gc_scraper.py`
- **Optimize Lineup**: `python tools/lineup_optimizer.py`
- **Generate Practice**: `python tools/practice_gen.py`

## Development Patterns
- **Read-Only GC**: Follow Playwright patterns for `web.gc.com` access.
- **Deterministic**: All SWOT and lineup outcomes must be formula-driven.
- **Mobile-First**: Frontend components must be responsive for dugout use.
- **PWA**: App is installable on phones. Service worker caches API data offline.
