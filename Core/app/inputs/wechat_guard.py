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
from typing import Any

import httpx

from app.core.bus import EventBus
from app.core.config import settings
from app.core.events import Event, EventType

logger = logging.getLogger(__name__)


def _extract_messages(payload: Any) -> list[dict[str, Any]]:
    """Extract message list from multiple bridge response shapes."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("messages", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]

    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("messages", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]

    return []


def _normalize_incoming(msg: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize raw bridge message to Core event payload."""
    text = str(
        msg.get("text")
        or msg.get("content")
        or msg.get("message")
        or msg.get("msg")
        or ""
    ).strip()
    if not text:
        return None

    sender = str(
        msg.get("from")
        or msg.get("sender")
        or msg.get("talker")
        or msg.get("wxid")
        or ""
    ).strip()
    message_id = str(msg.get("id") or msg.get("msg_id") or "").strip()

    return {
        "text": text,
        "from": sender,
        "message_id": message_id,
        "raw": msg,
    }


async def wechat_watcher(bus: EventBus) -> None:
    """Public API `wechat_watcher` used by other modules or route handlers."""
    poll_url = f"{settings.wechat_bridge_url.rstrip('/')}/poll"
    error_streak = 0

    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                resp = await client.get(poll_url)
                resp.raise_for_status()

                normalized = []
                for item in _extract_messages(resp.json()):
                    mapped = _normalize_incoming(item)
                    if mapped is not None:
                        normalized.append(mapped)

                for msg in normalized:
                    await bus.publish(
                        Event(
                            event_type=EventType.WECHAT_MESSAGE,
                            source="wechat",
                            payload={"text": msg["text"], "raw": msg},
                        )
                    )

                error_streak = 0
                await asyncio.sleep(0.4)
            except Exception as exc:
                error_streak += 1
                if error_streak % 10 == 1:
                    logger.warning("wechat watcher idle/error: %s", exc)
                await asyncio.sleep(min(3.0, 0.4 + error_streak * 0.2))