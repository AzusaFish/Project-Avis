@echo off
setlocal
cd /d "%~dp0"

if not exist "annotator.py" (
  echo [ERROR] Please run this script inside Tuning\LLaMa_Factory.
  exit /b 1
)

python train_internvl_lora.py %*
set "EC=%ERRORLEVEL%"
echo.
echo [INFO] train_internvl_lora.py exited with code %EC%.
exit /b %EC%
