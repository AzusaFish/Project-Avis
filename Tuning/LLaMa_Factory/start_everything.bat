@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "LOG_FILE=%~dp0start_everything.last.log"
echo [INFO] start at %DATE% %TIME% > "%LOG_FILE%"

set "DRY_RUN=0"
set "HOLD_ON_ERROR=1"
if /I "%~1"=="--dry-run" (
  set "DRY_RUN=1"
  shift
)
if /I "%~1"=="--no-pause" (
  set "HOLD_ON_ERROR=0"
  shift
)

set "LF_ENV=%~dp0.conda-lf"

set "MODEL_NAME_OR_PATH=InternVL3_5-14B-HF"
set "SFT_TEMPLATE=intern_vl"
set "DPO_TEMPLATE=intern_vl"
set "VISION_SUBSET_SIZE=4000"
set "VISION_DOWNLOAD_WORKERS=24"
set "VISION_MAX_RETRIES=2"
set "DPO_LIMIT=2500"
set "SFT_OUT=outputs/neuro_sft_lora_internvl35_14b"
set "DPO_OUT=outputs/neuro_dpo_lora_internvl35_14b"

set "HF_CACHE_ROOT=%~dp0.hf"
set "HF_HOME=%HF_CACHE_ROOT%"
set "HF_HUB_CACHE=%~dp0.hfh"
set "HF_DATASETS_CACHE=%~dp0.hfd"
set "HF_ASSETS_CACHE=%~dp0.hfa"
set "HF_DATASETS_DISABLE_CACHING=1"
set "TOKENIZERS_PARALLELISM=false"
set "OMP_NUM_THREADS=2"
set "MKL_NUM_THREADS=2"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PREP_ARGS=--model-name-or-path %MODEL_NAME_OR_PATH% --sft-template %SFT_TEMPLATE% --dpo-template %DPO_TEMPLATE% --vision-subset-size %VISION_SUBSET_SIZE% --vision-download-workers %VISION_DOWNLOAD_WORKERS% --vision-max-retries %VISION_MAX_RETRIES% --dpo-limit %DPO_LIMIT% --sft-output-dir %SFT_OUT% --dpo-output-dir %DPO_OUT%"

echo [INFO] ===== LLaMA-Factory one-click pipeline =====
echo [INFO] model: %MODEL_NAME_OR_PATH%
echo [INFO] sft template: %SFT_TEMPLATE%
echo [INFO] dpo template: %DPO_TEMPLATE%
echo [INFO] vision subset: %VISION_SUBSET_SIZE%
echo [INFO] vision workers: %VISION_DOWNLOAD_WORKERS%
echo [INFO] dpo limit: %DPO_LIMIT%
echo [INFO] lf env: %LF_ENV%
echo [INFO] hf cache root: %HF_CACHE_ROOT%
echo [INFO] log file: %LOG_FILE%

>> "%LOG_FILE%" echo [INFO] model=%MODEL_NAME_OR_PATH%
>> "%LOG_FILE%" echo [INFO] sft_template=%SFT_TEMPLATE%
>> "%LOG_FILE%" echo [INFO] dpo_template=%DPO_TEMPLATE%
>> "%LOG_FILE%" echo [INFO] vision_subset=%VISION_SUBSET_SIZE%
>> "%LOG_FILE%" echo [INFO] vision_workers=%VISION_DOWNLOAD_WORKERS%
>> "%LOG_FILE%" echo [INFO] dpo_limit=%DPO_LIMIT%
>> "%LOG_FILE%" echo [INFO] lf_env=%LF_ENV%
>> "%LOG_FILE%" echo [INFO] hf_cache_root=%HF_CACHE_ROOT%

if "%DRY_RUN%"=="1" (
  echo [DRY] call :ensure_env
  echo [DRY] conda run -p "%LF_ENV%" --no-capture-output python prepare_neuro_lf_data.py %PREP_ARGS%
  echo [DRY] conda run -p "%LF_ENV%" --no-capture-output python -m llamafactory.cli train train_neuro_sft_lora.yaml
  echo [DRY] conda run -p "%LF_ENV%" --no-capture-output python -m llamafactory.cli train train_neuro_dpo_lora.yaml
  exit /b 0
)

call :ensure_env
if not %ERRORLEVEL%==0 (
  call :fail "Environment setup failed." %ERRORLEVEL%
)

