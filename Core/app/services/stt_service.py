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
    def __init__(self) -> None:
        self.provider = settings.stt_provider
        self.base_url = settings.stt_base_url.rstrip("/")

    async def transcribe_chunk(
        self,
        pcm_base64: str,
        sample_rate: int = 16000,
        timeout_sec: float | None = None,
    ) -> str:
        payload: dict[str, object] = {
            "audio": pcm_base64,
            "sample_rate": sample_rate,
        }
        if timeout_sec is not None and timeout_sec > 0:
            payload["timeout_sec"] = float(timeout_sec)

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}/transcribe",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json().get("text", "")
