#!/usr/bin/env bash
# ralph.sh — Self-healing verification loop.
# Runs VERIFY_CMD in a loop until it passes or MAX_ITER is exhausted.
# Each attempt is logged to progress.md.
#
# Usage:
#   ./tools/ralph.sh [verify_cmd] [max_iterations]
#
# Examples:
#   ./tools/ralph.sh "python tools/opcheck.py" 5
#   ./tools/ralph.sh "pytest tests/ -q" 3
#   ./tools/ralph.sh                          # defaults: opcheck, 5 iterations

set -uo pipefail

VERIFY="${1:-python tools/opcheck.py}"
MAX_ITER="${2:-5}"
LOG="progress.md"
iter=1

echo "[ralph] Starting loop — cmd: $VERIFY  max: $MAX_ITER"

while [ "$iter" -le "$MAX_ITER" ]; do
  echo ""
  echo "[ralph] Iteration $iter/$MAX_ITER"

  if bash -c "$VERIFY"; then
    echo "- [$(date '+%Y-%m-%d %H:%M')] Ralph Loop: ✅ FIXED after $iter iteration(s). \`$VERIFY\`" >> "$LOG"
    echo ""
    echo "✅  FIXED in $iter iteration(s) — logged to $LOG"
    exit 0
  fi

  echo "- [$(date '+%Y-%m-%d %H:%M')] Ralph Loop: ❌ iteration $iter failed. \`$VERIFY\`" >> "$LOG"
  iter=$((iter + 1))
done

echo "- [$(date '+%Y-%m-%d %H:%M')] Ralph Loop: 🚨 EXHAUSTED $MAX_ITER iterations without passing. Manual review required." >> "$LOG"
echo ""
echo "❌  Exhausted $MAX_ITER iterations. Check $LOG for details."
exit 1
