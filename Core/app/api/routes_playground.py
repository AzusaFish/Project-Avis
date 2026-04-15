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
    text: str


@router.post("/text")
async def post_text(req: TextReq, request: Request) -> dict[str, str]:
    bus = request.app.state.bus
    await bus.publish(Event(event_type=EventType.USER_TEXT, source="playground", payload={"text": req.text}))
    return {"status": "queued"}


@router.post("/microphone")
async def post_microphone(
    request: Request,
    metadata: str = Form(default="{}"),
    audio: UploadFile = File(...),
) -> dict[str, object]:
    bus = request.app.state.bus
    meta = json.loads(metadata or "{}")

    raw = await audio.read()
    sample_rate = int(meta.get("sample_rate", 16000))
    pcm = raw

    if audio.content_type and "wav" in audio.content_type.lower():
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
