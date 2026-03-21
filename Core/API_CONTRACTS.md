# 接口契约（建议）

标准化 v1 接口文档请优先参考：`API_STANDARD.md`。
本文件更偏“外部系统集成约定与历史兼容说明”。

本文件定义 Core 与外部服务之间的最小 HTTP/WS 协议。

## 1. Core 输入

### WS 音频与控制

- Endpoint: `ws://<core_host>:8080/ws/audio`
- Client -> Core JSON:
  - 文本输入：`{"type":"text","text":"你好"}`
  - 音频块：`{"type":"audio","audio":"<base64_pcm16>"}`
  - 打断：`{"type":"interrupt"}`

### Live2DProtocol 兼容 WS（旧前端可直接接）

- Endpoint: `ws://<core_host>:8080/ws/live2d`
- Subprotocol: `Live2DProtocol`
- Core -> Frontend:
  - 历史消息：`{"action":"add_history","data":{"role":"assistant|user","text":"..."}}`
  - 流式文本：`{"action":"assistant_stream","data":{"text":"逐步累计文本"}}`
  - Live2D 动作：`{"action":"live2d_action","data":{"action_name":"开心|生气|普通|..."}}`
- Frontend -> Core（可选）：
  - 注入文本：`{"action":"inject_text","data":{"text":"你好"}}`

## 2. TTS 服务

- POST `/tts`
  - req: `{"text":"...","text_lang":"zh","ref_audio_path":"...","prompt_lang":"zh","prompt_text":"..."}`
  - resp: `{"ok":true}`
- POST `/stop`
  - req: `{}`
  - resp: `{"ok":true}`

## 3. STT 服务

- POST `/transcribe`
  - req: `{"audio":"<base64_pcm16>","sample_rate":16000}`
  - resp: `{"text":"识别结果"}`

> 如果使用 RealtimeSTT 原生双 WS，请先启动 `bridges/realtimestt_http_bridge.py` 把 WS 转为该 HTTP 接口。

## 4. OCR 服务

- POST `/ocr`
  - req: `{"image":"<base64_png_jpg>"}`
  - resp: `{"lines":["line1","line2"]}`

## 5. Vision 服务

- POST `/vision/analyze`
  - req: `{"image":"<base64_png_jpg>"}`
  - resp: `{"summary":"图像语义摘要"}`

## 6. 微信桥

- GET `/poll`
  - resp: `{"messages":[{"from":"wxid_xxx","text":"hello"}]}`
- POST `/send`
  - req: `{"to":"wxid_xxx","text":"reply"}`
  - resp: `{"ok":true}`

## 7. Slay the Spire 桥

- GET `/state`
  - resp: `{...游戏状态 JSON...}`
- POST `/action`
  - req: `{"type":"play_card","card_id":"...","target":"..."}`
  - resp: `{"ok":true}`

## 8. 搜索 API

- GET `/search?q=<query>`
  - resp: `{"summary":"纯文本摘要"}`

## 9. Playground 兼容 HTTP（旧前端可直接接）

- POST `/playground/text`
  - req: `{"text":"你好"}`
  - resp: `{"status":"queued"}`
- POST `/playground/microphone`
  - form-data:
    - `metadata`: JSON 字符串（含 sample_rate）
    - `audio`: wav 文件
  - resp: `{"status":"queued","sample_rate":16000,"bytes":12345}`
