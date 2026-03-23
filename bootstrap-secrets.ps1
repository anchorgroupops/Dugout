$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "scripts/bootstrap-secrets.ps1") @args
