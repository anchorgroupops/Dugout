#!/bin/bash
# Deploy the Sharks Dashboard on the Pi.
# Run: cd /home/joelycannoli/sharks && git pull origin main && bash scripts/setup_deploy.sh
set -e

cd /home/joelycannoli/dugout 2>/dev/null || cd /home/joelycannoli/sharks 2>/dev/null || cd "$(dirname "$0")/.."

echo "=== Deploying Sharks Dashboard ==="

# Try to pull GHCR images; if that fails, build locally
echo "[1/2] Building containers..."
if docker compose -f docker-compose.sharks.yml pull sharks_dashboard sharks_api 2>/dev/null; then
  echo "  Pulled images from GHCR."
else
  echo "  GHCR pull failed — building locally..."
  docker compose -f docker-compose.sharks.yml build --no-cache
fi

echo "[2/2] Starting containers..."
docker compose -f docker-compose.sharks.yml up -d

echo ""
echo "=== Done! Site should be live at dugout.joelycannoli.com ==="
