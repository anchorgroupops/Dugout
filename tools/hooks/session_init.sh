#!/usr/bin/env bash
# session_init.sh — UserPromptSubmit hook.
# Injects guardrails + recent progress into context ONCE per session.
# Subsequent prompts in the same session are skipped via a session-keyed flag.

REPO="/home/user/Dugout"
SESSION_FLAG="/tmp/.dugout_session_init_${CLAUDE_SESSION_ID:-default}"

# Only inject once per session
[ -f "$SESSION_FLAG" ] && exit 0
touch "$SESSION_FLAG"

echo "<session-context>"
echo "# Dugout Session — $(date '+%Y-%m-%d %H:%M')"
echo ""
echo "## Known Failure Patterns (read before acting)"
cat "$REPO/guardrails.md"
echo ""
echo "## Recent Progress"
tail -30 "$REPO/progress.md"
echo "</session-context>"
