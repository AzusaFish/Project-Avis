@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Core\scripts\start_everything.ps1" -WechatProvider itchat -WechatBridgePort 9015 -ItchatEnableCmdQr 2 -ItchatHotReload:$false
set "EC=%ERRORLEVEL%"
echo.
echo [INFO] start_everything_itchat exited with code %EC%.
exit /b %EC%
