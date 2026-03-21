"""
Module: app/storage/chroma_store.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# Chroma 存储：检索人格语料 few-shot 示例。

from __future__ import annotations

import logging

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
