# GC CSV Autopull — Self-Healing, Adaptive, Self-Improving

**Date:** 2026-04-22
**Status:** Draft — pending user review
**Author:** Claude Code (Opus 4.7) + Joel McKinney

## 1. Goal

Automate the manual "download season stats CSV" flow on `gc.com` so that Dugout (`dugout.joelycannoli.com`) always has fresh GameChanger data without human intervention. Data pulls fire after every game and as a daily safety-net. The system must:

- **Self-heal**: recover from transient network issues, session expiry, and 2FA challenges without human intervention.
- **Adapt**: detect when `gc.com`'s DOM changes break the CSV export flow and propose a new selector in-flight using the Claude API.
- **Self-improve**: rank DOM locator strategies by recent success so the common path runs fastest, and persist strategies learned at runtime.

Non-goals: live play-by-play scraping (still handled by the existing `sync_daemon` pbp path), per-game box-score CSV export (not exposed by GC), scraping opponent teams (separate pipeline).

## 2. Constraints and prior context

- **Host = Pi.** `tools/modal_app.py` explicitly keeps GC automation off Modal due to rotating IPs triggering 2FA email spam. Stable Pi IP = no 2FA triggers in steady state.
- **Existing primitives**: `tools/gc_csv_auto.py` (Playwright download + ingest chain), `tools/gc_full_scraper.py` (login + `storage_state` reuse), `tools/gc_csv_ingest.py` (CSV → normalized JSON), `tools/sync_daemon.py` (adaptive poller that already fires a postgame webhook to n8n at `https://n8n.joelycannoli.com/webhook/gc-alert`).
- **Policy**: `CLAUDE.md` says "CSV-First, no browser automation or API scraping." This spec amends that — browser automation is permitted **only for the single CSV download click**, not for continuous scraping. `CLAUDE.md` will be updated as part of rollout.
- **Gmail MCP**: the claude.ai-hosted Gmail MCP is OAuth-per-session and cannot run headless. This design uses a dedicated Google API credential (OAuth refresh token) stored in `.env` on the Pi — a sub-project within this work.

## 3. Architecture

```
               ┌──────────────────────────────────────────────────┐
               │                  Pi (dugout host)                │
               │                                                  │
  Daily 3am ET │  ┌──────────────────┐         ┌───────────────┐  │
  ──cron────▶──┼─▶│ gc_autopull CLI  │────────▶│ gc_session    │  │
               │  │ (entry point)    │         │ _manager.py   │──┼──▶ Playwright
   Postgame    │  └─────────┬────────┘         │  (login,      │  │    storage_state
   event       │            │                  │   2FA, heal)  │  │
  ──hook────▶──┼─ sync_daemon│                 └───────┬───────┘  │
               │             ▼                         │ 2FA email│
               │  ┌───────────────────┐                ▼ needed   │
               │  │ gc_locator_engine │       ┌───────────────┐   │
               │  │  (strategy        │──────▶│ gmail_2fa_    │   │
               │  │   registry + LLM  │       │  fetcher      │   │
               │  │   fallback)       │       └───────────────┘   │
               │  └─────────┬─────────┘                            │
               │            ▼                                      │
               │  ┌───────────────────┐    ┌──────────────────┐    │
               │  │ gc_csv_validator  │──▶ │ gc_csv_ingest.py │    │
               │  │ (schema+quarant.) │    │ (existing)       │    │
               │  └─────────┬─────────┘    └──────────────────┘    │
               │            ▼                                      │
               │  ┌───────────────────┐                            │
               │  │ gc_pull_notifier  │───▶ email / n8n / push    │
               │  └─────────┬─────────┘                            │
               │            ▼                                      │
               │  ┌───────────────────┐                            │
               │  │ autopull_state.db │ (SQLite)                   │
               │  └───────────────────┘                            │
               └──────────────────────────────────────────────────┘
```

### 3.1 New modules

All under `tools/autopull/` (new package):

