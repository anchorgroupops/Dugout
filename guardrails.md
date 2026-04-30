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

## Adding a New SIGN

When a new failure pattern is confirmed (not hypothetical):
```
## SIGN-NNN: Short description
**Symptom:** What the user or system observes.
**Fix:** Exact command or code change to resolve it.
**Ref:** Source file or session date
```
