# ==============================================================================
# AI HIVE SETUP SCRIPT
# Synchronizes rules, memory, and context across Antigravity, Claude, and Codex
# ==============================================================================

$homeDir = [Environment]::GetFolderPath("UserProfile")
$geminiRules = Join-Path $homeDir ".gemini\GEMINI.md"
$cursorRules = Join-Path $PWD ".cursorrules"
$claudeConfig = Join-Path $PWD "claude-project.md"

Write-Host "Syncing Universal Rules..." -ForegroundColor Cyan

# 1. Sync Cursor/Codex Rules
if (Test-Path $geminiRules) {
    Write-Host "Found GEMINI.md. Linking to .cursorrules for GPT/Codex..."
    Copy-Item -Path $geminiRules -Destination $cursorRules -Force
    Write-Host "✅ .cursorrules updated to match AG Global Rules." -ForegroundColor Green
} else {
    Write-Host "❌ Could not find ~/.gemini/GEMINI.md" -ForegroundColor Red
}

# 2. Sync Claude Context
if (Test-Path $geminiRules) {
    Write-Host "Linking to claude-project.md for Claude Code..."
    Copy-Item -Path $geminiRules -Destination $claudeConfig -Force
    Write-Host "✅ claude-project.md updated to match AG Global Rules." -ForegroundColor Green
}

# 3. Create a unified Workspace memory router
$aiMemoryDir = Join-Path $PWD ".ai_memory"
if (-Not (Test-Path $aiMemoryDir)) {
    New-Item -ItemType Directory -Path $aiMemoryDir | Out-Null
    Write-Host "✅ Created .ai_memory shared directory." -ForegroundColor Green
    
    # Initialize basic shared state files
    New-Item -ItemType File -Path (Join-Path $aiMemoryDir "task_plan.md") -Value "# Unified Task Plan`nAll agents read and update this file." | Out-Null
    New-Item -ItemType File -Path (Join-Path $aiMemoryDir "findings.md") -Value "# Unified Findings`nShared architectural discoveries." | Out-Null
} else {
    Write-Host "✅ .ai_memory shared directory already exists." -ForegroundColor Green
}

Write-Host "`nHive Synchronization Complete!" -ForegroundColor Cyan
Write-Host "You can run this script anytime you update GEMINI.md to push the new rules to Cursor and Claude."
