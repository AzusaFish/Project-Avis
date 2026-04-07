"""
Module: app/tools/wechat_tool.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 微信发送工具：通过 bridge 发送消息。

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import settings


class WeChatSendTool:
    """WeChatSendTool: main class container for related behavior in this module."""

    name = "wechat_send"

    def _normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Normalize common alias fields to bridge contract."""
        to = str(
            args.get("to")
            or args.get("target")
            or args.get("wxid")
            or args.get("receiver")
            or ""
        ).strip()
        text = str(
            args.get("text")
            or args.get("content")
            or args.get("message")
            or ""
        ).strip()

        payload = dict(args)
        if to:
            payload["to"] = to
        if text:
            payload["text"] = text
        return payload

    async def call(self, args: dict) -> str:
        """Public API `call` used by other modules or route handlers."""
        payload = self._normalize_args(args)
        if not str(payload.get("text", "")).strip():
            return "wechat send failed: text is required"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{settings.wechat_bridge_url.rstrip('/')}/send", json=payload)
            resp.raise_for_status()

            try:
                data = resp.json()
            except Exception:
                return "wechat sent"

            msg = data.get("message") or "wechat sent"
            if data.get("ok", True):
                return str(msg)
            return f"wechat send failed: {json.dumps(data, ensure_ascii=False)}"