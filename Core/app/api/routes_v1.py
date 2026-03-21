"""Standardized v1 API routes.

This file exposes a unified `/api/v1/*` interface for external clients.
For beginners:
- Each function decorated by `@router.get/post/...` is one HTTP endpoint.
- Request data is validated by Pydantic models.
- Business work is mostly delegated to EventBus or SQLiteStore.
"""

from __future__ import annotations

import base64
import io
import json
import os
import wave
from urllib.parse import urlparse

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.events import Event, EventType
from app.storage.sqlite_store import SQLiteStore

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


class ApiResp(BaseModel):
    # Unified response envelope used by this v1 route group.
    # `code == 0` means success.
    """ApiResp: main class container for related behavior in this module."""
    code: int = 0
    message: str = "ok"
    data: dict | list | str | int | float | bool | None = None


class TextReq(BaseModel):
    # Text input payload for chat endpoint.
    """TextReq: main class container for related behavior in this module."""
    text: str = Field(min_length=1, max_length=10000)


class InjectTextReq(BaseModel):
    # Debug/control endpoint payload.
    """InjectTextReq: main class container for related behavior in this module."""
    text: str = Field(min_length=1, max_length=10000)


class UpdateMemoryReq(BaseModel):
    # Update a stored memory line by id.
    """UpdateMemoryReq: main class container for related behavior in this module."""
    text: str = Field(min_length=1, max_length=10000)


class ClearMemoryReq(BaseModel):
    # Optional filter when clearing memory records.
    """ClearMemoryReq: main class container for related behavior in this module."""
    role: str | None = Field(default=None, pattern="^(user|assistant)?$")


def ok(data: dict | list | str | int | float | bool | None = None, message: str = "ok") -> dict:
    # Small helper to keep v1 responses structurally consistent.
    """Public API `ok` used by other modules or route handlers."""
    return {"code": 0, "message": message, "data": data}


async def _tcp_probe(url: str, timeout_sec: float = 0.8) -> dict[str, object]:
    # Lightweight TCP-level liveness probe used by /health/deps.
    # This checks if the target host:port is reachable, not business correctness.
    """Internal helper `_tcp_probe` used by this module implementation."""
    import asyncio

    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host=host, port=port), timeout=timeout_sec)
        writer.close()
        await writer.wait_closed()
        return {"ok": True, "host": host, "port": port}
    except Exception as exc:
        return {"ok": False, "host": host, "port": port, "error": str(exc)}


def _get_sqlite(request: Request) -> SQLiteStore:
    # Obtain initialized SQLite dependency from FastAPI app state.
    """Internal helper `_get_sqlite` used by this module implementation."""
    sqlite = getattr(request.app.state, "sqlite", None)
    if sqlite is None:
        raise HTTPException(status_code=500, detail="sqlite store is not ready")
    return sqlite


def _get_bus(request: Request):
    # Obtain initialized EventBus from FastAPI app state.
    """Internal helper `_get_bus` used by this module implementation."""
    bus = getattr(request.app.state, "bus", None)
    if bus is None:
        raise HTTPException(status_code=503, detail="event bus is not ready")
    return bus


@router.get("/health")
async def health() -> dict:
    # Process-level health indicator.
    """Public API `health` used by other modules or route handlers."""
    return ok({"status": "ok"})


@router.get("/health/deps")
async def health_deps() -> dict:
    # Dependency-level health: checks LLM/STT/TTS ports and key paths.
    """Public API `health_deps` used by other modules or route handlers."""
    llm_url = settings.ollama_base_url if settings.llm_provider.lower() == "ollama" else settings.llm_base_url
    checks = {
        "tts": await _tcp_probe(settings.tts_base_url),
        "stt": await _tcp_probe(settings.stt_base_url),
        "llm": await _tcp_probe(llm_url),
        "paths": {
            "gpt_sovits_repo": os.path.exists(settings.gpt_sovits_repo),
            "realtimestt_repo": os.path.exists(settings.realtimestt_repo),
            "sqlite_parent": os.path.exists(os.path.dirname(settings.sqlite_path) or "."),
            "chroma_path": os.path.exists(settings.chroma_path),
        },
    }
    service_ok = all(bool(checks[k].get("ok")) for k in ("tts", "stt", "llm"))
    path_ok = all(bool(v) for v in checks["paths"].values())
    status = "ok" if service_ok and path_ok else "degraded"
    return ok({"status": status, "checks": checks})


