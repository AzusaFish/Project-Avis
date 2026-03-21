"""
Module: app/services/tts_service.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# TTS 客户端：支持 Kokoro 与 GPT-SoVITS 双后端。

from __future__ import annotations

import httpx

from app.core.config import settings
from app.services.tts_profiles import TTSProfiles


class TTSService:
    """TTSService: main class container for related behavior in this module."""
    def __init__(self) -> None:
        # 初始化 TTS 提供商、端点与说话人配置。
        """Initialize the object state and cache required dependencies."""
        self.provider = settings.tts_provider.lower().strip()
        self.base_url = settings.tts_base_url.rstrip("/")
        self.gpt_sovits_base_url = settings.gpt_sovits_base_url.rstrip("/")
        self.kokoro_base_url = settings.kokoro_base_url.rstrip("/")
        self.default_speaker = settings.tts_default_speaker
        self.streaming_mode = settings.tts_streaming_mode
        self.kokoro_model = settings.kokoro_model
        self.kokoro_voice = settings.kokoro_voice
        self.kokoro_lang = settings.kokoro_lang
        self.kokoro_response_format = settings.kokoro_response_format
        self.kokoro_speed = settings.kokoro_speed
        self.profiles = TTSProfiles(settings.tts_profile_path)

    async def speak(self, text: str, emotion: str = "neutral", speaker: str | None = None) -> None:
        # 按 provider 路由到对应的 TTS 后端。
        """Public API `speak` used by other modules or route handlers."""
        if not (text or "").strip():
            return

        resolved_speaker = speaker or self.default_speaker
        profile = self.profiles.resolve(resolved_speaker, emotion=emotion)

        if self.provider == "kokoro":
            await self._speak_kokoro(text=text, profile=profile)
            return
        await self._speak_gpt_sovits(text=text, profile=profile)

    async def _speak_gpt_sovits(self, text: str, profile: dict) -> None:
        # 保留 GPT-SoVITS 原始接口字段，兼容旧部署与现有参数档案。
        """Internal helper `_speak_gpt_sovits` used by this module implementation."""
        payload = {
            "text": text,
            "text_lang": profile.get("text_lang", "zh"),
            "ref_audio_path": profile.get("ref_audio_path", ""),
            "prompt_lang": profile.get("prompt_lang", "zh"),
            "prompt_text": profile.get("prompt_text", ""),
            "text_split_method": profile.get("text_split_method", "cut5"),
            "batch_size": profile.get("batch_size", 1),
            "media_type": profile.get("media_type", "wav"),
            "streaming_mode": profile.get("streaming_mode", self.streaming_mode),
            "top_k": profile.get("top_k", 15),
            "top_p": profile.get("top_p", 1.0),
            "temperature": profile.get("temperature", 1.0),
            "speed_factor": profile.get("speed_factor", 1.0),
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self.gpt_sovits_base_url}/tts", json=payload)
            resp.raise_for_status()

    async def _speak_kokoro(self, text: str, profile: dict) -> None:
        # 优先尝试 OpenAI 风格接口；若后端实现不同则回退到 /tts 兼容调用。
        """Internal helper `_speak_kokoro` used by this module implementation."""
        voice = profile.get("kokoro_voice", self.kokoro_voice)
        speed = float(profile.get("kokoro_speed", profile.get("speed_factor", self.kokoro_speed)))
        response_format = profile.get("kokoro_response_format", self.kokoro_response_format)

        openai_payload = {
            "model": profile.get("kokoro_model", self.kokoro_model),
            "input": text,
            "voice": voice,
            "lang": profile.get("kokoro_lang", self.kokoro_lang),
            "response_format": response_format,
            "speed": speed,
        }
        fallback_payload = {
            "text": text,
            "voice": voice,
            "lang": profile.get("kokoro_lang", self.kokoro_lang),
            "speed": speed,
            "format": response_format,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self.kokoro_base_url}/v1/audio/speech", json=openai_payload)
            if resp.status_code < 400:
                return

            fallback_resp = await client.post(f"{self.kokoro_base_url}/tts", json=fallback_payload)
            if fallback_resp.status_code >= 400:
                raise RuntimeError(
                    "kokoro tts failed: "
                    f"openai={resp.status_code} legacy={fallback_resp.status_code}"
                )

    async def stop_current(self) -> None:
        # GPT-SoVITS 支持 /stop；Kokoro 常见服务一般不提供停止接口。
        """Public API `stop_current` used by other modules or route handlers."""
        if self.provider == "kokoro":
            return
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                await client.post(f"{self.gpt_sovits_base_url}/stop", json={})
            except Exception:
                # Some GPT-SoVITS API variants do not expose /stop.
                return
