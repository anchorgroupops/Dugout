#!/usr/bin/env bash
# session_end.sh — Stop hook.
# After each Claude turn: check for uncommitted changes and remind about
# logging new SIGNs / harvest notes to guardrails.md and progress.md.

REPO="/home/user/Dugout"
CHANGED=$(git -C "$REPO" status --porcelain 2>/dev/null)

if [ -n "$CHANGED" ]; then
  echo "<session-reminder>"
  echo "Uncommitted changes detected in Dugout:"
  echo "$CHANGED"
  echo ""
  echo "Before closing: commit changes, and if any new failure patterns were"
  echo "discovered this session, add them to guardrails.md as a new SIGN."
  echo "Log completed work to progress.md."
  echo "</session-reminder>"
fi
