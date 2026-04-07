@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "CONFIG_FILE=%~dp0config.yaml"
set "DRY_RUN=0"
set "NO_UI=0"
set "TTS_PROVIDER=kokoro"
set "KOKORO_VOICE=jf_alpha"
set "KOKORO_LANG=en-us"
set "KOKORO_SPEED=1.0"
set "GPU_ID=0"
set "CLEAN_PORTS=1"
set "LLM_PROVIDER=gguf"
set "LLM_MODEL_PROFILE=internvl"
set "GGUF_BASE_URL=http://127.0.0.1:8081/v1"
set "GGUF_MODEL=InternVL-14B"
set "GGUF_MODEL_PATH="
set "GGUF_QWEN_MODEL=Avis-14B-v1.Q4_K_M.gguf"
set "GGUF_QWEN_MODEL_PATH="
set "GGUF_INTERNVL_MODEL=InternVL-14B"
set "GGUF_INTERNVL_MODEL_PATH="
set "GGUF_MMPROJ_PATH="
set "GGUF_THREADS=10"
set "GGUF_N_GPU_LAYERS=99"
set "GGUF_CTX=8192"
set "GGUF_PORT=8081"
set "LLAMA_SERVER_EXE="
set "GGUF_MAIN_GPU=0"
set "GGUF_CHAT_TEMPLATE=chatml"
set "WECHAT_BRIDGE_PROVIDER=local"
set "GEWECHAT_BASE_URL=http://127.0.0.1:2531/v2/api"
set "GEWECHAT_TOKEN="
set "GEWECHAT_APP_ID="
set "GEWECHAT_ATS=[]"
set "SECURE_RELAY_SEND_URL="
set "SECURE_RELAY_SHARED_SECRET="
set "SECURE_RELAY_WINDOW_SEC=300"
set "SECURE_RELAY_SIGN_HEADER=X-Relay-Signature"
set "SECURE_RELAY_TS_HEADER=X-Relay-Timestamp"
set "SECURE_RELAY_NONCE_HEADER=X-Relay-Nonce"

call :load_config_defaults

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
if not defined GGUF_QWEN_MODEL_PATH set "GGUF_QWEN_MODEL_PATH=%AI_ROOT%\Unsloth\exports\gguf\%GGUF_QWEN_MODEL%"
if not defined GGUF_INTERNVL_MODEL_PATH set "GGUF_INTERNVL_MODEL_PATH=%AI_ROOT%\Model\Base\InternVL14B"
if /I "%LLM_MODEL_PROFILE%"=="qwen" (
  set "GGUF_MODEL=%GGUF_QWEN_MODEL%"
  set "GGUF_MODEL_PATH=%GGUF_QWEN_MODEL_PATH%"
) else (
  set "GGUF_MODEL=%GGUF_INTERNVL_MODEL%"
  set "GGUF_MODEL_PATH=%GGUF_INTERNVL_MODEL_PATH%"
)
if defined GGUF_MODEL_PATH if "!GGUF_MODEL_PATH:~0,1!"=="." (
  if "!GGUF_MODEL_PATH:~1,1!"=="/" set "GGUF_MODEL_PATH=%AI_ROOT%\!GGUF_MODEL_PATH:~2!"
  if "!GGUF_MODEL_PATH:~1,1!"=="\" set "GGUF_MODEL_PATH=%AI_ROOT%\!GGUF_MODEL_PATH:~2!"
)
if defined GGUF_MMPROJ_PATH if "!GGUF_MMPROJ_PATH:~0,1!"=="." (
  if "!GGUF_MMPROJ_PATH:~1,1!"=="/" set "GGUF_MMPROJ_PATH=%AI_ROOT%\!GGUF_MMPROJ_PATH:~2!"
  if "!GGUF_MMPROJ_PATH:~1,1!"=="\" set "GGUF_MMPROJ_PATH=%AI_ROOT%\!GGUF_MMPROJ_PATH:~2!"
)

