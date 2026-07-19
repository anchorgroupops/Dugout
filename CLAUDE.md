# CLAUDE.md — Dugout

**North Star:** Maximize win probability for The Sharks by turning GameChanger stats into formula-driven lineup decisions and targeted training plans.

Deterministic softball analyzer and training aid for The Sharks (PCLL). Ingests GameChanger CSV exports to perform SWOT analysis per player and team, optimize batting lineups, and generate targeted practice plans — all surfaced through a mobile-first web dashboard for dugout use.

---

## Operating Principles (Karpathy)
- **Data First**: define schemas and data contracts before writing code
- **Surgical Changes**: only touch what was explicitly asked — no unrequested cleanup
- **Simplicity First**: simplest working solution; no premature abstractions
- **Goal-Driven**: validate output against North Star before declaring done
- **One Task Per Message**: single clear purpose per prompt yields better results

---

## Rule Hierarchy
1. `gemini.md` — Project Constitution: North Star, data schemas, behavioral rules, and architecture (PRIMARY — do not silently mutate; show diff before any change)
2. `CLAUDE.md` — Operational context (this file)
3. `guardrails.md` — Living record of confirmed failure SIGNs; **consult before every session**

---

## Stack
- **Backend**: Python (tools/ scripts, Modal serverless deploy)
- **Frontend**: Vite/React PWA (`client/`) — mobile-first, Capacitor for iOS
- **Automation**: n8n workflows, Modal schedules
- **Data Source**: GameChanger CSV exports only

---

## Project Structure
```
gemini.md                    # Constitution — schemas, north star, behavioral rules
guardrails.md                # Known failure patterns (SIGNs) — read before each session
tools/gc_ingest_pipeline.py  # PRIMARY entry point after every game (CSV ingestion)
tools/lineup_optimizer.py    # Batting order generator (deterministic, formula-driven)
tools/swot_analyzer.py       # SWOT engine for players and team
tools/practice_gen.py        # Targeted practice plan generator
tools/opcheck.py             # Daemon health + data freshness check
tools/autopull/              # ONLY permitted browser automation (single CSV-download click, Pi-scheduled)
tools/notebooklm_sync.py     # Syncs ingested data to NotebookLM notebooks
tools/modal_app.py           # Modal serverless app deploy
client/                      # Vite/React PWA frontend (mobile-first dugout UI)
data/sharks/                 # Sharks-only ingested data (NEVER mix with opponents)
data/opponents/              # Opponent data (NEVER mix with sharks)
```

---

## Core Commands
```bash
python tools/opcheck.py                                         # Health check — run first
python tools/gc_ingest_pipeline.py --csv <path/to/export.csv>  # After every game
python tools/lineup_optimizer.py                               # Generate batting order
python tools/practice_gen.py                                   # Generate practice plan
python tools/autopull/cli.py pull                              # Pi-scheduled CSV pull
python tools/notebooklm_sync.py                                # Sync to NotebookLM
modal deploy tools/modal_app.py                                # Deploy to Modal
npm run dev        # (from client/) Local frontend dev server
npm run build      # (from client/) Production build — verify dist/manifest.webmanifest exists (SIGN-002)
```

---

## Working Rules
1. **CSV-First**: GameChanger CSV export is the sole data source — run `gc_ingest_pipeline.py` after every game; no live-page scraping beyond the single autopull click
2. **Deterministic only**: SWOT analysis and lineup recommendations must be formula-driven; never use LLM judgment for on-field decisions
3. **Data separation**: Sharks data goes to `data/sharks/`, opponents to `data/opponents/` — never mixed in storage or NotebookLM notebooks (SIGN-006)
4. **Use pathlib.Path or env vars** for all file paths — never hardcode Windows drive letters like `H:\` or `C:\` (SIGN-004)
5. **One scraper per function**: audit `tools/` for existing variants before adding any new scraper; consolidate first (SIGN-005)

---

## What NOT to Do
- Never write, modify, or delete any data on GameChanger (gc.com) — all access is strictly read-only
- Do not add NotebookLM Librarian code, YouTube fetchers, BlueStacks/Frida/ADB tools, or any non-softball tooling to this repo
- Do not run automated browser scraping of live GC pages — only the single CSV-download click in `tools/autopull/` is permitted
- Do not silently mutate `gemini.md` (the Constitution) — show the user a diff before any proposed change
- Do not commit `.env` files, `node_modules/`, `.venv/`, or build artifacts

---

## Available Skills (global `~/.claude/skills/`)
- `n8n-workflow-reviewer` — structured 5-category audit of n8n workflow JSON
- `n8n-code-javascript` / `n8n-code-python` — Code node patterns and gotchas
- `n8n-expression-syntax` — Expression syntax reference and common mistakes
- `n8n-mcp-tools-expert` / `n8n-node-configuration` / `n8n-validation-expert` / `n8n-workflow-patterns` — Full n8n toolkit
- `audit-website-skill` — Website quality audit
- `infinite-memory` — Pinecone vector memory for long-term recall
- `front-end-qa-auditor` — Frontend quality review
- `session-wrap-up` — end-of-session ritual: store decisions to NotebookLM, update memory.md
- `dream` — nightly memory consolidation (auto-runs via .dream-pending flag)

---

## Self-Improvement Rule
When you make a mistake that should not repeat, update this file immediately with a rule to prevent it. Keep this file under 200 lines.


## Available Skills
- **/grill-me** — checkpoint-to-disk interview: extract plan/design from your head before building. One question at a time, every answer saved immediately.
