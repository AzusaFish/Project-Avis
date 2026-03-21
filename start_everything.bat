@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "DRY_RUN=0"
set "NO_UI=0"
set "TTS_PROVIDER=kokoro"
set "KOKORO_VOICE=jf_alpha"
set "KOKORO_LANG=en-us"
set "KOKORO_SPEED=1.0"
set "GPU_ID=0"
set "CLEAN_PORTS=1"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--dry-run" (
  set "DRY_RUN=1"
  shift
  goto parse_args
)
if /I "%~1"=="--no-ui" (
  set "NO_UI=1"
  shift
  goto parse_args
)
if /I "%~1"=="--tts-provider" (
  if "%~2"=="" (
    echo [ERROR] --tts-provider requires a value: kokoro or gpt_sovits
    exit /b 1
  )
  set "TTS_PROVIDER=%~2"
  shift
  shift
  goto parse_args
)
if /I "%~1"=="--no-clean-ports" (
  set "CLEAN_PORTS=0"
  shift
  goto parse_args
)
echo [WARN] Unknown argument: %~1
shift
goto parse_args

:args_done
set "AI_ROOT=%~dp0"
if "%AI_ROOT:~-1%"=="\" set "AI_ROOT=%AI_ROOT:~0,-1%"
if not exist "%AI_ROOT%\Core" if exist "%AI_ROOT%\Development\AI\Core" (
  set "AI_ROOT=%AI_ROOT%\Development\AI"
)

set "CORE_DIR=%AI_ROOT%\Core"
set "GPT_DIR=%AI_ROOT%\GPT-SoVITS-main\GPT-SoVITS-main"
set "STT_DIR=%AI_ROOT%\RealtimeSTT-master\RealtimeSTT-master"
set "UI_DIR=%AI_ROOT%\live2d-desktop"
set "CORE_VENV_PY=%CORE_DIR%\.venv\Scripts\python.exe"
set "UV_EXE="
for /f "delims=" %%I in ('where uv 2^>nul') do (
  if not defined UV_EXE set "UV_EXE=%%~fI"
)

if not exist "%CORE_DIR%" (
  echo [ERROR] Core folder not found: %CORE_DIR%
  exit /b 1
)
if not exist "%STT_DIR%" (
  echo [ERROR] RealtimeSTT folder not found: %STT_DIR%
  exit /b 1
)
if /I "%TTS_PROVIDER%"=="gpt_sovits" if not exist "%GPT_DIR%" (
  echo [ERROR] GPT-SoVITS folder not found: %GPT_DIR%
  exit /b 1
)
if "%NO_UI%"=="0" if not exist "%UI_DIR%" (
  echo [ERROR] Live2D frontend folder not found: %UI_DIR%
  exit /b 1
)
if not defined UV_EXE (
  echo [ERROR] uv not found in PATH.
  echo [HINT] Install uv first: pip install uv
  exit /b 1
)

if not exist "%CORE_DIR%\.env" (
  if exist "%CORE_DIR%\.env.example" (
    echo [INFO] .env missing, creating from .env.example
    copy /y "%CORE_DIR%\.env.example" "%CORE_DIR%\.env" >nul
  )
)
if not exist "%CORE_DIR%\configs\tts_profiles.yaml" (
  if exist "%CORE_DIR%\configs\tts_profiles.example.yaml" (
    echo [INFO] tts_profiles.yaml missing, creating from example.
    copy /y "%CORE_DIR%\configs\tts_profiles.example.yaml" "%CORE_DIR%\configs\tts_profiles.yaml" >nul
  )
)

echo [INFO] uv: %UV_EXE%
echo [INFO] TTS provider: %TTS_PROVIDER%
if /I "%TTS_PROVIDER%"=="kokoro" (
  echo [INFO] Kokoro voice: %KOKORO_VOICE%
  echo [INFO] Kokoro lang: %KOKORO_LANG%
  echo [INFO] Kokoro speed: %KOKORO_SPEED%
)
if "%CLEAN_PORTS%"=="1" (
  echo [INFO] Port clean mode: enabled
) else (
  echo [INFO] Port clean mode: disabled
)

