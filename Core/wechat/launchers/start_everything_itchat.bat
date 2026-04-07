@echo off
setlocal

if /I not "%AVIS_WECHAT_RISK_ACK%"=="I_UNDERSTAND_WECHAT_RISK" (
	echo [BLOCKED] WeChat login automation is disabled by default due account-risk incidents.
	echo [BLOCKED] To run anyway, first execute:
	echo set AVIS_WECHAT_RISK_ACK=I_UNDERSTAND_WECHAT_RISK
	exit /b 2
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\scripts\start_everything.ps1" -WechatProvider itchat -WechatBridgePort 9015 -ItchatEnableCmdQr 0 -ItchatHotReload:$true
set "EC=%ERRORLEVEL%"
echo.
echo [INFO] start_everything_itchat exited with code %EC%.
exit /b %EC%
