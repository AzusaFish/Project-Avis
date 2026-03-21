"""
Module: app/agent/memory.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 记忆门面：统一封装短期对话与长期向量检索。

from __future__ import annotations

from app.storage.chroma_store import ChromaStore
from app.storage.sqlite_store import SQLiteStore


class MemoryFacade:
    """MemoryFacade: main class container for related behavior in this module."""
    def __init__(self, sqlite_store: SQLiteStore, chroma_store: ChromaStore) -> None:
        # 初始化短期存储与人格向量检索的双后端引用。
        """Initialize the object state and cache required dependencies."""
        self.sqlite = sqlite_store
        self.chroma = chroma_store

    async def append_dialogue(self, role: str, text: str) -> None:
        # 追加一条对话到 SQLite，供后续上下文拼接使用。
        """Public API `append_dialogue` used by other modules or route handlers."""
        await self.sqlite.insert_dialogue(role=role, text=text)

    async def recent_dialogue(self, limit: int = 16) -> list[str]:
        # 读取最近若干条记录并格式化为“role: text”文本行。
        # 返回 list[str] 是为了直接拼到 prompt，减少中间对象转换。
        """Public API `recent_dialogue` used by other modules or route handlers."""
        rows = await self.sqlite.fetch_recent_dialogue(limit=limit)
        return [f"{r['role']}: {r['text']}" for r in rows]

    def retrieve_persona_examples(self, query: str, top_k: int = 4) -> list[str]:
        # 从向量库检索与当前输入语义相近的人格语料片段。
        """Public API `retrieve_persona_examples` used by other modules or route handlers."""
        return self.chroma.search_persona(query=query, top_k=top_k)
