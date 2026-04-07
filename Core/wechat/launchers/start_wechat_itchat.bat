@echo off
setlocal

if /I not "%AVIS_WECHAT_RISK_ACK%"=="I_UNDERSTAND_WECHAT_RISK" (
	echo [BLOCKED] WeChat login automation is disabled by default due account-risk incidents.
	echo [BLOCKED] To run anyway, first execute:
	echo set AVIS_WECHAT_RISK_ACK=I_UNDERSTAND_WECHAT_RISK
	exit /b 2
)

cd /d "%~dp0..\.."

rem Ensure single bridge instance to avoid QR/session mismatch.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*wechat_http_bridge.py*' } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }" >nul 2>nul

set "WECHAT_BRIDGE_PROVIDER=itchat"
set "WECHAT_BRIDGE_PORT=9015"
set "ITCHAT_ENABLE_CMD_QR=0"
set "ITCHAT_HOT_RELOAD=1"
set "PYTHONUNBUFFERED=1"

uv run python wechat\bridge\wechat_http_bridge.py
set "EC=%ERRORLEVEL%"
echo.
echo [INFO] wechat itchat bridge exited with code %EC%.
pause
exit /b %EC%
