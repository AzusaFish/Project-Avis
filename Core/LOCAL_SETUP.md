# 本机集成指南（基于你当前环境）

本文件按你当前机器状态编写：

- Ollama 模型：`qwen2.5:14b`
- Ollama 模型目录：`C:\Users\AzusaFish\.ollama\models`
- Kokoro 运行方式（当前项目）：`Core/bridges/kokoro_onnx_http_bridge.py`
- GPT-SoVITS 仓库（兼容可选）：`D:\AzusaFish\Codes\Development\Project-Avis\GPT-SoVITS-main\GPT-SoVITS-main`
- RealtimeSTT 仓库：`D:\AzusaFish\Codes\Development\Project-Avis\RealtimeSTT-master\RealtimeSTT-master`
- 参考项目：`D:\AzusaFish\Codes\Development\Project-Avis\Z\reference-core-main`
- Conda 根目录：`D:\AzusaFish\Codes\Development\Project-Avis\.conda`

## 1. 启动 Ollama 并确认模型

```powershell
ollama list
```

应该能看到 `qwen2.5:14b`。

## 1.1 先标准化 Python 环境（推荐）

```powershell
cd D:\AzusaFish\Codes\Development\Project-Avis\Core
pip install uv
uv sync
```

说明：

- `uv sync` 会在 `Core/.venv` 里创建独立环境。
- 推荐固定依赖时使用 `uv sync --frozen`（基于 `uv.lock`）。
- 一键启动请使用仓库根目录的 `start_everything.bat`，其所有 Python 进程都通过 `uv --directory Core run ...` 启动，避免串用系统/conda 环境。

## 2. 启动 Kokoro（默认 TTS）

当前项目已内置 Kokoro ONNX bridge，可直接在 Core 目录启动：

```powershell
cd D:\AzusaFish\Codes\Development\Project-Avis\Core
uv run python bridges\kokoro_onnx_http_bridge.py
```

`.env` 建议：

- `TTS_PROVIDER=kokoro`
- `KOKORO_BASE_URL=http://127.0.0.1:9880`
- `KOKORO_CHUNK_CHARS=180`（可选，长文本分段阈值；显存/速度不足可调小到 120~160）

## 3. （可选）启动 GPT-SoVITS API v2

在 GPT-SoVITS 环境中运行（请替换为你的 conda 环境名）：

```powershell
cd D:\AzusaFish\Codes\Development\Project-Avis\GPT-SoVITS-main\GPT-SoVITS-main
python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```

说明：

- Core 默认调用 `POST /tts`，与 `api_v2.py` 兼容。
- 你还需要准备说话人档案文件，见第 7 节。

## 4. 启动 RealtimeSTT server

在 RealtimeSTT 环境中运行：

```powershell
cd D:\AzusaFish\Codes\Development\Project-Avis\RealtimeSTT-master\RealtimeSTT-master
uv run stt-server -m small -l zh -c 8011 -d 8012
```

说明：

- 该服务是双 WebSocket（control/data）。
- Core 默认 STT 走 HTTP 协议（`STT_PROVIDER=http`），请再启动本项目自带 bridge：

```powershell
cd D:\AzusaFish\Codes\Development\Project-Avis\Core
uv run python bridges/realtimestt_http_bridge.py
```

该 bridge 默认监听 `http://127.0.0.1:9000/transcribe`。

## 5. 启动 Core

```powershell
cd D:\AzusaFish\Codes\Development\Project-Avis\Core
copy .env.example .env
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## 6. 健康检查

- 基础：`GET http://127.0.0.1:8080/health`
- 依赖体检：`GET http://127.0.0.1:8080/health/deps`

`/health/deps` 会检查：

- LLM / TTS / STT 的 TCP 连通性
- GPT-SoVITS / RealtimeSTT / SQLite / Chroma 路径可用性

如果返回 `degraded`，优先看 `checks` 字段中失败项。

## 7. 接入你的 Vue3 + Tauri 前端

你的前端目录：

- `D:\AzusaFish\Codes\Development\Project-Avis\live2d-desktop`

已改为默认接 Core：

- WS: `ws://127.0.0.1:8080/ws/live2d`
- HTTP: `http://127.0.0.1:8080`
- 麦克风实时流：`ws://127.0.0.1:8080/ws/audio`

运行：

```powershell
cd D:\AzusaFish\Codes\Development\Project-Avis\live2d-desktop
npm install
npm run tauri dev
```

如果只测前端网页层：

```powershell
npm run dev
```

## 8. 一键启动全栈

脚本：`scripts/start_everything.ps1`

```powershell
cd D:\AzusaFish\Codes\Development\Project-Avis\Core
powershell -ExecutionPolicy Bypass -File .\scripts\start_everything.ps1
```

可指定 conda 环境名：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_everything.ps1 -CoreEnv base -TtsEnv base -RealtimeSttEnv base -TtsProvider kokoro -CondaRoot D:\AzusaFish\Codes\Development\Project-Avis\.conda
```

如果你要切回 GPT-SoVITS：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_everything.ps1 -TtsProvider gpt_sovits -TtsEnv base
```

## 9. TTS 说话人档案

请复制：

- `configs/tts_profiles.example.yaml` -> `configs/tts_profiles.yaml`

然后把 `ref_audio_path` 和 `prompt_text` 改成你的真实素材。

## 10. 参考外部 core 的可复用思想

本 Core 已吸收以下模式：

- 统一配置入口（像 `config.template.yaml` 的思路）
- 模型路由层（按 provider 切换 LLM）
- 启动前资源可用性检查（像 starter 前的预检）
