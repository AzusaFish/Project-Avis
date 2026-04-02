# Project Avis 路径说明

本文档用于说明配置中的路径基准与迁移规则，避免因目录变动导致服务启动失败。

## 1. 路径基准

当前启动方式下，Core 后端进程工作目录为 `Project-Avis/Core`。

因此：
- `.` 代表 `Project-Avis/Core`
- `../` 代表 `Project-Avis`

示例：
- `KOKORO_REPO: .` -> `Project-Avis/Core`
- `REALTIMESTT_REPO: ../RealtimeSTT-master/RealtimeSTT-master` -> `Project-Avis/RealtimeSTT-master/RealtimeSTT-master`

## 2. 推荐写法

优先使用以下两类路径：
- 相对路径：适用于仓库内目录，便于整仓迁移
- 环境变量路径：适用于用户目录，例如 `%USERPROFILE%/.ollama/models`

避免写死绝对路径（如 `D:/...`），否则换盘符或换机器会失效。

## 3. 当前关键配置说明PATH_INSTRUCTIONS

`config.yaml`：
- `GPT_SOVITS_REPO`: `../GPT-SoVITS-main/GPT-SoVITS-main`
- `KOKORO_REPO`: `.`
- `REALTIMESTT_REPO`: `../RealtimeSTT-master/RealtimeSTT-master`
- `REFERENCE_CORE_REPO`: `../Z/reference-core-main`
- `OLLAMA_MODELS_DIR`: `%USERPROFILE%/.ollama/models`

`Core/configs/tts_profiles.yaml`：
- `ref_audio_path` 使用相对路径，例如 `./assets/voices/neutral.wav`
- 运行时会自动将相对路径解析为基于配置文件所在目录的绝对路径

## 4. 迁移到新机器的最小检查清单

1. 确认目录结构存在：
- `Project-Avis/Core`
- `Project-Avis/RealtimeSTT-master/RealtimeSTT-master`
- `Project-Avis/GPT-SoVITS-main/GPT-SoVITS-main`（若使用 GPT-SoVITS）

2. 在 `Project-Avis/config.yaml` 中仅修改必要项：
- `LLM_PROVIDER` / `GGUF_MODEL_PATH` / `TTS_PROVIDER`
- 若目录结构不同，再改对应 repo 路径

3. 检查参考音频：
- `Core/assets/voices/neutral.wav` 必须存在（或改为你自己的文件）

4. 启动后查看依赖健康：
- `GET /health/deps`
- 若某个路径为 false，优先核对对应配置项是否仍是旧路径

## 5. 代码层路径展开规则

- `Core/app/core/config.py` 会对路径类配置执行：
  - 环境变量展开（如 `%USERPROFILE%`）
  - 家目录展开（如 `~`）
- `Core/app/services/tts_profiles.py` 会对 `ref_audio_path` 执行：
  - 环境变量/家目录展开
  - 相对路径锚定到 `tts_profiles.yaml` 所在目录
