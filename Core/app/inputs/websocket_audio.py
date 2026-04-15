"""
Module: app/inputs/websocket_audio.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 前端音频 WS 输入：接收文本、音频块和打断信号。

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.events import Event, EventType
router = APIRouter()


@router.websocket("/ws/audio")
async def ws_audio(ws: WebSocket) -> None:
    bus = ws.app.state.bus
    await ws.accept()
    try:
        while True:
            packet = await ws.receive_json()
            ptype = packet.get("type")
            if ptype == "interrupt":
                await bus.publish(Event(event_type=EventType.USER_INTERRUPTION, source="frontend", payload={}))
                continue
            if ptype == "text":
                text = packet.get("text", "")
                await bus.publish(
                    Event(event_type=EventType.USER_TEXT, source="frontend", payload={"text": text})
                )
                continue
            audio = packet.get("audio")
            if audio:
                try:
                    sample_rate = int(packet.get("sample_rate", 16000))
                except Exception:
                    sample_rate = 16000
                if sample_rate < 8000 or sample_rate > 96000:
                    sample_rate = 16000
                await bus.publish(
                    Event(
                        event_type=EventType.USER_AUDIO_CHUNK,
                        source="frontend",
                        payload={"audio": audio, "sample_rate": sample_rate},
                    )
                )
    except WebSocketDisconnect:
        return
