# Project-Avis API Inventory

Generated on 2026-05-06.

## Conventions
- Core base URL: http://127.0.0.1:8080
- v1 responses:
  - Success: {"code":0,"message":"ok","data":{...}} (code 0 means success)
  - Errors: FastAPI standard error responses (4xx/5xx + detail)
- Legacy endpoints return direct fields (no v1 envelope).

---

# Core HTTP (v1)

## Health and Time

### GET /api/v1/health
- Purpose: Process health check.
- Input: none
- Output:
  - data: {"status":"ok"}

### GET /api/v1/time/now
- Purpose: Server time snapshot.
- Input: none
- Output:
  - data: {"local_time":"YYYY-MM-DD HH:MM:SS +ZZZZ","iso":"ISO-8601","unix":1710000000} (unix is epoch seconds)

### GET /api/v1/health/deps
- Purpose: Dependency checks (LLM/TTS/STT + paths).
- Input: none
- Output:
  - data.status: ok|degraded
  - data.checks.tts/stt/llm: {ok,host,port,error?}
  - data.checks.paths: key->bool (true means the path exists and is accessible)

## Chat Input

### POST /api/v1/chat/text
- Purpose: Queue user text.
- Input (JSON):
  - {"text":"..."}
- Output:
  - data: {"queued": true} (true means accepted into the queue)

### POST /api/v1/chat/microphone
- Purpose: Queue microphone audio.
- Input (multipart/form-data):
  - metadata: JSON string (may include sample_rate)
  - audio: audio file (recommended wav)
- Output:
  - data: {"queued":true,"sample_rate":16000,"bytes":12345} (sample_rate in Hz, bytes is audio size)

## Control

### POST /api/v1/control/inject-text
- Purpose: Debug-only manual text injection.
- Input (JSON):
  - {"text":"..."}
- Output:
  - data: {"queued":true} (true means accepted into the queue)

### GET /api/v1/control/queue-size
- Purpose: Check EventBus queue length.
- Input: none
- Output:
  - data: {"queue_size": 3} (current pending item count)

## Memory Management

### GET /api/v1/memory/dialogues
- Purpose: List memory entries.
- Input (query):
  - limit: 1..500 (default 50)
  - offset: >=0 (default 0)
  - role: user|assistant|system|tool (optional)
  - q: keyword (optional)
  - min_importance: float (optional)
  - processed_flag: 0|1 (optional)
  - sort_by: time|importance (optional)
- Output:
  - data: {"total":N,"limit":L,"offset":O,"items":[...]} (N total, L applied limit, O applied offset)

### PATCH /api/v1/memory/dialogues/{memory_id}
- Purpose: Update memory text.
- Input (JSON):
  - {"text":"..."}
- Output:
  - data: {"updated":true,"id":123} (true means update applied; id is the memory entry id)

### DELETE /api/v1/memory/dialogues/{memory_id}
- Purpose: Delete a memory entry.
- Input: none
- Output:
  - data: {"deleted":true,"id":123} (true means delete applied; id is the memory entry id)

### POST /api/v1/memory/dialogues/clear
- Purpose: Clear memory by role or all.
- Input (JSON):
  - {"role":"user"} or {"role":null}
- Output:
  - data: {"deleted":42,"role":"user"} (deleted is number of entries removed)

## Config Management

### GET /api/v1/config
- Purpose: Read flat config.yaml.
- Input: none
- Output:
  - data: {"path":".../config.yaml","items":{"KEY":"VALUE"}}

### PATCH /api/v1/config
- Purpose: Patch config.yaml and update env.
- Input (JSON):
  - {"items": {"KEY":"VALUE", ...}}
- Output:
  - data: {"path":"...","updated":[...],"restart_recommended":true} (true means restart is recommended)

## Debug

### GET /api/v1/debug/snapshot
- Purpose: Combined runtime snapshot.
- Input: none
- Output:
  - data: queue_size, ws_clients, deps, llm_provider, llm_model, tts_provider,
    memory_count, memory_scoring, llm_io_summary, config_path

### GET /api/v1/debug/llm-io
- Purpose: LLM request/response snapshot.
- Input: none
- Output:
  - data: provider, model, llm_debug_to_frontend, payload

