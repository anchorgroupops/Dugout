#!/usr/bin/env bash
# Recovers sharks containers stuck in Created/missing state after Watchtower update.
# Uses docker compose up -d so healthcheck dependencies are respected.
set -uo pipefail
LOG="[watchtower-recover $(date -u +%Y-%m-%dT%H:%M:%SZ)]"
COMPOSE_FILE="/home/joelycannoli/dugout/docker-compose.sharks.yml"
NEEDS_RECOVERY=false

# Step 1: Check for containers stuck in Created or missing state
for c in sharks_api sharks_sync sharks_dashboard; do
  STATUS=$(docker inspect -f "{{.State.Status}}" "$c" 2>/dev/null || echo missing)
  if [ "$STATUS" = "created" ] || [ "$STATUS" = "missing" ]; then
    echo "$LOG Container $c in state: $STATUS -- triggering compose up"
    NEEDS_RECOVERY=true
  fi
done

# Step 2: If any container needs recovery, bring the whole stack up
if [ "$NEEDS_RECOVERY" = "true" ]; then
  docker compose -f "$COMPOSE_FILE" up -d
fi

# Step 3: Clean orphan renamed containers (e.g. b388f30f_sharks_api) only if
# the canonical container is already running (Watchtower done, just forgot to clean up).
for c in sharks_api sharks_sync sharks_dashboard; do
  CANON_STATUS=$(docker inspect -f "{{.State.Status}}" "$c" 2>/dev/null || echo missing)
  if [ "$CANON_STATUS" = running ]; then
    ORPHANS=$(docker ps -a --filter status=exited --format "{{.Names}}" | grep -E "^[0-9a-f]+_${c}$" || true)
    if [ -n "$ORPHANS" ]; then
      echo "$LOG Removing orphan: $ORPHANS (canonical $c is running)"
      echo "$ORPHANS" | xargs docker rm
    fi
  fi
done
echo "$LOG Done."