if exist "%GGUF_MODEL_PATH%\" (
  set "_GGUF_DIR=%GGUF_MODEL_PATH%"
  set "_GGUF_MODEL_FILE="
  set "_GGUF_MMPROJ_FILE="

  for %%F in ("!_GGUF_DIR!\*mmproj*.gguf") do (
    if not defined _GGUF_MMPROJ_FILE set "_GGUF_MMPROJ_FILE=%%~fF"
  )

  for %%F in ("!_GGUF_DIR!\*.gguf") do (
    if /I not "%%~fF"=="!_GGUF_MMPROJ_FILE!" if not defined _GGUF_MODEL_FILE set "_GGUF_MODEL_FILE=%%~fF"
  )

  if defined _GGUF_MODEL_FILE set "GGUF_MODEL_PATH=!_GGUF_MODEL_FILE!"
  if not defined GGUF_MMPROJ_PATH if defined _GGUF_MMPROJ_FILE set "GGUF_MMPROJ_PATH=!_GGUF_MMPROJ_FILE!"

  set "_GGUF_DIR="
  set "_GGUF_MODEL_FILE="
  set "_GGUF_MMPROJ_FILE="
)

for /f "delims=" %%P in ('powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; try {([uri]'%GGUF_BASE_URL%').Port} catch {''}"') do (
  if not "%%P"=="" set "GGUF_PORT=%%P"
)

if /I "%LLM_PROVIDER%"=="gguf" if not exist "%GGUF_MODEL_PATH%" (
  echo [ERROR] GGUF model not found: %GGUF_MODEL_PATH%
  exit /b 1
)

if /I "%LLM_PROVIDER%"=="gguf" if /I "%LLM_MODEL_PROFILE%"=="internvl" if "%GGUF_MMPROJ_PATH%"=="" (
  echo [ERROR] InternVL profile requires GGUF_MMPROJ_PATH or an auto-detected *mmproj*.gguf in model folder.
  exit /b 1
)

if /I "%LLM_PROVIDER%"=="gguf" if /I "%LLM_MODEL_PROFILE%"=="internvl" if not exist "%GGUF_MMPROJ_PATH%" (
  echo [ERROR] InternVL mmproj file not found: %GGUF_MMPROJ_PATH%
  exit /b 1
)

if /I "%WECHAT_BRIDGE_PROVIDER%"=="secure_relay" (
  if "%SECURE_RELAY_SEND_URL%"=="" (
    echo [ERROR] WECHAT_BRIDGE_PROVIDER=secure_relay but SECURE_RELAY_SEND_URL is empty.
    exit /b 1
  )
  if "%SECURE_RELAY_SHARED_SECRET%"=="" (
    echo [ERROR] WECHAT_BRIDGE_PROVIDER=secure_relay but SECURE_RELAY_SHARED_SECRET is empty.
    exit /b 1
  )
)

if /I "%LLM_PROVIDER%"=="gguf" (
  for /d %%D in ("%USERPROFILE%\.unsloth\llama.cpp\llama-b*-bin-win-vulkan-x64") do (
    if not defined LLAMA_SERVER_EXE if exist "%%~fD\llama-server.exe" set "LLAMA_SERVER_EXE=%%~fD\llama-server.exe"
  )

  for /d %%D in ("%USERPROFILE%\.unsloth\llama.cpp\llama-b*-bin-win-cuda-*-x64") do (
    if not defined LLAMA_SERVER_EXE if exist "%%~fD\llama-server.exe" set "LLAMA_SERVER_EXE=%%~fD\llama-server.exe"
  )

  for /f "delims=" %%I in ('where llama-server.exe 2^>nul') do (
    if not defined LLAMA_SERVER_EXE set "LLAMA_SERVER_EXE=%%~fI"
  )
  if not defined LLAMA_SERVER_EXE if exist "%USERPROFILE%\.unsloth\llama.cpp\llama-server.exe" (
    set "LLAMA_SERVER_EXE=%USERPROFILE%\.unsloth\llama.cpp\llama-server.exe"
  )
  if not defined LLAMA_SERVER_EXE if exist "%USERPROFILE%\.unsloth\llama.cpp\build\bin\Release\llama-server.exe" (
    set "LLAMA_SERVER_EXE=%USERPROFILE%\.unsloth\llama.cpp\build\bin\Release\llama-server.exe"
  )
  if not defined LLAMA_SERVER_EXE (
    echo [ERROR] llama-server.exe not found.
    echo [HINT] Expected one of:
    echo [HINT]   1. In PATH as llama-server.exe
    echo [HINT]   2. %USERPROFILE%\.unsloth\llama.cpp\llama-server.exe
    echo [HINT]   3. %USERPROFILE%\.unsloth\llama.cpp\build\bin\Release\llama-server.exe
    exit /b 1
  )

  set "HAS_GPU_BACKEND=0"
  for %%I in ("%LLAMA_SERVER_EXE%") do set "LLAMA_SERVER_DIR=%%~dpI"
  dir /b "%LLAMA_SERVER_DIR%ggml-vulkan*.dll" >nul 2>nul
  if not errorlevel 1 set "HAS_GPU_BACKEND=1"
  if "%HAS_GPU_BACKEND%"=="0" (
    dir /b "%LLAMA_SERVER_DIR%ggml-cuda*.dll" >nul 2>nul
    if not errorlevel 1 set "HAS_GPU_BACKEND=1"
  )
  if "%HAS_GPU_BACKEND%"=="0" (
    echo [ERROR] Selected llama-server has no GPU backend DLL ^(vulkan/cuda^): %LLAMA_SERVER_EXE%
    echo [HINT] Install a GPU build, e.g. llama-bXXXX-bin-win-vulkan-x64.
    exit /b 1
  )
)
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
echo [INFO] LLM provider: %LLM_PROVIDER%
if /I "%LLM_PROVIDER%"=="gguf" (
  echo [INFO] GGUF model profile: %LLM_MODEL_PROFILE%
  echo [INFO] GGUF model id: %GGUF_MODEL%
  echo [INFO] GGUF model path: %GGUF_MODEL_PATH%
  if defined GGUF_MMPROJ_PATH echo [INFO] GGUF mmproj path: %GGUF_MMPROJ_PATH%
  echo [INFO] GGUF base URL: %GGUF_BASE_URL%
  echo [INFO] llama-server: %LLAMA_SERVER_EXE%
)
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
  if /I "%LLM_PROVIDER%"=="gguf" call :kill_port %GGUF_PORT%
  call :kill_port 8080
  call :kill_port 9000
  call :kill_port 9010
  call :kill_port 9880
  call :kill_port 8011
  call :kill_port 8012
)

