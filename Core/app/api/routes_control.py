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
    # Pydantic 模型：自动做 JSON 反序列化与字段校验。
    """InjectTextReq: main class container for related behavior in this module."""
    text: str


router = APIRouter(prefix="/control")


@router.post("/inject_text")
async def inject_text(req: InjectTextReq, request: Request) -> dict[str, str]:
    # 手动注入一条用户文本事件，便于调试主循环。
    # `request.app.state` 是 FastAPI 的“全局运行时对象存储区”。
    """Public API `inject_text` used by other modules or route handlers."""
    bus = request.app.state.bus
    await bus.publish(Event(event_type=EventType.USER_TEXT, source="api", payload={"text": req.text}))
    return {"status": "queued"}


@router.get("/queue_size")
async def queue_size(request: Request) -> dict[str, int]:
    # 返回当前事件队列长度，用于观察系统负载。
    """Public API `queue_size` used by other modules or route handlers."""
    bus = request.app.state.bus
    return {"queue_size": bus.qsize()}
