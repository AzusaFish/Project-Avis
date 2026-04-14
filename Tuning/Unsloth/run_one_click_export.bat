@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"

set HTTP_PROXY=http://127.0.0.1:7897
set HTTPS_PROXY=http://127.0.0.1:7897
set ALL_PROXY=http://127.0.0.1:7897

set HF_TOKEN=your_huggingface_token_here

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python not found in PATH. Activate your venv first.
  pause >nul
  exit /b 1
)

python "%~dp0one_click_export.py" --token "%HF_TOKEN%"

if errorlevel 1 (
  echo.
  echo Pipeline failed. Press any key to exit.
  pause >nul
  exit /b 1
)

echo.
echo Pipeline finished successfully. Press any key to exit.
pause >nul