| Module | Responsibility |
|---|---|
| `tools/autopull/cli.py` | Entry point. Parses args, loads config, orchestrates run, emits summary JSON. |
| `tools/autopull/session_manager.py` | Wraps Playwright login. Reuses `storage_state` when valid. Detects 2FA prompt. Invokes `gmail_2fa_fetcher` on expiry. Persists fresh session. Circuit-breaker on repeated auth failure. |
| `tools/autopull/gmail_2fa_fetcher.py` | Polls Gmail API for the GC verification code email (from `no-reply@gc.com`, within last 5 min, subject matches `/verification code/i`). Extracts the 6-digit code. Marks the message read. |
| `tools/autopull/locator_engine.py` | Finds the CSV export button. Tries strategies in order of recent success from the strategy registry. On exhaustion, invokes Claude API with DOM snapshot → proposes new selector → tries it → persists on success. |
| `tools/autopull/csv_validator.py` | Post-download validation: MIME/extension check, parseable as CSV, row count ≥ 1, ≥80% column-name overlap with last-known schema. Rejects to a quarantine dir on failure. |
| `tools/autopull/notifier.py` | Fan-out to email (Gmail API send), n8n webhook (`/webhook/gc-pull-status`), and `PushNotification` tool for Claude Code. |
| `tools/autopull/state.py` | SQLite wrapper: runs history, strategy registry, circuit-breaker state, schema profile. |

### 3.2 State DB schema (`data/autopull/autopull_state.db`)

```sql
CREATE TABLE runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  trigger TEXT NOT NULL,                -- 'cron', 'postgame', 'manual'
  outcome TEXT NOT NULL,                -- 'success', 'failure', 'quarantined'
  csv_path TEXT,
  rows_ingested INTEGER,
  winning_strategy_id INTEGER,
  failure_reason TEXT,
  duration_ms INTEGER,
  llm_fallback_invoked INTEGER DEFAULT 0,
  session_refreshed INTEGER DEFAULT 0
);

CREATE TABLE strategies (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                   -- 'locator' | 'css' | 'xpath' | 'llm_generated'
  selector TEXT NOT NULL,               -- serialized strategy (JSON for locator, string for CSS/XPath)
  description TEXT,
  created_at TEXT NOT NULL,
  last_success_at TEXT,
  success_count INTEGER DEFAULT 0,
  failure_count INTEGER DEFAULT 0,
  source TEXT NOT NULL,                 -- 'builtin', 'llm', 'manual'
  enabled INTEGER DEFAULT 1
);

CREATE TABLE circuit_breaker (
  key TEXT PRIMARY KEY,                 -- e.g. 'auth', 'download', 'ingest'
  consecutive_failures INTEGER DEFAULT 0,
  opened_at TEXT,                       -- NULL = closed
  reset_at TEXT                         -- when to try again
);

CREATE TABLE schema_profile (
  observed_at TEXT PRIMARY KEY,
  column_names_json TEXT NOT NULL,      -- sorted column names from the CSV
  row_count INTEGER NOT NULL
);
```

## 4. Self-healing behaviors

1. **Retry with backoff.** Each run attempts up to 3 tries: immediate, +2 min, +10 min. Only for transient failures (network timeout, HTTP 5xx, `TimeoutError` during navigation). Auth failures and DOM-missing-button failures do **not** retry immediately — they fall through to higher-order healing.
2. **Session auto-refresh.** If the first page load lands on `/login` or a 2FA challenge is detected, `session_manager` invokes `gmail_2fa_fetcher` and completes the code entry automatically. On success, it saves a new `storage_state` and continues the run.
3. **Circuit breaker per failure class.** Three consecutive auth failures → `auth` breaker opens for 24 hours to avoid hammering GC and triggering real 2FA pressure. Three consecutive download failures → `download` breaker opens for 2 hours. Next run after `reset_at` tries once; success closes the breaker.
4. **Kill switch.** Env var `GC_AUTOPULL_ENABLED=false` causes the CLI to exit early with "disabled" status before any network call. Allows immediate stop without uninstalling.
5. **Quarantine on bad CSV.** If validation rejects the file, it moves to `data/autopull/quarantine/<timestamp>/` and the ingest is skipped — no bad data touches prod.

## 5. Self-improving and adaptive behaviors

### 5.1 Strategy registry and ranking

The `locator_engine` loads all enabled strategies from the `strategies` table, ordered by a recency-weighted score:

```
score = success_count * exp(-days_since_last_success / 14) - 0.5 * failure_count
```

Strategies with `failure_count > 3 * success_count` and no success in 30 days are auto-disabled. The five current hardcoded strategies in `gc_csv_auto.py:80–95` seed the registry at first run with `source='builtin'`.

### 5.2 LLM adaptive fallback

When all enabled strategies fail to locate a clickable "export" element:

1. Capture page DOM (pruned: strip `<script>`, `<style>`, base64 data URIs; cap at ~40KB to fit the prompt).
2. Capture screenshot + save both to `logs/autopull/adaptations/<timestamp>/`.
3. Invoke Claude API (Sonnet 4.6, prompt-cached) with system prompt:
   > You are helping automate downloading a season stats CSV from GameChanger. Given this DOM snapshot, return a JSON object with shape `{"strategy": "css"|"xpath", "selector": "...", "confidence": 0..1, "reasoning": "..."}` identifying the element that, when clicked, will download or expose a CSV export. If you propose a submenu click, chain them with `>>` (e.g. `button.actions >> li:has-text("CSV")`).
