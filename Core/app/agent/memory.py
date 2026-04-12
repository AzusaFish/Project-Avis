"""
Module: app/agent/memory.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 记忆门面：统一封装短期对话与长期向量检索。

from __future__ import annotations

import json
from typing import Any

from app.core.config import settings
from app.storage.chroma_store import ChromaStore
from app.storage.sqlite_store import SQLiteStore


class MemoryFacade:
    """MemoryFacade: main class container for related behavior in this module."""
    def __init__(self, sqlite_store: SQLiteStore, chroma_store: ChromaStore) -> None:
        # 初始化短期存储与人格向量检索的双后端引用。
        """Initialize the object state and cache required dependencies."""
        self.sqlite = sqlite_store
        self.chroma = chroma_store

    def _normalize_role(self, role: str) -> str:
        role_norm = str(role or "user").strip().lower()
        if role_norm not in {"user", "assistant", "system", "tool"}:
            return "user"
        return role_norm

    async def append_short_term_memory(
        self,
        role: str,
        content: str,
        *,
        source_event: str = "",
        emotion_vector: dict[str, Any] | str | None = None,
        importance_score: float | None = None,
        screenshot_path: str = "",
        token_estimate: int | None = None,
        processed_flag: int = 0,
    ) -> None:
        """统一短期记忆写入入口：文本/截图/工具结果都走这里。"""
        role_norm = self._normalize_role(role)
        text = str(content or "").strip()
        if not text:
            return

        if isinstance(emotion_vector, dict):
            emotion_json = json.dumps(emotion_vector, ensure_ascii=False)
        elif isinstance(emotion_vector, str) and emotion_vector.strip():
            emotion_json = emotion_vector.strip()
        else:
            emotion_json = "{}"

        score = (
            float(importance_score)
            if importance_score is not None
            else 0.0
        )
        tokens = int(token_estimate) if token_estimate is not None else max(1, len(text) // 3)

        await self.sqlite.insert_short_term_memory(
            role=role_norm,
            content=text,
            emotion_vector=emotion_json,
            importance_score=score,
            screenshot_path=str(screenshot_path or ""),
            token_estimate=tokens,
            processed_flag=processed_flag,
            source_event=str(source_event or ""),
        )

    async def append_dialogue(self, role: str, text: str) -> None:
        # 追加一条对话到 SQLite，供后续上下文拼接使用。
        """Public API `append_dialogue` used by other modules or route handlers."""
        await self.append_short_term_memory(role=role, content=text, source_event="dialogue_compat")

    async def recent_dialogue(self, limit: int = 16) -> list[dict[str, Any]]:
        # 读取最近若干条记录并保留 role 与重要度元信息。
        """Public API `recent_dialogue` used by other modules or route handlers."""
        scan_limit = max(limit * 4, int(getattr(settings, "memory_context_recent_window", 16)) * 4)
        rows = await self.sqlite.fetch_recent_dialogue(limit=scan_limit)
        normalized: list[dict[str, Any]] = []
        for row in rows:
            role = self._normalize_role(str(row.get("role", "user")))
            normalized.append(
                {
                    "id": int(row.get("id", 0) or 0),
                    "role": role,
                    "content": str(row.get("text", "")),
                    "importance_score": float(row.get("importance_score", 0.0) or 0.0),
                    "token_estimate": int(row.get("token_estimate", 0) or 0),
                    "screenshot_path": str(row.get("screenshot_path", "") or ""),
                    "source_event": str(row.get("source_event", "") or ""),
                }
            )
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
