"""
Module: app/inputs/sts_bridge.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 杀戮尖塔状态监听：轮询游戏 bridge 并投递事件。

from __future__ import annotations

import asyncio
import logging

import httpx

from app.core.bus import EventBus
from app.core.config import settings
from app.core.events import Event, EventType

logger = logging.getLogger(__name__)


async def sts_state_watcher(bus: EventBus) -> None:
    async with httpx.AsyncClient(timeout=8.0) as client:
        while True:
            try:
                resp = await client.get(f"{settings.sts_bridge_url}/state")
                resp.raise_for_status()
                state = resp.json()
                if state:
                    await bus.publish(
                        Event(event_type=EventType.GAME_STATE, source="sts", payload={"text": str(state), "raw": state})
                    )
            except Exception as exc:
                logger.debug("sts watcher idle/error: %s", exc)
            await asyncio.sleep(0.4)
