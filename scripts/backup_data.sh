#!/bin/bash
# =============================================================================
# Dugout — Data Backup Script
# =============================================================================
# Creates timestamped backups of the data/ directory.
# Keeps the last 7 days of backups by default.
#
# Usage:
#   bash scripts/backup_data.sh              # Backup to ./backups/
#   bash scripts/backup_data.sh /mnt/usb     # Backup to custom location
#
# Cron example (daily at 2 AM):
#   0 2 * * * cd /home/ubuntu/dugout && bash scripts/backup_data.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_DIR/data"
BACKUP_DIR="${1:-$PROJECT_DIR/backups}"
RETAIN_DAYS="${BACKUP_RETAIN_DAYS:-7}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/dugout-data-$TIMESTAMP.tar.gz"

# Ensure backup directory exists
mkdir -p "$BACKUP_DIR"

if [ ! -d "$DATA_DIR" ]; then
    echo "[Backup] No data directory found at $DATA_DIR — nothing to back up."
    exit 0
fi

# Create compressed backup
echo "[Backup] Backing up $DATA_DIR..."
tar -czf "$BACKUP_FILE" -C "$PROJECT_DIR" data/

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[Backup] Created: $BACKUP_FILE ($BACKUP_SIZE)"

# Prune old backups
PRUNED=0
if [ "$RETAIN_DAYS" -gt 0 ]; then
    while IFS= read -r old_file; do
        rm -f "$old_file"
        PRUNED=$((PRUNED + 1))
    done < <(find "$BACKUP_DIR" -name "dugout-data-*.tar.gz" -mtime +"$RETAIN_DAYS" -type f 2>/dev/null)
fi

TOTAL=$(find "$BACKUP_DIR" -name "dugout-data-*.tar.gz" -type f | wc -l)
echo "[Backup] Done. $TOTAL backups on disk ($PRUNED pruned, retaining ${RETAIN_DAYS}d)."
