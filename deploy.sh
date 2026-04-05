#!/usr/bin/env bash
# deploy.sh — Push The Librarian dashboard to the Pi at joelycannoli.com
# Run from project root: bash deploy.sh

set -e

PI="pi"
REMOTE_DIR="/srv/librarian"
LOCAL_DASH="dashboard/index.html"

echo "==> Deploying The Librarian to ${PI}:${REMOTE_DIR}"

# 1. Ensure target dir exists on Pi
ssh "$PI" "sudo mkdir -p ${REMOTE_DIR} && sudo chown joelycannoli:joelycannoli ${REMOTE_DIR}"

# 2. Copy static assets
echo "  -> Syncing dashboard..."
scp "$LOCAL_DASH" "${PI}:${REMOTE_DIR}/index.html"

# 3. Copy data files that the dashboard reads
echo "  -> Syncing data files..."
scp notebooks.json "${PI}:${REMOTE_DIR}/notebooks.json"
scp suggestions.json "${PI}:${REMOTE_DIR}/suggestions.json" 2>/dev/null || true

# 4. Sync logs dir (if it exists)
if [ -d "logs" ]; then
  echo "  -> Syncing logs..."
  rsync -az logs/ "${PI}:${REMOTE_DIR}/logs/"
fi

echo "==> Deploy complete."
echo "    Dashboard: http://joelycannoli.com"
