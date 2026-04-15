"""
Module: app/tools/sts_tool.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 杀戮尖塔工具：向游戏 bridge 下发动作。

from __future__ import annotations

import httpx

from app.core.config import settings


class SlayTheSpireTool:
    name = "sts_action"

    async def call(self, args: dict) -> str:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(f"{settings.sts_bridge_url}/action", json=args)
            resp.raise_for_status()
            return "sts action dispatched"
