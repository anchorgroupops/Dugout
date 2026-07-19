# Pi Session Brief — Diagnose & Heal `sync_daemon` (Dugout / softball-strategy-sharks)

**Paste the block below into a fresh Claude session running on the Pi (`joelycannoli@pi`). It's fully self-contained — do not explain it further.**

---

```
You are running on the Pi. Context you need, no hand-holding required:

BACKGROUND
- Dugout portal (PCLL/Sharks) stats have not been updating for ~3 weeks.
- Separate investigation on PC-side Claude confirmed root cause #1: a stale
  Modal deployment of `softball-strategy-sharks` was still invoking
  `tools/gc_scraper.py` and failing daily — generating email spam. That
  half is being fixed via `modal deploy tools/modal_app.py` on the PC.
- Root cause #2 (your job): scraping was refactored off Modal and onto
  THIS Pi via `tools/sync_daemon.py`, which is supposed to run as a
  Docker container. If stats aren't flowing, the container is either
  stopped, crashlooping, silently erroring, or pointed at stale config.

REPO
- GitHub: anchorgroupops/Dugout, branch `main`
- Pi clone expected at ~/projects/Dugout or similar — find it via
  `find /home /srv /opt -maxdepth 4 -name "Dugout" -type d 2>/dev/null`
- Daemon source: tools/sync_daemon.py (≈200KB — heavy; use sampling)
- Daemon posts GC alerts to https://n8n.joelycannoli.com/webhook/gc-alert

NON-SCOPE — DO NOT TOUCH
- Modal deployment (PC Claude is handling)
- n8n workflows (h1T0OtI2xnJqEfVh, jodsyjVl6HeTZjjI, 49HKHZiG82sg0eRJ)
- Watchdog or command-poller scripts in scripts/
- Any push to main — SIGN-004 says every change is HITL via PR

YOUR TASK
Find out why sync_daemon isn't producing fresh data, and if it's a
trivial fix (env var missing, container stopped, stale image), heal it.
If it needs code changes, open a branch + PR — don't push to main.

STEP 1 — Triage (read-only)
  docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' | grep -Ei 'sync|sharks|gc|dugout' || echo 'no matching container'
  docker logs --tail 120 sync_daemon 2>&1 | tail -80 || true
  # Data freshness — the daemon's job is to write these:
  ls -la /data/sharks/team_enriched.json /data/sharks/team.json /data/sharks/schedule_manual.json 2>&1
  stat -c '%y %n' /data/sharks/*.json 2>/dev/null | sort
  # Env sanity — daemon needs GC_TEAM_ID, GC_SEASON_SLUG, TEAM_NAME,
  # DEPLOY_WEBHOOK_TOKEN, CORS_ORIGINS, WRITE_ORIGINS, plus GC_EMAIL and
  # GC_PASSWORD (for the Playwright login path)
  docker exec sync_daemon env 2>/dev/null | grep -E '^(GC_|TEAM_|DEPLOY_|CORS_|WRITE_)' | sort || true
  # Playwright health (daemon uses chromium)
  docker exec sync_daemon which python playwright 2>&1 || true

STEP 2 — Classify the failure
Based on STEP 1, pick ONE bucket and act accordingly:

  A. Container missing / exited / stopped
     → `cd` to the Dugout clone, `docker compose up -d sync_daemon` (or
       `docker start sync_daemon` if already defined). If no compose
       file, look for `Dockerfile.sync` or similar; restart via existing
       script. Capture the startup logs and confirm it reaches
       "Entering sync loop" or equivalent.

  B. Container running but logs show auth failure (GC login)
     → Check GC_EMAIL / GC_PASSWORD are present (do NOT print values).
       If missing, tell Joel which env key is absent and STOP — he'll
       rotate. Do not attempt to guess credentials.

  C. Container running but logs show Playwright / chromium crash
     → Likely stale image. `docker compose build sync_daemon
       --no-cache && docker compose up -d sync_daemon`. Verify fresh
       chromium with `docker exec sync_daemon playwright --version`.

  D. Container healthy, logs look normal, but data files are stale
     → Trigger a manual cycle:
       `docker exec sync_daemon python -c "from tools.sync_daemon
       import run_sync_cycle; run_sync_cycle()"`
       Then re-check /data/sharks/*.json mtimes. If still stale, read
       the relevant scrape function in tools/sync_daemon.py via
       sequential small-chunk reads (file is ~200KB) and diagnose.

  E. Nothing on this Pi looks like sync_daemon at all
     → STOP. Report back that the daemon was never deployed here and
       let Joel decide where it should live.

STEP 3 — Report back
Write a single markdown summary to ~/pi-sync-daemon-report-$(date +%Y%m%d-%H%M).md with:
  - Classification (A/B/C/D/E)
  - Exact commands you ran
  - Before/after data-freshness timestamps
  - Whether DORI/Telegram should be notified (success only)
  - Next steps if you STOPPED (B or E)
Then tell Joel (plain English): fixed / partially fixed / blocked +
the report path. Do not open a PR unless STEP 2C required code
changes — in which case `git checkout -b fix/sync-daemon-<date>` and
`gh pr create` against main, body referencing
.auto-memory/project_modal_drift_2026-04-18.md on the PC side.

CONSTRAINTS
- Queen's English, terse, no fluff, no "let me…" narration
- Pasteable commands only; self-heal up to 3 attempts before asking
- Never log or print GC_PASSWORD / DEPLOY_WEBHOOK_TOKEN values
- Don't modify n8n or Modal — those are out of scope
- If a command would take >2 min, run it with & and poll
- At the end, offer Joel one sensible "yes" next step

Go.
```

---

**Why this prompt works:** It briefs the Pi session on what's already known (so it doesn't redo the Modal investigation), scopes it tightly (no n8n, no Modal, no main pushes), gives it a decision tree rather than a rigid recipe, and enforces the SIGN-004 PR-only rule. Output file path includes a timestamp so multiple runs don't clobber each other.

---

## DORI Telegram payloads (append to end of prompt above)

```
AFTER STEP 3, fire ONE curl from the matching block below. Webhook is
public (no auth). Payload must be valid JSON — no trailing commas.

Endpoint: https://n8n.joelycannoli.com/webhook/dugout-ralph-watchdog
Router logic: severity=success → ✅ silent, warning → ⚠️ silent,
              critical → 🚨 with sound

# === HEALED (class A, C, or D with fresh mtimes) ===
curl -sS -X POST https://n8n.joelycannoli.com/webhook/dugout-ralph-watchdog \
  -H "Content-Type: application/json" \
  -d '{"body":{"severity":"success","branch":"pi/sync_daemon","iterations":1,"duration_sec":0,"commits_made":"Pi sync_daemon healed — class <A|C|D>; latest team_enriched.json mtime: <ISO8601>"}}'

# === BLOCKED ON CREDS (class B) ===
curl -sS -X POST https://n8n.joelycannoli.com/webhook/dugout-ralph-watchdog \
  -H "Content-Type: application/json" \
  -d '{"body":{"severity":"critical","branch":"pi/sync_daemon","iterations":0,"duration_sec":0,"commits_made":"Pi sync_daemon BLOCKED — missing env var(s): <GC_EMAIL|GC_PASSWORD|...>. Joel must rotate."}}'

# === NEVER DEPLOYED (class E) ===
curl -sS -X POST https://n8n.joelycannoli.com/webhook/dugout-ralph-watchdog \
  -H "Content-Type: application/json" \
  -d '{"body":{"severity":"warning","branch":"pi/sync_daemon","iterations":0,"duration_sec":0,"commits_made":"Pi sync_daemon NOT FOUND on Pi — decision needed: deploy here or elsewhere"}}'

# === CODE FIX PRed (class C or D requiring patch) ===
curl -sS -X POST https://n8n.joelycannoli.com/webhook/dugout-ralph-watchdog \
  -H "Content-Type: application/json" \
  -d '{"body":{"severity":"warning","branch":"fix/sync-daemon-<date>","iterations":1,"duration_sec":0,"commits_made":"Pi sync_daemon fix PR opened: <PR_URL> — needs HITL review per SIGN-004"}}'

Do not invent severity values — the n8n Switch only routes critical|success|warning.
```
