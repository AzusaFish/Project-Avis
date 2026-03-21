"""
Module: app/services/ocr_service.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# OCR 客户端：提交图片并获取识别文本行。

from __future__ import annotations

import httpx

from app.core.config import settings


class OCRService:
    """OCRService: main class container for related behavior in this module."""
    def __init__(self) -> None:
        # 初始化 OCR 服务基地址。
        """Initialize the object state and cache required dependencies."""
        self.base_url = settings.ocr_base_url.rstrip("/")

    async def parse_screen(self, image_base64: str) -> list[str]:
        # 上传截图并返回识别到的文本行数组。
        # 协议约定见 API_CONTRACTS.md: POST /ocr -> {"lines":[...]}。
        """Public API `parse_screen` used by other modules or route handlers."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{self.base_url}/ocr", json={"image": image_base64})
            resp.raise_for_status()
            return resp.json().get("lines", [])
