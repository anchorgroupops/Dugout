# Project Findings: Dugout PWA

## 2026-04-10 Session

### Resolved

- **Port Alignment**: 5000 is now the standard port for local development. `vite.config.js` and `api.py` are aligned.
- **Route Standardization**: API route `/api/sync/status` is implemented and standardized across frontend/backend.
- **Downtime Hazards**: `/api/health` now correctly returns health status without 500 errors when `stale_sources` is queried.
- **UI Aesthetics**: Migrated to **Inter** and **Outfit** font families. Enhanced glassmorphism effects for a premium "Apple-like" dashboard feel.
- **Sync Resilience**: Manual sync trigger now attempts local API trigger (`/api/run`) before failing over to Modal cloud.

### Known Blockers

- [ ] **PWA Manifest Connectivity**: The `manifest.webmanifest` link in `index.html` may need verification in production environments (currently configured for Vite dev mode).
- [ ] **Data Freshness**: App relies on local JSON files managed by `sync_daemon.py`. Ensure daemon is running for live data updates.

### Hypotheses

1. **[High]** Performance spikes during manual sync may be due to browser-based scraping; consider moving full scraping logic to a background service if latency increases.
2. **[Medium]** PWA caching strategy (NetworkFirst) for API data may need adjustment if offline usage is a primary requirement.

## 2026-04-26

### Attempted Fixes

| # | Timestamp | Action / Command | Output (truncated) | Result |
| --- | --------- | ---------------- | ------------------ | ------ |
| 1 | 00:41 | `npx skillfish add obra/superpowers` | Interactive prompt hung | ❌ Failed |
| 2 | 00:44 | `$env:CI="true"; npx skillfish add ...`| Interactive prompt hung | ❌ Failed |
| 3 | 00:45 | `git clone https://.../superpowers.git` | `Copy-Item -Recurse` succeeded | ✅ Success |

### Session Summary

**Worked:** Bypassed `skillfish` interactive prompt bugs by directly cloning the `superpowers` repository and copying the 14 skills to the global `~/.gemini/antigravity/skills/` directory.
**Failed:** Automated installation using `npx skillfish` failed due to blocking interactive prompts not respecting `--all`, `--yes`, or `CI=true` logic in the current version.
**Next Steps:**

1. Leverage the newly installed `audit-website` skill to perform a comprehensive audit of the Dugout application dashboard.
2. Utilize the Superpowers orchestrator and specialized subagents for future complex workflows as outlined in the global W.R.A.P.S. framework.
