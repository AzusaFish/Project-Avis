"""
Module: app/api/routes_frontend_ws.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# Live2DProtocol 兼容 WS：用于桌面前端接入。

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.events import Event, EventType
router = APIRouter()


@router.websocket("/ws/live2d")
async def ws_live2d(ws: WebSocket) -> None:
    bus = ws.app.state.bus
    gateway = ws.app.state.frontend
    await gateway.connect(ws, subprotocol="Live2DProtocol")
    try:
        while True:
            text = await ws.receive_text()
            try:
                msg = json.loads(text)
            except Exception:
                continue

            action = msg.get("action")
            data = msg.get("data") or {}
            if action in {"inject_text", "show_user_text_input"}:
                user_text = str(data.get("text", "")).strip()
                if user_text:
                    await bus.publish(
                        Event(
                            event_type=EventType.USER_TEXT,
                            source="frontend_ws",
                            payload={"text": user_text},
                        )
                    )
            elif action == "think":
                await bus.publish(
                    Event(
                        event_type=EventType.USER_TEXT,
                        source="frontend_ws",
                        payload={
                            "text": "[SYSTEM: Continue]",
                            "silent": True,
                            "system_inject": True,
                        },
                    )
                )
            elif action == "ask":
                continue
    except WebSocketDisconnect:
        await gateway.disconnect(ws)
