@echo off
setlocal
cd /d "%~dp0..\.."

if "%SECURE_RELAY_SEND_URL%"=="" (
    echo [BLOCKED] SECURE_RELAY_SEND_URL is required.
    echo [HINT] set SECURE_RELAY_SEND_URL=https://your-relay.example.com/api/send
    exit /b 2
)

if "%SECURE_RELAY_SHARED_SECRET%"=="" (
    echo [BLOCKED] SECURE_RELAY_SHARED_SECRET is required.
    echo [HINT] Use Core\wechat\scripts\generate_secure_relay_secret.ps1 to generate one.
    exit /b 2
)

set "WECHAT_BRIDGE_PROVIDER=secure_relay"
set "WECHAT_BRIDGE_PORT=9015"
set "PYTHONUNBUFFERED=1"
set "SECURE_RELAY_WINDOW_SEC=300"
set "SECURE_RELAY_SIGN_HEADER=X-Relay-Signature"
set "SECURE_RELAY_TS_HEADER=X-Relay-Timestamp"
set "SECURE_RELAY_NONCE_HEADER=X-Relay-Nonce"

uv run python wechat\bridge\wechat_http_bridge.py
set "EC=%ERRORLEVEL%"
echo.
echo [INFO] wechat secure relay bridge exited with code %EC%.
pause
exit /b %EC%
