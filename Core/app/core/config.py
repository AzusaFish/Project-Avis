"""
Module: app/core/config.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 全局配置：通过 .env 注入所有服务地址与运行参数。

import os
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_project_yaml() -> dict[str, str]:
    """Load flat key-value YAML from project root config.yaml."""
    config_path = Path(__file__).resolve().parents[3] / "config.yaml"
    data: dict[str, str] = {}
    if not config_path.exists():
        return data

    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        data[key] = value
    return data


# Priority: project config.yaml > real process env/.env defaults
for _k, _v in _load_project_yaml().items():
    os.environ[_k] = _v


class Settings(BaseSettings):
    # 规则：
    # 1) alias="APP_NAME" 表示读取环境变量 APP_NAME
    # 2) default=... 表示环境变量缺失时的默认值
    # 3) 字段类型由 Pydantic 自动转换（比如 "8080" -> int）
    """Settings: main class container for related behavior in this module."""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ===== 应用自身监听参数 =====
    app_name: str = Field(default="neuro_core", alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8080, alias="APP_PORT")

    # ===== LLM 通用参数（OpenAI 兼容协议）=====
    # 当 LLM_PROVIDER=openai 时，主要使用这一组配置。
    llm_provider: str = Field(default="ollama", alias="LLM_PROVIDER")
    llm_base_url: str = Field(default="http://127.0.0.1:8001/v1", alias="LLM_BASE_URL")
    llm_model: str = Field(default="Qwen/Qwen2.5-14B-Instruct-GPTQ-Int4", alias="LLM_MODEL")
    llm_model_profile: str = Field(default="internvl", alias="LLM_MODEL_PROFILE")
    llm_api_key: str = Field(default="EMPTY", alias="LLM_API_KEY")
    llm_temperature: float = Field(default=0.8, alias="LLM_TEMPERATURE")
    llm_top_p: float = Field(default=0.95, alias="LLM_TOP_P")
    llm_stream: bool = Field(default=True, alias="LLM_STREAM")
    llm_max_context: int = Field(default=8192, alias="LLM_MAX_CONTEXT")
    llm_max_output: int = Field(default=512, alias="LLM_MAX_OUTPUT")
    assistant_max_chars: int = Field(default=260, alias="ASSISTANT_MAX_CHARS")
    # assistant_stream_* 控制“字幕流式回放”的切片大小与时间间隔。
    assistant_stream_chunk_chars: int = Field(default=12, alias="ASSISTANT_STREAM_CHUNK_CHARS")
    assistant_stream_interval_ms: int = Field(default=25, alias="ASSISTANT_STREAM_INTERVAL_MS")
    llm_debug_to_frontend: bool = Field(default=True, alias="LLM_DEBUG_TO_FRONTEND")

    # ===== GGUF / llama.cpp(OpenAI-compatible server) =====
    gguf_base_url: str = Field(default="http://127.0.0.1:8081/v1", alias="GGUF_BASE_URL")
    gguf_model: str = Field(default="Avis-14B-v1.Q4_K_M.gguf", alias="GGUF_MODEL")
    gguf_qwen_model: str = Field(default="Avis-14B-v1.Q4_K_M.gguf", alias="GGUF_QWEN_MODEL")
    gguf_internvl_model: str = Field(default="InternVL-14B", alias="GGUF_INTERNVL_MODEL")
    gguf_model_path: str = Field(default="", alias="GGUF_MODEL_PATH")
    gguf_mmproj_path: str = Field(default="", alias="GGUF_MMPROJ_PATH")

    # ===== Ollama 原生参数 =====
    # 当 LLM_PROVIDER=ollama 时，LLMRouter 走 /api/chat。
    ollama_base_url: str = Field(default="http://127.0.0.1:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen2.5:14b", alias="OLLAMA_MODEL")
    ollama_timeout_sec: int = Field(default=60, alias="OLLAMA_TIMEOUT_SEC")
    ollama_models_dir: str = Field(
        default=str(Path.home() / ".ollama" / "models"),
        alias="OLLAMA_MODELS_DIR",
    )

    context_reserved_for_response: int = Field(default=700, alias="CONTEXT_RESERVED_FOR_RESPONSE")
    context_reserved_for_tools: int = Field(default=800, alias="CONTEXT_RESERVED_FOR_TOOLS")

    # ===== 多模态子服务地址 =====
    tts_base_url: str = Field(default="http://127.0.0.1:9880", alias="TTS_BASE_URL")
    tts_provider: str = Field(default="kokoro", alias="TTS_PROVIDER")
    tts_profile_path: str = Field(default="./configs/tts_profiles.yaml", alias="TTS_PROFILE_PATH")
    tts_default_speaker: str = Field(default="default", alias="TTS_DEFAULT_SPEAKER")
    tts_streaming_mode: bool = Field(default=True, alias="TTS_STREAMING_MODE")
    gpt_sovits_base_url: str = Field(default="http://127.0.0.1:9880", alias="GPT_SOVITS_BASE_URL")
    kokoro_base_url: str = Field(default="http://127.0.0.1:9880", alias="KOKORO_BASE_URL")
    kokoro_model: str = Field(default="kokoro", alias="KOKORO_MODEL")
    kokoro_voice: str = Field(default="jf_alpha", alias="KOKORO_VOICE")
    kokoro_lang: str = Field(default="en-us", alias="KOKORO_LANG")
    kokoro_response_format: str = Field(default="wav", alias="KOKORO_RESPONSE_FORMAT")
    kokoro_speed: float = Field(default=1.0, alias="KOKORO_SPEED")
    kokoro_model_path: str = Field(default="./assets/kokoro/kokoro-v1.0.onnx", alias="KOKORO_MODEL_PATH")
    kokoro_voices_path: str = Field(default="./assets/kokoro/voices-v1.0.bin", alias="KOKORO_VOICES_PATH")
    stt_base_url: str = Field(default="http://127.0.0.1:9000", alias="STT_BASE_URL")
    stt_provider: str = Field(default="http", alias="STT_PROVIDER")
    stt_control_ws_url: str = Field(default="ws://127.0.0.1:8011", alias="STT_CONTROL_WS_URL")
    stt_data_ws_url: str = Field(default="ws://127.0.0.1:8012", alias="STT_DATA_WS_URL")
    ocr_base_url: str = Field(default="http://127.0.0.1:9001", alias="OCR_BASE_URL")
    vision_base_url: str = Field(default="http://127.0.0.1:9002", alias="VISION_BASE_URL")
    screenshot_max_edge: int = Field(default=768, alias="SCREENSHOT_MAX_EDGE")

    # ===== 本地仓库路径（主要用于 /health/deps 自检展示）=====
    gpt_sovits_repo: str = Field(
        default="../GPT-SoVITS-main/GPT-SoVITS-main",
        alias="GPT_SOVITS_REPO",
    )
    kokoro_repo: str = Field(
        default=".",
        alias="KOKORO_REPO",
    )
    realtimestt_repo: str = Field(
        default="../RealtimeSTT-master/RealtimeSTT-master",
        alias="REALTIMESTT_REPO",
    )
    reference_core_repo: str = Field(
        default="../Z/reference-core-main",
        alias="REFERENCE_CORE_REPO",
    )

    # ===== 外部桥接服务 =====
    wechat_bridge_url: str = Field(default="http://127.0.0.1:9010", alias="WECHAT_BRIDGE_URL")
    sts_bridge_url: str = Field(default="http://127.0.0.1:9011", alias="STS_BRIDGE_URL")
    search_api_url: str = Field(default="http://127.0.0.1:9012/search", alias="SEARCH_API_URL")

    # ===== 记忆存储 =====
    sqlite_path: str = Field(default="./data/memory.db", alias="SQLITE_PATH")
    chroma_path: str = Field(default="./data/chroma", alias="CHROMA_PATH")
    persona_collection: str = Field(default="persona_lines", alias="PERSONA_COLLECTION")
    memory_collection: str = Field(default="long_term_memory", alias="MEMORY_COLLECTION")

    # ===== 运行时节奏参数 =====
    agent_tick_interval_sec: float = Field(default=0.2, alias="AGENT_TICK_INTERVAL_SEC")
    proactive_silence_sec: int = Field(default=300, alias="PROACTIVE_SILENCE_SEC")
    think_max_continuations: int = Field(default=3, alias="THINK_MAX_CONTINUATIONS")

    # ===== 上下文压缩（伪 KV 压缩） =====
    kv_compress_enabled: bool = Field(default=True, alias="KV_COMPRESS_ENABLED")
    kv_compress_trigger_tokens: int = Field(default=2600, alias="KV_COMPRESS_TRIGGER_TOKENS")
    kv_compress_keep_last_turns: int = Field(default=8, alias="KV_COMPRESS_KEEP_LAST_TURNS")
    kv_compress_source_messages: int = Field(default=60, alias="KV_COMPRESS_SOURCE_MESSAGES")
    kv_compress_min_turns: int = Field(default=6, alias="KV_COMPRESS_MIN_TURNS")

    # ===== 异步记忆总结与反思 =====
    memory_reflect_enabled: bool = Field(default=True, alias="MEMORY_REFLECT_ENABLED")
    memory_reflect_poll_sec: int = Field(default=45, alias="MEMORY_REFLECT_POLL_SEC")
    memory_reflect_turn_interval: int = Field(default=100, alias="MEMORY_REFLECT_TURN_INTERVAL")
    memory_reflect_daily_hour: int = Field(default=3, alias="MEMORY_REFLECT_DAILY_HOUR")
    memory_reflect_max_scan: int = Field(default=260, alias="MEMORY_REFLECT_MAX_SCAN")
    memory_reflect_max_notes: int = Field(default=12, alias="MEMORY_REFLECT_MAX_NOTES")
    memory_recall_top_k: int = Field(default=4, alias="MEMORY_RECALL_TOP_K")

    @model_validator(mode="after")
    def expand_path_like_fields(self) -> "Settings":
        """Expand env vars / home shorthand in path-like settings."""
        path_fields = (
            "ollama_models_dir",
            "gguf_model_path",
            "gguf_mmproj_path",
            "tts_profile_path",
            "kokoro_model_path",
            "kokoro_voices_path",
            "gpt_sovits_repo",
            "kokoro_repo",
            "realtimestt_repo",
            "reference_core_repo",
            "sqlite_path",
            "chroma_path",
        )
        for field_name in path_fields:
            raw = getattr(self, field_name, "")
            if not isinstance(raw, str) or not raw.strip():
                continue
            expanded = os.path.expandvars(os.path.expanduser(raw.strip()))
            setattr(self, field_name, expanded)
        return self

settings = Settings()
