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
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, subprotocol: str | None = None) -> None:
        await ws.accept(subprotocol=subprotocol)
        async with self._lock:
            self._connections.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)

    async def broadcast(self, payload: dict) -> None:
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
