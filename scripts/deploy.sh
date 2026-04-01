#!/bin/bash
# Deployment script for Sharks Dashboard
# Can be triggered by GitHub Actions webhook or run manually on the Pi

set -e

# Determine project root (works whether called from repo root or scripts/)
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

# Pull the latest changes from Git
echo "Pulling latest code..."
git pull origin main

# Rebuild and restart the containers
echo "Rebuilding and restarting Docker containers..."
if command -v docker &> /dev/null; then
  docker compose -f docker-compose.sharks.yml build --no-cache
  docker compose -f docker-compose.sharks.yml up -d
  echo "Docker containers rebuilt and restarted."
else
  echo "Docker not found — skipping container rebuild."
fi

echo "Deployment complete."
