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
    """VisionService: main class container for related behavior in this module."""
    def __init__(self) -> None:
        # 初始化视觉服务基地址。
        """Initialize the object state and cache required dependencies."""
        self.base_url = settings.vision_base_url.rstrip("/")

    async def analyze(self, image_base64: str) -> str:
        # 向视觉模型发送图片并返回语义摘要。
        # 返回值是 summary 文本，供 LLM 继续推理使用。
        """Public API `analyze` used by other modules or route handlers."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"{self.base_url}/vision/analyze", json={"image": image_base64})
            resp.raise_for_status()
            return resp.json().get("summary", "")
