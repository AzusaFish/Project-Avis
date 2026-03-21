# 配置总指南（音色、环境变量、路径）

本指南用于统一回答三类问题：
- 音色在哪里改
- 环境变量在哪里改
- 各种路径配置在哪里改

## 1. 先看配置优先级

按实际生效顺序（从高到低）：
1) 启动脚本直接注入的环境变量
2) Core/.env
3) app/core/config.py 里的默认值

注意：改完配置后，需要重启对应进程。

## 2. 音色配置在哪里改

### 2.1 你用一键启动（start_everything.bat）时

优先改这个文件顶部变量：
- Development/Project-Avis/start_everything.bat
  - KOKORO_VOICE
  - KOKORO_LANG
  - KOKORO_SPEED

原因：一键启动会在拉起 Kokoro 子进程时显式设置这些环境变量。

### 2.2 你单独启动 Core / Kokoro 时

改 Core/.env：
- Core/.env
  - TTS_PROVIDER=kokoro
  - KOKORO_VOICE
  - KOKORO_LANG
  - KOKORO_SPEED
  - KOKORO_MODEL_PATH
  - KOKORO_VOICES_PATH

模板可参考：
- Core/.env.example

### 2.3 按角色（speaker）定制音色

改：
- Core/configs/tts_profiles.yaml

Kokoro 每个 speaker 可配置：
- kokoro_voice
- kokoro_lang
- kokoro_speed
- kokoro_model
- kokoro_response_format

GPT-SoVITS 每个 speaker 可配置：
- ref_audio_path
- prompt_text
- text_lang
- prompt_lang
- by_emotion

## 3. 一个容易踩坑的点（很重要）

当前代码里，默认 speaker 的实际来源是 .env 中的 TTS_DEFAULT_SPEAKER（由 tts_service.py 读取）。

tts_profiles.yaml 顶层的 default_speaker 字段目前不是主生效项。

所以请确保：
- .env 里的 TTS_DEFAULT_SPEAKER
- tts_profiles.yaml 里的 speakers 键名

两者一致。

## 4. 环境变量配置清单（后端 Core）

文件：
- Core/.env
- 模板：Core/.env.example
- 配置类定义：Core/app/core/config.py

### 4.1 应用自身
- APP_NAME, APP_ENV, APP_HOST, APP_PORT

### 4.2 LLM（Ollama/OpenAI 兼容）
- LLM_PROVIDER
- LLM_BASE_URL, LLM_MODEL, LLM_API_KEY
- LLM_TEMPERATURE, LLM_TOP_P
- LLM_STREAM, LLM_MAX_CONTEXT, LLM_MAX_OUTPUT
- OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT_SEC, OLLAMA_MODELS_DIR

### 4.3 TTS/STT/OCR/Vision
- TTS_BASE_URL, TTS_PROVIDER, TTS_PROFILE_PATH, TTS_DEFAULT_SPEAKER
- GPT_SOVITS_BASE_URL
- KOKORO_BASE_URL, KOKORO_VOICE, KOKORO_LANG, KOKORO_SPEED
- KOKORO_MODEL_PATH, KOKORO_VOICES_PATH, KOKORO_CHUNK_CHARS
- STT_BASE_URL, STT_CONTROL_WS_URL, STT_DATA_WS_URL
- OCR_BASE_URL, VISION_BASE_URL

### 4.4 数据与外部桥接
- SQLITE_PATH, CHROMA_PATH, PERSONA_COLLECTION, MEMORY_COLLECTION
- WECHAT_BRIDGE_URL, STS_BRIDGE_URL, SEARCH_API_URL

### 4.5 本地仓库路径（体检展示）
- GPT_SOVITS_REPO
- REALTIMESTT_REPO
- REFERENCE_CORE_REPO

## 5. 路径配置在哪里改

### 5.1 模型/语音资源路径
- Core/.env
  - KOKORO_MODEL_PATH
  - KOKORO_VOICES_PATH
- Core/configs/tts_profiles.yaml
  - ref_audio_path（GPT-SoVITS）

### 5.2 启动脚本中的仓库路径
- Development/Project-Avis/start_everything.bat
  - CORE_DIR
  - GPT_DIR
  - STT_DIR
  - UI_DIR

### 5.3 Core 数据路径
- Core/.env
  - SQLITE_PATH
  - CHROMA_PATH

## 6. 前端配置（live2d-desktop）

前端设置保存在浏览器存储 localStorage，由下面文件读写：
- Development/Project-Avis/live2d-desktop/src/App.vue

主要键：
- l2d_modelPath（模型路径）
- l2d_wsUrl（WS 地址）
- l2d_resServerUrl（Core HTTP 地址）
- l2d_ttsServerUrl（TTS 地址）
- l2d_ttsVolume（播放音量）
- l2d_audioOutputDeviceId（输出设备）

## 7. 推荐改配置流程

1) 先定后端模式（kokoro 或 gpt_sovits）
2) 改 Core/.env
3) 改 tts_profiles.yaml（speaker 与情绪）
4) 若用一键启动，再同步改 start_everything.bat 顶部 Kokoro 变量
5) 重启对应进程
6) 用 /api/v1/health/deps 检查依赖连通

## 8. 常见问题速查

- 改了音色没生效：
  先看是不是一键启动脚本覆盖了 KOKORO_VOICE。

- 说话人不生效：
  检查 TTS_DEFAULT_SPEAKER 是否与 tts_profiles.yaml 中 speakers 的键一致。

- 路径明明存在但报错：
  注意 Windows 路径分隔符，建议在 YAML 里统一用正斜杠。

## 9. LLM 系统提示词（System Prompt）在哪里改

### 9.1 主入口文件
- Core/app/agent/prompt_builder.py
  - build_system_prompt()

这里返回的字符串就是系统提示词，包含人格规则、输出协议、动作字段约束。

### 9.2 什么时候加载生效
- Core/app/agent/loop.py
  - AgentLoop 初始化时读取 build_system_prompt() 并保存到 self._system_prompt。

因此改完系统提示词后，需要重启 Core Backend 才会生效。

### 9.3 现在不在 .env 的配置项

当前系统提示词是代码内固定文本，不是 .env 项。
如果你希望改成“文件热更新”或“环境变量覆盖”，建议后续扩展为：
- SYSTEM_PROMPT_PATH（外部 prompt 文件）
- 或 SYSTEM_PROMPT_APPEND（在默认提示词后追加）

### 9.4 修改建议

建议只改这三类内容：
- 人格语气规则
- 输出 JSON 协议（action/text/emotion/tool_*）
- 工具调用触发规则

不要随意删除 JSON 输出约束，否则会影响 Planner 解析稳定性。
