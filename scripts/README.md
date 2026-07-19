# Dugout Ralph Autonomous Loop — Install & Operate

Full autonomous audit+heal+HITL stack for the Dugout portal. Three n8n workflows
on the Pi, two script pairs on your PC/Mac, all wired to DORI Telegram.

**What runs where:**

| Component | Host | Role |
|---|---|---|
| `ralph-watchdog.{ps1,sh}` | PC / Mac | Nightly runner — kicks Ralph, reports to Pi |
| `ralph-command-poller.{ps1,sh}` | PC / Mac | Every 5 min — drains GitHub issue command queue |
| Watchdog Router (`h1T0OtI2xnJqEfVh`) | Pi / n8n | Routes nightly results to Telegram |
| Telegram Commands (`jodsyjVl6HeTZjjI`) | Pi / n8n | `/dugout-*` commands → GitHub issue queue |
| Drift Watcher (`49HKHZiG82sg0eRJ`) | Pi / n8n | Every 10 min — catches non-full-send commits on main |

**Key safety invariants (SIGN-004):**

- Watchdog auto-opens a PR on clean runs — never pushes to `main` directly
- Rollback command opens a PR against `main` — never force-pushes
- Drift watcher only *queues* audits, never edits code

## Prerequisites

- `claude` CLI on PATH (`claude --version` works)
- `git` on PATH
- `gh` CLI installed and authenticated for the auto-PR step:
  ```bash
  gh auth login
  gh auth status   # confirm
  ```
- For Windows: `bash` from Git for Windows (path auto-detected by the wrapper)
- `jq` on PATH (macOS/Linux only, used by .sh wrapper)

If `gh` is not authenticated, the loop still runs and Telegram still notifies —
the auto-PR step is skipped silently with a log warning.

## Auto-PR flow

When a run exits with severity=`success` AND new commits exist AND the working
branch is `main`:

1. Wrapper carves the new commits onto branch `full-send/YYYY-MM-DD-HHMMSS-{sha}`
2. Resets `main` back to its pre-run state (no main pollution)
3. Pushes the feature branch to GitHub
4. Opens a PR against `main` with the execution summary as the body
5. Includes the PR URL in the Telegram message — tap to open and merge

`main` is never pushed to. SIGN-004 (GitOps: human approves every push to main)
is honoured by routing through PR review.


## n8n side (one-time)

Workflow ID: `h1T0OtI2xnJqEfVh`
URL: https://n8n.joelycannoli.com/workflow/h1T0OtI2xnJqEfVh

Before activating:

1. Open each Telegram node → bind the existing **Telegram account** credential used by "Watchtower - Telegram - Commands" (DORI).
2. Replace `REPLACE_WITH_DORI_CHAT_ID` in all three Telegram nodes with your Telegram chat ID (copy from the DORI workflow).
3. Toggle workflow to **Active**.
4. Test with:

   ```bash
   curl -X POST https://n8n.joelycannoli.com/webhook/dugout-ralph-watchdog \
     -H "Content-Type: application/json" \
     -d '{"body":{"severity":"success","branch":"main","iterations":10,"duration_sec":42,"commits_made":"test"}}'
   ```

   You should receive a ✅ Telegram message within seconds.

## Windows Task Scheduler (PC)

One-time install — paste into **elevated PowerShell**:

```powershell
$proj = "H:\Projects\PCLL\Dugout"
$task = "Dugout-Ralph-Watchdog"
schtasks /Create /SC DAILY /ST 02:00 /TN $task `
  /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$proj\scripts\ralph-watchdog.ps1`"" `
  /RL HIGHEST /F

# Verify
schtasks /Query /TN $task /V /FO LIST | Select-String "Next Run|Status"

# Run once on demand (test)
schtasks /Run /TN $task
```

**Remove:** `schtasks /Delete /TN "Dugout-Ralph-Watchdog" /F`

## macOS / Linux crontab (roaming MacBook)

```bash
# Edit crontab
crontab -e

