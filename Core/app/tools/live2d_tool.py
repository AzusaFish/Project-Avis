"""
Module: app/tools/live2d_tool.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# Live2D 控制工具：生成动作指令，供前端执行。

from __future__ import annotations


class Live2DControlTool:
    """Live2DControlTool: main class container for related behavior in this module."""
    name = "live2d_control"
    # 当前实现只返回文本描述；真正动作推送由 AgentLoop 的 broadcast 完成。

    async def call(self, args: dict) -> str:
        # 生成前端可消费的 Live2D 动作描述文本。
        """Public API `call` used by other modules or route handlers."""
        action = args.get("action", "idle")
        return f"live2d action queued: {action}"
