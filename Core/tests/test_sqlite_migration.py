import asyncio

import aiosqlite

from app.storage.sqlite_store import SQLiteStore


def test_cleared_legacy_dialogue_is_not_restored_on_restart(tmp_path) -> None:
    async def run_case() -> None:
        store = SQLiteStore()
        store.path = str(tmp_path / "memory.db")
        await store.init()
        async with aiosqlite.connect(store.path) as conn:
            await conn.execute("INSERT INTO dialogue(role, text) VALUES('user', 'legacy secret')")
            await conn.commit()

        await store.init()
        assert await store.count_dialogue() == 1
        await store.set_meta("kv_summary_text", "legacy summary")
        assert await store.clear_dialogue() == 1
        assert await store.get_meta("kv_summary_text") == ""
        await store.init()
        assert await store.count_dialogue() == 0

    asyncio.run(run_case())


def test_existing_cleared_buffer_is_not_migrated_again(tmp_path) -> None:
    async def run_case() -> None:
        store = SQLiteStore()
        store.path = str(tmp_path / "memory.db")
        await store.init()
        await store.insert_dialogue("user", "old short term entry")
        await store.clear_dialogue()
        async with aiosqlite.connect(store.path) as conn:
            await conn.execute("INSERT INTO dialogue(role, text) VALUES('user', 'legacy secret')")
            await conn.commit()

        await store.init()
        assert await store.count_dialogue() == 0

    asyncio.run(run_case())
