@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\start_gewechat_bootstrap.ps1" %*
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
	echo.
	echo [ERROR] start_gewechat failed with exit code %EC%.
	echo [ERROR] Check the printed diagnostics above.
	pause
)
exit /b %EC%
