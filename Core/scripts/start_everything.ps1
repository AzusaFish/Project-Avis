param(
    [string]$CoreEnv = "base",
    [string]$TtsEnv = "base",
    [string]$RealtimeSttEnv = "base",
    [ValidateSet("kokoro", "gpt_sovits")]
    [string]$TtsProvider = "kokoro",
    [string]$CondaRoot = "",
    [string]$KokoroDir = "",
    [string]$KokoroLaunchCmd = "python -m kokoro_fastapi --host 127.0.0.1 --port 9880",
    [bool]$EnableWechatBridge = $true,
    [ValidateSet("local", "gewechat", "wcferry", "itchat", "secure_relay")]
    [string]$WechatProvider = "local",
    [int]$WechatBridgePort = 9010,
    [string]$GewechatBaseUrl = "http://127.0.0.1:2531/v2/api",
    [string]$GewechatToken = "",
    [string]$GewechatAppId = "",
    [string]$GewechatAts = "[]",
    [int]$ItchatEnableCmdQr = 2,
    [bool]$ItchatHotReload = $false,
    [string]$SecureRelaySendUrl = "",
    [string]$SecureRelaySharedSecret = "",
    [int]$SecureRelayWindowSec = 300,
    [string]$SecureRelaySignHeader = "X-Relay-Signature",
    [string]$SecureRelayTsHeader = "X-Relay-Timestamp",
    [string]$SecureRelayNonceHeader = "X-Relay-Nonce"
)

# Start all local services in separate PowerShell windows.

$coreDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$repoDir = (Resolve-Path (Join-Path $coreDir "..")).Path
if (-not $CondaRoot) {
    $CondaRoot = Join-Path $repoDir ".conda"
}
if (-not $KokoroDir) {
    $KokoroDir = $coreDir
}
$gptDir = Join-Path $repoDir "GPT-SoVITS-main\GPT-SoVITS-main"
$sttDir = Join-Path $repoDir "RealtimeSTT-master\RealtimeSTT-master"
$uiDir = Join-Path $repoDir "live2d-desktop"

$CondaHook = Join-Path $CondaRoot "shell\condabin\conda-hook.ps1"
if (-not (Test-Path $CondaHook)) {
    throw "Conda hook not found: $CondaHook"
}

function Start-InCondaWindow {
    param(
        [string]$Title,
        [string]$EnvName,
        [string]$WorkDir,
        [string]$Command
    )

    $script = @"
`$Host.UI.RawUI.WindowTitle = '$Title'
Set-Location '$WorkDir'
& '$CondaHook'
`$requestedEnv = '$EnvName'

if (`$requestedEnv) {
    Write-Host "Activating conda env: `$requestedEnv" -ForegroundColor Cyan
    conda activate "`$requestedEnv"
}
if (`$LASTEXITCODE -ne 0) {
    Write-Host "Conda activate failed, fallback to base." -ForegroundColor Yellow
    conda activate base
}

$Command
if (`$LASTEXITCODE -ne 0) {
  Write-Host "Command exited with code `$LASTEXITCODE" -ForegroundColor Yellow
}
"@

    Start-Process powershell.exe -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $script | Out-Null
}

Write-Host "Launching GPT-SoVITS..."
if ($TtsProvider -eq "kokoro") {
    Write-Host "Launching Kokoro TTS..."
    $kokoroLaunch = @"
python -c "import kokoro" 2>`$null
if (`$LASTEXITCODE -ne 0) {
    Write-Host "Kokoro package not found in env. Please install it in advance (pip install kokoro)." -ForegroundColor Yellow
}
$KokoroLaunchCmd
"@
    Start-InCondaWindow -Title "Kokoro TTS" -EnvName $TtsEnv -WorkDir $KokoroDir -Command $kokoroLaunch
} else {
    Write-Host "Launching GPT-SoVITS..."
    $gptLaunch = @"
python -c "import soundfile" 2>`$null
if (`$LASTEXITCODE -ne 0) {
    Write-Host "Missing python package: soundfile. Installing..." -ForegroundColor Yellow
    python -m pip install soundfile
}
python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
"@
    Start-InCondaWindow -Title "GPT-SoVITS" -EnvName $TtsEnv -WorkDir $gptDir -Command $gptLaunch
}

Write-Host "Launching RealtimeSTT server..."
$sttLaunch = @"
if (Get-Command stt-server -ErrorAction SilentlyContinue) {
    stt-server -m small -l zh -c 8011 -d 8012
} elseif (Test-Path '.\RealtimeSTT_server\stt_server.py') {
    python -m RealtimeSTT_server.stt_server -m small -l zh -c 8011 -d 8012
} else {
    Write-Host 'RealtimeSTT server launcher not found. Please check repo path or installation.' -ForegroundColor Red
}
"@
Start-InCondaWindow -Title "RealtimeSTT" -EnvName $RealtimeSttEnv -WorkDir $sttDir -Command $sttLaunch

Write-Host "Launching RealtimeSTT HTTP bridge..."
Start-InCondaWindow -Title "STT Bridge" -EnvName $CoreEnv -WorkDir $coreDir -Command "python bridges/realtimestt_http_bridge.py"

if ($EnableWechatBridge) {
    if ($WechatProvider -eq "secure_relay") {
        if (-not $SecureRelaySendUrl.Trim()) {
            throw "WechatProvider=secure_relay requires -SecureRelaySendUrl"
        }
        if (-not $SecureRelaySharedSecret.Trim()) {
            throw "WechatProvider=secure_relay requires -SecureRelaySharedSecret"
        }
    }

    Write-Host "Launching WeChat bridge..."
    $wechatLaunch = @"
`$env:WECHAT_BRIDGE_PROVIDER = '$WechatProvider'
`$env:WECHAT_BRIDGE_PORT = '$WechatBridgePort'
`$env:GEWECHAT_BASE_URL = '$GewechatBaseUrl'
`$env:GEWECHAT_TOKEN = '$GewechatToken'
`$env:GEWECHAT_APP_ID = '$GewechatAppId'
`$env:GEWECHAT_ATS = '$GewechatAts'
`$env:ITCHAT_ENABLE_CMD_QR = '$ItchatEnableCmdQr'
`$env:ITCHAT_HOT_RELOAD = '$ItchatHotReload'
`$env:SECURE_RELAY_SEND_URL = '$SecureRelaySendUrl'
`$env:SECURE_RELAY_SHARED_SECRET = '$SecureRelaySharedSecret'
`$env:SECURE_RELAY_WINDOW_SEC = '$SecureRelayWindowSec'
`$env:SECURE_RELAY_SIGN_HEADER = '$SecureRelaySignHeader'
`$env:SECURE_RELAY_TS_HEADER = '$SecureRelayTsHeader'
`$env:SECURE_RELAY_NONCE_HEADER = '$SecureRelayNonceHeader'
python wechat/bridge/wechat_http_bridge.py
"@
    Start-InCondaWindow -Title "WeChat Bridge" -EnvName $CoreEnv -WorkDir $coreDir -Command $wechatLaunch
}

Write-Host "Launching Core backend..."
Start-InCondaWindow -Title "Core Backend" -EnvName $CoreEnv -WorkDir $coreDir -Command "uvicorn app.main:app --host 0.0.0.0 --port 8080"

Write-Host "Launching Live2D frontend..."
Start-Process powershell.exe -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", "Set-Location '$uiDir'; npm run tauri dev" | Out-Null

Write-Host "All components launched."
