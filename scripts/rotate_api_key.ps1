param(
    [string]$EnvPath = ".env"
)

$fullPath = Resolve-Path $EnvPath -ErrorAction SilentlyContinue
if (-not $fullPath) {
    Write-Host "Missing .env; copy from .env.example first."
    exit 1
}

$newKey = "baarn-api-key-$([Guid]::NewGuid().ToString('N').Substring(0,16))"
$lines = Get-Content $fullPath
$updated = $false
$out = @()
foreach ($line in $lines) {
    if ($line -like "API_KEY=*") {
        $out += "API_KEY=$newKey"
        $updated = $true
    } else {
        $out += $line
    }
}
if (-not $updated) {
    $out += "API_KEY=$newKey"
}
$out | Set-Content $fullPath -NoNewline
Add-Content $fullPath ""
Write-Host "New API_KEY set: $newKey"
exit 0
