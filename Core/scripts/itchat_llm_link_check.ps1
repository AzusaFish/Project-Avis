param(
    [string]$BridgeUrl = "http://127.0.0.1:9015",
    [string]$CoreUrl = "http://127.0.0.1:8080",
    [string]$To = "filehelper",
    [string]$Text = "hello from avis via itchat",
    [int]$WaitReadySec = 180,
    [int]$BridgeStartupSec = 40,
    [switch]$RestartBridge,
    [switch]$SkipCoreHealth,
    [switch]$AutoFallbackGewechat,
    [string]$GewechatToken = "",
    [string]$GewechatAppId = "",
    [string]$GewechatBaseUrl = "https://api.geweapi.com/gewe/v2/api",
    [string]$GewechatCallbackUrl = "http://host.docker.internal:9010/gewechat/callback",
    [string]$GewechatToWxid = "",
    [switch]$GewechatSkipCallback,
    [string]$RepoRoot = "D:\AzusaFish\Codes\Development\Project-Avis"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-Json {
    param([string]$Url)
    return Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec 5
}

function Post-Json {
    param([string]$Url, [hashtable]$Body)
    $json = $Body | ConvertTo-Json -Compress -Depth 8
    return Invoke-RestMethod -Method Post -Uri $Url -ContentType "application/json" -Body $json -TimeoutSec 15
}

function Wait-BridgeReady {
    param(
        [string]$BaseUrl,
        [int]$TimeoutSec = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $null = Get-Json "$($BaseUrl.TrimEnd('/'))/"
            return $true
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

function Invoke-GewechatFallback {
    param(
        [string]$Root,
        [string]$Token,
        [string]$AppId,
        [string]$BaseUrl,
        [string]$CallbackUrl,
        [string]$Bridge,
        [string]$ToWxid,
        [switch]$SkipCallback
    )

    $script = Join-Path $Root "Core\scripts\gewechat_saas_bind_and_check.ps1"
    if (-not (Test-Path -LiteralPath $script)) {
        throw "fallback script not found: $script"
    }

    if (-not $Token.Trim() -or -not $AppId.Trim()) {
        throw "AutoFallbackGewechat requires GewechatToken and GewechatAppId"
    }

    Write-Host "Invoking Gewechat SaaS fallback check..." -ForegroundColor Cyan
    $args = @(
        "-Token", $Token,
        "-AppId", $AppId,
        "-BaseUrl", $BaseUrl,
        "-CallbackUrl", $CallbackUrl,
        "-BridgeUrl", $Bridge
    )

    if ($ToWxid.Trim()) {
        $args += @("-ToWxid", $ToWxid, "-Text", $Text)
    }
    if ($SkipCallback) {
        $args += "-SkipCallback"
    }

    & $script @args
}

function Restart-ItchatBridge {
    param([string]$Root)

    Write-Host "Restarting itchat bridge and refreshing QR..." -ForegroundColor Cyan

    $procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*wechat_http_bridge.py*" }
    foreach ($p in $procs) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {}
    }

    $qrPath = Join-Path $Root "Core\QR.png"
    if (Test-Path -LiteralPath $qrPath) {
        Remove-Item -LiteralPath $qrPath -Force -ErrorAction SilentlyContinue
    }

    $launcher = Join-Path $Root "start_wechat_itchat.bat"
    if (-not (Test-Path -LiteralPath $launcher)) {
        throw "Launcher not found: $launcher"
    }
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "`"$launcher`"") -WindowStyle Normal | Out-Null
    Start-Sleep -Seconds 4

    if (Test-Path -LiteralPath $qrPath) {
        Write-Host "New QR generated: $qrPath" -ForegroundColor Green
    } else {
        Write-Host "QR file not found yet, but bridge may still be starting." -ForegroundColor Yellow
    }
}

if ($RestartBridge) {
    Restart-ItchatBridge -Root $RepoRoot
}

if (-not $SkipCoreHealth) {
    Write-Host "[1/5] Checking Core health..." -ForegroundColor Cyan
    $core = Get-Json "$($CoreUrl.TrimEnd('/'))/health"
    $core | ConvertTo-Json -Depth 5
} else {
    Write-Host "[1/5] Skipping Core health check." -ForegroundColor Yellow
}

Write-Host "[2/5] Checking bridge health..." -ForegroundColor Cyan
if (-not (Wait-BridgeReady -BaseUrl $BridgeUrl -TimeoutSec $BridgeStartupSec)) {
    throw "bridge is not reachable within $BridgeStartupSec seconds: $BridgeUrl"
}
$bridge = Get-Json "$($BridgeUrl.TrimEnd('/'))/"
$bridge | ConvertTo-Json -Depth 5

Write-Host "[3/5] Waiting for itchat_ready=true..." -ForegroundColor Cyan
$deadline = (Get-Date).AddSeconds($WaitReadySec)
$ready = $false
$loggingInSince = $null
while ((Get-Date) -lt $deadline) {
    $s = Get-Json "$($BridgeUrl.TrimEnd('/'))/"
    if ($s.itchat_ready -eq $true) {
        $ready = $true
        break
    }

    if ($s.itchat_state -eq "error") {
        $errText = [string]$s.itchat_last_error
        if ($errText -match "list index out of range") {
            throw "itchat login callback crashed (list index out of range). This is a known incompatibility with current WeChat web login flow for this account/version."
        }
        throw ("itchat entered error state: {0}" -f $errText)
    }

    if ($s.itchat_state -eq "logging_in") {
        if ($null -eq $loggingInSince) {
            $loggingInSince = Get-Date
        }
    } else {
        $loggingInSince = $null
    }

    if (($null -ne $loggingInSince) -and (((Get-Date) - $loggingInSince).TotalSeconds -ge 90)) {
        Write-Host "Detected long logging_in state (>90s). Likely blocked by WeChat web-login policy." -ForegroundColor Yellow
        break
    }

    Write-Host ("waiting... state={0} last_error={1}" -f $s.itchat_state, $s.itchat_last_error)
    Start-Sleep -Seconds 3
}
if (-not $ready) {
    if ($AutoFallbackGewechat) {
        Invoke-GewechatFallback \
            -Root $RepoRoot \
            -Token $GewechatToken \
            -AppId $GewechatAppId \
            -BaseUrl $GewechatBaseUrl \
            -CallbackUrl $GewechatCallbackUrl \
            -Bridge $BridgeUrl \
            -ToWxid $GewechatToWxid \
            -SkipCallback:$GewechatSkipCallback
        throw "itchat not ready; Gewechat fallback has been executed."
    }

    throw "itchat login not ready within $WaitReadySec seconds. If repeated QR confirm still fails, this account is likely blocked from web login; use Gewechat SaaS instead."
}
Write-Host "itchat login is ready." -ForegroundColor Green

Write-Host "[4/5] Sending real message via bridge /send..." -ForegroundColor Cyan
$sendResp = Post-Json "$($BridgeUrl.TrimEnd('/'))/send" @{ to = $To; text = $Text }
$sendResp | ConvertTo-Json -Depth 8

Write-Host "[5/5] Polling bridge queue once..." -ForegroundColor Cyan
$pollResp = Get-Json "$($BridgeUrl.TrimEnd('/'))/poll?limit=5&timeout_sec=1"
$pollResp | ConvertTo-Json -Depth 8

Write-Host "Done. LLM link path is ready: Core <-> Bridge(itchat) <-> WeChat" -ForegroundColor Green
