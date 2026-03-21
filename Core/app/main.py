"""
Module: app/main.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# FastAPI 入口：挂载 HTTP/WS 路由并管理生命周期。
# 给 C++ 读者的类比：
# - FastAPI 的 `app` 类似一个“HTTP 服务器对象”
# - `include_router(...)` 类似“注册一组 URL 回调函数”
# - `lifespan` 类似“进程启动/退出钩子（init/deinit）”

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_control import router as control_router
from app.api.routes_frontend_ws import router as frontend_ws_router
from app.api.routes_health import router as health_router
from app.api.routes_integrations import router as integration_router
from app.api.routes_memory import router as memory_router
from app.api.routes_playground import router as playground_router
from app.api.routes_v1 import router as v1_router
from app.core.lifecycle import shutdown, startup
from app.core.logger import setup_logging
from app.inputs.websocket_audio import router as audio_ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # FastAPI 生命周期钩子：统一管理启动与关闭流程。
    # 启动阶段：初始化日志与核心模块。
    # 注意：`async def` + `await` 表示协程，不会阻塞整个事件循环线程。
    """Public API `lifespan` used by other modules or route handlers."""
    setup_logging()
    await startup(app)
    try:
        yield
    finally:
        await shutdown(app)


app = FastAPI(title="Neuro Core", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(integration_router)
app.include_router(control_router)
app.include_router(memory_router)
app.include_router(playground_router)
app.include_router(v1_router)
app.include_router(audio_ws_router)
app.include_router(frontend_ws_router)
