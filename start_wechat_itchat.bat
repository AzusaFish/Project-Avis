@echo off
setlocal
cd /d "%~dp0Core"

rem Ensure single bridge instance to avoid QR/session mismatch.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*wechat_http_bridge.py*' } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }" >nul 2>nul

set "WECHAT_BRIDGE_PROVIDER=itchat"
set "WECHAT_BRIDGE_PORT=9015"
set "ITCHAT_ENABLE_CMD_QR=0"
set "ITCHAT_HOT_RELOAD=0"
set "PYTHONUNBUFFERED=1"

if exist ".venv\Scripts\python.exe" (
	".venv\Scripts\python.exe" bridges\wechat_http_bridge.py
) else (
	uv run python bridges\wechat_http_bridge.py
)
set "EC=%ERRORLEVEL%"
echo.
echo [INFO] wechat itchat bridge exited with code %EC%.
pause
exit /b %EC%
