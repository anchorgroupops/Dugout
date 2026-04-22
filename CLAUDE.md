# CLAUDE.md - Softball Project (The Sharks)

## Project Goal
Deterministic softball analyzer and training aid for **The Sharks** (PCLL). Maximize win probability through GameChanger CSV ingestion, SWOT analysis, and lineup optimization.

## Architecture: A.N.T. (Architecture, Navigation, Tools)
- **Architecture**: Logic governed by `gemini.md`.
- **Navigation**: Orchestrated via n8n and Agentic workflows.
- **Tools**: Atomic Python scripts in `tools/` (scrapers, analyzers, optimizers).

## Core Commands
- **Install Dependencies**: `pip install -r requirements.txt`
- **Run Opcheck**: `python tools/opcheck.py`
- **Ingest CSV**: `python tools/gc_ingest_pipeline.py --csv <path/to/export.csv>`
- **Ingest CSV + Scorebook**: `python tools/gc_ingest_pipeline.py --csv <path> --scorebook <path>`
- **Optimize Lineup**: `python tools/lineup_optimizer.py`
- **Generate Practice**: `python tools/practice_gen.py`
- **NotebookLM Sync**: `python tools/notebooklm_sync.py`
- **Modal Deploy**: `modal deploy tools/modal_app.py`

## Rule Hierarchy
- **Primary**: `gemini.md` (Constitution).
- **Secondary**: `CLAUDE.md` (Operational context).

## Development Patterns
- **CSV-First**: GameChanger CSV export is the primary data source. Browser
  automation is permitted ONLY for the single CSV-download click in
  `tools/autopull/` (scheduled, self-healing, on the Pi). No scraping of
  live pages, play-by-play, or opponent stats beyond this flow.
- **Scorebook Optional**: Scorebook image/PDF parsing is a low-priority supplement via `tools/scorebook_ocr.py`.
- **Deterministic**: All SWOT and lineup outcomes must be formula-driven.
- **Mobile-First**: Frontend components must be responsive for dugout use.
