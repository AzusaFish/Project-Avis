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
    """GoogleSearchTool: main class container for related behavior in this module."""
    name = "google_search"
    # 模型里发起工具调用时，tool_name 必须与这里完全一致。

    async def call(self, args: dict) -> str:
        # 调用搜索服务并提取摘要字段供模型继续推理。
        """Public API `call` used by other modules or route handlers."""
        query = args.get("query", "")
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(settings.search_api_url, params={"q": query})
            resp.raise_for_status()
            data = resp.json()
            return data.get("summary", "")
