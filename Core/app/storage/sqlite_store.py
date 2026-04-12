"""
Module: app/storage/sqlite_store.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# SQLite 存储：保存最近对话，作为短期记忆。

from __future__ import annotations

import os
from typing import Any

import aiosqlite

from app.core.config import settings


class SQLiteStore:
    """SQLiteStore: main class container for related behavior in this module."""
    def __init__(self) -> None:
        # 记录 SQLite 文件路径。
        """Initialize the object state and cache required dependencies."""
        self.path = settings.sqlite_path

    async def init(self) -> None:
        # 初始化数据库与短期记忆 Buffer。
        # `CREATE TABLE IF NOT EXISTS` 可重复执行，适合启动阶段幂等初始化。
        """Public API `init` used by other modules or route handlers."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        async with aiosqlite.connect(self.path) as conn:
            # 兼容保留旧表，便于回滚与历史查询。
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS dialogue ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "role TEXT NOT NULL,"
                "text TEXT NOT NULL,"
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ");"
            )
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS short_term_buffer ("
                "msg_id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                "role TEXT NOT NULL,"
                "content TEXT NOT NULL,"
                "emotion_vector TEXT NOT NULL DEFAULT '{}',"
                "importance_score REAL NOT NULL DEFAULT 0.0,"
                "screenshot_path TEXT NOT NULL DEFAULT '',"
                "token_estimate INTEGER NOT NULL DEFAULT 0,"
                "processed_flag INTEGER NOT NULL DEFAULT 0,"
                "source_event TEXT NOT NULL DEFAULT ''"
                ");"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_stb_timestamp ON short_term_buffer(timestamp DESC);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_stb_importance ON short_term_buffer(importance_score DESC, msg_id DESC);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_stb_processed ON short_term_buffer(processed_flag, msg_id ASC);"
            )
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS runtime_meta ("
                "k TEXT PRIMARY KEY,"
                "v TEXT NOT NULL,"
                "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ");"
            )

            # 无损迁移：仅当新表为空时，从旧 dialogue 一次性导入。
            await self._migrate_dialogue_to_short_term(conn)
            await conn.commit()

    async def _migrate_dialogue_to_short_term(self, conn: aiosqlite.Connection) -> None:
        """首次启用 short_term_buffer 时，把 dialogue 全量迁移过去。"""
        cursor = await conn.execute("SELECT COUNT(*) FROM short_term_buffer")
        row = await cursor.fetchone()
        if int(row[0] if row else 0) > 0:
            return

        cursor = await conn.execute("SELECT COUNT(*) FROM dialogue")
        row = await cursor.fetchone()
        if int(row[0] if row else 0) <= 0:
            return

        await conn.execute(
            "INSERT INTO short_term_buffer(timestamp, role, content, emotion_vector, importance_score, screenshot_path, token_estimate, processed_flag, source_event) "
            "SELECT created_at, role, text, '{}', "
            "CASE WHEN role IN ('user', 'assistant') THEN 0.6 ELSE 0.4 END, "
            "'', "
            "CASE WHEN LENGTH(COALESCE(text, '')) <= 0 THEN 1 ELSE CAST((LENGTH(text) + 2) / 3 AS INTEGER) END, "
            "0, 'dialogue_migration' "
            "FROM dialogue ORDER BY id ASC"
        )

    async def insert_short_term_memory(
        self,
        role: str,
        content: str,
        emotion_vector: str = "{}",
        importance_score: float = 0.0,
        screenshot_path: str = "",
        token_estimate: int = 0,
        processed_flag: int = 0,
        source_event: str = "",
    ) -> None:
        """插入一条短期记忆（新主路径）。"""
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(
                "INSERT INTO short_term_buffer(role, content, emotion_vector, importance_score, screenshot_path, token_estimate, processed_flag, source_event) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    role,
                    content,
                    emotion_vector,
                    float(importance_score),
                    screenshot_path,
                    max(0, int(token_estimate)),
                    1 if int(processed_flag) else 0,
                    source_event,
                ),
            )
            await conn.commit()

    async def insert_dialogue(self, role: str, text: str) -> None:
        # 兼容入口：内部转写到 short_term_buffer。
        """Public API `insert_dialogue` used by other modules or route handlers."""
        await self.insert_short_term_memory(
            role=role,
            content=text,
            emotion_vector="{}",
            importance_score=0.0,
            screenshot_path="",
            token_estimate=max(1, len(text) // 3),
            processed_flag=0,
            source_event="dialogue_compat",
        )

    async def fetch_recent_short_term(self, limit: int = 16) -> list[dict[str, Any]]:
        """读取最近 N 条短期记忆并按时间正序返回。"""
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT msg_id AS id, role, content AS text, timestamp AS created_at, emotion_vector, importance_score, screenshot_path, token_estimate, processed_flag, source_event "
                "FROM short_term_buffer ORDER BY msg_id DESC LIMIT ?",
                (max(1, int(limit)),),
            )
            rows = await cursor.fetchall()
        result = [dict(r) for r in rows]
        result.reverse()
        return result

    async def fetch_recent_dialogue(self, limit: int = 16) -> list[dict[str, Any]]:
        # 兼容入口：底层读取 short_term_buffer。
        """Public API `fetch_recent_dialogue` used by other modules or route handlers."""
        return await self.fetch_recent_short_term(limit=limit)

    async def fetch_short_term_after_id(self, after_id: int, limit: int = 200) -> list[dict[str, Any]]:
        """按主键增量读取 short_term_buffer。"""
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT msg_id AS id, role, content AS text, timestamp AS created_at, emotion_vector, importance_score, screenshot_path, token_estimate, processed_flag, source_event "
                "FROM short_term_buffer WHERE msg_id > ? ORDER BY msg_id ASC LIMIT ?",
                (max(0, int(after_id)), max(1, int(limit))),
            )
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def fetch_dialogue_after_id(self, after_id: int, limit: int = 200) -> list[dict[str, Any]]:
        # 兼容入口：底层读取 short_term_buffer。
        """Public API `fetch_dialogue_after_id` used by other modules or route handlers."""
        return await self.fetch_short_term_after_id(after_id=after_id, limit=limit)

    async def latest_short_term_id(self) -> int:
        """获取当前最大 short_term_buffer 主键。"""
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute("SELECT COALESCE(MAX(msg_id), 0) FROM short_term_buffer")
            row = await cursor.fetchone()
        return int(row[0] if row else 0)

    async def latest_dialogue_id(self) -> int:
        # 兼容入口：底层读取 short_term_buffer。
        """Public API `latest_dialogue_id` used by other modules or route handlers."""
        return await self.latest_short_term_id()

    async def get_meta(self, key: str, default: str = "") -> str:
        # 读取 runtime_meta 中的字符串键值。
        """Public API `get_meta` used by other modules or route handlers."""
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute("SELECT v FROM runtime_meta WHERE k = ?", (key,))
            row = await cursor.fetchone()
        if not row:
            return default
        return str(row[0])

    async def set_meta(self, key: str, value: str) -> None:
        # 写入 runtime_meta 键值，并更新 updated_at。
        """Public API `set_meta` used by other modules or route handlers."""
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(
                "INSERT INTO runtime_meta(k, v) VALUES(?, ?) "
                "ON CONFLICT(k) DO UPDATE SET v = excluded.v, updated_at = CURRENT_TIMESTAMP",
                (str(key), str(value)),
            )
            await conn.commit()

    async def list_dialogue(
        self,
        limit: int = 50,
        offset: int = 0,
        role: str | None = None,
        keyword: str | None = None,
        min_importance: float | None = None,
        processed_flag: int | None = None,
        sort_by: str = "time",
    ) -> list[dict[str, Any]]:
        # 分页列出短期记忆，支持角色/关键字/重要度/处理状态过滤。
        """Public API `list_dialogue` used by other modules or route handlers."""
        where: list[str] = []
        args: list[Any] = []

        if role:
            where.append("role = ?")
            args.append(role)
        if keyword:
            where.append("content LIKE ?")
            args.append(f"%{keyword}%")
        if min_importance is not None:
            where.append("importance_score >= ?")
            args.append(float(min_importance))
        if processed_flag is not None:
            where.append("processed_flag = ?")
            args.append(1 if int(processed_flag) else 0)

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        order_sql = "ORDER BY msg_id DESC"
        if str(sort_by).strip().lower() == "importance":
            order_sql = "ORDER BY importance_score DESC, msg_id DESC"

        sql = (
            "SELECT msg_id AS id, role, content AS text, timestamp AS created_at, emotion_vector, importance_score, screenshot_path, token_estimate, processed_flag, source_event "
            f"FROM short_term_buffer {where_sql} "
            f"{order_sql} LIMIT ? OFFSET ?"
        )
        args.extend([max(1, int(limit)), max(0, int(offset))])

        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(sql, tuple(args))
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def count_dialogue(
        self,
        role: str | None = None,
        keyword: str | None = None,
        min_importance: float | None = None,
        processed_flag: int | None = None,
    ) -> int:
        # 统计过滤条件下的条目总数，便于前端分页。
        """Public API `count_dialogue` used by other modules or route handlers."""
        where: list[str] = []
        args: list[Any] = []

        if role:
            where.append("role = ?")
            args.append(role)
        if keyword:
            where.append("content LIKE ?")
            args.append(f"%{keyword}%")
        if min_importance is not None:
            where.append("importance_score >= ?")
            args.append(float(min_importance))
        if processed_flag is not None:
            where.append("processed_flag = ?")
            args.append(1 if int(processed_flag) else 0)

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"SELECT COUNT(*) FROM short_term_buffer {where_sql}"

        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute(sql, tuple(args))
            row = await cursor.fetchone()
        return int(row[0] if row else 0)

    async def count_short_term_by_processed(self, processed_flag: int = 0) -> int:
        """统计指定 processed_flag 的短期记忆条目数。"""
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM short_term_buffer WHERE processed_flag = ?",
                (1 if int(processed_flag) else 0,),
            )
            row = await cursor.fetchone()
        return int(row[0] if row else 0)

    async def fetch_short_term_by_processed(
        self,
        processed_flag: int = 0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """读取指定 processed_flag 的短期记忆（按时间正序）。"""
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT msg_id AS id, role, content AS text, timestamp AS created_at, emotion_vector, importance_score, screenshot_path, token_estimate, processed_flag, source_event "
                "FROM short_term_buffer WHERE processed_flag = ? ORDER BY msg_id ASC LIMIT ?",
                (1 if int(processed_flag) else 0, max(1, int(limit))),
            )
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_short_term_assessment(
        self,
        msg_id: int,
        importance_score: float,
        emotion_vector: str,
        processed_flag: int = 1,
    ) -> bool:
        """回写 LLM 评审结果（重要度/情绪向量/处理标记）。"""
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute(
                "UPDATE short_term_buffer SET importance_score = ?, emotion_vector = ?, processed_flag = ? WHERE msg_id = ?",
                (
                    float(importance_score),
                    str(emotion_vector or "{}"),
                    1 if int(processed_flag) else 0,
                    int(msg_id),
                ),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def update_dialogue_text(self, dialogue_id: int, text: str) -> bool:
        # 按 id 更新短期记忆文本，返回是否更新成功。
        """Public API `update_dialogue_text` used by other modules or route handlers."""
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute(
                "UPDATE short_term_buffer SET content = ? WHERE msg_id = ?",
                (text, int(dialogue_id)),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def delete_dialogue(self, dialogue_id: int) -> bool:
        # 按 id 删除单条短期记忆，返回是否删除成功。
        """Public API `delete_dialogue` used by other modules or route handlers."""
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute("DELETE FROM short_term_buffer WHERE msg_id = ?", (int(dialogue_id),))
            await conn.commit()
            return cursor.rowcount > 0

    async def clear_dialogue(self, role: str | None = None) -> int:
        # 清空记忆：可选只清某个 role（user/assistant/system/tool）。
        """Public API `clear_dialogue` used by other modules or route handlers."""
        if role:
            sql = "DELETE FROM short_term_buffer WHERE role = ?"
            args: tuple[Any, ...] = (role,)
        else:
            sql = "DELETE FROM short_term_buffer"
            args = ()

        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute(sql, args)
            await conn.commit()
            return max(0, int(cursor.rowcount))
