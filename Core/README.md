# Neuro 风格 Core（中文说明）

这是一个“事件驱动”的数字人后端骨架：

- 用 FastAPI 提供 HTTP/WS 接口
- 用 asyncio 事件总线串联 STT / LLM / TTS / 工具调用
- 用 Agent 主循环持续处理输入，而不是一次性问答

## 系统目标

- 持续运行的 Agent 循环
- CPU/GPU 异构任务拆分
- 统一通信中枢（Router）
- 长期记忆 + 人格 RAG
- 对外工具调用（微信、搜索、游戏、Live2D）

## 快速启动（推荐 uv）

1. 安装 uv（只需一次）

```bash
pip install uv
```

2. 创建并同步项目环境

```bash
cd D:/AzusaFish/Codes/Development/AI/Core
uv sync
```

3. 复制环境变量模板

```bash
copy .env.example .env
```

4. 启动 Core

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080
```

5. 健康检查

- `GET /health`
- `GET /health/deps`（依赖体检）

## 兼容旧方式（pip）

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## 推荐 LLM 配置（你当前机器）

- `LLM_PROVIDER=ollama`
- `OLLAMA_BASE_URL=http://127.0.0.1:11434`
- `OLLAMA_MODEL=qwen2.5:14b`
- `LLM_STREAM=true`

## 关键通信接口

- 前端音频 WS：`/ws/audio`
- 旧协议兼容 WS：`/ws/live2d`
- 兼容文本接口：`/playground/text`
- 兼容麦克风接口：`/playground/microphone`

详细协议见：`API_CONTRACTS.md`

## 已实现能力（当前版本）

- 事件总线 + Agent 主循环
- Ollama / OpenAI 兼容 LLM（含流式）
- RealtimeSTT ws->http 桥接
- TTS 双后端（Kokoro 默认 + GPT-SoVITS 兼容接口）
- SQLite 短期记忆 + Chroma 人格检索
- Live2D 前端兼容推送（字幕、动作）

## 文档索引

- 本机启动：`LOCAL_SETUP.md`
- 配置总指南（音色/环境变量/路径）：`CONFIG_GUIDE.md`
- 标准 API 文档：`API_STANDARD.md`
- Python 文件功能总览：`PYTHON_FILES_OVERVIEW.md`
- 运行时调用链详解：`RUNTIME_FLOW_DETAILED.md`
- 依赖准备（通用）：`PREPARE_FILES.md`
- 依赖准备（精确路径+格式）：`PREPARE_EXACT.md`

