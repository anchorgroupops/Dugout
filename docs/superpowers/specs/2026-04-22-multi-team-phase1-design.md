# Multi-Team Dugout — Phase 1: Registry + Autopull + Ingest

**Date:** 2026-04-22
**Status:** Draft — pending user review
**Author:** Claude Code (Opus 4.7) + Joel McKinney
**Depends on:** `2026-04-22-gc-csv-autopull-design.md` (PR #53)
**Follow-on:** Phase 2 (analysis per team), Phase 3 (dashboard switcher) — separate specs

## 1. Goal

Turn the single-team Dugout data pipeline into a multi-team one, without
refactoring analysis or UI yet. After Phase 1 lands:

- A new team is added by editing `config/teams.yaml`; next autopull run
  pulls its CSV and writes `data/<slug>/` in the same shape as
  `data/sharks/` today.
- Each team's run, validation, schema profile, and notifications are
  independent — one team failing doesn't stop the others.
- The existing Sharks data is untouched; behavior with only the Sharks in
  `teams.yaml` is byte-identical to today.
- SWOT, lineup optimizer, stats_db, and the dashboard still target the
  Sharks exclusively — Phase 2 handles those.

Non-goals (Phase 1): per-team SWOT, per-team lineups, per-team dashboard,
per-team opponent tracking refactor, per-team notification channels,
multi-tenancy (multiple users).

## 2. Scope decomposition

Full multi-team Dugout is five subsystems:

1. **Team registry + data layout** — Phase 1
2. **Multi-team autopull** — Phase 1
3. **Multi-team ingest** — Phase 1
4. **Multi-team analysis (SWOT, lineups, stats_db)** — Phase 2
5. **Multi-team dashboard + API** — Phase 3

Each phase ships its own spec, plan, PR, rollout. Phase 1 is the data
capture foundation the others build on.

## 3. Architecture

```
                    ┌──────────────────────┐
                    │  config/teams.yaml   │ (git-tracked, source of truth)
                    └──────────┬───────────┘
                               │ loaded by
                               ▼
                    ┌──────────────────────┐
                    │ tools/team_registry  │  Team dataclass list
                    └──────────┬───────────┘
                               │
              ┌────────────────┼───────────────────┐
              ▼                ▼                   ▼
       ┌────────────┐   ┌────────────┐      ┌────────────┐
       │  autopull  │   │   ingest   │      │ Phase 2/3  │
       │  (loop)    │   │  (per-team)│      │ consumers  │
       └─────┬──────┘   └─────┬──────┘      └────────────┘
             │                │
             ▼                ▼
       data/sharks/     data/dolphins/     (…per team)
       data/<slug>/...
```

### 3.1 New module

`tools/team_registry.py` — the single place team metadata is loaded and
validated. Pure functions + a `Team` dataclass. No side effects.

### 3.2 Changed modules (autopull)

- `tools/autopull/config.py` — drop `gc_team_id`, `gc_season_slug`. Team
  data moves to `teams.yaml`. Config still owns flags and secrets.
- `tools/autopull/cli.py` — `default_runner` becomes a team loop. Pulls
  the registry, filters `active=true`, iterates with a 30-second inter-team
  sleep. Per-team idempotency. One shared Playwright browser, one shared
  session login, one shared LLM budget.
- `tools/autopull/state.py` — `runs` table gains `team_id TEXT`. Indexed.
  `schema_profile` keyed by `(team_id, observed_at)`. `strategies` stays
  shared (the CSV export button is a GC-wide UI, not team-specific).
  Migration: existing `runs` and `schema_profile` rows get `team_id='sharks'`.
- `tools/autopull/notifier.py` — `RunSummary.team_slug` added. Email
  subject and push message include the team name.
- `tools/autopull/weekly_report.py` — summary groups by team.

### 3.3 Changed modules (ingest)

- `tools/gc_csv_ingest.py` — `SHARKS_DIR` singleton becomes a `team_dir`
  parameter. All write paths and the "team_name" default flow from a
  `Team` argument. CLI takes `--team <slug>` (or `--team-config` path).
- `tools/gc_ingest_pipeline.py` — same treatment.

### 3.4 Explicitly untouched in Phase 1

- `tools/swot_analyzer.py`, `tools/lineup_optimizer.py`,
  `tools/practice_gen.py`, `tools/stats_db.py`, `tools/sync_daemon.py`
  (game-state logic), the dashboard frontend, `api.py`. These continue to
  operate on `data/sharks/`. Phase 2 parameterizes them.

## 4. `config/teams.yaml` schema

```yaml
teams:
  - id: NuGgx6WvP7TO             # GC team id (from the web.gc.com URL)
    season_slug: 2026-spring-sharks
    name: The Sharks
    data_slug: sharks              # directory name under data/
    league: PCLL
    is_own_team: true
    active: true

  - id: <second team gc id>
    season_slug: 2026-spring-dolphins
    name: The Dolphins
    data_slug: dolphins
    league: PCLL
    is_own_team: true
    active: true
```

Required fields: `id`, `season_slug`, `name`, `data_slug`, `active`.
Optional: `league` (default `""`), `is_own_team` (default `true`).

### Validation rules

- `data_slug` must match `[a-z0-9_-]+` and be unique across teams.
- `id` must be non-empty and unique.
- `active` is boolean.
- Unknown top-level fields cause a warning (forward compatibility), not a
  failure. Unknown per-team fields cause a warning.
- `teams.yaml` missing entirely: registry returns a synthetic single-team
  list seeded from the legacy env vars (`GC_TEAM_ID`, `GC_SEASON_SLUG`,
  `data_slug=sharks`). Back-compat escape hatch so merging Phase 1 without
  creating `teams.yaml` is non-breaking.

## 5. `Team` dataclass

```python
@dataclass(frozen=True)
class Team:
    id: str
    season_slug: str
    name: str
    data_slug: str
    league: str = ""
    is_own_team: bool = True
    active: bool = True

    @property
    def stats_url(self) -> str:
        return f"https://web.gc.com/teams/{self.id}/{self.season_slug}/stats"
```

## 6. State DB migration

Migration runs on `StateDB.init_schema()`:

```sql
-- runs: add column if missing, backfill
ALTER TABLE runs ADD COLUMN team_id TEXT;
UPDATE runs SET team_id = 'sharks' WHERE team_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_runs_team ON runs(team_id);

-- schema_profile: add column, rebuild PK
CREATE TABLE IF NOT EXISTS schema_profile_v2 (
  team_id TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  column_names_json TEXT NOT NULL,
  row_count INTEGER NOT NULL,
  PRIMARY KEY(team_id, observed_at)
);
INSERT OR IGNORE INTO schema_profile_v2(team_id, observed_at, column_names_json, row_count)
  SELECT 'sharks', observed_at, column_names_json, row_count FROM schema_profile;
DROP TABLE schema_profile;
ALTER TABLE schema_profile_v2 RENAME TO schema_profile;
```

`init_schema` is idempotent — checks for column presence before altering.

## 7. Autopull run flow (multi-team)

```
CLI invoked (cron or postgame)
  ├─ load config, check GC_AUTOPULL_ENABLED
  ├─ load teams = [t for t in team_registry.load() if t.active]
  ├─ check global auth breaker (shared across teams)
  ├─ open ONE Playwright browser + ONE session (storage_state reuse + 2FA)
  │
  ├─ for team in teams:
  │    ├─ team-scoped idempotency check
  │    │    └─ success within 15m? → log "skipped (recent)", continue
  │    ├─ db.start_run(trigger, team_id=team.data_slug)
  │    ├─ navigate to team.stats_url
  │    ├─ engine.find_and_download(page, out_dir=staging/<slug>)
  │    ├─ csv_validator.validate (against this team's schema_profile)
  │    ├─ ingest subprocess: gc_csv_ingest.py --team <slug> <csv>
  │    ├─ db.complete_run with team_id
  │    ├─ notifier.emit(RunSummary with team_slug)
  │    └─ sleep 30s
  │
  └─ close browser
```

### Per-team idempotency

`StateDB.last_successful_run_within(team_id=<slug>, minutes=15)`.
One team succeeding doesn't mark others as done.

### Breakers

- `auth` breaker stays **global** — if login itself fails, no team can
  proceed.
- `download` breakers become **per-team** (`download:<slug>`), since a
  broken locator for one team doesn't necessarily affect others (though
  in practice the page structure is identical, so this is cautious).