if "%DRY_RUN%"=="0" (
  if not exist "%CORE_DIR%\pyproject.toml" (
    echo [ERROR] pyproject.toml missing in Core: %CORE_DIR%\pyproject.toml
    exit /b 1
  )

  echo [PRECHECK] Syncing Core environment with uv...
  "%UV_EXE%" --directory "%CORE_DIR%" sync --link-mode=copy
  if errorlevel 1 (
    echo [ERROR] uv sync failed. Please fix dependency errors first.
    exit /b 1
  )

  if not exist "%CORE_VENV_PY%" (
    echo [ERROR] Core virtual env python not found: %CORE_VENV_PY%
    exit /b 1
  )

  echo [PRECHECK] Verifying Core imports in uv env...
  "%UV_EXE%" --directory "%CORE_DIR%" run python -c "import fastapi,uvicorn,httpx,websockets,pydantic_settings" 1>nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Core runtime imports check failed after uv sync.
    exit /b 1
  )

  if /I "%TTS_PROVIDER%"=="kokoro" (
    echo [PRECHECK] Ensuring Kokoro runtime packages...
    "%UV_EXE%" --directory "%CORE_DIR%" run python -c "import onnxruntime,kokoro_onnx,numpy,soundfile" 1>nul 2>nul
    if errorlevel 1 (
      echo [ERROR] Missing Kokoro runtime package in uv env. Run: uv --directory "%CORE_DIR%" sync
      exit /b 1
    )

    if not exist "%CORE_DIR%\assets\kokoro" mkdir "%CORE_DIR%\assets\kokoro"

    if not exist "%CORE_DIR%\assets\kokoro\kokoro-v1.0.onnx" (
      echo [PRECHECK] Downloading Kokoro model...
      "%UV_EXE%" --directory "%CORE_DIR%" run python -c "import urllib.request; urllib.request.urlretrieve('https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx', r'%CORE_DIR%\assets\kokoro\kokoro-v1.0.onnx')"
      if errorlevel 1 (
        echo [ERROR] Failed to download Kokoro model.
        exit /b 1
      )
    )
    if not exist "%CORE_DIR%\assets\kokoro\voices-v1.0.bin" (
      echo [PRECHECK] Downloading Kokoro voices...
      "%UV_EXE%" --directory "%CORE_DIR%" run python -c "import urllib.request; urllib.request.urlretrieve('https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin', r'%CORE_DIR%\assets\kokoro\voices-v1.0.bin')"
      if errorlevel 1 (
        echo [ERROR] Failed to download Kokoro voices.
        exit /b 1
      )
    )
  ) else (
    echo [PRECHECK] Ensuring GPT-SoVITS runtime packages...
    "%UV_EXE%" --directory "%CORE_DIR%" run python -c "import ffmpeg,soundfile" 1>nul 2>nul
    if errorlevel 1 (
      echo [ERROR] Missing ffmpeg-python/soundfile in uv env.
      exit /b 1
    )
  )

  echo [PRECHECK] Ensuring RealtimeSTT runtime packages...
  "%UV_EXE%" --directory "%CORE_DIR%" run python -c "from RealtimeSTT import AudioToTextRecorder; import RealtimeSTT_server.stt_server" 1>nul 2>nul
  if errorlevel 1 (
    echo [ERROR] RealtimeSTT import check failed in uv env.
    echo [HINT] Confirm source path exists: %STT_DIR%
    echo [HINT] Then run: uv --directory "%CORE_DIR%" sync
    exit /b 1
  )

  "%UV_EXE%" --directory "%CORE_DIR%" run python -c "import pyaudio" 1>nul 2>nul
  if errorlevel 1 (
    echo [ERROR] pyaudio missing in uv env.
    exit /b 1
  )
)

if "%DRY_RUN%"=="0" if "%CLEAN_PORTS%"=="1" (
  call :kill_port 8080
  call :kill_port 9000
  call :kill_port 9880
  call :kill_port 8011
  call :kill_port 8012
)

set "RUNNER_DIR=%TEMP%\neuro_core_launchers"
if not exist "%RUNNER_DIR%" mkdir "%RUNNER_DIR%"

if /I "%TTS_PROVIDER%"=="kokoro" (
  echo [1/5] Preparing Kokoro launcher...
  > "%RUNNER_DIR%\tts_backend.cmd" (
    echo @echo off
    echo title Kokoro TTS
    echo cd /d "%CORE_DIR%"
    echo set "CUDA_VISIBLE_DEVICES=%GPU_ID%"
    echo set "KOKORO_MODEL_PATH=%CORE_DIR%\assets\kokoro\kokoro-v1.0.onnx"
    echo set "KOKORO_VOICES_PATH=%CORE_DIR%\assets\kokoro\voices-v1.0.bin"
    echo set "KOKORO_VOICE=%KOKORO_VOICE%"
    echo set "KOKORO_LANG=%KOKORO_LANG%"
    echo set "KOKORO_SPEED=%KOKORO_SPEED%"
    echo "%UV_EXE%" --directory "%CORE_DIR%" run python bridges\kokoro_onnx_http_bridge.py
    echo if errorlevel 1 echo [WARN] Command exited with code %%errorlevel%%
  )
) else (
  echo [1/5] Preparing GPT-SoVITS launcher...
  > "%RUNNER_DIR%\tts_backend.cmd" (
    echo @echo off
    echo title GPT-SoVITS
    echo cd /d "%GPT_DIR%"
    echo set "CUDA_VISIBLE_DEVICES=%GPU_ID%"
    echo "%UV_EXE%" --directory "%CORE_DIR%" run python -u api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
    echo if errorlevel 1 echo [WARN] Command exited with code %%errorlevel%%
  )
)

