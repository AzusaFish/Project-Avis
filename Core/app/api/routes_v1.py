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
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.events import Event, EventType
from app.core.time_utils import now_payload
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
    role: str | None = Field(default=None, pattern="^(user|assistant|system|tool)?$")


class UpdateConfigReq(BaseModel):
    # Batch config update payload, key-value style.
    """UpdateConfigReq: main class container for related behavior in this module."""
    items: dict[str, Any] = Field(default_factory=dict)


def ok(data: dict | list | str | int | float | bool | None = None, message: str = "ok") -> dict:
    # Small helper to keep v1 responses structurally consistent.
    """Public API `ok` used by other modules or route handlers."""
    return {"code": 0, "message": message, "data": data}


def _project_config_path() -> Path:
    """Resolve project root config.yaml path."""
    return Path(__file__).resolve().parents[3] / "config.yaml"


def _format_config_value(value: Any) -> str:
    """Serialize primitive values into flat config.yaml style."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _read_flat_config() -> dict[str, str]:
    """Read flat key-value config lines from project config.yaml."""
    path = _project_config_path()
    if not path.exists():
        return {}

    data: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        data[key] = value
    return data


def _apply_flat_config_updates(updates: dict[str, Any]) -> dict[str, object]:
    """Update existing config keys in-place and append new keys at the end."""
    path = _project_config_path()
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"config file not found: {path}")

    raw_lines = path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    pending = {k: _format_config_value(v) for k, v in updates.items() if str(k).strip()}

    for raw in raw_lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in line:
            output.append(line)
            continue

        left, right = line.split(":", 1)
        key = left.strip()
        if key not in pending:
            output.append(line)
            continue

        comment = ""
        if " #" in right:
            comment = " #" + right.split(" #", 1)[1].strip()
        output.append(f"{key}: {pending[key]}{comment}")
        pending.pop(key, None)

    if pending:
        if output and output[-1].strip() != "":
            output.append("")
        output.append("# Appended by /api/v1/config update")
        for key in sorted(pending.keys()):
            output.append(f"{key}: {pending[key]}")

    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    for key, value in updates.items():
        os.environ[str(key)] = _format_config_value(value)

    return {
        "path": str(path),
        "updated": sorted(str(k) for k in updates.keys()),
        "restart_recommended": True,
    }


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


def _get_agent(request: Request):
    """Internal helper `_get_agent` used by this module implementation."""
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(status_code=503, detail="agent is not ready")
    return agent


def _get_reflector(request: Request):
    """Internal helper `_get_reflector` used by this module implementation."""
    reflector = getattr(request.app.state, "reflector", None)
    if reflector is None:
        raise HTTPException(status_code=503, detail="memory reflector is not ready")
    return reflector


@router.get("/health")
async def health() -> dict:
    # Process-level health indicator.
    """Public API `health` used by other modules or route handlers."""
    return ok({"status": "ok"})


@router.get("/time/now")
async def time_now() -> dict:
    # Return current local time in multiple formats.
    """Public API `time_now` used by other modules or route handlers."""
    return ok(now_payload())


@router.get("/health/deps")
async def health_deps() -> dict:
    # Dependency-level health: checks LLM/STT/TTS ports and key paths.
    """Public API `health_deps` used by other modules or route handlers."""
    provider = settings.llm_provider.lower().strip()
    if provider == "ollama":
        llm_url = settings.ollama_base_url
    elif provider in {"gguf", "llama_cpp"}:
        llm_url = settings.gguf_base_url
    else:
        llm_url = settings.llm_base_url
    path_checks = {
        "realtimestt_repo": os.path.exists(settings.realtimestt_repo),
        "sqlite_parent": os.path.exists(os.path.dirname(settings.sqlite_path) or "."),
        "chroma_path": os.path.exists(settings.chroma_path),
    }
    if settings.tts_provider.lower().strip() == "gpt_sovits":
        path_checks["gpt_sovits_repo"] = os.path.exists(settings.gpt_sovits_repo)
    else:
        path_checks["kokoro_repo"] = os.path.exists(settings.kokoro_repo)

    checks = {
        "tts": await _tcp_probe(settings.tts_base_url),
        "stt": await _tcp_probe(settings.stt_base_url),
        "llm": await _tcp_probe(llm_url),
        "paths": path_checks,
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
    role: str | None = Query(default=None, pattern="^(user|assistant|system|tool)$"),
    q: str | None = Query(default=None, max_length=200),
    min_importance: float | None = Query(default=None, ge=0.0),
    processed_flag: int | None = Query(default=None, ge=0, le=1),
    sort_by: str = Query(default="time", pattern="^(time|importance)$"),
) -> dict:
    # Paginated dialogue query with optional role/keyword filters.
    """Public API `list_memory` used by other modules or route handlers."""
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


@router.get("/config")
async def get_config() -> dict:
    # Read current project config file for visual config editor.
    """Public API `get_config` used by other modules or route handlers."""
    data = _read_flat_config()
    return ok({"path": str(_project_config_path()), "items": data})


@router.patch("/config")
async def patch_config(req: UpdateConfigReq) -> dict:
    # Apply key-value updates to project config.yaml.
    """Public API `patch_config` used by other modules or route handlers."""
    if not req.items:
        return ok({"updated": [], "restart_recommended": False}, message="no changes")
    result = _apply_flat_config_updates(req.items)
    return ok(result)


@router.get("/debug/snapshot")
async def debug_snapshot(request: Request) -> dict:
    # Aggregate runtime status for debug dashboard page.
    """Public API `debug_snapshot` used by other modules or route handlers."""
    bus = _get_bus(request)
    sqlite = _get_sqlite(request)
    agent = _get_agent(request)
    reflector = _get_reflector(request)
    frontend = getattr(request.app.state, "frontend", None)

    provider = settings.llm_provider.lower().strip()
    if provider == "ollama":
        llm_url = settings.ollama_base_url
    elif provider in {"gguf", "llama_cpp"}:
        llm_url = settings.gguf_base_url
    else:
        llm_url = settings.llm_base_url

    deps = {
        "tts": await _tcp_probe(settings.tts_base_url),
        "stt": await _tcp_probe(settings.stt_base_url),
        "llm": await _tcp_probe(llm_url),
    }
    role_counts = {
        "user": await sqlite.count_dialogue(role="user"),
        "assistant": await sqlite.count_dialogue(role="assistant"),
        "system": await sqlite.count_dialogue(role="system"),
        "tool": await sqlite.count_dialogue(role="tool"),
    }
    pending_scoring = await sqlite.count_short_term_by_processed(processed_flag=0)
    processed_scoring = await sqlite.count_short_term_by_processed(processed_flag=1)
    llm_io = agent.get_llm_debug_snapshot() if hasattr(agent, "get_llm_debug_snapshot") else {}
    score_debug = reflector.get_score_debug_state() if hasattr(reflector, "get_score_debug_state") else {}

    ws_clients = 0
    if frontend is not None and hasattr(frontend, "_connections"):
        try:
            ws_clients = len(getattr(frontend, "_connections"))
        except Exception:
            ws_clients = 0

    return ok(
        {
            "queue_size": bus.qsize(),
            "ws_clients": ws_clients,
            "deps": deps,
            "llm_provider": provider,
            "llm_model": settings.gguf_model if provider in {"gguf", "llama_cpp"} else settings.llm_model,
            "tts_provider": settings.tts_provider,
            "memory_count": role_counts,
            "memory_scoring": {
                "enabled": bool(getattr(settings, "memory_llm_scoring_enabled", True)),
                "pending": pending_scoring,
                "processed": processed_scoring,
                "trigger_count": int(getattr(settings, "memory_llm_score_trigger_count", 24)),
                "batch_size": int(getattr(settings, "memory_llm_score_batch_size", 24)),
                "worker": score_debug,
            },
            "llm_io_summary": {
                "seq": int(llm_io.get("seq", 0) or 0),
                "last_request_ts": (llm_io.get("last_request") or {}).get("ts", ""),
                "last_response_ts": (llm_io.get("last_response") or {}).get("ts", ""),
                "has_request": bool((llm_io.get("last_request") or {}).get("messages")),
                "has_response": bool((llm_io.get("last_response") or {}).get("raw_output")),
            },
            "config_path": str(_project_config_path()),
        }
    )


@router.get("/debug/llm-io")
async def debug_llm_io(request: Request) -> dict:
    # Return latest full LLM request/response payloads for deep debugging.
    """Public API `debug_llm_io` used by other modules or route handlers."""
    agent = _get_agent(request)
    payload = agent.get_llm_debug_snapshot() if hasattr(agent, "get_llm_debug_snapshot") else {}
    return ok(
        {
            "provider": settings.llm_provider.lower().strip(),
            "model": settings.gguf_model
            if settings.llm_provider.lower().strip() in {"gguf", "llama_cpp"}
            else settings.llm_model,
            "llm_debug_to_frontend": bool(settings.llm_debug_to_frontend),
            "payload": payload,
        }
    )


@router.get("/debug/memory-mechanism")
async def debug_memory_mechanism(request: Request) -> dict:
    # Return memory pipeline internals: scoring threshold, pending batches and recent rows.
    """Public API `debug_memory_mechanism` used by other modules or route handlers."""
    sqlite = _get_sqlite(request)
    reflector = _get_reflector(request)

    pending = await sqlite.count_short_term_by_processed(processed_flag=0)
    processed = await sqlite.count_short_term_by_processed(processed_flag=1)
    pending_items = await sqlite.list_dialogue(limit=20, offset=0, processed_flag=0, sort_by="time")
    processed_items = await sqlite.list_dialogue(limit=20, offset=0, processed_flag=1, sort_by="time")

    return ok(
        {
            "llm_scoring": {
                "enabled": bool(getattr(settings, "memory_llm_scoring_enabled", True)),
                "trigger_count": int(getattr(settings, "memory_llm_score_trigger_count", 24)),
                "batch_size": int(getattr(settings, "memory_llm_score_batch_size", 24)),
                "max_text": int(getattr(settings, "memory_llm_score_max_text", 360)),
                "pending_count": pending,
                "processed_count": processed,
                "worker": reflector.get_score_debug_state()
                if hasattr(reflector, "get_score_debug_state")
                else {},
            },
            "decay_policy": {
                "base_lambda": float(settings.memory_decay_lambda_base),
                "negative": {
                    "multiplier": float(settings.memory_decay_negative_lambda_multiplier),
                    "threshold": float(settings.memory_decay_negative_emotion_threshold),
                },
                "positive": {
                    "multiplier": float(settings.memory_decay_positive_lambda_multiplier),
                    "threshold": float(settings.memory_decay_positive_emotion_threshold),
                },
            },
            "hybrid_ranking": {
                "semantic_weight": float(settings.memory_hybrid_semantic_weight),
                "recency_weight": float(settings.memory_hybrid_recency_weight),
                "importance_weight": float(settings.memory_hybrid_importance_weight),
                "semantic_pool": int(settings.memory_hybrid_semantic_pool),
            },
            "recent_pending": pending_items,
            "recent_processed": processed_items,
        }
    )
