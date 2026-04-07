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

## 11. Gewechat（Docker Desktop）接入 WeChat

说明：Gewechat 官方仓库当前标注为不再维护，接入前请自行评估可用性与合规风险。

### 11.0 一键启动（推荐）

仓库根目录执行（可重复执行）：

```powershell
cd D:\AzusaFish\Codes\Development\Project-Avis
.\Core\wechat\launchers\start_gewechat.bat
```

脚本会自动完成：

- 启动/复用 `gewe` 容器
- 容器内拉起 Redis、MySQL
- 在正确目录启动 `long`/`pact`
- 启动 Gewechat API（2531）
- 自动请求并打印 `GEWECHAT_TOKEN`

注意：如果脚本提示 `Device layer not ready (pact/4600)`，表示 token 可用但设备层未连通（通常会导致 `getLoginQrCode` 返回“创建设备失败”）。
这不是命令拼写问题，需按脚本输出的诊断命令检查 `pact.log/system.txt`，重点看是否有“无法与设备库进行通信”。

若只想输出 token：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Core\wechat\scripts\start_gewechat_bootstrap.ps1 -PrintTokenOnly
```

### 11.1 启动 Gewechat 容器

```powershell
docker pull registry.cn-hangzhou.aliyuncs.com/gewe/gewe:latest
docker tag registry.cn-hangzhou.aliyuncs.com/gewe/gewe gewe
mkdir D:\gewechat-temp -Force
docker run -itd -v D:\gewechat-temp:/root/temp -p 2531:2531 -p 2532:2532 --privileged=true --name gewe gewe /usr/sbin/init
```

### 11.2 获取 GEWECHAT_TOKEN 与 GEWECHAT_APP_ID

1. 获取 token（记下返回里的 token）。

```powershell
curl.exe -X POST "http://127.0.0.1:2531/v2/api/tools/getTokenId" -H "Content-Type: application/json" -d "{}"
```

2. 获取登录二维码（首次登录 appId 传空字符串）。

```powershell
curl.exe -X POST "http://127.0.0.1:2531/v2/api/login/getLoginQrCode" -H "Content-Type: application/json" -H "X-GEWE-TOKEN: <你的 token>" -d "{\"appId\":\"\",\"type\":\"ipad\",\"regionId\":\"510000\"}"
```

常见错误：

- `header:X-GEWE-TOKEN 不可为空`：请求头名写错了，必须是 `X-GEWE-TOKEN`。
- 例如 `X-GEWE-TOKE`（少了 `N`）会触发该错误。

返回中会有 `appId`、`uuid`、`qrData`。扫描 `qrData` 对应二维码。

3. 轮询确认登录（直到 ret=200 且在线）。

```powershell
curl.exe -X POST "http://127.0.0.1:2531/v2/api/login/checkLogin" -H "Content-Type: application/json" -H "X-GEWE-TOKEN: <你的 token>" -d "{\"appId\":\"<上一步 appId>\",\"uuid\":\"<上一步 uuid>\",\"captchCode\":\"\"}"
```

登录成功后，`appId` 就是你要填到 `GEWECHAT_APP_ID` 的值；token 即 `GEWECHAT_TOKEN`。

### 11.3 配置 Project Avis

在仓库根目录 `config.yaml` 设置：

- `WECHAT_BRIDGE_PROVIDER: gewechat`
- `GEWECHAT_BASE_URL: http://127.0.0.1:2531/v2/api`
- `GEWECHAT_TOKEN: <你的 token>`
- `GEWECHAT_APP_ID: <你的 appId>`

你也可以不改文件，直接在启动前用环境变量覆盖同名键。

### 11.4 启动 WeChat bridge

可以直接用一键脚本（已内置 WeChat bridge 启动）：

- 仓库根目录：`start_everything.bat`
- 或 `Core/scripts/start_everything.ps1`

bridge 默认监听：`http://127.0.0.1:9010`

### 11.5 绑定 Gewechat 回调到 bridge

先测试 bridge：

```powershell
curl http://127.0.0.1:9010/
```

然后将 Gewechat 回调地址设置为：

- `http://host.docker.internal:9010/gewechat/callback`

示例（按 Gewechat 常用接口）：

```powershell
curl.exe -X POST "http://127.0.0.1:2531/v2/api/tools/setCallback" -H "Content-Type: application/json" -H "X-GEWE-TOKEN: <你的 token>" -d "{\"token\":\"<你的 token>\",\"callbackUrl\":\"http://host.docker.internal:9010/gewechat/callback\"}"
```

### 11.6 联调验证

1. 查看 Core 拉取入口：`http://127.0.0.1:9010/poll`
2. 发送测试消息（走 Core 的工具契约）：

```powershell
curl.exe -X POST "http://127.0.0.1:9010/send" -H "Content-Type: application/json" -d "{\"to\":\"wxid_xxx\",\"text\":\"hello from avis\"}"
```

3. 看 `Core` 日志里是否收到 `WECHAT_MESSAGE` 事件。