set "RUNNER_DIR=%TEMP%\neuro_core_launchers"
if not exist "%RUNNER_DIR%" mkdir "%RUNNER_DIR%"

if /I "%LLM_PROVIDER%"=="gguf" (
  echo [0/6] Preparing GGUF llama-server launcher...
  > "%RUNNER_DIR%\gguf_llm.cmd" (
    echo @echo off
    echo title GGUF LLM
    echo cd /d "%AI_ROOT%"
    echo set "CUDA_VISIBLE_DEVICES=%GPU_ID%"
    if defined GGUF_MMPROJ_PATH (
      echo "%LLAMA_SERVER_EXE%" -m "%GGUF_MODEL_PATH%" --mmproj "%GGUF_MMPROJ_PATH%" --host 127.0.0.1 --port %GGUF_PORT% --ctx-size %GGUF_CTX% --threads %GGUF_THREADS% --gpu-layers %GGUF_N_GPU_LAYERS% --main-gpu %GGUF_MAIN_GPU% --parallel 1 --jinja --chat-template %GGUF_CHAT_TEMPLATE% --no-webui
    ) else (
      echo "%LLAMA_SERVER_EXE%" -m "%GGUF_MODEL_PATH%" --host 127.0.0.1 --port %GGUF_PORT% --ctx-size %GGUF_CTX% --threads %GGUF_THREADS% --gpu-layers %GGUF_N_GPU_LAYERS% --main-gpu %GGUF_MAIN_GPU% --parallel 1 --jinja --chat-template %GGUF_CHAT_TEMPLATE% --no-webui
    )
    echo if errorlevel 1 echo [WARN] Command exited with code %%%%errorlevel%%%%
  )
)

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

echo [4/6] Preparing WeChat bridge launcher...
> "%RUNNER_DIR%\wechat_bridge.cmd" (
  echo @echo off
  echo title WeChat Bridge
  echo cd /d "%CORE_DIR%"
  echo set "CUDA_VISIBLE_DEVICES=-1"
  echo set "WECHAT_BRIDGE_PROVIDER=%WECHAT_BRIDGE_PROVIDER%"
  echo set "GEWECHAT_BASE_URL=%GEWECHAT_BASE_URL%"
  echo set "GEWECHAT_TOKEN=%GEWECHAT_TOKEN%"
  echo set "GEWECHAT_APP_ID=%GEWECHAT_APP_ID%"
  echo set "GEWECHAT_ATS=%GEWECHAT_ATS%"
  echo set "SECURE_RELAY_SEND_URL=%SECURE_RELAY_SEND_URL%"
  echo set "SECURE_RELAY_SHARED_SECRET=%SECURE_RELAY_SHARED_SECRET%"
  echo set "SECURE_RELAY_WINDOW_SEC=%SECURE_RELAY_WINDOW_SEC%"
  echo set "SECURE_RELAY_SIGN_HEADER=%SECURE_RELAY_SIGN_HEADER%"
  echo set "SECURE_RELAY_TS_HEADER=%SECURE_RELAY_TS_HEADER%"
  echo set "SECURE_RELAY_NONCE_HEADER=%SECURE_RELAY_NONCE_HEADER%"
  echo "%UV_EXE%" --directory "%CORE_DIR%" run python wechat\bridge\wechat_http_bridge.py
  echo if errorlevel 1 echo [WARN] Command exited with code %%errorlevel%%
)

