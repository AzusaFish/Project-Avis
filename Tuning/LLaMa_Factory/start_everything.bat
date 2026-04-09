@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "LOG_FILE=%~dp0start_everything.last.log"
echo [INFO] start at %DATE% %TIME% > "%LOG_FILE%"

set "DRY_RUN=0"
set "HOLD_ON_ERROR=1"
set "EXPORT_ONLY=0"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--dry-run" (
  set "DRY_RUN=1"
  shift
  goto parse_args
)
if /I "%~1"=="--no-pause" (
  set "HOLD_ON_ERROR=0"
  shift
  goto parse_args
)
if /I "%~1"=="--export-only" (
  set "EXPORT_ONLY=1"
  shift
  goto parse_args
)
shift
goto parse_args

:args_done

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
set "EXPORTS_DIR=exports/neuro_dpo"
set "OUTPUT_STEM=neuro-internvl35-14b"
set "LLAMA_CPP_DIR=%~dp0tools\llama.cpp"
set "EXPORT_YAML=%~dp0%EXPORTS_DIR%\export_lf.generated.yaml"
set "MERGED_DIR=%~dp0%EXPORTS_DIR%\merged_hf"
set "MERGED_DIR_POSIX=%MERGED_DIR:\=/%"
set "GGUF_DIR=%~dp0%EXPORTS_DIR%\gguf"
for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
set "DEPLOY_GGUF_DIR=%PROJECT_ROOT%\Model\Tuned1"

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
echo [INFO] export only: %EXPORT_ONLY%
echo [INFO] hf cache root: %HF_CACHE_ROOT%
echo [INFO] exports dir: %EXPORTS_DIR%
echo [INFO] deploy gguf dir: %DEPLOY_GGUF_DIR%
echo [INFO] log file: %LOG_FILE%

>> "%LOG_FILE%" echo [INFO] model=%MODEL_NAME_OR_PATH%
>> "%LOG_FILE%" echo [INFO] sft_template=%SFT_TEMPLATE%
>> "%LOG_FILE%" echo [INFO] dpo_template=%DPO_TEMPLATE%
>> "%LOG_FILE%" echo [INFO] vision_subset=%VISION_SUBSET_SIZE%
>> "%LOG_FILE%" echo [INFO] vision_workers=%VISION_DOWNLOAD_WORKERS%
>> "%LOG_FILE%" echo [INFO] dpo_limit=%DPO_LIMIT%
>> "%LOG_FILE%" echo [INFO] lf_env=%LF_ENV%
>> "%LOG_FILE%" echo [INFO] export_only=%EXPORT_ONLY%
>> "%LOG_FILE%" echo [INFO] hf_cache_root=%HF_CACHE_ROOT%
>> "%LOG_FILE%" echo [INFO] exports_dir=%EXPORTS_DIR%
>> "%LOG_FILE%" echo [INFO] deploy_gguf_dir=%DEPLOY_GGUF_DIR%

if "%DRY_RUN%"=="1" (
  echo [DRY] call :ensure_env
  if "%EXPORT_ONLY%"=="0" (
    echo [DRY] conda run -p "%LF_ENV%" --no-capture-output python prepare_neuro_lf_data.py %PREP_ARGS%
    echo [DRY] conda run -p "%LF_ENV%" --no-capture-output python -m llamafactory.cli train train_neuro_sft_lora.yaml
    echo [DRY] conda run -p "%LF_ENV%" --no-capture-output python -m llamafactory.cli train train_neuro_dpo_lora.yaml
  )
  echo [DRY] generate %EXPORT_YAML%
  echo [DRY] conda run -p "%LF_ENV%" --no-capture-output python -m llamafactory.cli export %EXPORT_YAML%
  echo [DRY] conda run -p "%LF_ENV%" --no-capture-output python "%LLAMA_CPP_DIR%\convert_hf_to_gguf.py" "%MERGED_DIR%" --outfile "%GGUF_DIR%\%OUTPUT_STEM%.F16.gguf" --outtype f16
  echo [DRY] conda run -p "%LF_ENV%" --no-capture-output python "%LLAMA_CPP_DIR%\convert_hf_to_gguf.py" "%MERGED_DIR%" --outfile "%GGUF_DIR%\%OUTPUT_STEM%.F16.gguf" --outtype f16 --mmproj
  echo [DRY] "%LLAMA_CPP_DIR%\build\bin\Release\llama-quantize.exe" "%GGUF_DIR%\%OUTPUT_STEM%.F16.gguf" "%GGUF_DIR%\%OUTPUT_STEM%.Q4_K_M.gguf" Q4_K_M
  echo [DRY] copy gguf to "%DEPLOY_GGUF_DIR%"
  exit /b 0
)

call :ensure_env
if not %ERRORLEVEL%==0 (
  call :fail "Environment setup failed." %ERRORLEVEL%
)

