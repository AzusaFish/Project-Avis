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
    def __init__(self) -> None:
        self.base_url = settings.ocr_base_url.rstrip("/")

    async def parse_screen(self, image_base64: str) -> list[str]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{self.base_url}/ocr", json={"image": image_base64})
            resp.raise_for_status()
            return resp.json().get("lines", [])
