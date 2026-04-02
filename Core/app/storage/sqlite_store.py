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
        # 初始化数据库与 dialogue 表。
        # `CREATE TABLE IF NOT EXISTS` 可重复执行，适合启动阶段幂等初始化。
        """Public API `init` used by other modules or route handlers."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        async with aiosqlite.connect(self.path) as conn:
            create_sql = (
                "CREATE TABLE IF NOT EXISTS dialogue ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "role TEXT NOT NULL,"
                "text TEXT NOT NULL,"
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ");"
            )
            await conn.execute(
                create_sql
            )
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS runtime_meta ("
                "k TEXT PRIMARY KEY,"
                "v TEXT NOT NULL,"
                "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ");"
            )
            await conn.commit()

    async def insert_dialogue(self, role: str, text: str) -> None:
        # 插入单条对话记录。
        """Public API `insert_dialogue` used by other modules or route handlers."""
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("INSERT INTO dialogue(role, text) VALUES(?, ?)", (role, text))
            await conn.commit()

    async def fetch_recent_dialogue(self, limit: int = 16) -> list[dict[str, Any]]:
        # 读取最近 N 条对话并按时间正序返回。
        # SQL 先 DESC 取最新 N 条，再 reverse() 变回时间正序。
        """Public API `fetch_recent_dialogue` used by other modules or route handlers."""
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT role, text FROM dialogue ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
        result = [dict(r) for r in rows]
        result.reverse()
        return result

    async def fetch_dialogue_after_id(self, after_id: int, limit: int = 200) -> list[dict[str, Any]]:
        # 按主键增量读取对话，适合后台总结任务做游标推进。
        """Public API `fetch_dialogue_after_id` used by other modules or route handlers."""
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT id, role, text, created_at FROM dialogue WHERE id > ? ORDER BY id ASC LIMIT ?",
                (max(0, int(after_id)), max(1, int(limit))),
            )
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def latest_dialogue_id(self) -> int:
        # 获取当前最大对话 id，便于计算累计新增轮次。
        """Public API `latest_dialogue_id` used by other modules or route handlers."""
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute("SELECT COALESCE(MAX(id), 0) FROM dialogue")
            row = await cursor.fetchone()
        return int(row[0] if row else 0)

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
    ) -> list[dict[str, Any]]:
        # 分页列出记忆条目，支持按角色和关键字过滤。
        """Public API `list_dialogue` used by other modules or route handlers."""
        where: list[str] = []
        args: list[Any] = []

        if role:
            where.append("role = ?")
            args.append(role)
        if keyword:
            where.append("text LIKE ?")
            args.append(f"%{keyword}%")

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        sql = (
            "SELECT id, role, text, created_at "
            f"FROM dialogue {where_sql} "
            "ORDER BY id DESC LIMIT ? OFFSET ?"
        )
        args.extend([limit, offset])

        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(sql, tuple(args))
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def count_dialogue(self, role: str | None = None, keyword: str | None = None) -> int:
        # 统计过滤条件下的条目总数，便于前端分页。
        """Public API `count_dialogue` used by other modules or route handlers."""
        where: list[str] = []
        args: list[Any] = []

        if role:
            where.append("role = ?")
            args.append(role)
        if keyword:
            where.append("text LIKE ?")
            args.append(f"%{keyword}%")

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"SELECT COUNT(*) FROM dialogue {where_sql}"

        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute(sql, tuple(args))
            row = await cursor.fetchone()
        return int(row[0] if row else 0)

    async def update_dialogue_text(self, dialogue_id: int, text: str) -> bool:
        # 按 id 更新记忆文本，返回是否更新成功。
        """Public API `update_dialogue_text` used by other modules or route handlers."""
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute(
                "UPDATE dialogue SET text = ? WHERE id = ?",
                (text, dialogue_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def delete_dialogue(self, dialogue_id: int) -> bool:
        # 按 id 删除单条记忆，返回是否删除成功。
        """Public API `delete_dialogue` used by other modules or route handlers."""
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute("DELETE FROM dialogue WHERE id = ?", (dialogue_id,))
            await conn.commit()
            return cursor.rowcount > 0

    async def clear_dialogue(self, role: str | None = None) -> int:
        # 清空记忆：可选只清某个 role（user/assistant）。
        """Public API `clear_dialogue` used by other modules or route handlers."""
        if role:
            sql = "DELETE FROM dialogue WHERE role = ?"
            args: tuple[Any, ...] = (role,)
        else:
            sql = "DELETE FROM dialogue"
            args = ()

        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute(sql, args)
            await conn.commit()
            return max(0, int(cursor.rowcount))
