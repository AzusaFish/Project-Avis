"""
Module: app/storage/chroma_store.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# Chroma 存储：检索人格语料 few-shot 示例。

from __future__ import annotations

import logging
import math
import re
import uuid
from datetime import datetime, timezone
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

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_time(raw: Any) -> datetime | None:
        if not isinstance(raw, str) or not raw.strip():
            return None
        text = raw.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @classmethod
    def _hours_since(cls, created_at: Any, *, now: datetime | None = None) -> float:
        dt = cls._parse_time(created_at)
        if dt is None:
            return 0.0
        anchor = now or datetime.now(timezone.utc)
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        delta = anchor - dt
        return max(0.0, delta.total_seconds() / 3600.0)

    @staticmethod
    def _sanitize_metadata(meta: dict[str, Any]) -> dict[str, str | int | float | bool]:
        clean: dict[str, str | int | float | bool] = {}
        for key, value in meta.items():
            k = str(key)
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                clean[k] = value
            else:
                clean[k] = str(value)
        return clean

    @staticmethod
    def _extract_topic_tags(text: str, limit: int = 4) -> str:
        stop_words = {
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "from",
            "have",
            "about",
            "you",
            "your",
            "我",
            "你",
            "我们",
            "这个",
            "那个",
            "然后",
            "但是",
            "就是",
        }
        tokens = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", str(text or "").lower())
        uniq: list[str] = []
        seen: set[str] = set()
        for tok in tokens:
            if tok in stop_words or tok in seen:
                continue
            seen.add(tok)
            uniq.append(tok)
            if len(uniq) >= max(1, int(limit)):
                break
        return ",".join(uniq)

    @staticmethod
    def _parse_topic_tags(raw: Any) -> set[str]:
        if not isinstance(raw, str):
            return set()
        parts = [x.strip().lower() for x in re.split(r"[,;|]", raw) if x.strip()]
        return set(parts)

    @classmethod
    def _infer_emotion_profile(cls, text: str, metadata: dict[str, Any]) -> tuple[str, float]:
        tag = str(metadata.get("emotion_tag", "")).strip().lower()
        intensity = cls._safe_float(metadata.get("emotion_intensity"), default=-1.0)
        if tag and intensity >= 0.0:
            return tag, cls._clamp(intensity, 0.0, 1.0)
        if tag:
            return tag, cls._clamp(cls._safe_float(metadata.get("emotion_intensity"), default=0.3), 0.0, 1.0)
        return "neutral", 0.25

    @classmethod
    def _estimate_information_density(cls, text: str) -> float:
        t = str(text or "").strip()
        if not t:
            return 0.0
        length_factor = cls._clamp(len(t) / 180.0, 0.0, 1.0)
        symbol_bonus = 0.15 if any(ch in t for ch in "#[](){}:/\\") else 0.0
        digit_bonus = 0.1 if any(ch.isdigit() for ch in t) else 0.0
        return cls._clamp(length_factor + symbol_bonus + digit_bonus, 0.0, 1.0)

    @classmethod
    def _estimate_event_severity(cls, text: str, metadata: dict[str, Any]) -> float:
        explicit = cls._safe_float(metadata.get("event_severity"), default=-1.0)
        if explicit >= 0.0:
            return cls._clamp(explicit, 0.0, 1.0)
        return 0.2

    def _initial_weight(self, text: str, metadata: dict[str, Any], emotion_intensity: float) -> float:
        base_importance = self._safe_float(metadata.get("importance_score"), default=0.6)
        info = self._estimate_information_density(text)
        severity = self._estimate_event_severity(text, metadata)
        w0 = 0.45 * base_importance + 0.25 * info + 0.2 * severity + 0.1 * emotion_intensity
        return self._clamp(w0, 0.0, 2.0)

    def _decay_lambda(self, emotion_tag: str, emotion_intensity: float) -> float:
        base = max(1e-4, float(settings.memory_decay_lambda_base))
        tag = str(emotion_tag or "neutral").lower()
        is_negative = tag in {"negative", "angry", "sad", "fear", "frustrated", "anxious"}
        is_positive = tag in {"positive", "happy", "joy", "excited", "grateful", "relieved"}
        if is_negative and emotion_intensity >= float(settings.memory_decay_negative_emotion_threshold):
            return max(1e-4, base * float(settings.memory_decay_negative_lambda_multiplier))
        if is_positive and emotion_intensity >= float(settings.memory_decay_positive_emotion_threshold):
            return max(1e-4, base * float(settings.memory_decay_positive_lambda_multiplier))
        return base

    def _rule_bonus(self, metadata: dict[str, Any], query: str) -> float:
        bonus = 0.0
        src = str(metadata.get("source_event", metadata.get("source", ""))).lower()
        if src in {"tool_result", "desktop_screenshot", "reflection"}:
            bonus += 0.06

        emotion_tag = str(metadata.get("emotion_tag", "")).lower()
        if emotion_tag in {"negative", "angry", "sad", "fear", "frustrated", "anxious"}:
            bonus += 0.05

        query_tokens = set(re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", str(query or "").lower()))
        if query_tokens:
            tags = self._parse_topic_tags(metadata.get("topic_tags"))
            if query_tokens & tags:
                bonus += 0.08
        return self._clamp(bonus, 0.0, 0.25)

    def _effective_importance(
        self,
        text: str,
        metadata: dict[str, Any],
        query: str,
        *,
        now: datetime | None = None,
    ) -> float:
        emotion_tag, emotion_intensity = self._infer_emotion_profile(text, metadata)
        hours = self._hours_since(metadata.get("created_at"), now=now)
        w0 = self._initial_weight(text, metadata, emotion_intensity)
        lam = self._decay_lambda(emotion_tag, emotion_intensity)
        wt = w0 * math.exp(-lam * hours)
        enriched = dict(metadata)
        enriched["emotion_tag"] = emotion_tag
        bonus = self._rule_bonus(enriched, query)
        return self._clamp(wt + bonus, 0.0, 2.0)

    @staticmethod
    def _semantic_score(distance: Any, rank: int) -> float:
        if distance is None:
            return 1.0 / (1.0 + max(0, rank))
        d = max(0.0, ChromaStore._safe_float(distance, default=1.0))
        return 1.0 / (1.0 + d)

    def _recency_score(self, metadata: dict[str, Any], *, now: datetime | None = None) -> float:
        hours = self._hours_since(metadata.get("created_at"), now=now)
        decay = max(1e-4, float(settings.memory_hybrid_recency_lambda))
        return self._clamp(math.exp(-decay * hours), 0.0, 1.0)

    def _hybrid_rank(
        self,
        *,
        query: str,
        documents: list[str],
        metadatas: list[dict[str, Any]],
        distances: list[Any],
    ) -> list[dict[str, Any]]:
        ranked: list[dict[str, Any]] = []
        sw = max(0.0, float(settings.memory_hybrid_semantic_weight))
        rw = max(0.0, float(settings.memory_hybrid_recency_weight))
        iw = max(0.0, float(settings.memory_hybrid_importance_weight))
        denom = sw + rw + iw
        if denom <= 0:
            denom = 1.0

        for idx, doc in enumerate(documents):
            text = str(doc or "").strip()
            if not text:
                continue
            meta = metadatas[idx] if idx < len(metadatas) and isinstance(metadatas[idx], dict) else {}
            distance = distances[idx] if idx < len(distances) else None

            semantic = self._semantic_score(distance, idx)
            recency = self._recency_score(meta)
            importance = self._effective_importance(text=text, metadata=meta, query=query) / 2.0
            hybrid = (sw * semantic + rw * recency + iw * importance) / denom

            ranked.append(
                {
                    "document": text,
                    "metadata": meta,
                    "semantic_score": semantic,
                    "recency_score": recency,
                    "effective_importance": importance,
                    "hybrid_score": hybrid,
                }
            )

        ranked.sort(
            key=lambda x: (
                float(x["hybrid_score"]),
                float(x["effective_importance"]),
                float(x["semantic_score"]),
            ),
            reverse=True,
        )
        return ranked

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
        source_event = str(extra.get("source_event", source) or source)
        default_importance = self._clamp(
            self._safe_float(extra.get("importance_score"), default=0.7 if source == "reflection" else 0.6),
            0.0,
            2.0,
        )
        for note in cleaned:
            row_meta: dict[str, Any] = dict(extra)
            row_meta.setdefault("source", source)
            row_meta.setdefault("source_event", source_event)
            row_meta.setdefault("created_at", now)
            row_meta.setdefault("importance_score", default_importance)
            row_meta.setdefault("topic_tags", self._extract_topic_tags(note))

            emotion_tag, emotion_intensity = self._infer_emotion_profile(note, row_meta)
            row_meta.setdefault("emotion_tag", emotion_tag)
            row_meta.setdefault("emotion_intensity", emotion_intensity)
            row_meta.setdefault("event_severity", self._estimate_event_severity(note, row_meta))

            metadatas.append(self._sanitize_metadata(row_meta))
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

        top_n = max(1, int(top_k))
        semantic_pool = max(top_n, int(settings.memory_hybrid_semantic_pool), top_n * 3)
        try:
            result = self.memory.query(
                query_texts=[q],
                n_results=semantic_pool,
                include=["documents", "metadatas", "distances"],
            )
            docs = result.get("documents") or []
            if not docs:
                return []

            documents = [str(d) for d in docs[0] if str(d or "").strip()]
            metadatas_raw = result.get("metadatas") or [[]]
            distances_raw = result.get("distances") or [[]]
            metadatas = metadatas_raw[0] if metadatas_raw else []
            distances = distances_raw[0] if distances_raw else []

            ranked = self._hybrid_rank(
                query=q,
                documents=documents,
                metadatas=metadatas,
                distances=distances,
            )
            return [x["document"] for x in ranked[:top_n]]
        except Exception as exc:
            logger.warning("long-term memory retrieval failed: %s", exc)
            return []
