# Coverage uplift — dugout 0% → 78.6%

**Date:** 2026-04-22
**Branch:** `claude/coverage-uplift`
**Context:** Applying the same coverage pattern that grade-tracker PR #6 used
(9% → 68%) to this repo, which started with no `tests/` directory at all.

## Scope

**In scope (testable pure logic):**
- `api.py` — Flask endpoints, auth, connectivity helpers
- `tools/stats_normalizer.py` — GameChanger stat normalization
- `tools/swot_analyzer.py` — deterministic SWOT classification
- `tools/lineup_optimizer.py` — deterministic lineup ordering + Monte Carlo sim
- `tools/notify.py` — Telegram wrapper (mocked urllib)
- `tools/logger.py` — audit log writer
- `tools/aggregate_team_stats.py` — roster merge helpers
- `tools/practice_gen.py` — weakness → drill mapping + plan generation

**Out of scope (coverage excluded in `.coveragerc`):**
- `tools/gc_*.py`, `tools/scrape_*.py`, `tools/*_scraper*.py` — Playwright
  browser automation; requires live GameChanger session
- `tools/frida*.py`, `tools/adb*.py`, `tools/diag_*.py` — device-dependent
  mobile scrapers
- `tools/test_direct_api.py`, `tools/test_gc_login.py` — misnamed diagnostic
  scripts, not pytest tests
- `tools/modal_app.py` — Modal deployment entrypoint
- `tools/fetch_*.py`, `tools/orchestrate_*.py`, `tools/parse_plays*.py` — network
  / session-dependent helpers
- `batch_sync.py` — NotebookLM sync engine, heavy external I/O. Parked for a
  follow-up coverage PR using a dedicated integration-test job with a mock
  MCP server.
- Dashboard entrypoints, one-shot migration scripts, base64 utilities

## Decomposition

1. **Infra** — `pytest.ini` (strict-markers, short tb), `requirements-dev.txt`
   (pytest 8, pytest-cov, hypothesis, + structlog which was missing from
   `requirements.txt` entirely — api.py needs it at import time),
   `tests/conftest.py` (shared fixtures: `sample_player`, `sample_roster`,
   `sample_batting_row`, `clean_env`, `tmp_data_dir`), `tests/README.md`,
   `.coveragerc` (exclusion list above), `Makefile` (install-dev, test, cov,
   cov-html, run, clean).

2. **tools/stats_normalizer.py** — 101 tests covering `safe_float`,
   `safe_int`, `safe_pct_ratio`, `innings_to_float`, all `normalize_*_row`
   helpers, `player_identity_key`, `build_player_metric_profile`,
   `detect_player_outlier_stats`, `validate_team_outlier_stats`,
   `normalize_pitching_breakdown_row`, `normalize_pitching_advanced_full_row`.
   Lands at 97%.

3. **tools/swot_analyzer.py** — 77 tests covering helpers, `compute_derived_stats`,
   all `classify_*` functions, `analyze_player`, `analyze_team`,
   `_team_aggregates`, `analyze_matchup` (including the limited-AB gate at
   line 789 and the opponent-sample empty gate at 769), `_swot_rationale_from_team`,
   and `load_team` (enriched → merged → plain fallback). Lands at 86%.

4. **tools/lineup_optimizer.py** — 40 tests covering `compute_batting_score`
   (all three strategies + small-sample regression), `slot_players`
   (including the leadoff PA-penalty at line 166), `validate_mandatory_play`,
   `generate_lineup`, `_player_outcome_probs`, `simulate_inning`
   (deterministic with fixed seed), `recommend_strategy`, and
   `generate_all_lineups`. Lands at 80%.

   **Documented quirk:** when the roster has exactly 3 players,
   `slot_players` emits a `{"name": "—", "number": 0}` placeholder in slot 2
   because leadoff/best/cleanup drain the pool first. Covered by an explicit
   test so this behavior is frozen until the code changes.

