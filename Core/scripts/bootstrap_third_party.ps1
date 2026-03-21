# 第三方仓库初始化脚本：按需克隆 GPT-SoVITS / STT 等项目。
param(
    [string]$Root = "./third_party"
)

New-Item -ItemType Directory -Force -Path $Root | Out-Null

function Clone-IfMissing {
    param(
        [string]$Repo,
        [string]$Dir
    )
    if (Test-Path $Dir) {
        Write-Host "Skip existing: $Dir"
        return
    }
    git clone $Repo $Dir
}

# Replace these URLs with the exact repos you choose.
Clone-IfMissing "https://github.com/RVC-Boss/GPT-SoVITS.git" "$Root/GPT-SoVITS"

# Example realtime STT repositories (pick one and keep one URL)
# Clone-IfMissing "https://github.com/SYSTRAN/faster-whisper.git" "$Root/faster-whisper"
# Clone-IfMissing "https://github.com/ggerganov/whisper.cpp.git" "$Root/whisper.cpp"

# Optional OCR/Vision wrappers
# Clone-IfMissing "<your_ocr_service_repo>" "$Root/ocr_service"
# Clone-IfMissing "<your_vision_service_repo>" "$Root/vision_service"

Write-Host "Done. Next: install each repo dependencies and expose APIs in .env"
