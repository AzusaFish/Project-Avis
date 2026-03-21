"""
Module: app/inputs/scheduler.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 主动话题定时器：长时间静默后触发一次发话事件。

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from app.core.bus import EventBus
from app.core.config import settings
from app.core.events import Event, EventType


async def proactive_scheduler(bus: EventBus) -> None:
    # 轮询静默时长，到达阈值后投递主动发话事件。
    # 注意：当前实现只在内部更新时间，不感知真实用户活跃事件。
    # 未来可通过订阅 USER_TEXT/USER_AUDIO_CHUNK 来刷新 last_active。
    """Public API `proactive_scheduler` used by other modules or route handlers."""
    last_active = datetime.utcnow()
    while True:
        await asyncio.sleep(1)
        if datetime.utcnow() - last_active >= timedelta(seconds=settings.proactive_silence_sec):
            await bus.publish(Event(event_type=EventType.SCHEDULE_TICK, source="scheduler", payload={}))
            last_active = datetime.utcnow()
