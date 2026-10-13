"""
Module: app/core/bus.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 异步事件总线：系统内模块通过队列解耦通信。

import asyncio

from app.core.events import Event, EventType


class EventBus:
    # Initialize the internal event queue with a max size.
    def __init__(self, maxsize: int = 2048) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._audio_queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max(1, min(maxsize, 256)))
        self._interrupt_queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max(1, min(maxsize, 64)))
        self._input_available = asyncio.Event()

    # Publish an event onto the queue.
    async def publish(self, event: Event) -> None:
        if event.event_type == EventType.USER_INTERRUPTION:
            if self._interrupt_queue.full():
                self._interrupt_queue.get_nowait()
            self._interrupt_queue.put_nowait(event)
            self._input_available.set()
        elif event.event_type == EventType.USER_AUDIO_CHUNK:
            if self._audio_queue.full():
                self._audio_queue.get_nowait()
            self._audio_queue.put_nowait(event)
            self._input_available.set()
        else:
            await self._queue.put(event)

    # Consume the next event from the queue.
    async def consume(self) -> Event:
        return await self._queue.get()

    async def consume_input(self) -> Event:
        while True:
            if not self._interrupt_queue.empty():
                return self._interrupt_queue.get_nowait()
            if not self._audio_queue.empty():
                return self._audio_queue.get_nowait()
            self._input_available.clear()
            await self._input_available.wait()

    # Return current queue size.
    def qsize(self) -> int:
        return self._queue.qsize() + self._audio_queue.qsize() + self._interrupt_queue.qsize()
