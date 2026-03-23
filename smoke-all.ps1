$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "scripts/smoke-all.ps1") @args
