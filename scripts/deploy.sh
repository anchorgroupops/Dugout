#!/bin/bash
# Deployment script for Sharks Dashboard
# Executed by GitHub Actions on push to main

echo "Starting deployment..."
cd /home/joelycannoli/sharks || exit 1

# Pull the latest changes from Git
echo "Pulling latest code..."
git pull origin main

# Rebuild and restart the containers
echo "Rebuilding and restarting Docker containers..."
docker compose -f docker-compose.sharks.yml build --no-cache
docker compose -f docker-compose.sharks.yml up -d

echo "Deployment complete."
