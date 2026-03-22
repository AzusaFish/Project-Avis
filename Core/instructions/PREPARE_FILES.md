# 你需要准备的文件与仓库

下面是按模块拆分的准备清单。先准备最小集，再迭代。

## 1. LLM (14B)

- 模型权重目录（建议量化版）
  - 例如：Qwen2.5-14B-Instruct GPTQ/AWQ/GGUF
- 推理后端（任选其一）
  - vLLM（OpenAI API 兼容）
  - Ollama（建议先验证 8B，再切 14B）

建议目录：

- `models/llm/<model_name>/...`

## 2. STT (realtime)

- 从 GitHub 拉取 realtime STT 项目
- 确认其可提供 HTTP/WebSocket 接口
- 若无标准接口，需要加一层 bridge，转成：
  - `POST /transcribe`
  - 或 websocket 事件流

建议目录：

- `third_party/realtime_stt/...`

## 3. GPT-SoVITS (TTS)

- 从 GitHub 拉取 GPT-SoVITS
- 准备模型权重（GPT + SoVITS）
- 准备说话人配置与参考音频
- 对外暴露 TTS 接口（建议 `POST /tts`）

建议目录：

- `third_party/GPT-SoVITS/...`
- `models/gpt_sovits/...`

## 4. OCR

- PaddleOCR 模型文件（CPU 推理）
- 一个可调用服务（建议 `POST /ocr`）

建议目录：

- `third_party/paddleocr_service/...`

## 5. 图像理解模型

- 轻量 VLM 或图像分类模型（非必须全时启用）
- 建议做成独立接口（`POST /vision/analyze`）

建议目录：

- `third_party/vision_service/...`

## 6. 微信接入

- 微信守护进程/机器人桥接程序
- 能提供：
  - 拉取新消息
  - 发送消息
  - 联系人映射

建议目录：

- `bridges/wechat_bridge/...`

## 7. Slay the Spire 接入

- 游戏安装 Communication Mod
- Python bridge 用于轮询或订阅游戏状态 JSON
- 命令下发接口（如出牌、结束回合）

建议目录：

- `bridges/sts_bridge/...`

## 8. 人格语料

- 单人格最小集：只准备 1 份语料即可（例如 atri）
- 格式建议：jsonl
  - 字段：`speaker`, `text`, `scene`, `tags`, `emotion`
- 向量化导入脚本

建议目录（最小可运行）：

- `datasets/persona/atri.jsonl`

可选扩展（未来要做多人格再加）：

- `datasets/persona/neuro.jsonl`
- `datasets/persona/evil.jsonl`

## 9. 长期记忆初始数据

- 可选：历史聊天导入文件
- 可选：用户画像初始表

建议目录：

- `datasets/memory/*.jsonl`

## 10. Live2D + 前端

- Vue3/Tauri 项目（单独仓库或本仓库子目录）
- WS 协议约定：
  - 接收表情/动作标签
  - 接收语音播放事件
  - 回传麦克风音频流

建议目录：

- `frontend/live2d_tauri/...`

## 推荐先后顺序

1. 先跑通 LLM + TTS + 简单文本聊天
2. 接入 STT 中断机制
3. 接入微信
4. 接入长期记忆和人格 RAG
5. 最后接入 Slay the Spire 与图像模型
