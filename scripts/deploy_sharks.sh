#!/bin/bash
# deploy_sharks.sh — Deploy Sharks Dashboard to Raspberry Pi
#
# SAFETY: This script ONLY touches port 3000 via a standalone docker-compose.
# It does NOT interact with n8n (port 5678), Postgres (port 5432),
# or any existing Docker networks/containers.
#
# Prerequisites:
#   1. Git repo cloned on Pi at ~/sharks (or wherever)
#   2. Docker and docker-compose installed on Pi
#   3. npm installed on build machine (for production build)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Sharks Dashboard Deployment ==="
echo "Project: $PROJECT_DIR"
echo ""

# Step 1: Build production bundle (run on build machine, not Pi)
echo "[1/3] Building production bundle..."
cd "$PROJECT_DIR/client"
npm run build
echo "      Build complete."

# Step 2: Start the dashboard container
echo "[2/3] Starting sharks_dashboard container on port 3000..."
cd "$PROJECT_DIR"
docker compose -f docker-compose.sharks.yml up -d --force-recreate
echo "      Container started."

# Step 3: Verify
echo "[3/3] Verifying deployment..."
sleep 3
if curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 | grep -q "200"; then
    echo "      ✅ Dashboard is live at http://localhost:3000"
else
    echo "      ⚠️  Dashboard may still be starting. Check: docker logs sharks_dashboard"
fi

echo ""
echo "=== Deployment Complete ==="
echo "Next step: Add Cloudflare tunnel for dugout.joelycannoli.com -> http://192.168.7.222:3000"
