#!/usr/bin/env bash
# Dugout Command Poller — drains the GitHub issue command queue (macOS / Linux).
# Polls anchorgroupops/Dugout for open issues labelled 'dugout-command'.
# Executes run|rollback locally, comments result + closes issue.
# Schedule via crontab — every 5 min.
#   */5 * * * * /Users/joel/code/Dugout/scripts/ralph-command-poller.sh >> /tmp/poller-cron.log 2>&1

set -uo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$HOME/code/Dugout}"
REPO="${REPO:-anchorgroupops/Dugout}"
LABEL="${LABEL:-dugout-command}"
LOG_DIR="${LOG_DIR:-$HOME/Logs/ralph-dugout}"

mkdir -p "$LOG_DIR"
TS="$(date +%Y-%m-%d_%H%M%S)"
LOG_FILE="$LOG_DIR/poller-$TS.log"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"; }

# Preflight
if ! gh auth status >/dev/null 2>&1; then
    log "FATAL: gh CLI not authenticated. Run 'gh auth login'."
    exit 1
fi

cd "$PROJECT_ROOT" || { log "FATAL: project root not found: $PROJECT_ROOT"; exit 1; }

# Fetch open commands
ISSUES_JSON="$(gh issue list --repo "$REPO" --label "$LABEL" --state open --json number,title,body --limit 20 2>&1)" || {
    log "FATAL: gh issue list failed: $ISSUES_JSON"
    exit 1
}

COUNT="$(echo "$ISSUES_JSON" | jq 'length')"
if [ "$COUNT" -eq 0 ]; then
    log "No open commands. Exiting clean."
    exit 0
fi

log "Found $COUNT open command(s)."

# Process each
echo "$ISSUES_JSON" | jq -c '.[]' | while read -r issue; do
    NUM="$(echo "$issue" | jq -r '.number')"
    TITLE="$(echo "$issue" | jq -r '.title')"
    BODY="$(echo "$issue" | jq -r '.body')"
    log "Processing #$NUM — '$TITLE'"

    COMMAND="$(echo "$BODY" | grep -oE 'command:\s*[a-zA-Z]+' | head -1 | sed -E 's/command:\s*//' | tr 'A-Z' 'a-z')"
    [ -z "$COMMAND" ] && COMMAND="unknown"
    log "  command=$COMMAND"

    RESULT_FILE="/tmp/poller-result-$NUM.md"
    SUCCESS="false"

    case "$COMMAND" in
        run)
            log "  executing ./ralph.sh 10"
            RUN_OUT="$(./ralph.sh 10 2>&1)"
            RUN_EXIT=$?
            TAIL="$(echo "$RUN_OUT" | tail -n 30)"
            [ "$RUN_EXIT" -eq 0 ] && SUCCESS="true"
            cat > "$RESULT_FILE" <<EOF
## Command result: \`run\`

**Exit code:** $RUN_EXIT
**Host:** $(hostname)
**Completed:** $(date -u +%Y-%m-%dT%H:%M:%SZ)

### Tail of output
\`\`\`
$TAIL
\`\`\`

_Closed by ralph-command-poller.sh. Watchdog will post the full summary to DORI._
EOF
            ;;
        rollback)
            PRE_HEAD="$(git rev-parse HEAD)"
            BRANCH="$(git rev-parse --abbrev-ref HEAD)"

            if [ "$BRANCH" != "main" ]; then
                cat > "$RESULT_FILE" <<EOF
## Command result: \`rollback\` — SKIPPED

Current branch is \`$BRANCH\` (expected \`main\`). Rollback only runs on main.
EOF
            else
                ROLLBACK_BRANCH="rollback/$(date +%Y-%m-%d-%H%M%S)-$(git rev-parse --short HEAD)"
                log "  carving rollback branch $ROLLBACK_BRANCH from HEAD~1"
                git checkout -b "$ROLLBACK_BRANCH" "HEAD~1" >/dev/null 2>&1

                if git push -u origin "$ROLLBACK_BRANCH" >/dev/null 2>&1; then
                    PR_URL="$(gh pr create --base main --head "$ROLLBACK_BRANCH" \
                        --title "ROLLBACK: revert most recent autonomous commit" \
                        --body "Rollback triggered by Telegram command (issue #$NUM). Review diff before merging." 2>/dev/null)"
                    SUCCESS="true"
                    cat > "$RESULT_FILE" <<EOF
## Command result: \`rollback\` — PR OPENED

**Rollback branch:** \`$ROLLBACK_BRANCH\`
**Reverted commit:** \`$PRE_HEAD\`
**PR URL:** $PR_URL

_Merge the PR to complete rollback. SIGN-004 respected — no force-push to main._
EOF
                else
                    cat > "$RESULT_FILE" <<EOF
## Command result: \`rollback\` — FAILED

git push of rollback branch failed.
EOF
                fi

                git checkout main >/dev/null 2>&1
            fi
            ;;
        *)
            cat > "$RESULT_FILE" <<EOF
## Command result: unknown command \`$COMMAND\`

Supported commands: \`run\`, \`rollback\`.
EOF
            ;;
    esac

    gh issue comment "$NUM" --repo "$REPO" --body-file "$RESULT_FILE" >/dev/null
    gh issue close "$NUM" --repo "$REPO" >/dev/null
    rm -f "$RESULT_FILE"

    MARKER="OK"
    [ "$SUCCESS" = "true" ] || MARKER="FAIL"
    log "  #$NUM closed [$MARKER]"
done

log "Poller run complete."
exit 0