# Add this line (2:00 AM nightly). Swap PROJECT_ROOT if needed.
0 2 * * * /Users/joel/code/Dugout/scripts/ralph-watchdog.sh >> /tmp/ralph-cron.log 2>&1
```

Check it queued: `crontab -l`

## Logs

- **PC:** `%USERPROFILE%\Logs\ralph-dugout\ralph-{timestamp}.log`
- **macOS:** `~/Logs/ralph-dugout/ralph-{timestamp}.log`
- **n8n executions:** https://n8n.joelycannoli.com/executions

## Severity mapping

| Severity   | Trigger                                    | Telegram icon | Notification |
|------------|--------------------------------------------|---------------|--------------|
| `critical` | SIGN-008 hit, exit ≠ 0, blocker/rollback   | 🚨             | Sound on     |
| `success`  | `<promise>COMPLETE</promise>` present      | ✅             | Silent       |
| `warning`  | Anything else                              | ⚠️             | Silent       |

## SIGN-008 behaviour

If three self-heal attempts on the same error fail:
1. Watchdog captures `MAX ITERATIONS REACHED` or `SIGN-008` in the log
2. Classifies severity as `critical`
3. Telegram alert posts with full tail + git state
4. Next morning you can triage via Telegram thread (DORI can `/commands` into follow-up actions)

## Kill-switch

Disable the schedule:
- **Windows:** `schtasks /Change /TN "Dugout-Ralph-Watchdog" /DISABLE`
- **macOS:** comment the cron line: `crontab -l | sed 's|^0 2.*ralph-watchdog.sh|# &|' | crontab -`
- **n8n:** flip workflow `h1T0OtI2xnJqEfVh` to Inactive

---

# Command Poller (runs every 5 min)

Drains the GitHub issue command queue. Issues labelled `dugout-command` with body
`command: run` or `command: rollback` get executed locally and closed with a result
comment.

## n8n workflow: Dugout Telegram Commands (`jodsyjVl6HeTZjjI`)

Telegram listener. Before activating:

1. Open each Telegram node → bind DORI credential from `h2FGBUte0ckc8Z14`.
2. Create `REPLACE_WITH_GITHUB_PAT` credential env (or swap placeholder inline in both HTTP Request nodes). PAT scopes: `repo` (for issues write).
3. Create `REPLACE_WITH_N8N_API_KEY` value (n8n → Settings → API) and swap in the `Query Last Execution` node header.
4. Toggle **Active**.
5. In Telegram (DORI thread): send `/dugout-help` — you should get the menu.

## Windows Task Scheduler (poller)

```powershell
$proj = "H:\Projects\PCLL\Dugout"
$task = "Dugout-Command-Poller"
schtasks /Create /SC MINUTE /MO 5 /TN $task `
  /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$proj\scripts\ralph-command-poller.ps1`"" `
  /RL HIGHEST /F

# Verify
schtasks /Query /TN $task /V /FO LIST | Select-String "Next Run|Status"

# Run once manually
schtasks /Run /TN $task
```

**Remove:** `schtasks /Delete /TN "Dugout-Command-Poller" /F`

## macOS crontab (poller)

```bash
crontab -e

# Add (every 5 minutes)
*/5 * * * * /Users/joel/code/Dugout/scripts/ralph-command-poller.sh >> /tmp/poller-cron.log 2>&1
```

## Available commands (Telegram → DORI)

| Command | Behaviour |
|---|---|
| `/dugout-help` | Menu |
| `/dugout-status` | Last watchdog run summary (queries n8n executions API) |
| `/dugout-run` | Queue manual Ralph audit (poller executes within ≤5 min) |
| `/dugout-rollback` | Revert HEAD~1 → open rollback PR (HITL gates merge) |

---

# Drift Watcher (runs every 10 min on Pi)

## n8n workflow: Dugout Drift Watcher (`49HKHZiG82sg0eRJ`)

Fires every 10 min, lists main commits from last 15 min, flags any commit whose
message does NOT contain `full-send` and whose author type is not `Bot`.
When drift is detected it simultaneously:

1. Creates a `dugout-command` issue with `command: run` → picked up by next poller pass
2. Sends a silent heads-up to DORI Telegram

Before activating:

1. Bind Telegram credential + swap `REPLACE_WITH_DORI_CHAT_ID` in the `Heads-Up to DORI` node.
2. Swap `REPLACE_WITH_GITHUB_PAT` in both HTTP Request nodes (or bind a credential).
3. Toggle **Active**.

## Kill-switch (full stack)

| Layer | Command |
|---|---|
| Watchdog schedule (PC) | `schtasks /Change /TN "Dugout-Ralph-Watchdog" /DISABLE` |
| Poller schedule (PC) | `schtasks /Change /TN "Dugout-Command-Poller" /DISABLE` |
| Watchdog router (n8n) | Flip `h1T0OtI2xnJqEfVh` Inactive |
| Telegram commands (n8n) | Flip `jodsyjVl6HeTZjjI` Inactive |
| Drift watcher (n8n) | Flip `49HKHZiG82sg0eRJ` Inactive |

---

# See also

- `.ralph/PLUGIN-ROADMAP.md` — plan to extract this whole stack into a reusable Cowork plugin
