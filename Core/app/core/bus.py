"""
Module: app/core/bus.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 异步事件总线：系统内模块通过队列解耦通信。

import asyncio

from app.core.events import Event


class EventBus:
    # Initialize the internal event queue with a max size.
    def __init__(self, maxsize: int = 2048) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)

    # Publish an event onto the queue.
    async def publish(self, event: Event) -> None:
        await self._queue.put(event)

    # Consume the next event from the queue.
    async def consume(self) -> Event:
        return await self._queue.get()

    # Return current queue size.
    def qsize(self) -> int:
        return self._queue.qsize()
