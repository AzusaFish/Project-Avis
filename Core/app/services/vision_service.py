"""
Module: app/services/vision_service.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 视觉服务客户端：获取图像语义摘要。

from __future__ import annotations

import httpx

from app.core.config import settings


class VisionService:
    def __init__(self) -> None:
        self.base_url = settings.vision_base_url.rstrip("/")

    async def analyze(self, image_base64: str) -> str:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"{self.base_url}/vision/analyze", json={"image": image_base64})
            resp.raise_for_status()
            return resp.json().get("summary", "")
