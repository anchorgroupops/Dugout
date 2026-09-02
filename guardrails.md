# Guardrails — Known Failure Patterns (SIGNs)

Consult this before every session. Each SIGN is a confirmed failure with a prescribed fix. Never repeat a SIGN.

---

## SIGN-001: `skillfish` Interactive Prompt Blocks in CI
**Symptom:** `npx skillfish add ...` hangs indefinitely even with `CI=true`, `--yes`, or `--all` flags.
**Fix:** Clone the skills repo directly with `git clone`, then copy the skills directory manually.
```bash
git clone https://github.com/<org>/<repo>.git /tmp/skills-tmp
cp -r /tmp/skills-tmp/skills/* ~/.gemini/antigravity/skills/
```
**Ref:** findings.md 2026-04-26

---

## SIGN-002: PWA Manifest 404 in Production
**Symptom:** `manifest.webmanifest` link in `index.html` 404s in production builds.
**Fix:** After `npm run build`, verify `dist/manifest.webmanifest` exists. Confirm `vite-plugin-pwa` has `registerType: 'autoUpdate'` and `injectRegister: 'auto'` set in `vite.config.js`.
**Ref:** findings.md 2026-04-10

---

## SIGN-003: Dashboard Shows Stale Data
**Symptom:** Dashboard shows old stats; `/api/sync/status` returns stale timestamps.
**Fix:** Ensure `sync_daemon.py` is running. Run `python tools/opcheck.py` to verify daemon health and data freshness.
**Ref:** findings.md 2026-04-10

---

## SIGN-004: Hardcoded Windows Paths Break Linux/Pi
**Symptom:** Scripts fail on Raspberry Pi or Linux with `H:\Repos\...` or `C:\...` path errors.
**Fix:** All file paths must use `pathlib.Path` or environment variables. Never hardcode Windows drive letters.
**Ref:** CLAUDE.md

---

## SIGN-005: Duplicate Scrapers Cause Data Drift
**Symptom:** Conflicting player stats when two scrapers write to the same data target.
**Fix:** One scraper per function only. Audit `tools/` for variants before adding a new scraper. Consolidate first.
**Ref:** CLAUDE.md

---

## SIGN-006: Sharks and Opponent Data Merged
**Symptom:** SWOT analysis or lineup optimizer produces cross-contaminated results.
**Fix:** Always write Sharks data to `data/sharks/` and opponent data to `data/opponents/`. Never share a JSON file between both. Enforce at ingest time.
**Ref:** gemini.md Behavioral Rules

---

## SIGN-007: Multiple GC Login Engines Cause 2FA Email Storms
**Symptom:** GC account inbox flooded with verification-code emails; scrapers log `2FA required` + cooldown cycles.
**Fix:** All GC logins must (1) reuse the shared session store `data/auth.json`, (2) read the emailed code via `fetch_emailed_gc_code()` (`tools/gc_scraper.py`, needs `GMAIL_USERNAME`/`GMAIL_APP_PASSWORD`), and (3) pass `login_budget_exhausted()` before submitting the login email form. Never add a new login flow — reuse `GameChangerScraper.login` or `tools/autopull/session_manager.SessionManager`.
**Ref:** PR #126 follow-up, session 2026-07-11

---

## SIGN-007: Deploy Webhook Recreates Its Own Container → API Stuck in `Created`
**Symptom:** After a push to main, `dugout.joelycannoli.com/api/*` returns 502; `docker ps -a` shows `sharks_api`/`sharks_sync` in state `Created` (never started). Watchtower logs look clean.
**Fix:** Deploy is Watchtower-only. Never call `/api/deploy` (or `scripts/pi-deploy.sh` via SSH from inside a container): `docker compose up -d` stops the calling container mid-recreate and the `start` step never runs. If it happens: `docker compose -f docker-compose.sharks.yml up -d` on the Pi.
**Ref:** 2026-08-27 council audit (GHA `notify-deploy` job removed)

---

## SIGN-008: Live GC Scrapers Cause a Verification-Code Email Storm
**Symptom:** Owner receives bursts of 4 "Your GameChanger code is …" emails every 12 h (and on every container restart).
**Fix:** `sync_daemon` live-page scrapers are gated behind `GC_LIVE_SCRAPE_ENABLED` (default off) — leave it off. The Constitution makes the CSV export the sole data source; `tools/autopull` is the only sanctioned GC login (Gmail 2FA + saved session, password-only step once the device is remembered). Never add another `.login(` path.
**Ref:** 2026-08-27 council audit

---

## SIGN-009: Autopull Login Succeeds but Reports "not authenticated" at /teams
**Symptom:** Daily "Dugout autopull failure" email: `Still on login/2FA page or not authenticated after credential submission (url=https://web.gc.com/teams, login_form=False, 2fa_form=False)`. Credentials were accepted (GC landed on `/teams`); the auth breaker then opens for 24 h, so it repeats once a day.
**Fix:** Never detect GC auth by matching the text "Sign In" in any button/link — the logged-in `/teams` page can contain such text, and the SPA renders the anonymous header until its session request resolves. `tools/autopull/session_manager.is_authenticated` must use GC's anonymous-only controls (`[data-testid='desktop-sign-in-button'], [data-testid='mobile-sign-in-button']`, same as `gc_scraper._get_auth_state`) plus the `jwt` cookie as positive proof, and `wait_until_authenticated` must poll after submission rather than checking once.
**Ref:** autopull run #146, session 2026-09-02

## Adding a New SIGN

When a new failure pattern is confirmed (not hypothetical):
```
## SIGN-NNN: Short description
**Symptom:** What the user or system observes.
**Fix:** Exact command or code change to resolve it.
**Ref:** Source file or session date
```