## 8. Ingest refactor

`gc_csv_ingest.py` current shape:

```python
SHARKS_DIR = DATA_DIR / "sharks"
def main():
    csv_path = sys.argv[1]
    # ... writes to SHARKS_DIR/team.json, SHARKS_DIR/app_stats.json, etc.
```

Refactored shape:

```python
def run_ingest(*, team: Team, csv_path: Path, data_root: Path = DATA_DIR) -> IngestResult:
    team_dir = data_root / team.data_slug
    team_dir.mkdir(parents=True, exist_ok=True)
    # ... writes to team_dir/team.json with "team_name": team.name, etc.

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--team", required=True,
                    help="data_slug of the team (from teams.yaml)")
    args = ap.parse_args()
    team = team_registry.require_by_slug(args.team)
    run_ingest(team=team, csv_path=Path(args.csv_path))
```

Existing call sites that pass only `csv_path` (e.g. in `sync_daemon.py`
scorebook pipeline) default `--team sharks` for back-compat.

Same pattern for `gc_ingest_pipeline.py`.

## 9. Notifications

- `RunSummary` gains `team_slug: str` and `team_name: str`.
- Email subject: `[Dugout Autopull] SUCCESS Dolphins run #47`.
- Push message: `GC autopull failed: auth expired [Dolphins] (#47)`.
- n8n payload includes `team_id` and `team_name` so briefing workflows
  can segment.
