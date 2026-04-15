"""
Module: app/api/routes_control.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 控制接口：手动注入文本、查看队列状态。

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.events import Event, EventType


class InjectTextReq(BaseModel):
    text: str


router = APIRouter(prefix="/control")


@router.post("/inject_text")
async def inject_text(req: InjectTextReq, request: Request) -> dict[str, str]:
    bus = request.app.state.bus
    await bus.publish(Event(event_type=EventType.USER_TEXT, source="api", payload={"text": req.text}))
    return {"status": "queued"}


@router.get("/queue_size")
async def queue_size(request: Request) -> dict[str, int]:
    bus = request.app.state.bus
    return {"queue_size": bus.qsize()}
