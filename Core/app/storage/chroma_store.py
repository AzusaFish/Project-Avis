"""
Module: app/storage/chroma_store.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# Chroma 存储：检索人格语料 few-shot 示例。

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from chromadb import PersistentClient

from app.core.config import settings

logger = logging.getLogger(__name__)


class ChromaStore:
    """ChromaStore: main class container for related behavior in this module."""
    def __init__(self) -> None:
        # 初始化 Chroma 客户端并打开人格集合。
        """Initialize the object state and cache required dependencies."""
        self.client = PersistentClient(path=settings.chroma_path)
        self.persona = self.client.get_or_create_collection(settings.persona_collection)
        self.memory = self.client.get_or_create_collection(settings.memory_collection)

    def search_persona(self, query: str, top_k: int = 4) -> list[str]:
        # 执行语义检索并返回 top_k 文本片段。
        # Chroma 会内部做向量化（默认嵌入器），这里直接传原文本查询。
        """Public API `search_persona` used by other modules or route handlers."""
        try:
            result = self.persona.query(query_texts=[query], n_results=top_k)
            docs = result.get("documents") or []
            if not docs:
                return []
            return [d for d in docs[0] if d]
        except Exception as exc:
            logger.warning("persona retrieval failed: %s", exc)
            return []

    def add_long_term_notes(
        self,
        notes: list[str],
        source: str = "reflection",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        # 将高密度记忆块写入长期记忆集合，便于后续语义召回。
        """Public API `add_long_term_notes` used by other modules or route handlers."""
        cleaned = [str(x).strip() for x in notes if str(x).strip()]
        if not cleaned:
            return 0

        now = datetime.utcnow().isoformat()
        metadatas = []
        ids = []
        extra = metadata or {}
        for _ in cleaned:
            row_meta: dict[str, Any] = {
                "source": source,
                "created_at": now,
            }
            row_meta.update(extra)
            metadatas.append(row_meta)
            ids.append(uuid.uuid4().hex)

        try:
            self.memory.add(documents=cleaned, metadatas=metadatas, ids=ids)
            return len(cleaned)
        except Exception as exc:
            logger.warning("long-term memory add failed: %s", exc)
            return 0

    def search_long_term(self, query: str, top_k: int = 4) -> list[str]:
        # 召回长期记忆，作为后续上下文增强输入。
        """Public API `search_long_term` used by other modules or route handlers."""
        q = str(query).strip()
        if not q:
            return []
        try:
            result = self.memory.query(query_texts=[q], n_results=max(1, top_k))
            docs = result.get("documents") or []
            if not docs:
                return []
            return [d for d in docs[0] if d]
        except Exception as exc:
            logger.warning("long-term memory retrieval failed: %s", exc)
            return []
