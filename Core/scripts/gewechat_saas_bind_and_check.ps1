param(
    [Parameter(Mandatory = $true)]
    [string]$Token,
    [Parameter(Mandatory = $true)]
    [string]$AppId,
    [string]$BaseUrl = "https://api.geweapi.com/gewe/v2/api",
    [string]$CallbackUrl = "http://host.docker.internal:9010/gewechat/callback",
    [string]$BridgeUrl = "http://127.0.0.1:9010",
    [string]$ToWxid = "",
    [string]$Text = "hello from avis",
    [switch]$SkipCallback,
    [switch]$CheckBridgeSend,
    [switch]$InjectBridgeTestMessage
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-GewePost {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][hashtable]$Body,
        [Parameter(Mandatory = $true)][string]$TokenValue,
        [Parameter(Mandatory = $true)][string]$ApiBase
    )

    $uri = "{0}/{1}" -f $ApiBase.TrimEnd('/'), $Path.TrimStart('/')
    $headers = @{
        "Content-Type" = "application/json"
        "X-GEWE-TOKEN" = $TokenValue
    }
    $json = $Body | ConvertTo-Json -Depth 8 -Compress
    return Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -Body $json -TimeoutSec 20
}

Write-Host "[1/5] Checking bridge health..." -ForegroundColor Cyan
try {
    $bridgeInfo = Invoke-RestMethod -Method Get -Uri ("{0}/" -f $BridgeUrl.TrimEnd('/')) -TimeoutSec 5
    Write-Host ("Bridge ok: provider={0}" -f $bridgeInfo.provider) -ForegroundColor Green
} catch {
    Write-Host "Bridge is not reachable. Start Core/bridges/wechat_http_bridge.py first." -ForegroundColor Yellow
}

Write-Host "[2/5] Setting callback in Gewechat SaaS..." -ForegroundColor Cyan
if ($SkipCallback) {
    Write-Host "Skip callback binding by request." -ForegroundColor Yellow
} else {
    $setCallback = $null
    $callbackPaths = @("tools/setCallback", "callback/setUrl", "v2/api/callback/setUrl")
    $lastCallbackError = ""
    foreach ($path in $callbackPaths) {
        try {
            $setCallback = Invoke-GewePost -Path $path -Body @{ token = $Token; callbackUrl = $CallbackUrl } -TokenValue $Token -ApiBase $BaseUrl
            Write-Host ("Callback set via path: {0}" -f $path) -ForegroundColor Green
            break
        } catch {
            $lastCallbackError = $_.Exception.Message
            continue
        }
    }

    if ($null -eq $setCallback) {
        throw "Failed to set callback. Tried: $($callbackPaths -join ', '). LastError: $lastCallbackError"
    }

    $setCallback | ConvertTo-Json -Depth 8
}

Write-Host "[3/5] Checking node online status..." -ForegroundColor Cyan
$online = Invoke-GewePost -Path "login/checkOnline" -Body @{} -TokenValue $Token -ApiBase $BaseUrl
$online | ConvertTo-Json -Depth 8

if ($ToWxid.Trim()) {
    Write-Host "[4/5] Sending direct Gewechat text message..." -ForegroundColor Cyan
    $send = Invoke-GewePost -Path "message/postText" -Body @{ appId = $AppId; toWxid = $ToWxid; content = $Text; ats = @() } -TokenValue $Token -ApiBase $BaseUrl
    $send | ConvertTo-Json -Depth 8
} else {
    Write-Host "[4/5] Skip direct send (ToWxid is empty)." -ForegroundColor Yellow
}

if ($CheckBridgeSend -and $ToWxid.Trim()) {
    Write-Host "[4b] Sending via local bridge /send..." -ForegroundColor Cyan
    $bridgeSendBody = @{ to = $ToWxid; text = $Text } | ConvertTo-Json -Compress
    $bridgeSend = Invoke-RestMethod -Method Post -Uri ("{0}/send" -f $BridgeUrl.TrimEnd('/')) -ContentType "application/json" -Body $bridgeSendBody -TimeoutSec 12
    $bridgeSend | ConvertTo-Json -Depth 8
}

if ($InjectBridgeTestMessage) {
    Write-Host "[5/5] Injecting a synthetic callback event into bridge..." -ForegroundColor Cyan
    $fake = @{
        TypeName = "AddMsg"
        Data = @{
            MsgType = 1
            FromUserName = "wxid_test_sender"
            Content = "bridge ingest smoke test"
            CreateTime = [int][double]::Parse((Get-Date -UFormat %s))
            MsgId = (Get-Random -Minimum 100000 -Maximum 999999)
        }
    } | ConvertTo-Json -Depth 8 -Compress
    Invoke-RestMethod -Method Post -Uri ("{0}/gewechat/callback" -f $BridgeUrl.TrimEnd('/')) -ContentType "application/json" -Body $fake -TimeoutSec 10 | Out-Null

    $polled = Invoke-RestMethod -Method Get -Uri ("{0}/poll?limit=5&timeout_sec=1" -f $BridgeUrl.TrimEnd('/')) -TimeoutSec 10
    $polled | ConvertTo-Json -Depth 8
}

Write-Host "Done. If online=false, finish node login in Gewechat console first." -ForegroundColor Green
