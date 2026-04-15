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
    name: str

    async def call(self, args: dict) -> str:
        ...
