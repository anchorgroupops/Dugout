# Project Constitution: Softball (Strategy & Training)

## The North Star

Use GameChanger statistics to build a comprehensive softball analyzer and training aid for **The Sharks** (PCLL). Perform SWOT analysis per player and team, optimize batting orders, develop targeted training regimens, and maximize improvement and win probability.

## B.L.A.S.T. Strategy (Blueprint, Link, Architect, Stylize, Trigger)

1. **Blueprint**: This `gemini.md` file defines the North Star, schemas, and guardrails.
2. **Link**: Data pipelines connect GameChanger CSV exports to NotebookLM and Pinecone.
3. **Architect**: A.N.T. structure (Architecture/Navigation/Tools).
4. **Stylize**: UI adheres to Anchor Team brand guidelines (Clear Water, Sandy Shore, Pearl Aqua).
5. **Trigger**: Workflows are triggered by Modal schedules or user requests.

## Data Schemas

### Player Schema

```json
{
  "id": "string",
  "name": "string",
  "number": "integer",
  "position_primary": "string",
  "positions_secondary": ["string"],
  "stats": {
    "hitting": {
      "ab": "integer", "h": "integer", "bb": "integer", "k": "integer",
      "hbp": "integer", "rbi": "integer", "runs": "integer",
      "doubles": "integer", "triples": "integer", "hr": "integer",
      "sb": "integer", "cs": "integer",
      "ba": "float", "obp": "float", "slg": "float", "ops": "float"
    },
    "pitching": {
      "ip": "float", "er": "integer", "k": "integer", "bb": "integer",
      "w": "integer", "l": "integer",
      "era": "float", "whip": "float"
    },
    "fielding": {
      "po": "integer", "a": "integer", "e": "integer",
      "fielding_pct": "float"
    }
  },
  "swot": {
    "strengths": ["string"],
    "weaknesses": ["string"],
    "opportunities": ["string"],
    "threats": ["string"]
  }
}
```

### Team Schema

```json
{
  "team_name": "string",
  "league": "PCLL",
  "division": "string",
  "season": "Spring 2026",
  "is_own_team": "boolean",
  "roster": ["Player"],
  "record": { "w": "integer", "l": "integer", "t": "integer" },
  "games": ["Game"],
  "team_swot": {
    "strengths": ["string"],
    "weaknesses": ["string"],
    "opportunities": ["string"],
    "threats": ["string"]
  }
}
```

### Game Schema

```json
{
  "game_id": "string",
  "date": "ISO8601",
  "opponent": "string",
  "location": "string",
  "result": "W|L|T",
  "score_us": "integer",
  "score_them": "integer",
  "box_score": {},
  "gc_url": "string"
}
```

## Integrations

1. **GameChanger (gc.com)**: Primary data source. CSV exports downloaded manually from the gc.com stats page. No browser automation or API scraping.
2. **Google Docs**: Practice plans are maintained in a shared Google Doc. New practices should be appended.
3. **NotebookLM**: All ingested GC data pushed here, categorized by team (Sharks vs opponents).
4. **Web App**: Simple frontend for viewing SWOT analysis, lineup recommendations, and training plans.

## Behavioral Rules

1. **🚨 READ-ONLY on gc.com**: NEVER modify, delete, or write any data on GameChanger. All access is strictly read-only (scraping/exporting). Any write action requires EXPLICIT Q&A approval from the user — a button click is NOT sufficient.
2. **PCLL Compliance**: Must respect Palm Coast Little League rules (mandatory play, pitching, batting order).
3. **Data Separation**: Sharks data and opponent data must NEVER be mixed in storage or NotebookLM.
4. **Regular Updates**: Export a fresh CSV from gc.com after each game and run the ingestion pipeline. No automated scraping.
5. **Real-Time During Games**: Compile and analyze data during and immediately after games.
6. **Deterministic Analysis**: SWOT analysis and lineup recommendations must be formula-driven, not guessed.
7. **Training Alignment**: Recommended training areas must directly map to identified weaknesses.

## Architecture: A.N.T. (3 Layers)

1.  **Architecture**: SOPs and strategy documented in `architecture/` and `gemini.md`.
2.  **Navigation**: Agentic orchestration to process data and generate insights.
3.  **Tools**: Atomic Python scripts in `tools/` (scrapers, memory, optimizers).

## Self-Improvement Protocol (Karpathy Loop)

Every non-trivial change must follow the **Modify-Verify-Harvest** cycle:

1. **Change** — Modify exactly one file or logic block per iteration.
2. **Measure** — Run a deterministic command (e.g. `python tools/opcheck.py` or `pytest`). Pass/fail only. No subjective judgement.
3. **Harvest** — If the variant beats the baseline, commit to Git as the new baseline and append a one-line note to `progress.md`. If it fails, log to `guardrails.md` as a new SIGN and reset.

**Guardrails:** `guardrails.md` is the living record of confirmed failure patterns. Consult it before every session. Never repeat a SIGN.

**Self-Evolution Authorization:** If this Constitution (`gemini.md`) contains a rule that contradicts observed codebase reality, this agent is authorized to propose an edit to this file. The proposal must be surfaced to the user as a diff before committing. Never silently mutate the Constitution.

**Ralph Loop:** For stuck failures, run `tools/ralph.sh <verify_cmd> [max_iterations]`. Each iteration logs to `progress.md`. Loop exits on first pass or after max iterations with a manual-review flag.

**Anti-Gravity Skills:** Global Gemini skills reside in `~/.gemini/antigravity/skills/`. Reference `audit-website`, `UIUX Pro`, and the W.R.A.P.S. orchestrator for complex multi-step workflows.

**NotebookLM Second Brain:** Use `tools/notebooklm_sync.py` or the NotebookLM MCP to retrieve research context without expanding the working context window. Push all GC-ingested data here after each game.

## Directory Structure

```text
h:/Repos/Personal/Softball/
├── gemini.md              # This file (Constitution)
├── .env                   # GC credentials, API keys
├── architecture/          # SOPs and strategy docs
├── tools/                 # Python scripts (analyzers, optimizers)
│   ├── gc_ingest_pipeline.py  # CSV ingestion pipeline orchestrator
│   ├── gc_csv_ingest.py       # GC CSV → team.json parser
│   ├── scorebook_ocr.py       # Scorebook PDF/image parser (optional)
│   ├── swot_analyzer.py       # SWOT analysis engine
│   ├── lineup_optimizer.py    # Batting order generator
│   └── practice_gen.py        # Training plan generator
├── client/                # Web app (Vite)
├── data/                  # Exported/scraped data (JSON/CSV)
│   ├── sharks/            # Our team data
│   └── opponents/         # Opponent data
└── .tmp/                  # Intermediates
```
