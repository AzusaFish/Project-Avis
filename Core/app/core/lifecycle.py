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
    # 启动阶段：创建依赖、注册工具并拉起后台任务。
    # 启动顺序（重要）：
    # 1) 先建存储（SQLite/Chroma）
    # 2) 再建服务与工具
    # 3) 最后启动后台协程（主循环/轮询器）
    """Public API `startup` used by other modules or route handlers."""
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

    # app.state 是 FastAPI 的运行时共享上下文，等价“全局服务容器”。
    app.state.bus = bus
    app.state.agent = agent
    app.state.llm = llm
    app.state.frontend = frontend
    app.state.sqlite = sqlite
    app.state.reflector = reflector
    # `create_task` 会把协程挂到事件循环后台持续运行，类似“长期工作线程”。
    app.state.tasks = [
        # Agent 主循环：消费 EventBus 并执行业务链路。
        asyncio.create_task(agent.run_forever(), name="agent_loop"),
        # 微信输入轮询器：桥接微信消息到 EventBus。
        asyncio.create_task(wechat_watcher(bus), name="wechat_watcher"),
        # 游戏状态轮询器：桥接 STS 状态到 EventBus。
        asyncio.create_task(sts_state_watcher(bus), name="sts_watcher"),
        # 定时器：静默过久时投递主动发话事件。
        asyncio.create_task(proactive_scheduler(bus), name="scheduler"),
        # 后台记忆总结与反思：定期提炼长期记忆并写入 Chroma。
        asyncio.create_task(reflector.run_forever(), name="memory_reflector"),
    ]


async def shutdown(app: FastAPI) -> None:
    # 关闭阶段：停止主循环并取消所有后台任务。
    # 按统一顺序停止后台协程，避免资源泄漏。
    # 关闭顺序：
    # 1) 先给 agent 设置停止标志
    # 2) 再 cancel 所有后台 task
    # 3) gather 等待退出，吞掉取消异常
    """Public API `shutdown` used by other modules or route handlers."""
    app.state.agent.stop()
    reflector = getattr(app.state, "reflector", None)
    if reflector is not None:
        reflector.stop()
    for task in app.state.tasks:
        task.cancel()
    # return_exceptions=True: 避免某个任务抛错导致其它任务无法回收。
    await asyncio.gather(*app.state.tasks, return_exceptions=True)