- A daily "roll-up" n8n POST fires at the end of the whole sweep with an
  array of per-team outcomes — useful for a single morning briefing line
  like "4 of 5 teams pulled cleanly."

## 10. Testing

### Unit

- `tests/test_team_registry.py`:
  - valid YAML parses into Team list
  - duplicate `data_slug` raises
  - duplicate `id` raises
  - bad `data_slug` format raises
  - missing file falls back to env-var synthetic team
  - `active=false` filtered by `load_active()`
- `tests/autopull/test_state.py`:
  - migration adds `team_id` column and backfills 'sharks'
  - `last_successful_run_within(team_id=X)` scopes correctly
  - `record_schema(team_id=X, ...)` + `schema_overlap` per-team
- `tests/autopull/test_cli.py`:
  - multi-team loop: two teams, both succeed → two `runs` rows
  - one team fails, other succeeds → one failure row, one success row
  - team `active=false` is skipped
  - per-team idempotency: team A succeeded 5m ago, team B hasn't → only
    team B runs

### Integration

- `tests/autopull/test_cli_integration.py`:
  - serve two fixture stats pages (Sharks + Dolphins)
  - run autopull against both
  - assert `data/sharks/season_stats.csv` and `data/dolphins/season_stats.csv`
    both written with correct content
  - assert DB has two `runs` rows with correct `team_id`

### Back-compat

- Existing Sharks tests for `gc_csv_ingest` + `gc_ingest_pipeline` get a
  `team` fixture representing the Sharks and keep passing unchanged in
  meaning.

## 11. Rollout

1. **Merge PR** — migrations run automatically. `teams.yaml` ships with a
   single Sharks entry. All existing behavior preserved.
2. **Verify** on Pi: manual `python -m tools.autopull.cli --trigger=manual`
   run still writes to `data/sharks/` and is byte-identical to prior runs.
3. **Add second team** — edit `config/teams.yaml`, commit, push. Pi
   autosync picks it up. Next cron pulls both teams.
4. **Phase 2** spec begins when you want SWOT/lineups per team.

## 12. Self-sustaining guarantees

- Adding/removing teams: edit `teams.yaml` only. No code, no restart.
- Renaming a team: change `name`. `data_slug` is stable, so data + runs
  are preserved.
- Pausing a team mid-season: set `active: false`. Historical data + runs
  remain for audit.
- LLM-learned selectors work across all teams automatically (shared
  registry).
- Schema drift alerts are per-team, so GC changing the Sharks CSV doesn't
  silently mask a Dolphins regression.

## 13. Open questions / deferred

- **Per-team credentials (Option B from brainstorming):** deferred. If a
  future team isn't on your primary GC account, we add
  `team.gc_credentials` as an optional override. `teams.yaml` schema
  supports this additively.
- **Opponent data attribution per team:** currently opponents live in
  `data/opponents/` as a league pool. Phase 2 will add a per-team
  "opponents faced" view without duplicating opponent data.
- **Team-specific n8n workflows:** each team may eventually want its own
  morning briefing webhook. Phase 3.
- **Data retention by team:** Phase 1 keeps all team data forever. If
  this grows unbounded, Phase 3 adds a per-team retention policy.

## 14. Safety guarantees

- Kill switch remains `GC_AUTOPULL_ENABLED`. Also flips off for all teams.
- Per-team kill: set `active: false` in `teams.yaml`.
- Bad `teams.yaml` fails fast, doesn't touch data, emits a critical push.
- Back-compat path (no `teams.yaml`) keeps today's single-team operation
  working exactly as before.
