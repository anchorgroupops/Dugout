# CLAUDE.md - Softball Project (The Sharks)

## Project Goal
Deterministic softball analyzer and training aid for **The Sharks** (PCLL). Maximize win probability through GameChanger data scraping, SWOT analysis, and lineup optimization.

## Architecture: A.N.T. (Architecture, Navigation, Tools)
- **Architecture**: Logic governed by `gemini.md`.
- **Navigation**: Orchestrated via n8n and Agentic workflows.
- **Tools**: Atomic Python scripts in `tools/` (scrapers, analyzers, optimizers).

## Core Commands
- **Install Dependencies**: `pip install -r requirements.txt`
- **Run Opcheck**: `python tools/opcheck.py`
- **Run Scraper**: `python tools/gc_scraper.py`
- **Optimize Lineup**: `python tools/lineup_optimizer.py`
- **Generate Practice**: `python tools/practice_gen.py`
- **NotebookLM Sync**: `python tools/notebooklm_sync.py`
- **Night Shift (full)**: `python tools/night_shift.py`
- **Night Shift (single stage)**: `python tools/night_shift.py --stage scrape`
- **Night Shift (dry run)**: `python tools/night_shift.py --dry-run`
- **Night Shift (Docker)**: `docker compose -f docker-compose.sharks.yml --profile night-shift run sharks_night_shift`
- **Modal Deploy**: `modal deploy tools/modal_app.py`

## Rule Hierarchy
- **Primary**: `gemini.md` (Constitution).
- **Secondary**: `CLAUDE.md` (Operational context).

## Development Patterns
- **Read-Only GC**: Follow Playwright patterns for `web.gc.com` access.
- **Deterministic**: All SWOT and lineup outcomes must be formula-driven.
- **Mobile-First**: Frontend components must be responsive for dugout use.
