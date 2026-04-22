# dugout tests

## Running

```bash
make install-dev           # one-time: create /tmp/dugout-venv and install dev deps
make test                  # run all tests
make cov                   # run with coverage report
make cov-html              # HTML coverage report at htmlcov/index.html
```

Or directly:

```bash
source /tmp/dugout-venv/bin/activate
pytest                     # all tests
pytest tests/test_stats_normalizer.py -v
pytest -k lineup           # filter by name
pytest -m "not slow"       # skip slow tests
```

## Layout

```
tests/
├── conftest.py                     # shared fixtures
├── test_stats_normalizer.py        # pure-logic stat normalization
├── test_swot_analyzer.py           # deterministic SWOT classification
├── test_lineup_optimizer.py        # deterministic lineup ordering
├── test_api.py                     # Flask endpoints (flask test client)
├── test_aggregate_team_stats.py    # team aggregation
├── test_practice_gen.py            # practice generator
├── test_notify.py                  # Telegram notifier (HTTP mocked)
└── test_properties.py              # Hypothesis property tests across pure-logic modules
```

## Mocking boundaries

- **HTTP calls**: mock `requests.get` / `requests.post` at the call site (not at the urllib3 layer).
- **LLM/Gemini/OpenAI**: mock the SDK client object returned by the factory function.
- **Filesystem**: use `tmp_data_dir` fixture; never write to the repo directory.
- **Env vars**: use `clean_env` fixture; never leak real credentials into tests.

## Scope / exclusions

**Excluded from coverage:**
- `tools/gc_*.py`, `tools/scrape_*.py`, `tools/parse_plays*.py`, `tools/gc_*_scraper*.py` — Playwright-driven browser automation; require live GameChanger session.
- `tools/frida*.py`, `tools/adb*.py`, `tools/diag_*.py`, `tools/diagnose_*.py` — device-dependent mobile scrapers.
- `tools/test_direct_api.py`, `tools/test_gc_login.py` — misnamed diagnostic scripts, not pytest tests.
- `tools/modal_app.py` — Modal deployment entrypoint; integration-test on Modal side.

These live at 0% unit coverage by design. Move to a separate integration-test job with a live browser / device if ever needed.

## Hypothesis property tests

Pure-logic modules (`stats_normalizer`, `lineup_optimizer`) get property tests in `test_properties.py` to catch edge cases the example-based tests would miss. Property tests found a bad assumption in grade-tracker's `gpa_to_percent` clamping within seconds — worth the investment for any pure-math code.

## Rate-limit caveat

`batch_sync.py` and `api.py` Flask routes that trigger external sync should mock `time.sleep` and the sync function directly. Don't rely on real timing in tests.