4. Validate the LLM response with JSON schema.
5. Try the proposed selector with the same `expect_download` guard as the builtin strategies.
6. If a download actually fires and `csv_validator` accepts the result: persist the new strategy with `source='llm'`, `success_count=1`. Future runs try it in ranked order alongside builtins.
7. If it fails: record `failure_count=1` but keep the row so we can see attempted adaptations in the run history.

**Safety rails:**
- LLM fallback runs at most 2 times per 24h per Pi (to cap cost and prevent runaway loops).
- Any LLM-proposed selector that causes a download of a non-CSV file (or a file whose schema overlap is <50% with the last known profile) is immediately disabled and quarantined.
- The LLM is never allowed to propose a selector that matches `a[href*="logout"]`, `button:has-text("Delete")`, or similar destructive patterns — a deny-list filter is applied before try.

### 5.3 Schema drift detection

After each successful ingest, `csv_validator` records the sorted column-name list in `schema_profile`. On the next run, it computes overlap against the most recent profile:

- ≥95% overlap: silent pass.
- 80–95% overlap: ingest proceeds but `notifier` emits an "advisory" status ("GC CSV schema drifted: added [X], removed [Y]").
- <80% overlap: ingest aborted, file quarantined, "critical" notification fires. Human must review.

### 5.4 Weekly self-report

A separate `tools/autopull/weekly_report.py`, cron'd Sundays at 6am ET, summarises:
- total runs, success rate
- which strategies won each day
- any LLM adaptations and whether they stuck
- schema drift events
- circuit breaker trips

The output JSON is POSTed to `https://n8n.joelycannoli.com/webhook/autopull-weekly` for inclusion in your Monday morning briefing.

## 6. Scheduling

### 6.1 Daily safety-net cron

`systemd` timer `gc-autopull.timer` → service `gc-autopull.service` → `python -m tools.autopull.cli --trigger=cron` at 03:00 America/New_York.

### 6.2 Postgame event

