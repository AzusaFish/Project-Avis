from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.storage.chroma_store import ChromaStore


class _FakeMemoryCollection:
    def __init__(self, query_result: dict | None = None) -> None:
        self.query_result = query_result or {}
        self.query_calls: list[dict] = []
        self.add_calls: list[dict] = []

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        return self.query_result

    def add(self, documents, metadatas, ids):
        self.add_calls.append(
            {
                "documents": documents,
                "metadatas": metadatas,
                "ids": ids,
            }
        )


def _make_store(query_result: dict | None = None) -> tuple[ChromaStore, _FakeMemoryCollection]:
    fake = _FakeMemoryCollection(query_result=query_result)
    store = object.__new__(ChromaStore)
    store.client = None
    store.persona = fake
    store.memory = fake
    return store, fake


def test_emotional_decay_order_negative_then_positive_then_neutral() -> None:
    store, _ = _make_store()
    now = datetime(2026, 4, 12, tzinfo=timezone.utc)
    created_at = (now - timedelta(hours=48)).isoformat()

    negative_meta = {
        "created_at": created_at,
        "importance_score": 1.0,
        "emotion_tag": "negative",
        "emotion_intensity": 0.95,
        "source_event": "tool_result",
        "topic_tags": "build,error,stacktrace",
    }
    neutral_meta = {
        "created_at": created_at,
        "importance_score": 1.0,
        "emotion_tag": "neutral",
        "emotion_intensity": 0.2,
        "source_event": "reflection",
        "topic_tags": "build,error,stacktrace",
    }
    positive_meta = {
        "created_at": created_at,
        "importance_score": 1.0,
        "emotion_tag": "positive",
        "emotion_intensity": 0.85,
        "source_event": "reflection",
        "topic_tags": "build,error,stacktrace",
    }

    negative_score = store._effective_importance(
        text="build failed with traceback and panic",
        metadata=negative_meta,
        query="build error",
        now=now,
    )
    neutral_score = store._effective_importance(
        text="build failed with traceback and panic",
        metadata=neutral_meta,
        query="build error",
        now=now,
    )
    positive_score = store._effective_importance(
        text="build failed with traceback and panic",
        metadata=positive_meta,
        query="build error",
        now=now,
    )

    assert negative_score > neutral_score
    assert negative_score > positive_score > neutral_score


def test_hybrid_ranking_prefers_recent_and_important_notes() -> None:
    now = datetime.now(timezone.utc)
    query_result = {
        "documents": [
            [
                "Old compile note that is semantically very close.",
                "Recent severe build failure with stack trace and fix details.",
                "Recent casual chat about coffee.",
            ]
        ],
        "metadatas": [
            [
                {
                    "created_at": (now - timedelta(days=12)).isoformat(),
                    "importance_score": 0.7,
                    "emotion_tag": "neutral",
                    "emotion_intensity": 0.2,
                    "topic_tags": "compile,error",
                    "source_event": "reflection",
                },
                {
                    "created_at": (now - timedelta(hours=2)).isoformat(),
                    "importance_score": 1.2,
                    "emotion_tag": "negative",
                    "emotion_intensity": 0.9,
                    "topic_tags": "build,error,stacktrace",
                    "source_event": "tool_result",
                },
                {
                    "created_at": (now - timedelta(hours=1)).isoformat(),
                    "importance_score": 0.35,
                    "emotion_tag": "positive",
                    "emotion_intensity": 0.25,
                    "topic_tags": "chat,coffee",
                    "source_event": "reflection",
                },
            ]
        ],
        "distances": [[0.04, 0.12, 0.2]],
    }
    store, fake = _make_store(query_result=query_result)

    notes = store.search_long_term(query="build error stacktrace", top_k=2)

    assert len(notes) == 2
    assert notes[0] == "Recent severe build failure with stack trace and fix details."
    assert fake.query_calls
    assert int(fake.query_calls[0]["n_results"]) >= 6


def test_add_long_term_notes_includes_l2_metadata_fields() -> None:
    store, fake = _make_store()

    inserted = store.add_long_term_notes(
        notes=["I felt frustrated after repeated compile errors in the avis project."],
        source="reflection",
        metadata={"from_dialogue_id": "11", "to_dialogue_id": "14"},
    )

    assert inserted == 1
    assert len(fake.add_calls) == 1

    payload = fake.add_calls[0]
    assert payload["documents"]
    assert payload["metadatas"]

    meta = payload["metadatas"][0]
    assert meta.get("source_event") == "reflection"
    assert isinstance(meta.get("topic_tags"), str) and bool(meta.get("topic_tags"))
    assert isinstance(meta.get("emotion_tag"), str) and bool(meta.get("emotion_tag"))
    assert "emotion_intensity" in meta
    assert "importance_score" in meta
