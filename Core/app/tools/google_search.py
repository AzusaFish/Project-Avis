"""
Module: app/tools/google_search.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# Google 搜索工具：调用搜索 API 获取文本摘要。

from __future__ import annotations

import httpx

from app.core.config import settings


class GoogleSearchTool:
    name = "google_search"

    async def call(self, args: dict) -> str:
        query = args.get("query", "")
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(settings.search_api_url, params={"q": query})
            resp.raise_for_status()
            data = resp.json()
            return data.get("summary", "")