`sync_daemon.py` already has a `POSTGAME` state transition that fires the `gc-alert` n8n webhook. We add a second call **immediately after** that webhook fire: `subprocess.Popen([sys.executable, '-m', 'tools.autopull.cli', '--trigger=postgame'])` (non-blocking; runs in a detached process so the daemon's state loop is not held up).

Idempotency: `cli.py` checks `state.db` — if a successful run completed within the last 15 minutes, it logs "recent success, skipping" and exits 0. Prevents double-pulls if both cron and postgame trigger within the same window.

## 7. Notifications

`notifier.py` fans out to:

| Channel | Trigger | Payload |
|---|---|---|
| Email → `anchorgroupops@gmail.com` | Any `failure` or `quarantined` outcome; weekly summary | Run ID, trigger, failure reason, link to logs |
| n8n webhook `/webhook/gc-pull-status` | Every run (success + failure) | Full run row from `state.db` as JSON |
| `PushNotification` tool | Failures only; `critical` schema drift; circuit breaker openings | Short one-line message |

Success runs are silent except for the n8n feed (which drives your morning briefing).

## 8. Data flow and validation

1. CLI picks trigger; checks enabled flag + idempotency guard + `auth` circuit breaker.
2. `session_manager.get_page()` → logged-in Playwright page.
3. `locator_engine.find_and_click_export(page)` → `download` event.
4. Save to `data/autopull/staging/season_stats_<timestamp>.csv`.
5. `csv_validator.validate(path)` → ok | quarantine.
6. If ok: move to `data/sharks/season_stats_<YYYYMMDD>.csv` (existing naming), invoke `gc_csv_ingest.py` via subprocess, update `schema_profile`.
7. `notifier.emit(run_summary)` → fan-out.
8. Update `runs` row; update `strategies` success/failure counts; update circuit breakers.

## 9. Testing strategy

### 9.1 Unit tests (`tests/autopull/`)

- `test_state.py` — SQLite wrapper CRUD, schema migrations, strategy ranking.
- `test_csv_validator.py` — happy path, missing columns, wrong MIME, zero rows, schema drift thresholds.
- `test_notifier.py` — fan-out with mocked Gmail + webhook + push; verifies each channel is called per policy (failure-only for push, etc.).
- `test_locator_engine.py` — strategy ranking math, LLM fallback with mocked Anthropic SDK, deny-list filter, safety caps.
- `test_gmail_2fa_fetcher.py` — mocked Gmail API; extracts code from known GC email templates.

### 9.2 Integration tests

- `test_cli_integration.py` — end-to-end with a local HTTP fixture that serves a minimal stats page + fake CSV. No real GC calls.
- `test_circuit_breaker_integration.py` — simulate 3 failures → breaker opens → assert next run short-circuits.

### 9.3 Live smoke test (manual, not CI)

`python -m tools.autopull.cli --trigger=manual --dry-run --headed` on the Pi performs the full flow with a visible browser, saves the CSV to a throwaway dir, skips ingest. Used to verify real GC integration after code changes.

Coverage target: ≥85% for new modules (aligns with the coverage-uplift branch you just merged).

## 10. Deployment and rollout

1. **Phase 0 — infra:** create dedicated Google Cloud project + OAuth app for Gmail read-only + send scopes. Generate refresh token once via interactive script. Store as `GMAIL_OAUTH_REFRESH_TOKEN` in `.env` on the Pi.
2. **Phase 1 — code:** land all new modules + tests + CI. Feature-flagged off (`GC_AUTOPULL_ENABLED=false` default). Merge to `main`. Watchtower picks it up.
3. **Phase 2 — cron enable:** manual run on Pi with `--headed`. If green, `systemctl enable --now gc-autopull.timer`. Leave `GC_AUTOPULL_ENABLED=true` for cron path only. Postgame hook still disabled via a second flag `GC_AUTOPULL_POSTGAME_ENABLED=false`.
4. **Phase 3 — postgame enable:** after 5 successful daily cron runs, flip the postgame flag. Observe.
5. **Phase 4 — LLM adaptive enable:** the adaptive fallback is off by default (`GC_AUTOPULL_LLM_ADAPT=false`). After two consecutive successful weeks, enable. Always enabled in `test_locator_engine.py`.

Rollback at any phase: flip the relevant env flag → Watchtower does nothing (no image change needed) → systemd picks up the flag on next run.

## 11. Configuration

New `.env` keys:

```
# Kill switches
GC_AUTOPULL_ENABLED=false                  # master switch
GC_AUTOPULL_POSTGAME_ENABLED=false         # postgame event hook
GC_AUTOPULL_LLM_ADAPT=false                # LLM-driven selector adaptation

# Gmail API (headless)
GMAIL_OAUTH_CLIENT_ID=...
GMAIL_OAUTH_CLIENT_SECRET=...
GMAIL_OAUTH_REFRESH_TOKEN=...
GMAIL_NOTIFY_FROM=anchorgroupops@gmail.com
GMAIL_NOTIFY_TO=anchorgroupops@gmail.com

# Anthropic (LLM adaptive fallback only)
ANTHROPIC_API_KEY=...
GC_AUTOPULL_LLM_MODEL=claude-sonnet-4-6
GC_AUTOPULL_LLM_DAILY_BUDGET_USD=1.00      # hard cap; breaker opens if exceeded

# n8n
N8N_AUTOPULL_STATUS_WEBHOOK=https://n8n.joelycannoli.com/webhook/gc-pull-status
N8N_AUTOPULL_WEEKLY_WEBHOOK=https://n8n.joelycannoli.com/webhook/autopull-weekly

# Schedules (for reference; actual schedule is in the systemd unit)
GC_AUTOPULL_CRON_HOUR=3
GC_AUTOPULL_IDEMPOTENCY_WINDOW_MIN=15
```

## 12. Safety guarantees

- Never commits credentials. All secrets via `.env`, never hard-coded.
- LLM fallback budget-capped and rate-limited; breaker opens on overspend.
- Deny-list applied to LLM-proposed selectors before any click.
- Quarantine folder for every rejected download; nothing bad reaches `data/sharks/`.
- All runs logged to `state.db`; purge policy: 90 days.
- `GC_AUTOPULL_ENABLED=false` is the universal kill switch.
- `CLAUDE.md` updated to reflect: "Browser automation permitted for CSV download only; no live scraping."

## 13. Open questions / deferred

- **Multi-team support**: current design assumes the Sharks only (`GC_TEAM_ID` singleton). If you eventually track multiple teams, the strategy registry stays shared but `runs` and state need a `team_id` column. Deferred.
- **Per-game box score export**: not currently exposed by GC. If GC adds it, a second locator engine instance handles it. Deferred.
- **Dashboard UI**: no "retry now" button yet; must SSH to Pi. If needed later, the CLI's JSON output is already consumable by a future `/api/autopull/status` endpoint.
