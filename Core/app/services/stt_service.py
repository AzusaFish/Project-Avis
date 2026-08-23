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
    # Initialize STT client settings and retry policy.
    def __init__(self) -> None:
        self.provider = settings.stt_provider
        self.base_url = settings.stt_base_url.rstrip("/")
        self.http_timeout_sec = max(2.0, float(getattr(settings, "stt_http_timeout_sec", 12.0)))
        self.http_retries = max(0, int(getattr(settings, "stt_http_retries", 1)))

    # Send an audio chunk for transcription and return text.
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

        last_exc: Exception | None = None
        async with httpx.AsyncClient(timeout=self.http_timeout_sec) as client:
            for attempt in range(self.http_retries + 1):
                try:
                    resp = await client.post(
                        f"{self.base_url}/transcribe",
                        json=payload,
                    )
                    resp.raise_for_status()
                    return resp.json().get("text", "")
                except (httpx.HTTPError, ValueError) as exc:
                    last_exc = exc
                    if attempt >= self.http_retries:
                        break
        if last_exc is not None:
            raise last_exc
        return ""
