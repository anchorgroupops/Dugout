# CLAUDE.md - Dugout (Softball Strategy Dashboard)

## Project Goal
**Dugout** is a team-agnostic, deterministic softball analyzer and training aid. It works for any team — configure yours via the `TEAM_NAME` env var (defaults to "The Sharks"). Maximize win probability through GameChanger data scraping, SWOT analysis, and lineup optimization.

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
- **Modal Deploy**: `modal deploy tools/modal_app.py`

## Rule Hierarchy
- **Primary**: `gemini.md` (Constitution).
- **Secondary**: `CLAUDE.md` (Operational context).

## Development Patterns
- **Read-Only GC**: Follow Playwright patterns for `web.gc.com` access.
- **Deterministic**: All SWOT and lineup outcomes must be formula-driven.
- **Mobile-First**: Frontend components must be responsive for dugout use.
- **Team-Agnostic**: Use `TEAM_NAME` / `TEAM_SLUG` env vars instead of hardcoding team names.
