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
    """ToolRegistry: main class container for related behavior in this module."""
    def __init__(self) -> None:
        # 使用名称到工具实例的映射，支持运行时扩展注册。
        """Initialize the object state and cache required dependencies."""
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        # 注册单个工具实例，后注册同名工具会覆盖旧值。
        """Public API `register` used by other modules or route handlers."""
        self._tools[tool.name] = tool

    async def call(self, name: str, args: dict) -> str:
        # 按名称查找工具并执行；未命中时返回错误文本。
        # 当前错误用字符串返回，而非抛异常，避免中断 Agent 主循环。
        """Public API `call` used by other modules or route handlers."""
        tool = self._tools.get(name)
        if not tool:
            return f"tool not found: {name}"
        return await tool.call(args)
