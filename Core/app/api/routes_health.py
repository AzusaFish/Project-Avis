"""
Module: app/api/routes_health.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 基础健康检查接口。

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

from fastapi import APIRouter

from app.core.config import settings


router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    # 返回进程级健康状态。
    # 这是最基础探针：只代表“Core 进程活着”，不代表依赖都正常。
    """Public API `health` used by other modules or route handlers."""
    return {"status": "ok"}


async def _tcp_probe(url: str, timeout_sec: float = 0.6) -> dict[str, str | bool | int]:
    """Internal helper `_tcp_probe` used by this module implementation."""
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        conn = asyncio.open_connection(host=host, port=port)
        reader, writer = await asyncio.wait_for(conn, timeout=timeout_sec)
        writer.close()
        await writer.wait_closed()
        return {"ok": True, "host": host, "port": port}
    except Exception as exc:
        return {"ok": False, "host": host, "port": port, "error": str(exc)}


@router.get("/health/deps")
async def health_deps() -> dict:
    # 依赖可用性检查：服务端口连通 + 关键本地目录存在性。
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

    service_ok = all(bool(checks[name].get("ok")) for name in ("tts", "stt", "llm"))
    path_ok = all(bool(v) for v in checks["paths"].values())
    status = "ok" if service_ok and path_ok else "degraded"

    return {"status": status, "checks": checks}
