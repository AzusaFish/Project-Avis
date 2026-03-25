@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"

set HTTP_PROXY=http://127.0.0.1:7897
set HTTPS_PROXY=http://127.0.0.1:7897
set ALL_PROXY=http://127.0.0.1:7897

set HF_TOKEN=your_huggingface_token_here

"%~dp0.conda\python.exe" "%~dp0one_click_export.py" --token "%HF_TOKEN%"

if errorlevel 1 (
  echo.
  echo Pipeline failed. Press any key to exit.
  pause >nul
  exit /b 1
)

echo.
echo Pipeline finished successfully. Press any key to exit.
pause >nul
