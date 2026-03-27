# Project Constitution: Softball (Strategy & Training)

## The North Star

Use GameChanger statistics to build a comprehensive softball analyzer and training aid for **The Sharks** (PCLL). Perform SWOT analysis per player and team, optimize batting orders, develop targeted training regimens, and maximize improvement and win probability.

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

1. **GameChanger (gc.com)**: Primary data source. Browser automation via Playwright to scrape stats from `web.gc.com`.
2. **Google Docs**: Practice plans are maintained in a shared Google Doc. New practices should be appended.
3. **NotebookLM**: All scraped GC data pushed here, categorized by team (Sharks vs opponents).
4. **Web App**: Simple frontend for viewing SWOT analysis, lineup recommendations, and training plans.

## Behavioral Rules

1. **🚨 READ-ONLY on gc.com**: NEVER modify, delete, or write any data on GameChanger. All access is strictly read-only (scraping/exporting). Any write action requires EXPLICIT Q&A approval from the user — a button click is NOT sufficient.
2. **PCLL Compliance**: Must respect Palm Coast Little League rules (mandatory play, pitching, batting order).
3. **Data Separation**: Sharks data and opponent data must NEVER be mixed in storage or NotebookLM.
4. **Regular Updates**: System should check GC for new game data on a schedule (post-game).
5. **Real-Time During Games**: Compile and analyze data during and immediately after games.
6. **Deterministic Analysis**: SWOT analysis and lineup recommendations must be formula-driven, not guessed.
7. **Training Alignment**: Recommended training areas must directly map to identified weaknesses.

## Architecture

```text
h:/Repos/Personal/Softball/
├── gemini.md              # This file (Constitution)
├── .env                   # GC credentials, API keys
├── architecture/          # SOPs and strategy docs
├── tools/                 # Python scripts (scrapers, analyzers)
│   ├── gc_scraper.py      # GameChanger browser automation
│   ├── swot_analyzer.py   # SWOT analysis engine
│   ├── lineup_optimizer.py # Batting order generator
│   └── practice_gen.py    # Training plan generator
├── client/                # Web app (Vite)
├── data/                  # Exported/scraped data (JSON/CSV)
│   ├── sharks/            # Our team data
│   └── opponents/         # Opponent data
└── .tmp/                  # Intermediates
```