echo [5/6] Preparing Core backend launcher...
> "%RUNNER_DIR%\core_backend.cmd" (
  echo @echo off
  echo title Core Backend
  echo cd /d "%CORE_DIR%"
  echo set "CUDA_VISIBLE_DEVICES=-1"
  echo "%UV_EXE%" --directory "%CORE_DIR%" run uvicorn app.main:app --host 0.0.0.0 --port 8080
  echo if errorlevel 1 echo [WARN] Command exited with code %%errorlevel%%
)

if "%NO_UI%"=="0" (
  echo [6/6] Preparing Live2D frontend launcher...
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
  if /I "%LLM_PROVIDER%"=="gguf" echo [DRY] start "GGUF LLM" cmd /k "%RUNNER_DIR%\gguf_llm.cmd"
  echo [DRY] start "TTS Backend" cmd /k "%RUNNER_DIR%\tts_backend.cmd"
  echo [DRY] start "RealtimeSTT" cmd /k "%RUNNER_DIR%\realtimestt.cmd"
  echo [DRY] start "STT Bridge" cmd /k "%RUNNER_DIR%\stt_bridge.cmd"
  echo [DRY] start "WeChat Bridge" cmd /k "%RUNNER_DIR%\wechat_bridge.cmd"
  echo [DRY] start "Core Backend" cmd /k "%RUNNER_DIR%\core_backend.cmd"
  if "%NO_UI%"=="0" echo [DRY] start "live2d-desktop" cmd /k "%RUNNER_DIR%\live2d_ui.cmd"
  exit /b 0
)

if /I "%LLM_PROVIDER%"=="gguf" (
  start "GGUF LLM" cmd /k "%RUNNER_DIR%\gguf_llm.cmd"
  timeout /t 3 /nobreak >nul
  call :wait_http "%GGUF_BASE_URL%/models" 45 2
  if errorlevel 1 (
    echo [ERROR] GGUF service did not become ready: %GGUF_BASE_URL%/models
    exit /b 1
  )
)

start "TTS Backend" cmd /k "%RUNNER_DIR%\tts_backend.cmd"
timeout /t 2 /nobreak >nul
start "RealtimeSTT" cmd /k "%RUNNER_DIR%\realtimestt.cmd"
timeout /t 2 /nobreak >nul
start "STT Bridge" cmd /k "%RUNNER_DIR%\stt_bridge.cmd"
timeout /t 2 /nobreak >nul
start "WeChat Bridge" cmd /k "%RUNNER_DIR%\wechat_bridge.cmd"
timeout /t 2 /nobreak >nul
start "Core Backend" cmd /k "%RUNNER_DIR%\core_backend.cmd"
call :wait_http "http://127.0.0.1:8080/health" 45 1
if errorlevel 1 (
  echo [ERROR] Core backend did not become ready.
  exit /b 1
)
if "%NO_UI%"=="0" (
  timeout /t 2 /nobreak >nul
  start "live2d-desktop" cmd /k "%RUNNER_DIR%\live2d_ui.cmd"
)

