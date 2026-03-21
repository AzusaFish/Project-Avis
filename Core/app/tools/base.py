"""
Module: app/tools/base.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 工具协议定义：统一工具调用签名。

from __future__ import annotations

from typing import Protocol


class Tool(Protocol):
    # Protocol 是“结构化接口”：只要对象有同名属性/方法就算实现该接口。
    # C++ 类比：接近“鸭子类型版纯虚接口”。
    """Tool: main class container for related behavior in this module."""
    name: str

    async def call(self, args: dict) -> str:
        # 工具统一调用接口：传入参数字典，返回可显示文本。
        """Public API `call` used by other modules or route handlers."""
        ...
