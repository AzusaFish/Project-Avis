"""
Module: app/agent/memory.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 记忆门面：统一封装短期对话与长期向量检索。

from __future__ import annotations

from typing import Any

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

    async def recent_dialogue(self, limit: int = 16) -> list[dict[str, str]]:
        # 读取最近若干条记录并保留 role，避免上下文角色混淆。
        """Public API `recent_dialogue` used by other modules or route handlers."""
        rows = await self.sqlite.fetch_recent_dialogue(limit=limit)
        normalized: list[dict[str, str]] = []
        for row in rows:
            role = str(row.get("role", "user")).strip().lower()
            if role not in {"user", "assistant", "system", "tool"}:
                role = "user"
            normalized.append({"role": role, "content": str(row.get("text", ""))})
        return normalized

    def retrieve_persona_examples(self, query: str, top_k: int = 4) -> list[str]:
        # 从向量库检索与当前输入语义相近的人格语料片段。
        """Public API `retrieve_persona_examples` used by other modules or route handlers."""
        return self.chroma.search_persona(query=query, top_k=top_k)

    def retrieve_long_term_notes(self, query: str, top_k: int = 4) -> list[str]:
        # 召回长期记忆笔记，用于增强上下文的一致性与延续性。
        """Public API `retrieve_long_term_notes` used by other modules or route handlers."""
        return self.chroma.search_long_term(query=query, top_k=top_k)

    def append_long_term_notes(
        self,
        notes: list[str],
        source: str = "reflection",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        # 批量写入长期记忆。
        """Public API `append_long_term_notes` used by other modules or route handlers."""
        return self.chroma.add_long_term_notes(notes=notes, source=source, metadata=metadata)
