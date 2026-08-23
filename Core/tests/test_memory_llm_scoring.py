from __future__ import annotations

import asyncio
import json

from app.agent.memory_reflector import MemoryReflector
from app.core.config import settings


class _FakeSQLite:
    # Initialize fake SQLite store state.
    def __init__(self, pending: int, rows: list[dict]) -> None:
        self.pending = pending
        self.rows = rows
        self.updated: list[dict] = []

    # Return the pending count for scoring checks.
    async def count_short_term_by_processed(self, processed_flag: int = 0) -> int:
        return self.pending

    # Return a slice of pending rows for scoring.
    async def fetch_short_term_by_processed(self, processed_flag: int = 0, limit: int = 50) -> list[dict]:
        return self.rows[:limit]

    # Record scoring updates for later assertions.
    async def update_short_term_assessment(
        self,
        msg_id: int,
        importance_score: float,
        emotion_vector: str,
        processed_flag: int = 1,
    ) -> bool:
        self.updated.append(
            {
                "id": msg_id,
                "importance_score": importance_score,
                "emotion_vector": emotion_vector,
                "processed_flag": processed_flag,
            }
        )
        return True


class _FakeMemory:
    # Wrap the fake sqlite store.
    def __init__(self, sqlite: _FakeSQLite) -> None:
        self.sqlite = sqlite


class _FakeLLM:
    # Initialize fake LLM with a fixed response object.
    def __init__(self, response_obj: dict) -> None:
        self.response_obj = response_obj
        self.calls = 0

    # Return the canned response and count calls.
    async def generate(self, messages):
        self.calls += 1
        return json.dumps(self.response_obj, ensure_ascii=False)


# Temporarily override settings values for tests.
def _set_settings(**kwargs):
    backup = {k: getattr(settings, k) for k in kwargs}
    for k, v in kwargs.items():
        setattr(settings, k, v)
    return backup


# Restore settings values after a test.
def _restore_settings(backup: dict) -> None:
    for k, v in backup.items():
        setattr(settings, k, v)


# Ensure scoring runs and updates rows when threshold is met.
def test_llm_scoring_updates_rows_when_threshold_reached() -> None:
    rows = [
        {"id": 11, "role": "user", "source_event": "user_text", "text": "我今天修好了构建错误"},
        {"id": 12, "role": "assistant", "source_event": "assistant_speak", "text": "很好，我们继续优化"},
    ]
    sqlite = _FakeSQLite(pending=2, rows=rows)
    llm = _FakeLLM(
        {
            "assessments": [
                {"id": 11, "importance_score": 1.2, "emotion_vector": {"tag": "negative", "intensity": 0.8}},
                {"id": 12, "importance_score": 0.9, "emotion_vector": {"tag": "positive", "intensity": 0.7}},
            ]
        }
    )
    reflector = MemoryReflector(memory=_FakeMemory(sqlite), llm=llm)

    backup = _set_settings(
        memory_llm_scoring_enabled=True,
        memory_llm_score_trigger_count=2,
        memory_llm_score_batch_size=8,
        memory_llm_score_max_text=200,
    )
    try:
        asyncio.run(reflector._score_short_term_once())
    finally:
        _restore_settings(backup)

    assert llm.calls == 1
    assert len(sqlite.updated) == 2
    assert sqlite.updated[0]["processed_flag"] == 1

    emo0 = json.loads(sqlite.updated[0]["emotion_vector"])
    emo1 = json.loads(sqlite.updated[1]["emotion_vector"])
    assert emo0["tag"] == "negative"
    assert emo1["tag"] == "positive"


# Ensure scoring is skipped below the trigger threshold.
def test_llm_scoring_not_triggered_below_threshold() -> None:
    rows = [{"id": 21, "role": "user", "source_event": "user_text", "text": "普通聊天"}]
    sqlite = _FakeSQLite(pending=1, rows=rows)
    llm = _FakeLLM({"assessments": []})
    reflector = MemoryReflector(memory=_FakeMemory(sqlite), llm=llm)

    backup = _set_settings(
        memory_llm_scoring_enabled=True,
        memory_llm_score_trigger_count=3,
        memory_llm_score_batch_size=8,
        memory_llm_score_max_text=200,
    )
    try:
        asyncio.run(reflector._score_short_term_once())
    finally:
        _restore_settings(backup)

    assert llm.calls == 0
    assert sqlite.updated == []
