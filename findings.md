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
