$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
python (Join-Path $repoRoot "tools/runtime_ops.py") smoke-all @args
