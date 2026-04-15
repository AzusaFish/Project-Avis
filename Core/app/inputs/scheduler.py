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
from threading import Lock

from app.core.bus import EventBus
from app.core.config import settings
from app.core.events import Event, EventType


_last_active = datetime.utcnow()
_engagement = 0.6
_active_lock = Lock()


def _clamp(value: float, lo: float, hi: float) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def mark_activity(kind: str = "generic", text: str = "") -> None:
    global _last_active, _engagement
    with _active_lock:
        _last_active = datetime.utcnow()
        if kind in {"user_text", "wechat", "game"}:
            boost = 0.10 if len(text.strip()) >= 8 else 0.06
            _engagement = _clamp(_engagement + boost, 0.05, 1.0)
        elif kind in {"user_audio", "user_interruption"}:
            _engagement = _clamp(_engagement + 0.08, 0.05, 1.0)
        elif kind == "schedule_tick":
            _engagement = _clamp(_engagement - 0.08, 0.05, 1.0)
        elif kind == "assistant_response":
            _engagement = _clamp(_engagement - 0.01, 0.05, 1.0)


def _read_last_active() -> datetime:
    with _active_lock:
        return _last_active


def _read_engagement() -> float:
    with _active_lock:
        return _engagement


def _silence_multiplier(engagement: float) -> float:
    if engagement >= 0.8:
        return 0.7
    if engagement >= 0.55:
        return 1.0
    if engagement >= 0.35:
        return 1.8
    return 3.6


async def proactive_scheduler(bus: EventBus) -> None:
    while True:
        await asyncio.sleep(1)
        engagement = _read_engagement()
        dynamic_silence = max(
            30,
            int(settings.proactive_silence_sec * _silence_multiplier(engagement)),
        )
        if datetime.utcnow() - _read_last_active() >= timedelta(seconds=dynamic_silence):
            can_start_topic = engagement >= 0.35
            prefer_tool = engagement < 0.55
            await bus.publish(
                Event(
                    event_type=EventType.SCHEDULE_TICK,
                    source="scheduler",
                    payload={
                        "engagement": round(engagement, 3),
                        "dynamic_silence_sec": dynamic_silence,
                        "can_start_topic": can_start_topic,
                        "prefer_tool": prefer_tool,
                        "allow_skip": True,
                    },
                )
            )
            mark_activity(kind="schedule_tick")
