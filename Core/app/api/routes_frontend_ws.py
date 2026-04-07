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
    # 处理前端上行消息，并转成系统事件。
    # WebSocket 是长连接；while True 持续收包直到断开。
    """Public API `ws_live2d` used by other modules or route handlers."""
    bus = ws.app.state.bus
    gateway = ws.app.state.frontend
    # 约定子协议，方便旧前端零改造接入。
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
                # 旧前端的两个 action 都映射成 USER_TEXT。
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
                # think 动作走静默续写，推动下一轮 LLM 推理。
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
                # ask 动作表示前端进入等待用户输入态，这里不自动注入任何文本。
                continue
    except WebSocketDisconnect:
        await gateway.disconnect(ws)
