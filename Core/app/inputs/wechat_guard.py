"""
Module: app/inputs/wechat_guard.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 微信输入监听：轮询 bridge 并转为系统事件。

from __future__ import annotations

import asyncio
import logging

import httpx

from app.core.bus import EventBus
from app.core.config import settings
from app.core.events import Event, EventType

logger = logging.getLogger(__name__)


async def wechat_watcher(bus: EventBus) -> None:
    # 轮询微信桥接层消息并投递到总线。
    # 这是“外部系统输入适配器”：把微信消息转成内部统一事件。
    # 协议约定：桥接服务返回 {"messages":[{...}, ...]}。
    """Public API `wechat_watcher` used by other modules or route handlers."""
    async with httpx.AsyncClient(timeout=8.0) as client:
        while True:
            try:
                resp = await client.get(f"{settings.wechat_bridge_url}/poll")
                resp.raise_for_status()
                messages = resp.json().get("messages", [])
                for msg in messages:
                    # 这里保留 raw 原始字段，后续若要做联系人路由可直接复用。
                    await bus.publish(
                        Event(
                            event_type=EventType.WECHAT_MESSAGE,
                            source="wechat",
                            payload={"text": msg.get("text", ""), "raw": msg},
                        )
                    )
            except Exception as exc:
                # 这里只打 debug，不让轮询器因网络抖动退出。
                logger.debug("wechat watcher idle/error: %s", exc)
            # 轮询间隔 0.5s，兼顾实时性与 CPU/网络开销。
            await asyncio.sleep(0.5)
