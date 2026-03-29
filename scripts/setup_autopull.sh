#!/bin/bash
# One-time Pi setup for auto-deploy via GHCR + Watchtower
# Run on the Pi: bash scripts/setup_autopull.sh
#
# After this, every push to main auto-deploys in ~5 minutes.
# No SSH, no webhooks, no manual pulls ever again.

set -e

PROJECT_DIR="/home/joelycannoli/dugout"
cd "$PROJECT_DIR"

echo "=== Dugout Auto-Deploy Setup ==="
echo ""

# 1. Pull latest code
echo "[1/5] Pulling latest code from GitHub..."
git pull origin main

# 2. Authenticate Docker with GHCR
echo ""
echo "[2/5] Setting up GitHub Container Registry access..."
if docker pull ghcr.io/anchorgroupops/dugout-dashboard:latest 2>/dev/null; then
  echo "  Already authenticated with GHCR."
else
  echo ""
  echo "  You need a GitHub Personal Access Token (classic) with 'read:packages' scope."
  echo "  Create one at: https://github.com/settings/tokens/new"
  echo "  Select scope: read:packages"
  echo ""
  read -p "  Paste your GitHub token: " GH_TOKEN
  echo "$GH_TOKEN" | docker login ghcr.io -u anchorgroupops --password-stdin
  echo "  Logged in to GHCR."
fi

# 3. Generate deploy webhook token if not set
if grep -q "DEPLOY_WEBHOOK_TOKEN" "$PROJECT_DIR/.env" 2>/dev/null; then
  echo ""
  echo "[3/5] Deploy webhook token already exists — skipping."
else
  TOKEN=$(openssl rand -hex 32)
  echo "DEPLOY_WEBHOOK_TOKEN=$TOKEN" >> "$PROJECT_DIR/.env"
  echo ""
  echo "[3/5] Deploy webhook token generated."
  echo "  ┌─────────────────────────────────────────────────────────────────┐"
  echo "  │ Add this to GitHub > Settings > Secrets > DEPLOY_WEBHOOK_TOKEN │"
  echo "  │ $TOKEN │"
  echo "  └─────────────────────────────────────────────────────────────────┘"
fi

# 4. Pull images and start everything (including Watchtower)
echo ""
echo "[4/5] Pulling Docker images from GHCR..."
docker compose -f docker-compose.dugout.yml pull

echo ""
echo "[5/5] Starting all containers (dashboard + API + sync + watchtower)..."
docker compose -f docker-compose.dugout.yml up -d

echo ""
echo "=== Setup Complete ==="
echo ""
echo "How it works now:"
echo "  1. You (or Claude) push code to main"
echo "  2. GitHub Actions builds new Docker images (~3 min)"
echo "  3. Watchtower on this Pi detects new images (~5 min)"
echo "  4. Watchtower auto-pulls and restarts containers"
echo "  5. Dashboard is live at dugout.joelycannoli.com"
echo ""
echo "Total deploy time: ~5-8 min after push. Fully automatic."
echo ""
echo "To check status:  docker ps"
echo "To view logs:     docker logs -f dugout_api"
echo "Watchtower logs:  docker logs -f watchtower"