echo [2/5] Preparing RealtimeSTT launcher...
> "%RUNNER_DIR%\realtimestt.cmd" (
  echo @echo off
  echo title RealtimeSTT
  echo cd /d "%STT_DIR%"
  echo set "CUDA_VISIBLE_DEVICES=-1"
  echo "%UV_EXE%" --directory "%CORE_DIR%" run python -m RealtimeSTT_server.stt_server -m small -l zh -c 8011 -d 8012 --device cpu --compute_type int8
  echo if errorlevel 1 echo [WARN] Command exited with code %%errorlevel%%
)

echo [3/5] Preparing STT bridge launcher...
> "%RUNNER_DIR%\stt_bridge.cmd" (
  echo @echo off
  echo title STT Bridge
  echo cd /d "%CORE_DIR%"
  echo set "CUDA_VISIBLE_DEVICES=-1"
  echo "%UV_EXE%" --directory "%CORE_DIR%" run python bridges\realtimestt_http_bridge.py
  echo if errorlevel 1 echo [WARN] Command exited with code %%errorlevel%%
)

echo [4/5] Preparing Core backend launcher...
> "%RUNNER_DIR%\core_backend.cmd" (
  echo @echo off
  echo title Core Backend
  echo cd /d "%CORE_DIR%"
  echo set "CUDA_VISIBLE_DEVICES=-1"
  echo "%UV_EXE%" --directory "%CORE_DIR%" run uvicorn app.main:app --host 0.0.0.0 --port 8080
  echo if errorlevel 1 echo [WARN] Command exited with code %%errorlevel%%
)

if "%NO_UI%"=="0" (
  echo [5/5] Preparing Live2D frontend launcher...
  > "%RUNNER_DIR%\live2d_ui.cmd" (
    echo @echo off
    echo title live2d-desktop
    echo cd /d "%UI_DIR%"
    echo where npm 1^>nul 2^>nul ^|^| ^(echo [ERROR] npm not found in PATH ^& goto :eof^)
    echo npm run tauri dev
    echo if errorlevel 1 echo [WARN] Command exited with code %%errorlevel%%
  )
)

if "%DRY_RUN%"=="1" (
  echo [DRY] start "TTS Backend" cmd /k "%RUNNER_DIR%\tts_backend.cmd"
  echo [DRY] start "RealtimeSTT" cmd /k "%RUNNER_DIR%\realtimestt.cmd"
  echo [DRY] start "STT Bridge" cmd /k "%RUNNER_DIR%\stt_bridge.cmd"
  echo [DRY] start "Core Backend" cmd /k "%RUNNER_DIR%\core_backend.cmd"
  if "%NO_UI%"=="0" echo [DRY] start "live2d-desktop" cmd /k "%RUNNER_DIR%\live2d_ui.cmd"
  exit /b 0
)

start "TTS Backend" cmd /k "%RUNNER_DIR%\tts_backend.cmd"
timeout /t 2 /nobreak >nul
start "RealtimeSTT" cmd /k "%RUNNER_DIR%\realtimestt.cmd"
timeout /t 2 /nobreak >nul
start "STT Bridge" cmd /k "%RUNNER_DIR%\stt_bridge.cmd"
timeout /t 2 /nobreak >nul
start "Core Backend" cmd /k "%RUNNER_DIR%\core_backend.cmd"
if "%NO_UI%"=="0" (
  timeout /t 2 /nobreak >nul
  start "live2d-desktop" cmd /k "%RUNNER_DIR%\live2d_ui.cmd"
)

echo [OK] All launchers started.
echo [INFO] Core health URL: http://127.0.0.1:8080/health
echo [INFO] Dependency check: http://127.0.0.1:8080/health/deps
exit /b 0

:kill_port
set "PORT=%~1"
for /f "delims=" %%P in ('powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; Get-NetTCPConnection -State Listen -LocalPort !PORT! ^| Select-Object -ExpandProperty OwningProcess -Unique"') do (
  if not "%%P"=="" (
    echo [PORT] !PORT! occupied by PID %%P, terminating...
    taskkill /PID %%P /F >nul 2>nul
  )
)
exit /b 0
