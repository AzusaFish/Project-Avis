"""
Module: app/services/frontend_gateway.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 前端网关：维护 WS 连接并广播消息。

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable

from fastapi import WebSocket


class FrontendGateway:
    """FrontendGateway: main class container for related behavior in this module."""
    def __init__(self) -> None:
        # 维护当前在线前端连接集合与并发访问锁。
        """Initialize the object state and cache required dependencies."""
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, subprotocol: str | None = None) -> None:
        # 接受连接并加入广播目标列表。
        # `subprotocol` 可理解为“协议版本名/握手标识”。
        """Public API `connect` used by other modules or route handlers."""
        await ws.accept(subprotocol=subprotocol)
        async with self._lock:
            self._connections.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        # 连接断开后从集合中移除。
        """Public API `disconnect` used by other modules or route handlers."""
        async with self._lock:
            self._connections.discard(ws)

    async def broadcast(self, payload: dict) -> None:
        # 向所有存活连接广播一条 JSON 文本消息。
        # 死连接会在发送失败后延迟清理，避免边遍历边修改集合。
        """Public API `broadcast` used by other modules or route handlers."""
        dead: list[WebSocket] = []
        text = json.dumps(payload, ensure_ascii=False)
        async with self._lock:
            targets: Iterable[WebSocket] = tuple(self._connections)
        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)