@router.post("/chat/text")
async def chat_text(req: TextReq, request: Request) -> dict:
    # Convert HTTP text input into USER_TEXT event for AgentLoop consumption.
    """Public API `chat_text` used by other modules or route handlers."""
    bus = _get_bus(request)
    await bus.publish(Event(event_type=EventType.USER_TEXT, source="api_v1", payload={"text": req.text.strip()}))
    return ok({"queued": True})


@router.post("/chat/microphone")
async def chat_microphone(
    request: Request,
    metadata: str = Form(default="{}"),
    audio: UploadFile = File(...),
) -> dict:
    # Compatibility endpoint: accepts uploaded audio and forwards as USER_AUDIO_CHUNK.
    # If WAV is uploaded, decode container and extract raw PCM frames.
    """Public API `chat_microphone` used by other modules or route handlers."""
    bus = _get_bus(request)
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
            source="api_v1",
            payload={"audio": audio_b64, "sample_rate": sample_rate},
        )
    )
    return ok({"queued": True, "sample_rate": sample_rate, "bytes": len(pcm)})


@router.post("/control/inject-text")
async def control_inject_text(req: InjectTextReq, request: Request) -> dict:
    # Manual injection endpoint used for testing the end-to-end pipeline.
    """Public API `control_inject_text` used by other modules or route handlers."""
    bus = _get_bus(request)
    await bus.publish(Event(event_type=EventType.USER_TEXT, source="api_v1", payload={"text": req.text.strip()}))
    return ok({"queued": True})


@router.get("/control/queue-size")
async def control_queue_size(request: Request) -> dict:
    # Observe event queue pressure for runtime diagnostics.
    """Public API `control_queue_size` used by other modules or route handlers."""
    bus = _get_bus(request)
    return ok({"queue_size": bus.qsize()})


@router.get("/memory/dialogues")
async def list_memory(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    role: str | None = Query(default=None, pattern="^(user|assistant)$"),
    q: str | None = Query(default=None, max_length=200),
) -> dict:
    # Paginated dialogue query with optional role/keyword filters.
    """Public API `list_memory` used by other modules or route handlers."""
    sqlite = _get_sqlite(request)
    rows = await sqlite.list_dialogue(limit=limit, offset=offset, role=role, keyword=q)
    total = await sqlite.count_dialogue(role=role, keyword=q)
    return ok({"total": total, "limit": limit, "offset": offset, "items": rows})


@router.patch("/memory/dialogues/{memory_id}")
async def update_memory(memory_id: int, req: UpdateMemoryReq, request: Request) -> dict:
    # Update one memory row by id.
    """Public API `update_memory` used by other modules or route handlers."""
    sqlite = _get_sqlite(request)
    ok_flag = await sqlite.update_dialogue_text(memory_id, req.text.strip())
    if not ok_flag:
        raise HTTPException(status_code=404, detail=f"memory id not found: {memory_id}")
    return ok({"updated": True, "id": memory_id})


@router.delete("/memory/dialogues/{memory_id}")
async def delete_memory(memory_id: int, request: Request) -> dict:
    # Delete one memory row by id.
    """Public API `delete_memory` used by other modules or route handlers."""
    sqlite = _get_sqlite(request)
    ok_flag = await sqlite.delete_dialogue(memory_id)
    if not ok_flag:
        raise HTTPException(status_code=404, detail=f"memory id not found: {memory_id}")
    return ok({"deleted": True, "id": memory_id})


@router.post("/memory/dialogues/clear")
async def clear_memory(req: ClearMemoryReq, request: Request) -> dict:
    # Bulk clear dialogue rows (optionally filtered by role).
    """Public API `clear_memory` used by other modules or route handlers."""
    sqlite = _get_sqlite(request)
    deleted = await sqlite.clear_dialogue(role=req.role)
    return ok({"deleted": deleted, "role": req.role})
