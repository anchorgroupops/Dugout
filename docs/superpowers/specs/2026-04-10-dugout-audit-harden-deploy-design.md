# Design Spec: Dugout Audit, Hardening & Deployment
**Date:** 2026-04-10
**Status:** Approved — executing

---

## Goal
Get `dugout.joelycannoli.com` fully operational and keep it that way through a hardened, automated pipeline from GitHub push → GHCR build → Pi redeploy → live site.

---

## Architecture (as-is, kept)

```
[GitHub main push]
    → CI: lint / build / python-check
    → build-deploy: builds arm64+amd64 images → pushes to GHCR
    → notify-deploy: POST /api/deploy to dugout.joelycannoli.com

[Pi — cloudflared-tunnel (tunnel ID: 50a18b93)]
    dugout.joelycannoli.com → http://sharks_dashboard:8080
    training.joelycannoli.com → http://training-app:3000

[Pi — Docker Compose (sharks_net)]
    sharks_dashboard  nginx:1.27-alpine  :8080 (serves React SPA + proxies /api/*)
    sharks_api        gunicorn/Flask     :5000 (sync_daemon.py — team data, SWOT, lineups)
    sharks_sync       sync_daemon.py     (GC scraper daemon, scheduled)
    watchtower        containrrr/watchtower (polls GHCR every 5 min, rolling restart)
```

Traefik is **not** used for Dugout — cloudflared handles SSL at the Cloudflare edge. This is intentional (simpler than routing through Traefik).

---

## Issues Found & Fixes

### Critical

| # | Issue | Fix |
|---|-------|-----|
| 1 | `sharks_api` crash loop: `PermissionError` on `logs/sync_daemon.log` (owned uid 1000, container `sharks` user blocked) | `chmod 666` on Pi + harden `sync_daemon.py` to create log with open permissions at startup |
| 2 | Cloudflare tunnel ingress routes `sharks_dashboard:80` but nginx listens on **8080** — will silently break on next Watchtower pull | Update `/home/joelycannoli/repos/Training/cloudflared/config.yml` → `sharks_dashboard:8080`, restart tunnel |
| 3 | Pi's `docker-compose.sharks.yml` has `ports: "3000:80"` (diverged from repo `"3000:8080"`) | `git pull` on Pi |

### High

| # | Issue | Fix |
|---|-------|-----|
| 4 | GitHub Actions `notify-deploy` has `continue-on-error: true` with no verification — CI goes green even if Pi never redeployed | Add `verify-deploy` job: polls `/api/health` after deploy webhook with retry |
| 5 | Deploy webhook chain dead when `sharks_api` is down (circular dependency) | Fixed by fixing #1 |

### Medium

| # | Issue | Fix |
|---|-------|-----|
| 6 | `deploy.sh` in project root is the old Librarian SCP script | Delete it |
| 7 | `architecture/07_pi_deployment.md` describes old Librarian systemd setup | Rewrite for Docker/Dugout |

---

## Files Changed

**Pi (SSH, no git commit needed):**
- `/home/joelycannoli/repos/Training/cloudflared/config.yml` — port 80 → 8080
- `/home/joelycannoli/dugout/logs/sync_daemon.log` — chmod 666
- `/home/joelycannoli/dugout/` — git pull

**Repo (committed + pushed):**
- `tools/sync_daemon.py` — log file creation hardening
- `.github/workflows/build-deploy.yml` — add verify-deploy job
- `deploy.sh` — deleted
- `architecture/07_pi_deployment.md` — rewritten

---

## Success Criteria
1. `docker ps` on Pi shows all 4 Dugout containers healthy (no restarts)
2. `curl https://dugout.joelycannoli.com/api/health` returns HTTP 200
3. Push to `main` → GitHub Actions green → Pi logs show `docker compose pull` ran
4. `dugout.joelycannoli.com` serves the React app in a browser