if exist "%HF_DATASETS_CACHE%" (
  echo [INFO] Clearing local HF datasets cache to avoid stale Arrow collisions...
  rmdir /s /q "%HF_DATASETS_CACHE%"
)
if exist "%~dp0.hf_cache" (
  echo [INFO] Removing legacy long-path HF cache dir...
  rmdir /s /q "%~dp0.hf_cache"
)
if not exist "%HF_HUB_CACHE%" mkdir "%HF_HUB_CACHE%"
if not exist "%HF_DATASETS_CACHE%" mkdir "%HF_DATASETS_CACHE%"
if not exist "%HF_ASSETS_CACHE%" mkdir "%HF_ASSETS_CACHE%"

call conda run -p "%LF_ENV%" --no-capture-output python prepare_neuro_lf_data.py %PREP_ARGS%
if not %ERRORLEVEL%==0 (
  call :fail "prepare_neuro_lf_data.py failed." %ERRORLEVEL%
)

call conda run -p "%LF_ENV%" --no-capture-output python -c "import json,sys; r=json.load(open('datasets/prepare_report.json','r',encoding='utf-8')); target=int(r.get('stats',{}).get('vision_target',0)); kept=int(r.get('vision_records',0)); enabled=bool(r.get('vision_in_sft_enabled')); print(f'[CHECK] vision_in_sft_enabled={enabled}, vision_records={kept}, vision_target={target}'); sys.exit(0 if enabled and kept>=target and target>0 else 1)"
if not %ERRORLEVEL%==0 (
  call :fail "Vision subset was not included in SFT. Check sft-template/intern_vl and prepare report." %ERRORLEVEL%
)

call conda run -p "%LF_ENV%" --no-capture-output python -m llamafactory.cli train train_neuro_sft_lora.yaml
if not %ERRORLEVEL%==0 (
  call :fail "SFT failed." %ERRORLEVEL%
)

call conda run -p "%LF_ENV%" --no-capture-output python -m llamafactory.cli train train_neuro_dpo_lora.yaml
if not %ERRORLEVEL%==0 (
  call :fail "DPO failed." %ERRORLEVEL%
)

echo [OK] Training pipeline completed.
echo [OUT] SFT adapter: %~dp0%SFT_OUT%
echo [OUT] DPO adapter: %~dp0%DPO_OUT%
exit /b 0

:ensure_env
where conda >nul 2>nul
if not %ERRORLEVEL%==0 (
  echo [ERROR] conda not found in PATH.
  exit /b 1
)

if exist "%LF_ENV%\python.exe" (
  echo [INFO] Reusing env: %LF_ENV%
) else (
  echo [INFO] Creating env: %LF_ENV%
  call conda create -p "%LF_ENV%" -y python=3.11
  if not %ERRORLEVEL%==0 exit /b %ERRORLEVEL%
)

call conda run -p "%LF_ENV%" --no-capture-output python -c "import torch,llamafactory,pandas,pyarrow,bitsandbytes,timm; print('ready')" >nul 2>nul
if %ERRORLEVEL%==0 (
  echo [OK] Env packages ready.
  exit /b 0
)

echo [INFO] Installing/upgrading training dependencies...
call conda run -p "%LF_ENV%" --no-capture-output python -m pip install -U pip
if not %ERRORLEVEL%==0 exit /b %ERRORLEVEL%

call conda run -p "%LF_ENV%" --no-capture-output python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
if not %ERRORLEVEL%==0 exit /b %ERRORLEVEL%

call conda run -p "%LF_ENV%" --no-capture-output python -m pip install llamafactory pandas pyarrow bitsandbytes timm
if not %ERRORLEVEL%==0 exit /b %ERRORLEVEL%

call conda run -p "%LF_ENV%" --no-capture-output python -c "import torch,llamafactory,pandas,pyarrow,bitsandbytes,timm; print('ready')"
if not %ERRORLEVEL%==0 exit /b %ERRORLEVEL%

exit /b 0

:fail
set "MSG=%~1"
set "EC=%~2"
if "%EC%"=="" set "EC=1"
echo [ERROR] %MSG%
echo [ERROR] Exit code: %EC%
>> "%LOG_FILE%" echo [ERROR] %DATE% %TIME% %MSG%
>> "%LOG_FILE%" echo [ERROR] Exit code: %EC%
echo [INFO] failure log written: %LOG_FILE%
if "%HOLD_ON_ERROR%"=="1" pause
exit /b %EC%
