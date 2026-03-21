param(
    [string]$CoreEnv = "base",
    [string]$TtsEnv = "base",
    [string]$RealtimeSttEnv = "base",
    [ValidateSet("kokoro", "gpt_sovits")]
    [string]$TtsProvider = "kokoro",
    [string]$CondaRoot = "D:\AzusaFish\Codes\Development\AI\.conda",
    [string]$KokoroDir = "D:\AzusaFish\Codes\Development\AI\kokoro",
    [string]$KokoroLaunchCmd = "python -m kokoro_fastapi --host 127.0.0.1 --port 9880"
)

# Start all local services in separate PowerShell windows.

$coreDir = "D:\AzusaFish\Codes\Development\AI\Core"
$gptDir = "D:\AzusaFish\Codes\Development\AI\GPT-SoVITS-main\GPT-SoVITS-main"
$sttDir = "D:\AzusaFish\Codes\Development\AI\RealtimeSTT-master\RealtimeSTT-master"
$uiDir = "D:\AzusaFish\Codes\Development\AI\live2d-desktop"

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
$requestedEnv = '$EnvName'
$envNames = @()
try {
    $envJson = conda env list --json | ConvertFrom-Json
    if ($envJson -and $envJson.envs) {
        $envNames = $envJson.envs | ForEach-Object { Split-Path $_ -Leaf }
    }
} catch {
    Write-Host "Failed to read conda env list, fallback to base." -ForegroundColor Yellow
}

if ($requestedEnv -and ($envNames -contains $requestedEnv)) {
    Write-Host "Activating conda env: $requestedEnv" -ForegroundColor Cyan
    conda activate "$requestedEnv"
} else {
    Write-Host "Conda env '$requestedEnv' not found, fallback to base." -ForegroundColor Yellow
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

Write-Host "Launching Core backend..."
Start-InCondaWindow -Title "Core Backend" -EnvName $CoreEnv -WorkDir $coreDir -Command "uvicorn app.main:app --host 0.0.0.0 --port 8080"

Write-Host "Launching Live2D frontend..."
Start-Process powershell.exe -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", "Set-Location '$uiDir'; npm run tauri dev" | Out-Null

Write-Host "All components launched."
