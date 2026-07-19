<#
.SYNOPSIS
    Dugout Command Poller — drains the GitHub issue command queue.

.DESCRIPTION
    Polls anchorgroupops/Dugout for open issues labelled `dugout-command`.
    For each issue:
      - Parses `command:` line from body (run | rollback)
      - Executes the action locally (run = ./ralph.sh, rollback = revert HEAD~1)
      - Comments the result + closes the issue
      - Auto-PR on rollback so HITL still gates pushes to main
    Ships SIGN-004 compliance: never pushes to main directly.

.NOTES
    Scheduled via Windows Task Scheduler every 5 minutes.
    Requires: gh CLI authenticated, git, bash on PATH.
#>

param(
    [string]$ProjectRoot = "H:\Projects\PCLL\Dugout",
    [string]$Repo = "anchorgroupops/Dugout",
    [string]$Label = "dugout-command",
    [string]$LogDir = "$env:USERPROFILE\Logs\ralph-dugout"
)

$ErrorActionPreference = "Continue"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
$ts = Get-Date -Format "yyyy-MM-dd_HHmmss"
$logFile = Join-Path $LogDir "poller-$ts.log"

function Log($msg) {
    $stamp = (Get-Date -Format "u")
    "[$stamp] $msg" | Tee-Object -FilePath $logFile -Append | Out-Null
    Write-Host "[$stamp] $msg"
}

# --- Preflight ---
& gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Log "FATAL: gh CLI not authenticated. Run 'gh auth login'."
    exit 1
}

Set-Location $ProjectRoot

# --- Fetch open commands ---
$issuesJson = & gh issue list --repo $Repo --label $Label --state open --json number,title,body,labels --limit 20 2>&1
if ($LASTEXITCODE -ne 0) {
    Log "FATAL: gh issue list failed: $issuesJson"
    exit 1
}

$issues = $issuesJson | ConvertFrom-Json
if (-not $issues -or $issues.Count -eq 0) {
    Log "No open commands. Exiting clean."
    exit 0
}

Log "Found $($issues.Count) open command(s)."

# --- Process each ---
foreach ($issue in $issues) {
    $num = $issue.number
    $body = $issue.body
    Log "Processing #$num — '$($issue.title)'"

    # Parse command from body (e.g. "command: run")
    $cmdMatch = $body | Select-String -Pattern "command:\s*(\w+)" -AllMatches
    $command = if ($cmdMatch.Matches.Count -gt 0) { $cmdMatch.Matches[0].Groups[1].Value.ToLower() } else { "unknown" }
    Log "  command=$command"

    $resultBody = ""
    $success = $false

    switch ($command) {
        "run" {
            $bashPath = (Get-Command bash -ErrorAction SilentlyContinue).Source
            if (-not $bashPath) { $bashPath = "C:\Program Files\Git\bin\bash.exe" }

            Log "  executing ./ralph.sh 10 via $bashPath"
            $runOut = & $bashPath -c "cd `"$ProjectRoot`" && ./ralph.sh 10" 2>&1
            $runExit = $LASTEXITCODE
            $tail = ($runOut | Select-Object -Last 30) -join "`n"
            $success = ($runExit -eq 0)
            $resultBody = @"
## Command result: ``run``

**Exit code:** $runExit
**Host:** $($env:COMPUTERNAME)
**Completed:** $(Get-Date -Format "u")

### Tail of output
``````
$tail
``````

_Closed by ralph-command-poller.ps1. Watchdog will post the full summary to DORI once the nightly run reports in._
"@
        }
        "rollback" {
            $preHead = (git rev-parse HEAD).Trim()
            $branch = (git rev-parse --abbrev-ref HEAD).Trim()

            if ($branch -ne "main") {
                $success = $false
                $resultBody = @"
## Command result: ``rollback`` — SKIPPED

Current branch is ``$branch`` (expected ``main``). Rollback only runs on main to preserve SIGN-004 safety.

_Closed by ralph-command-poller.ps1. Check out main and re-queue if needed._
"@
                break
            }

            # Create rollback branch from HEAD~1
            $rollbackBranch = "rollback/$(Get-Date -Format 'yyyy-MM-dd-HHmmss')-$(git rev-parse --short HEAD)"
            Log "  carving rollback branch $rollbackBranch from HEAD~1"
            & git checkout -b $rollbackBranch "HEAD~1" | Out-Null

            $pushResult = & git push -u origin $rollbackBranch 2>&1
            if ($LASTEXITCODE -eq 0) {
                $prUrl = & gh pr create --base main --head $rollbackBranch `
                    --title "ROLLBACK: revert most recent autonomous commit" `
                    --body "Rollback triggered by Telegram command (issue #$num). Review diff before merging."
                $success = $true
                $resultBody = @"
## Command result: ``rollback`` — PR OPENED

**Rollback branch:** ``$rollbackBranch``
**Reverted commit:** ``$preHead``
**PR URL:** $prUrl

_Merge the PR to complete rollback. SIGN-004 respected — no force-push to main._
"@
            } else {
                $success = $false
                $resultBody = @"
## Command result: ``rollback`` — FAILED

git push of rollback branch failed:
``````
$pushResult
``````

_Closed by ralph-command-poller.ps1. Investigate and re-queue._
"@
            }

            # Return to main regardless
            & git checkout main | Out-Null
        }
        default {
            $resultBody = @"
## Command result: unknown command ``$command``

Supported commands: ``run``, ``rollback``.
_Closed by ralph-command-poller.ps1._
"@
        }
    }

    # Comment + close
    $bodyFile = Join-Path $env:TEMP "poller-result-$num.md"
    Set-Content -Path $bodyFile -Value $resultBody -Encoding UTF8
    & gh issue comment $num --repo $Repo --body-file $bodyFile | Out-Null
    & gh issue close $num --repo $Repo | Out-Null
    Remove-Item $bodyFile -ErrorAction SilentlyContinue

    $marker = if ($success) { "OK" } else { "FAIL" }
    Log "  #$num closed [$marker]"
}

Log "Poller run complete."
exit 0
