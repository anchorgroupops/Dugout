#!/bin/bash
# Deployment script for Sharks Dashboard
# Can be triggered by GitHub Actions webhook or run manually on the Pi.
# Prefers GHCR pull (fast, matches CI-built images); falls back to local build.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}/.."

# If running on the Pi in the expected location, use that path
if [ -d "/home/joelycannoli/dugout" ]; then
  PROJECT_DIR="/home/joelycannoli/dugout"
elif [ -d "/home/joelycannoli/sharks" ]; then
  PROJECT_DIR="/home/joelycannoli/sharks"
fi

echo "Starting deployment in ${PROJECT_DIR}..."
cd "$PROJECT_DIR" || exit 1

# Pull the latest code (config/compose changes)
echo "Pulling latest code..."
git pull origin main

if ! command -v docker &> /dev/null; then
  echo "Docker not found — cannot deploy."
  exit 1
fi

# Pull pre-built images from GHCR; fall back to local build only if pull fails
echo "Pulling images from GHCR..."
if docker compose -f docker-compose.sharks.yml pull sharks_dashboard sharks_api 2>/dev/null; then
  echo "GHCR images pulled successfully."
else
  echo "GHCR pull failed — building locally as fallback..."
  docker compose -f docker-compose.sharks.yml build
fi

echo "Removing any watchtower-orphaned containers (missing compose project label)..."
for svc in sharks_dashboard sharks_api sharks_sync; do
  if docker inspect "$svc" >/dev/null 2>&1; then
    PROJ=$(docker inspect "$svc" --format '{{index .Config.Labels "com.docker.compose.project"}}' 2>/dev/null)
    if [ "$PROJ" != "dugout" ]; then
      echo "  Removing unmanaged container $svc (project label: '${PROJ}')..."
      docker stop "$svc" 2>/dev/null || true
      docker rm "$svc" 2>/dev/null || true
    fi
  fi
done

echo "Restarting containers..."
docker compose -f docker-compose.sharks.yml up -d

echo "Deployment complete."
