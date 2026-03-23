$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$json = & python (Join-Path $repoRoot "tools/runtime_ops.py") bootstrap-secrets --emit-json
if (-not $json) {
    throw "No data returned from bootstrap-secrets."
}

$data = $json | ConvertFrom-Json
$keys = @(
    "PINECONE_API_KEY",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID",
    "GC_EMAIL",
    "GC_PASSWORD",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET"
)

foreach ($k in $keys) {
    $v = $data.$k
    if ($v) {
        Set-Item -Path ("env:" + $k) -Value $v
        $masked = if ($v.Length -gt 8) { $v.Substring(0, 4) + "..." + $v.Substring($v.Length - 4, 4) + " (len=" + $v.Length + ")" } else { $v.Substring(0,1) + "***" + $v.Substring($v.Length-1,1) }
        Write-Host ("[SECRETS] " + $k + ": present " + $masked)
    } else {
        Write-Host ("[SECRETS] " + $k + ": missing")
    }
}

Write-Host "[SECRETS] Session environment updated."