call :wait_http "http://127.0.0.1:8080/health/deps" 60 1
if errorlevel 1 (
  echo [WARN] /health/deps not ready yet. Check service windows for details.
) else (
  echo [OK] /health/deps is reachable.
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

:load_config_defaults
if not exist "%CONFIG_FILE%" exit /b 0

call :yaml_get "TTS_PROVIDER" TTS_PROVIDER
call :yaml_get "LLM_PROVIDER" LLM_PROVIDER
call :yaml_get "LLM_MODEL_PROFILE" LLM_MODEL_PROFILE
call :yaml_get "GGUF_BASE_URL" GGUF_BASE_URL
call :yaml_get "GGUF_MODEL" GGUF_MODEL
call :yaml_get "GGUF_MODEL_PATH" GGUF_MODEL_PATH
call :yaml_get "GGUF_QWEN_MODEL" GGUF_QWEN_MODEL
call :yaml_get "GGUF_QWEN_MODEL_PATH" GGUF_QWEN_MODEL_PATH
call :yaml_get "GGUF_INTERNVL_MODEL" GGUF_INTERNVL_MODEL
call :yaml_get "GGUF_INTERNVL_MODEL_PATH" GGUF_INTERNVL_MODEL_PATH
call :yaml_get "GGUF_MMPROJ_PATH" GGUF_MMPROJ_PATH
call :yaml_get "GGUF_THREADS" GGUF_THREADS
call :yaml_get "GGUF_N_GPU_LAYERS" GGUF_N_GPU_LAYERS
call :yaml_get "GGUF_CTX" GGUF_CTX
call :yaml_get "GGUF_MAIN_GPU" GGUF_MAIN_GPU
call :yaml_get "GGUF_CHAT_TEMPLATE" GGUF_CHAT_TEMPLATE
call :yaml_get "GGUF_PORT" GGUF_PORT
call :yaml_get "WECHAT_BRIDGE_PROVIDER" WECHAT_BRIDGE_PROVIDER
call :yaml_get "GEWECHAT_BASE_URL" GEWECHAT_BASE_URL
call :yaml_get "GEWECHAT_TOKEN" GEWECHAT_TOKEN
call :yaml_get "GEWECHAT_APP_ID" GEWECHAT_APP_ID
call :yaml_get "GEWECHAT_ATS" GEWECHAT_ATS
call :yaml_get "SECURE_RELAY_SEND_URL" SECURE_RELAY_SEND_URL
call :yaml_get "SECURE_RELAY_SHARED_SECRET" SECURE_RELAY_SHARED_SECRET
call :yaml_get "SECURE_RELAY_WINDOW_SEC" SECURE_RELAY_WINDOW_SEC
call :yaml_get "SECURE_RELAY_SIGN_HEADER" SECURE_RELAY_SIGN_HEADER
call :yaml_get "SECURE_RELAY_TS_HEADER" SECURE_RELAY_TS_HEADER
call :yaml_get "SECURE_RELAY_NONCE_HEADER" SECURE_RELAY_NONCE_HEADER
call :yaml_get "KOKORO_VOICE" KOKORO_VOICE
call :yaml_get "KOKORO_LANG" KOKORO_LANG
call :yaml_get "KOKORO_SPEED" KOKORO_SPEED
call :yaml_get "GPU_ID" GPU_ID
call :yaml_get "CLEAN_PORTS" CLEAN_PORTS
exit /b 0

:yaml_get
set "_YAML_KEY=%~1"
set "_YAML_TARGET=%~2"
set "_YAML_VALUE="
for /f "usebackq tokens=1* delims=:" %%A in (`findstr /R /B /C:"%_YAML_KEY%:" "%CONFIG_FILE%"`) do set "_YAML_VALUE=%%B"
for /f "tokens=*" %%A in ("%_YAML_VALUE%") do set "_YAML_VALUE=%%A"
for /f "tokens=1 delims=#" %%A in ("%_YAML_VALUE%") do set "_YAML_VALUE=%%A"
for /f "tokens=*" %%A in ("%_YAML_VALUE%") do set "_YAML_VALUE=%%A"
if defined _YAML_VALUE set "%_YAML_TARGET%=%_YAML_VALUE%"
set "_YAML_KEY="
set "_YAML_TARGET="
set "_YAML_VALUE="
exit /b 0

:wait_http
set "_WAIT_URL=%~1"
set "_WAIT_TRIES=%~2"
set "_WAIT_SLEEP=%~3"
if not defined _WAIT_TRIES set "_WAIT_TRIES=30"
if not defined _WAIT_SLEEP set "_WAIT_SLEEP=1"
set /a _WAIT_I=0
:wait_http_loop
set /a _WAIT_I+=1
curl -fsS "%_WAIT_URL%" >nul 2>nul
if not errorlevel 1 goto wait_http_ok
if !_WAIT_I! GEQ !_WAIT_TRIES! goto wait_http_fail
timeout /t !_WAIT_SLEEP! /nobreak >nul
goto wait_http_loop

:wait_http_ok
set "_WAIT_URL="
set "_WAIT_TRIES="
set "_WAIT_SLEEP="
set "_WAIT_I="
exit /b 0

:wait_http_fail
echo [WAIT] timeout: %_WAIT_URL%
set "_WAIT_URL="
set "_WAIT_TRIES="
set "_WAIT_SLEEP="
set "_WAIT_I="
exit /b 1

