"""
Module: app/tools/wechat_tool.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 微信发送工具：通过 bridge 发送消息。

from __future__ import annotations

import httpx

from app.core.config import settings


class WeChatSendTool:
    """WeChatSendTool: main class container for related behavior in this module."""
    name = "wechat_send"
    # 入参约定由外部 bridge 决定，常见字段：to/text。

    async def call(self, args: dict) -> str:
        # 透传参数到微信桥服务的发送接口。
        """Public API `call` used by other modules or route handlers."""
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(f"{settings.wechat_bridge_url}/send", json=args)
            resp.raise_for_status()
            return "wechat sent"
