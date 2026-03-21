"""
Module: app/api/routes_playground.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 兼容旧前端的 Playground 接口：文本和麦克风上传。

from __future__ import annotations

import base64
import io
import json
import wave

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel

from app.core.events import Event, EventType

router = APIRouter(prefix="/playground")


class TextReq(BaseModel):
    """TextReq: main class container for related behavior in this module."""
    text: str


@router.post("/text")
async def post_text(req: TextReq, request: Request) -> dict[str, str]:
    # 兼容旧前端文本输入：转发为 USER_TEXT 事件。
    """Public API `post_text` used by other modules or route handlers."""
    bus = request.app.state.bus
    await bus.publish(Event(event_type=EventType.USER_TEXT, source="playground", payload={"text": req.text}))
    return {"status": "queued"}


@router.post("/microphone")
async def post_microphone(
    request: Request,
    metadata: str = Form(default="{}"),
    audio: UploadFile = File(...),
) -> dict[str, object]:
    # 兼容旧前端麦克风上传：统一转换为 PCM16 Base64 事件。
    # C++ 类比：这里做的是“输入适配层”，把多种输入格式归一化。
    """Public API `post_microphone` used by other modules or route handlers."""
    bus = request.app.state.bus
    meta = json.loads(metadata or "{}")

    raw = await audio.read()
    sample_rate = int(meta.get("sample_rate", 16000))
    pcm = raw

    # 前端通常上传 wav，这里统一转成 PCM16 原始帧给 STT。
    if audio.content_type and "wav" in audio.content_type.lower():
        # wave 模块负责从 WAV 容器里抽取原始 PCM 帧。
        with wave.open(io.BytesIO(raw), "rb") as wf:
            sample_rate = wf.getframerate()
            pcm = wf.readframes(wf.getnframes())

    audio_b64 = base64.b64encode(pcm).decode("utf-8")
    await bus.publish(
        Event(
            event_type=EventType.USER_AUDIO_CHUNK,
            source="playground",
            payload={"audio": audio_b64, "sample_rate": sample_rate},
        )
    )
    return {"status": "queued", "sample_rate": sample_rate, "bytes": len(pcm)}
