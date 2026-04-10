# SOP 07: Raspberry Pi 5 Deployment — Dugout

Layer 3 — Infrastructure | Sharks Softball Dashboard

## Overview

Dugout runs on the Raspberry Pi 5 (`192.168.7.222`) as a Docker Compose stack.
Traffic reaches the Pi via a **Cloudflare Tunnel** (no port-forwarding required).

```text
Internet
  └── Cloudflare (dugout.joelycannoli.com, DNS proxied)
        └── cloudflared-tunnel (container on Pi)
              └── http://sharks_dashboard:8080  ← nginx/React SPA
                    └── /api/* proxied → sharks_api:5000 (gunicorn/Flask)
```

## Services (docker-compose.sharks.yml)

| Container | Image | Role |
| --- | --- | --- |
| `sharks_dashboard` | `ghcr.io/anchorgroupops/sharks-dashboard:latest` | nginx serving React SPA + API proxy |
| `sharks_api` | `ghcr.io/anchorgroupops/sharks-api:latest` | gunicorn/Flask serving team data, SWOT, lineups |
| `sharks_sync` | `ghcr.io/anchorgroupops/sharks-api:latest` | sync_daemon.py — GC scraper, runs on schedule |
| `watchtower` | `containrrr/watchtower:latest` | polls GHCR every 5 min, rolling restart on new images |

## Deploy Directory on Pi

```text
/home/joelycannoli/dugout/
├── docker-compose.sharks.yml   ← source of truth for container config
├── .env                        ← secrets (never committed)
├── data/                       ← mounted into sharks_api + sharks_sync
│   └── sharks/                 ← team.json, swot_analysis.json, lineups.json, etc.
├── logs/                       ← mounted into sharks_api + sharks_sync
│   └── sync_daemon.log
└── Scorebooks/                 ← PDF scorebooks (read-only mount)
```

## Automated Deploy Flow (GitHub Actions → Pi)

1. **Push to `main`** → `build-deploy.yml` runs
2. **Builds** `sharks-dashboard` (React + nginx) and `sharks-api` (Python + Playwright) for `linux/arm64,linux/amd64`
3. **Pushes** both images to `ghcr.io/anchorgroupops/`
4. **Fires webhook**: `POST https://dugout.joelycannoli.com/api/deploy` with `DEPLOY_WEBHOOK_TOKEN`
5. **`sharks_api`** handles the webhook → runs `scripts/deploy.sh` on Pi:
   - `git pull origin main` (syncs compose + config)
   - `docker compose pull sharks_dashboard sharks_api`
   - `docker compose up -d`
6. **`verify-deploy` job** polls `/api/health` for up to 3 minutes to confirm the Pi came up

**Watchtower** (every 5 min) acts as a fallback if the webhook is temporarily unreachable.

## Manual Deploy (Pi)

```bash
cd /home/joelycannoli/dugout
git pull origin main
docker compose -f docker-compose.sharks.yml pull
docker compose -f docker-compose.sharks.yml up -d
```

## Cloudflare Tunnel Config

File: `/home/joelycannoli/repos/Training/cloudflared/config.yml`

```yaml
ingress:
  - hostname: dugout.joelycannoli.com
    service: http://sharks_dashboard:8080
  - hostname: training.joelycannoli.com
    service: http://training-app:3000
  - service: http_status:404
```

After editing, restart the tunnel:

```bash
docker restart cloudflared-tunnel
```

**Note:** Traefik is NOT used for Dugout. SSL is terminated by Cloudflare at the edge.
The `cloudflared-tunnel` container must be on `sharks_net` to reach `sharks_dashboard` by name.

## Secrets (.env)

Copy `.env.example` to `.env` and fill in:

- `GC_EMAIL`, `GC_TEAM_ID`, `GC_SEASON_SLUG`, `GC_ORG_IDS` — GameChanger credentials
- `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` — voice synthesis
- `DEPLOY_WEBHOOK_TOKEN` — must match the GitHub Actions secret of the same name
- `CLOUDFLARE_EMAIL` — used by Traefik ACME (n8n/librarian, not Dugout directly)

## Verification

```bash
# All containers healthy
docker ps --filter 'name=sharks' --format 'table {{.Names}}\t{{.Status}}'

# API health check
curl https://dugout.joelycannoli.com/api/health

# Logs
docker logs sharks_api --tail 50
docker logs sharks_dashboard --tail 20
```

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `sharks_api` crash loop: `PermissionError: logs/sync_daemon.log` | Log file owned by host uid 1000, container user blocked | `chmod 666 /home/joelycannoli/dugout/logs/sync_daemon.log` then `docker restart sharks_api` |
| `dugout.joelycannoli.com` returns 502/connection refused | cloudflared ingress pointing to wrong port | Edit `cloudflared/config.yml` → ensure `sharks_dashboard:8080`, `docker restart cloudflared-tunnel` |
| Dashboard loads but `/api/*` returns 502 | `sharks_api` not healthy | `docker logs sharks_api --tail 50` to diagnose |
| Watchtower not updating | GHCR credentials missing | Ensure `~/.docker/config.json` has GHCR token on Pi |
