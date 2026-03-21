# 你需要手动准备的具体文件（精确版）

本清单按“文件名 + 格式 + 放置路径”给出，直接照着建就行。

## 0. 先创建目录

在 Core 根目录下创建：

- `configs/`
- `datasets/persona/`
- `datasets/memory/`
- `assets/voices/atri/`
- `data/chroma/`
- `data/`

说明：单人格模式只需要 `atri` 目录；`neuro/evil` 仅在你后续做多人格时再创建。

## 1. 环境变量文件

1. 复制模板
- 源文件：`.env.example`
- 目标文件：`.env`

2. 重点确认这些字段
- `LLM_PROVIDER=ollama`
- `OLLAMA_BASE_URL=http://127.0.0.1:11434`
- `OLLAMA_MODEL=qwen2.5:14b`
- `LLM_STREAM=true`
- `TTS_BASE_URL=http://127.0.0.1:9880`
- `STT_BASE_URL=http://127.0.0.1:9000`
- `STT_CONTROL_WS_URL=ws://127.0.0.1:8011`
- `STT_DATA_WS_URL=ws://127.0.0.1:8012`

## 2. TTS 说话人档案

1. 复制模板
- 源文件：`configs/tts_profiles.example.yaml`
- 目标文件：`configs/tts_profiles.yaml`

2. 必填字段（每个 speaker）
- `ref_audio_path`: 参考音频绝对路径（wav）
- `prompt_text`: 参考音频对应文本
- `text_lang`: `zh` / `en` / `ja` ...
- `prompt_lang`: 与 prompt_text 一致

3. 推荐格式（YAML）

```yaml
default_speaker: atri
speakers:
  atri:
    text_lang: zh
    prompt_lang: zh
    ref_audio_path: D:/AzusaFish/Codes/Development/Project-Avis/Core/assets/voices/atri/neutral.wav
    prompt_text: 今天也要一起努力哦。
    by_emotion:
      happy:
        ref_audio_path: D:/AzusaFish/Codes/Development/Project-Avis/Core/assets/voices/atri/happy.wav
        prompt_text: 太好了，今天状态很好。
```

## 3. 人格语料（RAG）

单人格模式只需要 1 个 jsonl 文件：

- `datasets/persona/atri.jsonl`

多人格扩展时再额外准备：

- `datasets/persona/neuro.jsonl`
- `datasets/persona/evil.jsonl`

每行一个 JSON，字段建议：

- `speaker`: 字符串（例如 `atri`）
- `text`: 台词正文（必须）
- `scene`: 场景标签
- `tags`: 数组
- `emotion`: 情绪标签

示例：

```json
{"speaker":"atri","text":"今天也要加油。","scene":"encourage","tags":["warm"],"emotion":"happy"}
```

导入命令（每个文件跑一次）：

```bash
python scripts/import_persona_jsonl.py --input datasets/persona/atri.jsonl --chroma-path ./data/chroma --collection persona_lines
```

## 4. 可选：长期记忆初始化数据

文件路径：
- `datasets/memory/bootstrap.jsonl`

每行建议格式：

```json
{"role":"user","text":"我喜欢策略游戏"}
{"role":"assistant","text":"收到，我会优先聊策略类内容"}
```

说明：当前代码默认运行时写入 `data/memory.db`，初始化导入可后续加脚本。

## 5. RealtimeSTT 相关

你已有仓库：
- `D:/AzusaFish/Codes/Development/Project-Avis/RealtimeSTT-master/RealtimeSTT-master`

需要启动两个进程：

1. 原生 STT server（双 WS）
```bash
stt-server -m small -l zh -c 8011 -d 8012
```

2. HTTP bridge
```bash
python bridges/realtimestt_http_bridge.py
```

## 6. GPT-SoVITS 相关

你已有仓库：
- `D:/AzusaFish/Codes/Development/Project-Avis/GPT-SoVITS-main/GPT-SoVITS-main`

需要准备：

- GPT/SoVITS 权重（按仓库说明放置）
- 你的参考音频 wav（建议 3~10 秒，16k/32k 单声道也可）

启动示例：

```bash
python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```

## 7. 前端 Live2D 资源

前端项目路径：
- `D:/AzusaFish/Codes/Development/Project-Avis/live2d-desktop`

你需要确认：

- Live2D 模型文件（`.model3.json`）真实存在
- 在前端设置里填写模型路径

推荐把模型放到：
- `D:/AzusaFish/Codes/Development/Project-Avis/Data/Live2D Cubism/...`

## 8. 微信桥（待你接入）

当前 Core 预留接口，需你提供 bridge 服务：

- `GET /poll` 返回新消息
- `POST /send` 发送消息

建议你单独放在：
- `D:/AzusaFish/Codes/Development/Project-Avis/bridges/wechat_bridge/`

## 9. 杀戮尖塔桥（待你接入）

当前 Core 预留接口，需你提供 bridge 服务：

- `GET /state` 游戏状态 JSON
- `POST /action` 出牌指令

建议路径：
- `D:/AzusaFish/Codes/Development/Project-Avis/bridges/sts_bridge/`

## 10. 一键启动

建议使用：

```bat
scripts\start_everything.bat
```

说明：当前推荐 `.bat` 启动器；它已内置环境回退与依赖自检。