if "%EXPORT_ONLY%"=="1" goto export_phase

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

:export_phase
if not exist "%~dp0%EXPORTS_DIR%" mkdir "%~dp0%EXPORTS_DIR%"
if not exist "%GGUF_DIR%" mkdir "%GGUF_DIR%"

if not exist "%~dp0%DPO_OUT%\adapter_model.safetensors" (
  call :fail "DPO adapter not found: %~dp0%DPO_OUT%\adapter_model.safetensors" 1
)

(
  echo ### model
  echo model_name_or_path: %MODEL_NAME_OR_PATH%
  echo adapter_name_or_path: %DPO_OUT%
  echo trust_remote_code: true
  echo.
  echo ### method
  echo finetuning_type: lora
  echo template: %SFT_TEMPLATE%
  echo.
  echo ### export
  echo export_dir: %MERGED_DIR_POSIX%
  echo export_size: 2
  echo export_device: cpu
  echo export_legacy_format: false
) > "%EXPORT_YAML%"

call conda run -p "%LF_ENV%" --no-capture-output python -m llamafactory.cli export "%EXPORT_YAML%"
if not %ERRORLEVEL%==0 (
  call :fail "LLaMA-Factory export (merge) failed." %ERRORLEVEL%
)

if not exist "%LLAMA_CPP_DIR%\convert_hf_to_gguf.py" (
  call :fail "llama.cpp converter not found: %LLAMA_CPP_DIR%\convert_hf_to_gguf.py" 1
)

call conda run -p "%LF_ENV%" --no-capture-output python "%LLAMA_CPP_DIR%\convert_hf_to_gguf.py" "%MERGED_DIR%" --outfile "%GGUF_DIR%\%OUTPUT_STEM%.F16.gguf" --outtype f16
if not %ERRORLEVEL%==0 (
  call :fail "HF -> F16 GGUF conversion failed." %ERRORLEVEL%
)

call conda run -p "%LF_ENV%" --no-capture-output python "%LLAMA_CPP_DIR%\convert_hf_to_gguf.py" "%MERGED_DIR%" --outfile "%GGUF_DIR%\%OUTPUT_STEM%.F16.gguf" --outtype f16 --mmproj
if not %ERRORLEVEL%==0 (
  call :fail "mmproj GGUF conversion failed." %ERRORLEVEL%
)

set "QUANTIZER=%LLAMA_CPP_DIR%\build\bin\Release\llama-quantize.exe"
if not exist "%QUANTIZER%" set "QUANTIZER=%LLAMA_CPP_DIR%\build\bin\llama-quantize.exe"
if not exist "%QUANTIZER%" set "QUANTIZER=%LLAMA_CPP_DIR%\llama-quantize.exe"
if not exist "%QUANTIZER%" (
  call :fail "llama-quantize.exe not found under %LLAMA_CPP_DIR%" 1
)

call "%QUANTIZER%" "%GGUF_DIR%\%OUTPUT_STEM%.F16.gguf" "%GGUF_DIR%\%OUTPUT_STEM%.Q4_K_M.gguf" Q4_K_M
if not %ERRORLEVEL%==0 (
  call :fail "Q4_K_M quantization failed." %ERRORLEVEL%
)

if not exist "%GGUF_DIR%\%OUTPUT_STEM%.Q4_K_M.gguf" (
  call :fail "Expected Q4 GGUF missing after quantization." 1
)
if not exist "%GGUF_DIR%\mmproj-%OUTPUT_STEM%.F16.gguf" (
  call :fail "Expected mmproj GGUF missing after conversion." 1
)

if not exist "%DEPLOY_GGUF_DIR%" mkdir "%DEPLOY_GGUF_DIR%"
copy /Y "%GGUF_DIR%\%OUTPUT_STEM%.Q4_K_M.gguf" "%DEPLOY_GGUF_DIR%\" >nul
if not %ERRORLEVEL%==0 call :fail "Failed to copy Q4 GGUF to deploy dir." %ERRORLEVEL%
copy /Y "%GGUF_DIR%\mmproj-%OUTPUT_STEM%.F16.gguf" "%DEPLOY_GGUF_DIR%\" >nul
if not %ERRORLEVEL%==0 call :fail "Failed to copy mmproj GGUF to deploy dir." %ERRORLEVEL%

echo [OK] Training pipeline completed.
echo [OUT] SFT adapter: %~dp0%SFT_OUT%
echo [OUT] DPO adapter: %~dp0%DPO_OUT%
echo [OUT] Q4 GGUF: %GGUF_DIR%\%OUTPUT_STEM%.Q4_K_M.gguf
echo [OUT] MMPROJ GGUF: %GGUF_DIR%\mmproj-%OUTPUT_STEM%.F16.gguf
echo [OUT] Deployed: %DEPLOY_GGUF_DIR%
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