5. **api.py** — 64 tests covering auth (`require_api_key` with 401/503
   paths, Bearer + X-API-Key headers), all endpoints (`/favicon.ico`,
   `/health`, `/status`, `/sync/status`, `/notebooks`, `/notebooks/discover`,
   `/run`, `/run/status`, `/suggestions` GET + POST generate + PATCH update),
   response-hardening headers (CSP, HSTS, X-Correlation-ID), error handler,
   and connectivity helpers (`_youtube_connectivity`,
   `_last_batch_sync_status`).

   **Key mocking decisions:**
   - The `api` module is re-imported per-test via a fixture so the module-level
     path constants (`ROOT`, `LOGS_DIR`, `REGISTRY_PATH`, `SUGGESTIONS_PATH`,
     `PID_FILE`, `BATCH_SYNC_STATE_PATH`) get retargeted to a `tmp_path` on
     each test. This prevents the test suite from reading/writing real
     `notebooks.json` / `suggestions.json` / `logs/` in the repo.
   - `subprocess.Popen` is mocked at `api.subprocess.Popen` for `/run`.
   - `MCPClient` is mocked via `sys.modules` patch at `mcp_client`.

   Lands at 95%.

6. **tools/aggregate_team_stats.py** — 37 tests covering all helpers
   (`_norm_name`, `_parse_number`, `_innings_to_outs`, `_outs_to_innings`,
   `_merge_numeric`, `_merge_innings`, `_is_rate_key`, `_merge_generic`)
   and all `_recompute_*` functions. `main()` is untested (heavy filesystem
   + manifest orchestration). Lands at 58%.

7. **tools/practice_gen.py** — 42 tests covering pure helpers (`_iso`,
   `_normalize_date_str`, `_parse_event_datetime`, `_extract_time_hint`,
   `_clean_opponent_name`), `map_weaknesses_to_drills` (including
   matchup-aware boosting), and `generate_practice_plan` (duration budgeting,
   warmup always first, fun-drill always last, opponent header,
   weakness-driven drill selection). `_compute_windows`, `_load_*_events`,
   `_resolve_next_opponent_matchup`, `run()`, `run_scheduled()` are not
   tested — they require complex filesystem state (practice_rsvp.json,
   schedule_manual.json, opponent_discovery.json, plan_meta.json).
   Lands at 48%.

8. **tools/notify.py** — 13 tests. Mocks `urlopen` at
   `notify.urlopen` for success/failure/unconfigured paths. Lands at 100%.

9. **tools/logger.py** — 4 tests. Uses `monkeypatch.chdir(tmp_path)` to
   redirect the `logs/` directory. Lands at 100%.

## Dependencies added

- `structlog>=25.0,<26` — already used by `api.py`, but missing from
  `requirements.txt`. If this had been a fresh deployment the service
  would not have started.
- `pytest`, `pytest-cov`, `hypothesis` — dev-only (in `requirements-dev.txt`)

## CI changes

- `.github/workflows/ci.yml` → python-check job:
  - Install `requirements-dev.txt` (was: `requirements.txt`)
  - Replace 3 of the 4 smoke-import tests with a single `pytest --cov` run
  - Keep the `sync_daemon.py` syntax check (it's still at 0% unit coverage)
  - Upload `coverage.xml` as a 14-day artifact

## Rate-limit / timing caveats

None in dugout (unlike grade-tracker's `/send-test` endpoint). The Flask
test client is synchronous and all endpoints are single-request. The Monte
Carlo simulation in `lineup_optimizer.py` uses `random.Random(seed)` so
tests are deterministic at the 50-200 simulation sample size.

## Follow-ups (parked)

1. `batch_sync.py` (0% → target 40%) — needs a mock MCP / NotebookLM server.
   Best done in a follow-up PR that introduces an integration-test job.
2. `tools/practice_gen.py` (48% → target 75%) — `run()` / `run_scheduled()`
   / `_compute_windows` / `_load_*_events` require fixture JSON for
   practice_rsvp.json + schedule_manual.json. Mechanical work.
3. `tools/aggregate_team_stats.py` (58% → target 85%) — `main()` needs
   fixture team.json files and a manifest. Mechanical work.
4. `tools/modal_app.py` — integration-test on Modal side, not here.
5. Hypothesis property tests across `stats_normalizer` + `lineup_optimizer`
   consolidated into `tests/test_properties.py`. Good payoff target.

## Reusable pattern

Same decomposition as grade-tracker: `conftest.py` with `sample_*` fixtures,
mock at SDK / module boundary (not HTTP layer), one test file per subsystem,
`.coveragerc` with a named scraper/entrypoint exclusion list. The pattern
also applies cleanly to `notebooklm-mcp` once its dirty-tree blocker is
resolved.
