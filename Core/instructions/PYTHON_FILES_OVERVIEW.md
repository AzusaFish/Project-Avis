# Python 文件功能总览（面向零 Python 基础）

本文回答三件事：
1) 目前实现了哪些功能
2) 每个 .py 文件在做什么
3) 哪些功能“有接口但主要是转发/薄实现”

说明：以下清单覆盖 Core 目录下全部 41 个 Python 文件。

## 一、目前已实现的核心功能

- FastAPI 后端主服务（HTTP + WebSocket）
- 事件总线驱动的 Agent 主循环（EventBus + AgentLoop）
- LLM 路由（Ollama / OpenAI 兼容）
- TTS 双后端（Kokoro 默认 + GPT-SoVITS 兼容调用）
- STT HTTP 转写调用 + RealtimeSTT 双 WS 桥接
- 记忆系统（SQLite 对话短期记忆 + Chroma 人格检索）
- 前端网关广播（字幕、动作、历史）
- 工具调用框架（搜索、微信、STS、Live2D）
- 标准化 API（/api/v1）与兼容 API（/playground、/control、/memory）

## 二、每个 Python 文件在做什么

### 1) app 根模块
- app/main.py: 创建 FastAPI app，挂载中间件和全部路由
- app/__init__.py: 包入口说明（无业务逻辑）

### 2) app/api 路由层
- app/api/routes_health.py: /health 与 /health/deps
- app/api/routes_control.py: /control/inject_text 与 /control/queue_size
- app/api/routes_memory.py: /memory 的列表、修改、删除、清空
- app/api/routes_playground.py: 旧前端兼容 /playground/text 与 /playground/microphone
- app/api/routes_frontend_ws.py: Live2DProtocol 兼容 WebSocket（/ws/live2d）
- app/api/routes_integrations.py: /integrations/status（外部依赖聚合探活）
- app/api/routes_v1.py: 标准化接口 /api/v1/*（统一返回结构）

### 3) app/agent 智能体层
- app/agent/loop.py: 主循环，处理事件并串起 STT->LLM->工具/TTS
- app/agent/prompt_builder.py: 系统提示词（System Prompt）定义
- app/agent/planner.py: 解析模型输出 JSON 动作并做降级兜底
- app/agent/context_manager.py: 按 token 预算裁剪上下文
- app/agent/memory.py: MemoryFacade，统一调用 SQLite/Chroma

### 4) app/core 基础设施
- app/core/config.py: 所有 .env 配置项定义与读取
- app/core/events.py: EventType/AgentActionType 和数据结构定义
- app/core/bus.py: 异步队列事件总线
- app/core/lifecycle.py: 启动依赖装配、后台任务启动与关闭回收
- app/core/logger.py: 日志格式和级别初始化

### 5) app/inputs 输入适配层
- app/inputs/websocket_audio.py: /ws/audio，收 text/audio/interrupt
- app/inputs/wechat_guard.py: 轮询微信 bridge 并投递 WECHAT_MESSAGE
- app/inputs/sts_bridge.py: 轮询游戏状态并投递 GAME_STATE
- app/inputs/scheduler.py: 静默定时器，触发 SCHEDULE_TICK

### 6) app/services 服务调用层
- app/services/llm_router.py: LLM 调用路由（流式/非流式/容错回退）
- app/services/tts_service.py: TTS 后端路由（kokoro 或 gpt_sovits）
- app/services/tts_profiles.py: 读 YAML 说话人配置
- app/services/stt_service.py: 调 STT /transcribe
- app/services/ocr_service.py: 调 OCR /ocr
- app/services/vision_service.py: 调 Vision /vision/analyze
- app/services/frontend_gateway.py: 管理前端 WS 连接并广播消息

### 7) app/storage 存储层
- app/storage/sqlite_store.py: dialogue 表 CRUD 与分页统计
- app/storage/chroma_store.py: 人格语料向量检索

### 8) app/tools 工具层
- app/tools/base.py: 工具协议接口定义
- app/tools/registry.py: 工具注册与按名调用
- app/tools/google_search.py: 搜索工具
- app/tools/wechat_tool.py: 微信发送工具
- app/tools/sts_tool.py: STS 动作工具
- app/tools/live2d_tool.py: Live2D 控制工具

### 9) bridges 桥接服务
- bridges/realtimestt_http_bridge.py: RealtimeSTT 双 WS -> HTTP /transcribe
- bridges/kokoro_onnx_http_bridge.py: Kokoro TTS HTTP 服务（/v1/audio/speech, /tts）

### 10) scripts 脚本
- scripts/import_persona_jsonl.py: 把人格 jsonl 导入 Chroma

## 三、“有接口但主要是转发/薄实现”的点

这些并非“没写”，但当前属于薄实现（主要把请求转发到外部服务）：

- app/tools/google_search.py
  - 接口在，但核心能力依赖 SEARCH_API_URL 外部服务
- app/tools/wechat_tool.py
  - 接口在，但仅向微信桥发送请求并返回固定成功文本
- app/tools/sts_tool.py
  - 接口在，但仅向游戏桥发送动作并返回固定成功文本
- app/tools/live2d_tool.py
  - 接口在，但只返回文本描述，真正动作由 AgentLoop 广播给前端
- app/services/ocr_service.py / vision_service.py / stt_service.py
  - 都是“客户端薄层”，核心算法在外部服务

## 四、你最常改的文件（建议）

- 改系统提示词: app/agent/prompt_builder.py
- 改音色与 TTS 参数: configs/tts_profiles.yaml + .env
- 改 LLM 模型和地址: .env（OLLAMA_* / LLM_*）
- 改接口行为: app/api/routes_v1.py
- 改记忆策略: app/agent/memory.py + app/storage/*

## 五、给零 Python 基础的阅读顺序

1) app/main.py（先看系统入口）
2) app/core/lifecycle.py（看依赖怎么组装）
3) app/agent/loop.py（看主流程）
4) app/services/llm_router.py + tts_service.py + stt_service.py（看模型链路）
5) app/storage/sqlite_store.py + chroma_store.py（看记忆）
6) app/api/routes_v1.py（看对外接口）
