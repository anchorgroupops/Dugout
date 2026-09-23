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

## SIGN-010: nginx Served the Whole ./data Mount Publicly
**Symptom:** `https://dugout.joelycannoli.com/data/auth.json` returned the live GameChanger session (cookies + localStorage) to anyone; `data/autopull/` state and raw exports were equally reachable.
**Fix:** `client/nginx.conf` serves only `^/data/sharks/[A-Za-z0-9_-]+\.json$` (the dashboard snapshots) and hard-404s everything else under `/data/`. Never widen that allow-list to a directory; add a filename pattern. After a leak, rotate the GC session (log out all sessions / change the GC password) and delete `data/auth.json` on the Pi so autopull re-logs in.
**Ref:** 2026-09-02 site audit

## SIGN-011: Mutating /api Routes Were Gated by the Origin Header Only
**Symptom:** ~35 POST/PATCH/DELETE routes (roster overrides, evals, announcer deletes, music ingest) accepted any request whose `Origin` header said `https://dugout.joelycannoli.com` — trivially spoofed with curl.
**Fix:** Set `DUGOUT_WRITE_TOKEN` in the Pi `.env`; the API then requires `X-Dugout-Token` on every mutating `/api` request (`_guard_write_token`, enforced in `_security_before_request`). The PWA prompts once for the token and stores it per browser. Never add a mutating route that bypasses `_is_mutating_api_request()`.
**Ref:** 2026-09-02 site audit

## Adding a New SIGN

When a new failure pattern is confirmed (not hypothetical):
```
## SIGN-NNN: Short description
**Symptom:** What the user or system observes.
**Fix:** Exact command or code change to resolve it.
**Ref:** Source file or session date
```

## SIGN-012: `amix` Silently Collapsed the Announcer's Stereo to Mono on the Pi
**Symptom:** Announcer clips render and sound processed (loudness and bitrate correct) but are plain mono — `side/mid 0.000`. No error is logged, because the FFmpeg graph succeeds.
**Fix:** Never feed a mono leg into `amix` in the Stadium Wrap. `amix` negotiates one channel layout across its inputs, so a mono input downmixes the whole mix and discards any stereo built upstream. Build stereo with two separate legs joined instead:
```
[processed]asplit=2[la][ra];
[la]aecho=...:145|285|435:...[left];
[ra]aecho=...:168|312|462:...[right];
[left][right]join=inputs=2:channel_layout=stereo,...
```
Verify against the Pi's FFmpeg, not the dev box: the Pi image is jammy (FFmpeg 4.4) and one v2 arrangement survived on 4.4 but not 6.x. Measure with:
```bash
ffmpeg -v error -i clip.mp3 -ac 2 -f f32le - | python3 -c "import sys,numpy as np;s=np.frombuffer(sys.stdin.buffer.read(),dtype=np.float32).reshape(-1,2);print(np.sqrt(np.mean((s[:,0]-s[:,1])**2)))"
```
CI now installs FFmpeg so `TestStadiumWrapQuality` actually runs — it was skipping, which is how the mono chain shipped.
**Ref:** PR #218 follow-up, session 2026-09-16

## SIGN-012: GC API Answers 403 to Headless Playwright → "not authenticated" at /teams
**Symptom:** Daily autopull fails `Still on login/2FA page or not authenticated after credential submission (url=https://web.gc.com/teams, … sign_in_controls=2, auth_cookie=False)`. Email, 2FA code and password are all accepted (`POST /auth` returns a user token), but every `GET api.team-manager.gc.com/me/*` returns `403 {}` so the SPA never leaves the anonymous /teams view. The same account works in a real Chrome. Previously misdiagnosed as an account-level block.
**Fix:** GC's API sits behind AWS WAF bot control, which rejects browsers with `navigator.webdriver === true`. `SessionManager.new_logged_in_page` launches Chromium with `CHROMIUM_LAUNCH_ARGS` (`--disable-blink-features=AutomationControlled`); verified on the Pi 2026-09-23: same credentials, `/me/user` 200, `/teams` renders logged in. Never launch a GC browser without those args, and note GC's token lives in localStorage `eden-auth-tokens`, not a `jwt` cookie — `auth_cookie=False` alone is not evidence of a failed login.
**Ref:** session 2026-09-23, autopull runs since 2026-08-26

## SIGN-013: Host Autopull Cannot Write ./data After a chown to the Container User
**Symptom:** `gc-autopull.service` dies in `init_schema` with `sqlite3.OperationalError: attempt to write a readonly database` before ever reaching GC. `./data` and `./logs` are owned by uid/gid 999 (the `sharks` user inside `sharks_api`/`sharks_sync`; shows as `caddy:systemd-journal` on the host) while the timer runs as `joelycannoli` (uid 1000).
**Fix:** The tree is shared by two uids, so use ACLs rather than chown ping-pong: `sudo setfacl -R -m u:joelycannoli:rwX -m u:999:rwX data logs && sudo setfacl -R -d -m u:joelycannoli:rwX -m u:999:rwX data logs`. The default ACL keeps files created by either side writable by the other. Never `chown -R` `./data` to a single owner.
**Ref:** ctime 2026-09-15 15:59 on the whole tree; failures 2026-09-16 → 2026-09-23
