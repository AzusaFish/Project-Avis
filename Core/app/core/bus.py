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
    """EventBus: main class container for related behavior in this module."""
    def __init__(self, maxsize: int = 2048) -> None:
        # 单队列实现：先保证简单可维护，后续可扩展多优先级队列。
        # C++ 类比：这里的 asyncio.Queue ~= 线程安全阻塞队列（生产者-消费者模型）。
        # maxsize 达到后，publish 会等待；这是天然背压机制。
        """Initialize the object state and cache required dependencies."""
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)

    async def publish(self, event: Event) -> None:
        # 发布一条事件到队列尾部。
        # 如果队列满，这里会挂起等待消费侧腾出空间。
        """Public API `publish` used by other modules or route handlers."""
        await self._queue.put(event)

    async def consume(self) -> Event:
        # 消费下一条事件（无事件时阻塞等待）。
        # `await` 在等待时会让出执行权，其他协程可继续运行。
        # 当前是 FIFO 顺序，先到先处理。
        """Public API `consume` used by other modules or route handlers."""
        return await self._queue.get()

    def qsize(self) -> int:
        # 返回当前队列长度，便于观测背压。
        # 典型用途：暴露 `/control/queue_size` 观察系统是否堆积。
        """Public API `qsize` used by other modules or route handlers."""
        return self._queue.qsize()
