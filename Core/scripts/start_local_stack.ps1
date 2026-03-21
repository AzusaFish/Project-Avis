# 本地分步启动提示脚本：检查模型并给出各服务启动命令。
param(
    [switch]$StartCoreOnly
)

Write-Host "[1/4] Checking Ollama model..."
ollama list

if (-not $StartCoreOnly) {
    Write-Host "[2/4] Start GPT-SoVITS in another terminal:"
    Write-Host "cd D:\AzusaFish\Codes\Development\Project-Avis\GPT-SoVITS-main\GPT-SoVITS-main"
    Write-Host "python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml"

    Write-Host "[3/5] Start RealtimeSTT in another terminal:"
    Write-Host "cd D:\AzusaFish\Codes\Development\Project-Avis\RealtimeSTT-master\RealtimeSTT-master"
    Write-Host "stt-server -m small -l zh -c 8011 -d 8012"

    Write-Host "[4/5] Start STT ws->http bridge in another terminal:"
    Write-Host "cd D:\AzusaFish\Codes\Development\Project-Avis\Core"
    Write-Host "python bridges/realtimestt_http_bridge.py"
}

Write-Host "[5/5] Start Core"
Set-Location D:\AzusaFish\Codes\Development\Project-Avis\Core
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}
if (-not (Test-Path .\configs\tts_profiles.yaml) -and (Test-Path .\configs\tts_profiles.example.yaml)) {
    Copy-Item .\configs\tts_profiles.example.yaml .\configs\tts_profiles.yaml
}
uvicorn app.main:app --host 0.0.0.0 --port 8080
