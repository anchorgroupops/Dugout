# fix-modal-drift.ps1
# One-shot remediation for the stale softball-strategy-sharks Modal deployment.
# Drafted 2026-04-18 — see .auto-memory/project_modal_drift_2026-04-18.md
#
# What this does:
#   1. Confirms we're in the Dugout repo root
#   2. Verifies modal CLI is installed and authed
#   3. Runs `modal deploy tools/modal_app.py` (push current main → strip the broken scraper step)
#   4. Confirms the deployed daily_scout_job no longer references gc_scraper.py
#   5. Pings DORI via the existing watchdog webhook with the outcome
#
# Run elevated PowerShell (Windows). For Mac use `pwsh` or transcribe to bash.

$ErrorActionPreference = "Stop"
$projectRoot = "H:\Projects\PCLL\Dugout"
$webhook     = "https://n8n.joelycannoli.com/webhook/dugout-ralph-watchdog"
$startedAt   = Get-Date

function Send-DoriPing {
    param([string]$Severity, [string]$Body)
    try {
        $payload = @{
            body = @{
                severity     = $Severity
                branch       = "n/a"
                iterations   = 0
                duration_sec = ((Get-Date) - $startedAt).TotalSeconds
                commits_made = "modal-drift-fix: $Body"
            }
        } | ConvertTo-Json -Depth 6
        Invoke-RestMethod -Uri $webhook -Method Post -ContentType "application/json" -Body $payload -TimeoutSec 10 | Out-Null
    } catch {
        Write-Warning "DORI ping failed: $_"
    }
}

Write-Host "== Modal drift remediation ==" -ForegroundColor Cyan
Set-Location $projectRoot

# Pre-flight
$modal = Get-Command modal -ErrorAction SilentlyContinue
if (-not $modal) {
    Write-Host "[X] modal CLI not on PATH. Install: pip install --user modal" -ForegroundColor Red
    Send-DoriPing "critical" "modal CLI missing on PC"
    exit 1
}

$tokenInfo = & modal token current 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[X] modal not authenticated. Run: modal token new" -ForegroundColor Red
    Send-DoriPing "critical" "modal not authed"
    exit 1
}
Write-Host "[OK] modal CLI ready"

# Sanity-check the local file no longer contains the broken gc_scraper step
$localApp = Get-Content "tools\modal_app.py" -Raw
if ($localApp -match "gc_scraper\.py") {
    Write-Host "[X] tools/modal_app.py STILL references gc_scraper.py locally — abort." -ForegroundColor Red
    Write-Host "    Pull main and re-run, or you'll redeploy the same broken version." -ForegroundColor Red
    Send-DoriPing "critical" "local modal_app.py still has broken scraper step"
    exit 2
}
Write-Host "[OK] local modal_app.py is clean (no gc_scraper reference)"

# Deploy
Write-Host ""
Write-Host "== Deploying to Modal ==" -ForegroundColor Cyan
& modal deploy tools/modal_app.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "[X] modal deploy failed (exit $LASTEXITCODE)." -ForegroundColor Red
    Send-DoriPing "critical" "modal deploy failed exit=$LASTEXITCODE"
    exit 3
}
Write-Host "[OK] modal deploy completed"

# Verify the new app shows up
Write-Host ""
Write-Host "== Post-deploy verification ==" -ForegroundColor Cyan
$apps = & modal app list 2>&1
$appLine = $apps | Select-String "softball-strategy-sharks"
if (-not $appLine) {
    Write-Host "[!] Could not find softball-strategy-sharks in 'modal app list' output. Check manually:" -ForegroundColor Yellow
    Write-Host "    modal app list" -ForegroundColor Yellow
} else {
    Write-Host "[OK] $appLine"
}

# Done
$dur = ((Get-Date) - $startedAt).TotalSeconds
Write-Host ""
Write-Host "============================================="
Write-Host "  Modal drift remediation: DONE in $dur sec"
Write-Host "============================================="
Write-Host "Next failure email window: 02:00 ET tomorrow."
Write-Host "If no email arrives by 02:30 ET, fix held. If one does, check Modal logs."
Write-Host ""
Write-Host "Stats outage is a SEPARATE concern — verify Pi sync_daemon container next:"
Write-Host "  ssh joelycannoli@<pi-tailscale-ip>"
Write-Host "  docker ps | grep sync_daemon"
Write-Host "  docker logs --tail 80 sync_daemon"

Send-DoriPing "success" "modal redeployed; spam should stop after next 02:00 ET cron"
