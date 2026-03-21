# Core API 标准接口文档（v1）

本项目保留历史兼容接口（如 /playground/*、/control/*、/memory/*），同时新增标准化接口前缀：`/api/v1`。

统一返回结构（HTTP 200 成功时）：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

错误返回：沿用 FastAPI 标准错误结构（如 4xx/5xx + detail）。

## 1) 健康与依赖

### GET /api/v1/health
功能：进程级健康检查。

响应 data 字段：
- status: `ok`

### GET /api/v1/health/deps
功能：依赖体检（LLM/TTS/STT 端口连通性 + 关键路径存在性）。

响应 data 字段：
- status: `ok|degraded`
- checks.tts/stt/llm: 连通性信息
- checks.paths: 关键目录可用性

## 2) 聊天输入

### POST /api/v1/chat/text
功能：提交文本消息，异步入队到 AgentLoop。

请求体：
```json
{ "text": "你好" }
```

响应 data 字段：
- queued: `true`

### POST /api/v1/chat/microphone
功能：提交麦克风音频（multipart），服务端转为 PCM16 base64 入队。

表单字段：
- metadata: JSON 字符串，可含 sample_rate
- audio: 音频文件（推荐 wav）

响应 data 字段：
- queued: `true`
- sample_rate: 采样率
- bytes: PCM 字节数

## 3) 控制面

### POST /api/v1/control/inject-text
功能：调试用，手动注入文本到事件总线。

请求体：
```json
{ "text": "测试注入" }
```

响应 data 字段：
- queued: `true`

### GET /api/v1/control/queue-size
功能：查看当前事件队列长度。

响应 data 字段：
- queue_size: 整数

## 4) 记忆管理

### GET /api/v1/memory/dialogues
功能：分页查询对话记忆。

查询参数：
- limit: 1~500，默认 50
- offset: 默认 0
- role: `user|assistant`（可选）
- q: 关键字检索（可选）

响应 data 字段：
- total, limit, offset
- items: 记忆列表

### PATCH /api/v1/memory/dialogues/{memory_id}
功能：更新某条记忆文本。

请求体：
```json
{ "text": "新的文本" }
```

响应 data 字段：
- updated: `true`
- id: 记忆 ID

### DELETE /api/v1/memory/dialogues/{memory_id}
功能：删除某条记忆。

响应 data 字段：
- deleted: `true`
- id: 记忆 ID

### POST /api/v1/memory/dialogues/clear
功能：清空记忆（可按角色）。

请求体：
```json
{ "role": "user" }
```
或
```json
{ "role": null }
```

响应 data 字段：
- deleted: 删除数量
- role: 清理角色条件

## 5) WebSocket 接口（实时）

### WS /ws/live2d
功能：前端文本/动作/字幕通道（Live2DProtocol 兼容）。

主要上行 action：
- inject_text
- show_user_text_input

主要下行 action：
- add_history
- assistant_stream
- live2d_action

### WS /ws/audio
功能：麦克风实时输入通道。

上行包示例：
```json
{ "type": "audio", "sample_rate": 16000, "seq": 1, "audio": "<base64 pcm16>" }
```

打断包示例：
```json
{ "type": "interrupt" }
```

## 6) 历史兼容接口（仍可用）

- POST /playground/text
- POST /playground/microphone
- POST /control/inject_text
- GET /control/queue_size
- GET /memory/list
- PATCH /memory/{id}
- DELETE /memory/{id}
- POST /memory/clear

建议新接入优先使用 `/api/v1/*`。

## 7) 常见故障说明

### LLM 502（Ollama）
现已增强容错：
- /api/chat 5xx 会自动回退到 /api/generate
- 流式失败会降级非流式，避免前端静默

排查建议：
1. 检查 `GET /api/v1/health/deps`
2. 检查 Ollama 是否已启动、模型是否存在
3. 高负载时可重试请求
