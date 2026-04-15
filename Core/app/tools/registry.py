"""
Module: app/tools/registry.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 工具注册中心：按名称路由到具体工具实现。

from __future__ import annotations

from app.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    async def call(self, name: str, args: dict) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"tool not found: {name}"
        return await tool.call(args)