### GET /api/v1/debug/memory-mechanism
- Purpose: Memory scoring/decay diagnostics.
- Input: none
- Output:
  - data: llm_scoring, decay_policy, hybrid_ranking, recent_pending, recent_processed

---

# Core WebSocket

## WS /ws/audio
- Purpose: Realtime audio/text input.
- Client -> Core messages:
  - {"type":"audio","sample_rate":16000,"audio":"<base64_pcm16>"} (sample_rate in Hz)
  - {"type":"text","text":"..."}
  - {"type":"interrupt"}
- Output: none

## WS /ws/live2d (Subprotocol: Live2DProtocol)
- Purpose: Live2D front-end message channel.
- Frontend -> Core:
  - {"action":"inject_text","data":{"text":"..."}}
  - {"action":"show_user_text_input","data":{"text":"..."}}
  - {"action":"think","data":{}}
- Core -> Frontend:
  - {"action":"add_history","data":{"role":"user|assistant","text":"..."}}
  - {"action":"assistant_stream","data":{"text":"..."}}
  - {"action":"live2d_action","data":{"action_name":"开心","expression":"开心","motion_group":"TapHead","motion_index":0}} (motion_index is 0-based)

---

# Core Legacy HTTP (Compatibility)

## GET /health
- Output: {"status":"ok"}

## GET /health/deps
- Output: {"status":"ok|degraded","checks":{...}}

## GET /integrations/status
- Output: llm state, paths, services status

## POST /playground/text
- Input: {"text":"..."}
- Output: {"status":"queued"} (queued means accepted into the queue)

## POST /playground/microphone
- Input (multipart): metadata JSON + audio file
- Output: {"status":"queued","sample_rate":16000,"bytes":12345} (sample_rate in Hz, bytes is audio size)

## POST /control/inject_text
- Input: {"text":"..."}
- Output: {"status":"queued"} (queued means accepted into the queue)

## GET /control/queue_size
- Output: {"queue_size":3} (current pending item count)

## GET /memory/list
- Query: same as v1 list
- Output: {"total":N,"limit":L,"offset":O,"items":[...]} (N total, L applied limit, O applied offset)

## PATCH /memory/{id}
- Input: {"text":"..."}
- Output: {"ok":true,"id":123} (true means update applied; id is the memory entry id)

## DELETE /memory/{id}
- Output: {"ok":true,"id":123} (true means delete applied; id is the memory entry id)

## POST /memory/clear
- Input: {"role":"user"|null}
- Output: {"ok":true,"deleted":42,"role":"user"} (deleted is number of entries removed)

---

# External Services (Core Dependencies)

## STT Service
- POST /transcribe
- Input (JSON): {"audio":"<base64_pcm16>","sample_rate":16000}
- Output (JSON): {"text":"..."}
- Notes: sample_rate in Hz

## TTS Service
- POST /tts
- Input (JSON): {"text":"...","text_lang":"zh","ref_audio_path":"...","prompt_lang":"zh","prompt_text":"..."}
- Output (JSON): {"ok":true} (true means the request was accepted)

- POST /stop
- Input: {}
- Output: {"ok":true} (true means the stop signal was accepted)

## OCR Service
- POST /ocr
- Input (JSON): {"image":"<base64_png_jpg>"}
- Output (JSON): {"lines":["line1","line2"]}

## Vision Service
- POST /vision/analyze
- Input (JSON): {"image":"<base64_png_jpg>"}
- Output (JSON): {"summary":"..."}

## Search API
- GET /search?q=<query>
- Output (JSON): {"summary":"..."} or structured search result JSON

## WeChat Bridge
- GET /poll
- Output (JSON): {"messages":[{"from":"wxid_xxx","text":"hello"}]}

- POST /send
- Input (JSON): {"to":"wxid_xxx","text":"reply"}
- Output (JSON): {"ok":true} (true means the send request was accepted)

## Slay the Spire Bridge
- GET /state
- Output: game state JSON

- POST /action
- Input (JSON): {"type":"play_card","card_id":"...","target":"..."}
- Output (JSON): {"ok":true} (true means the action request was accepted)
