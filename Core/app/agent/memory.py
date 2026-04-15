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
    def __init__(self, sqlite_store: SQLiteStore, chroma_store: ChromaStore) -> None:
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
        await self.append_short_term_memory(role=role, content=text, source_event="dialogue_compat")

    async def recent_dialogue(self, limit: int = 16) -> list[dict[str, Any]]:
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
        return self.chroma.search_persona(query=query, top_k=top_k)

    def retrieve_long_term_notes(self, query: str, top_k: int = 4) -> list[str]:
        return self.chroma.search_long_term(query=query, top_k=top_k)

    def append_long_term_notes(
        self,
        notes: list[str],
        source: str = "reflection",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        return self.chroma.add_long_term_notes(notes=notes, source=source, metadata=metadata)
