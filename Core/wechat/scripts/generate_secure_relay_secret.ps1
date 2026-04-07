param(
    [int]$Bytes = 32
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($Bytes -lt 16) {
    throw "Bytes must be >= 16"
}

$buf = New-Object byte[] $Bytes
[System.Security.Cryptography.RandomNumberGenerator]::Fill($buf)
$hex = -join ($buf | ForEach-Object { $_.ToString("x2") })
$b64 = [Convert]::ToBase64String($buf)

Write-Host "SECURE_RELAY_SHARED_SECRET (hex):" -ForegroundColor Cyan
Write-Host $hex
Write-Host ""
Write-Host "SECURE_RELAY_SHARED_SECRET (base64):" -ForegroundColor Cyan
Write-Host $b64
