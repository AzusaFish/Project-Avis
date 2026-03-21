"""
Module: app/services/stt_service.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# STT 客户端：把音频块发送到统一 /transcribe 接口。

from __future__ import annotations

import httpx

from app.core.config import settings


class STTService:
    """STTService: main class container for related behavior in this module."""
    def __init__(self) -> None:
        # 缓存 STT 提供商与接口地址，避免重复拼接。
        """Initialize the object state and cache required dependencies."""
        self.provider = settings.stt_provider
        self.base_url = settings.stt_base_url.rstrip("/")

    async def transcribe_chunk(self, pcm_base64: str, sample_rate: int = 16000) -> str:
        # 上传音频分片并返回转写文本。
        # 约定：`pcm_base64` 是 PCM16 原始帧的 Base64 字符串。
        """Public API `transcribe_chunk` used by other modules or route handlers."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}/transcribe",
                json={"audio": pcm_base64, "sample_rate": sample_rate},
            )
            resp.raise_for_status()
            return resp.json().get("text", "")
