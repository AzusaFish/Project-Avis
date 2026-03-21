"""
Module: app/api/routes_integrations.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 依赖体检接口：检查本地路径与外部服务连通性。

from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import APIRouter, Request

from app.core.config import settings

router = APIRouter(prefix="/integrations")


async def _check_http(url: str) -> dict[str, object]:
    # 对目标 URL 做轻量探活，返回状态码或错误信息。
    # 这里把 4xx 也视为“服务在线”，因为目标是判活，不是业务正确性。
    """Internal helper `_check_http` used by this module implementation."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
            return {"ok": 200 <= resp.status_code < 500, "status": resp.status_code}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/status")
async def deps(request: Request) -> dict[str, object]:
    # 汇总本地路径、LLM 模型与外部服务连通性。
    # 汇总输出：便于前端或脚本快速判断“哪块没启动/没配置好”。
    """Public API `deps` used by other modules or route handlers."""
    llm = request.app.state.llm

    paths = {
        "ollama_models_dir": settings.ollama_models_dir,
        "gpt_sovits_repo": settings.gpt_sovits_repo,
        "kokoro_repo": settings.kokoro_repo,
        "realtimestt_repo": settings.realtimestt_repo,
        "reference_core_repo": settings.reference_core_repo,
    }
    path_state = {
        key: {
            "path": value,
            "exists": Path(value).exists(),
        }
        for key, value in paths.items()
    }

    llm_state = await llm.check_ready()

    tts_url = settings.kokoro_base_url if settings.tts_provider.lower().strip() == "kokoro" else settings.gpt_sovits_base_url
    tts_state = await _check_http(f"{tts_url.rstrip('/')}/")
    stt_state = await _check_http(f"{settings.stt_base_url.rstrip('/')}/")

    return {
        "llm": llm_state,
        "paths": path_state,
        "services": {
            "tts_provider": settings.tts_provider,
            "tts_base_url": tts_url,
            "tts_probe": tts_state,
            "stt_base_url": settings.stt_base_url,
            "stt_probe": stt_state,
        },
    }
