"""
Module: app/api/routes_memory.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 记忆管理接口：支持分页查看、修改、删除、清空对话记忆。

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.storage.sqlite_store import SQLiteStore

router = APIRouter(prefix="/memory")


class UpdateMemoryReq(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


class ClearMemoryReq(BaseModel):
    role: str | None = Field(default=None, pattern="^(user|assistant|system|tool)?$")


def _get_sqlite(request: Request) -> SQLiteStore:
    sqlite = getattr(request.app.state, "sqlite", None)
    if sqlite is None:
        raise HTTPException(status_code=500, detail="sqlite store is not ready")
    return sqlite


@router.get("/list")
async def list_memory(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    role: str | None = Query(default=None, pattern="^(user|assistant|system|tool)$"),
    q: str | None = Query(default=None, max_length=200),
    min_importance: float | None = Query(default=None, ge=0.0),
    processed_flag: int | None = Query(default=None, ge=0, le=1),
    sort_by: str = Query(default="time", pattern="^(time|importance)$"),
) -> dict[str, object]:
    sqlite = _get_sqlite(request)
    rows = await sqlite.list_dialogue(
        limit=limit,
        offset=offset,
        role=role,
        keyword=q,
        min_importance=min_importance,
        processed_flag=processed_flag,
        sort_by=sort_by,
    )
    total = await sqlite.count_dialogue(
        role=role,
        keyword=q,
        min_importance=min_importance,
        processed_flag=processed_flag,
    )
    return {"total": total, "limit": limit, "offset": offset, "items": rows}


@router.patch("/{memory_id}")
async def update_memory(memory_id: int, req: UpdateMemoryReq, request: Request) -> dict[str, object]:
    sqlite = _get_sqlite(request)
    ok = await sqlite.update_dialogue_text(memory_id, req.text.strip())
    if not ok:
        raise HTTPException(status_code=404, detail=f"memory id not found: {memory_id}")
    return {"ok": True, "id": memory_id}


@router.delete("/{memory_id}")
async def delete_memory(memory_id: int, request: Request) -> dict[str, object]:
    sqlite = _get_sqlite(request)
    ok = await sqlite.delete_dialogue(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"memory id not found: {memory_id}")
    return {"ok": True, "id": memory_id}


@router.post("/clear")
async def clear_memory(req: ClearMemoryReq, request: Request) -> dict[str, object]:
    sqlite = _get_sqlite(request)
    deleted = await sqlite.clear_dialogue(role=req.role)
    return {"ok": True, "deleted": deleted, "role": req.role}
