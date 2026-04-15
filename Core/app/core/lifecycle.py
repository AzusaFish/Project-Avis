"""
Module: app/core/lifecycle.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 应用生命周期：启动时装配模块，关闭时回收任务。

from __future__ import annotations

import asyncio

from fastapi import FastAPI

from app.agent.loop import AgentLoop
from app.agent.memory import MemoryFacade
from app.agent.memory_reflector import MemoryReflector
from app.core.bus import EventBus
from app.inputs.scheduler import proactive_scheduler
from app.inputs.sts_bridge import sts_state_watcher
from wechat.runtime.wechat_guard import wechat_watcher
from app.services.frontend_gateway import FrontendGateway
from app.services.llm_router import LLMRouter
from app.services.stt_service import STTService
from app.services.tts_service import TTSService
from app.storage.chroma_store import ChromaStore
from app.storage.sqlite_store import SQLiteStore
from app.tools.google_search import GoogleSearchTool
from app.tools.desktop_screenshot_tool import DesktopScreenshotTool
from app.tools.live2d_tool import Live2DControlTool
from app.tools.registry import ToolRegistry
from app.tools.sts_tool import SlayTheSpireTool
from app.tools.time_tool import CurrentTimeTool
from wechat.runtime.wechat_tool import WeChatSendTool


async def startup(app: FastAPI) -> None:
    bus = EventBus()
    sqlite = SQLiteStore()
    await sqlite.init()
    chroma = ChromaStore()

    memory = MemoryFacade(sqlite_store=sqlite, chroma_store=chroma)
    llm = LLMRouter()
    tts = TTSService()
    stt = STTService()
    frontend = FrontendGateway()

    tools = ToolRegistry()
    tools.register(GoogleSearchTool())
    tools.register(DesktopScreenshotTool())
    tools.register(WeChatSendTool())
    tools.register(Live2DControlTool())
    tools.register(SlayTheSpireTool())
    tools.register(CurrentTimeTool())

    agent = AgentLoop(
        bus=bus,
        llm=llm,
        tts=tts,
        stt=stt,
        memory=memory,
        tools=tools,
        frontend=frontend,
    )
    reflector = MemoryReflector(memory=memory, llm=llm)

    app.state.bus = bus
    app.state.agent = agent
    app.state.llm = llm
    app.state.frontend = frontend
    app.state.sqlite = sqlite
    app.state.reflector = reflector
    app.state.tasks = [
        asyncio.create_task(agent.run_forever(), name="agent_loop"),
        asyncio.create_task(wechat_watcher(bus), name="wechat_watcher"),
        asyncio.create_task(sts_state_watcher(bus), name="sts_watcher"),
        asyncio.create_task(proactive_scheduler(bus), name="scheduler"),
        asyncio.create_task(reflector.run_forever(), name="memory_reflector"),
    ]


async def shutdown(app: FastAPI) -> None:
    app.state.agent.stop()
    reflector = getattr(app.state, "reflector", None)
    if reflector is not None:
        reflector.stop()
    for task in app.state.tasks:
        task.cancel()
    await asyncio.gather(*app.state.tasks, return_exceptions=True)
