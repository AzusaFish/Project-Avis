import asyncio
import sqlite3

import pytest

from app.storage.sqlite_store import SQLiteStore


def test_database_path_can_be_a_filename(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    store = SQLiteStore()
    store.path = "memory.db"

    asyncio.run(store.init())

    assert (tmp_path / "memory.db").is_file()


@pytest.mark.parametrize("already_migrated", [False, True])
def test_cleared_legacy_memories_stay_deleted_after_restart(tmp_path, already_migrated) -> None:
    store = SQLiteStore()
    store.path = str(tmp_path / "memory.db")
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "CREATE TABLE dialogue (id INTEGER PRIMARY KEY, role TEXT, "
            "text TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute("INSERT INTO dialogue (role, text) VALUES ('user', 'Old memory')")

    async def run_case() -> None:
        await store.init()
        assert await store.count_dialogue() == 1
        if already_migrated:
            # Simulate a database migrated by an older version without a marker.
            with sqlite3.connect(store.path) as conn:
                conn.execute("DELETE FROM runtime_meta")
            await store.init()
        assert await store.clear_dialogue() == 1
        await store.init()
        assert await store.count_dialogue() == 0

    asyncio.run(run_case())


def test_editing_memory_invalidates_assessment_and_updates_token_estimate(tmp_path) -> None:
    store = SQLiteStore()
    store.path = str(tmp_path / "memory.db")

    async def run_case() -> None:
        await store.init()
        await store.insert_short_term_memory(
            role="user", content="Old", token_estimate=1,
            processed_flag=1, importance_score=1.2,
            emotion_vector='{"tag":"negative","intensity":0.9}',
        )
        row = (await store.fetch_recent_dialogue())[0]
        replacement = "A much longer replacement message with different meaning."
        assert await store.update_dialogue_text(row["id"], replacement)
        edited = (await store.fetch_recent_dialogue())[0]
        assert edited["text"] == replacement
        assert edited["token_estimate"] == max(1, len(replacement) // 3)
        assert edited["processed_flag"] == 0
        assert edited["importance_score"] == 0.0
        assert edited["emotion_vector"] == "{}"
        assert not await store.update_dialogue_text(row["id"] + 100, "Missing")

    asyncio.run(run_case())
