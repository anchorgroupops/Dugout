#!/bin/bash
# One-time setup script for webhook-based auto-deploy
# Run this on the Pi via Raspberry Pi Connect:
#   curl -sL https://raw.githubusercontent.com/anchorgroupops/Softball/main/scripts/setup_deploy.sh | bash
#
# Or if the repo is already cloned:
#   bash /home/joelycannoli/sharks/scripts/setup_deploy.sh

set -e

PROJECT_DIR="/home/joelycannoli/sharks"

echo "=== Sharks Dashboard Deploy Setup ==="

# 1. Pull latest code
echo "[1/4] Pulling latest code..."
cd "$PROJECT_DIR"
git pull origin main

# 2. Generate deploy token if not already set
if grep -q "DEPLOY_WEBHOOK_TOKEN" "$PROJECT_DIR/.env" 2>/dev/null; then
  echo "[2/4] Deploy token already exists in .env — skipping."
else
  TOKEN=$(openssl rand -hex 32)
  echo "DEPLOY_WEBHOOK_TOKEN=$TOKEN" >> "$PROJECT_DIR/.env"
  echo "[2/4] Deploy token generated."
  echo ""
  echo "╔══════════════════════════════════════════════════════════════════╗"
  echo "║  IMPORTANT: Copy this token and add it to GitHub:              ║"
  echo "║  Settings > Secrets > Actions > DEPLOY_WEBHOOK_TOKEN           ║"
  echo "╠══════════════════════════════════════════════════════════════════╣"
  echo "║  $TOKEN  ║"
  echo "╚══════════════════════════════════════════════════════════════════╝"
  echo ""
fi

# 3. Rebuild containers
echo "[3/4] Rebuilding Docker containers (this may take a few minutes)..."
docker compose -f docker-compose.sharks.yml build --no-cache

# 4. Restart
echo "[4/4] Starting containers..."
docker compose -f docker-compose.sharks.yml up -d

echo ""
echo "=== Done! Dashboard should be live at sharks.joelycannoli.com ==="
echo "=== Don't forget to add the token to GitHub Secrets if shown above ==="
