"""
Module: app/agent/memory_reflector.py

Beginner note:
- This background worker summarizes recent dialogues and writes compact notes
  into Chroma long-term memory.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from app.agent.memory import MemoryFacade
from app.core.config import settings
from app.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)


class MemoryReflector:
    """Periodic dialogue reflection worker."""

    def __init__(self, memory: MemoryFacade, llm: LLMRouter) -> None:
        """Initialize worker dependencies."""
        self.memory = memory
        self.llm = llm
        self._running = False

    def stop(self) -> None:
        """Stop loop on next tick."""
        self._running = False

    async def run_forever(self) -> None:
        """Main periodic loop."""
        self._running = True
        logger.info("memory reflector started")
        while self._running:
            try:
                await self._tick_once()
            except Exception:
                logger.exception("memory reflector tick failed")
            await asyncio.sleep(max(10, int(settings.memory_reflect_poll_sec)))

    async def _tick_once(self) -> None:
        if not settings.memory_reflect_enabled:
            return

        sqlite = self.memory.sqlite
        latest_id = await sqlite.latest_dialogue_id()
        if latest_id <= 0:
            return

        last_id = int(await sqlite.get_meta("reflect_last_dialogue_id", "0") or 0)
        last_day = await sqlite.get_meta("reflect_last_day", "")

        now = datetime.now()
        today = now.date().isoformat()
        by_turns = (latest_id - last_id) >= max(10, int(settings.memory_reflect_turn_interval))
        by_daily = (
            now.hour >= int(settings.memory_reflect_daily_hour)
            and last_day != today
            and latest_id > last_id
        )

        if not by_turns and not by_daily:
            return

        rows = await sqlite.fetch_dialogue_after_id(
            after_id=last_id,
            limit=max(20, int(settings.memory_reflect_max_scan)),
        )
        rows = [r for r in rows if str(r.get("role", "")) in {"user", "assistant"}]
        if not rows:
            if by_daily:
                await sqlite.set_meta("reflect_last_day", today)
            return

        notes = await self._summarize_to_notes(rows)
        if notes:
            inserted = self.memory.append_long_term_notes(
                notes=notes,
                source="reflection",
                metadata={
                    "from_dialogue_id": str(rows[0].get("id", "")),
                    "to_dialogue_id": str(rows[-1].get("id", "")),
                },
            )
            logger.info("memory reflection inserted %s long-term notes", inserted)

        await sqlite.set_meta("reflect_last_dialogue_id", str(rows[-1].get("id", latest_id)))
        if by_daily:
            await sqlite.set_meta("reflect_last_day", today)

    async def _summarize_to_notes(self, rows: list[dict[str, Any]]) -> list[str]:
        transcript = []
        for r in rows:
            role = str(r.get("role", "user"))
            text = str(r.get("text", "")).strip().replace("\n", " ")
            if not text:
                continue
            transcript.append({"id": r.get("id"), "role": role, "text": text[:500]})

        if not transcript:
            return []

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a memory reflection engine. "
                    "Read dialogue transcript and output JSON only. "
                    "Return object with keys: notes, preferences, recent_events, open_tasks. "
                    "Each value must be an array of concise factual strings. "
                    "Avoid duplicate statements and avoid speculation."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Summarize the transcript into long-term memory facts. "
                    "Focus on user preferences, ongoing projects, recent experiences, and commitments.\n\n"
                    + json.dumps(transcript, ensure_ascii=False)
                ),
            },
        ]

        try:
            raw = await self.llm.generate(messages)
            data = json.loads(raw)
        except Exception as exc:
            logger.warning("memory reflection llm/json failed: %s", exc)
            return []

        out: list[str] = []
        for key in ("notes", "preferences", "recent_events", "open_tasks"):
            value = data.get(key)
            if isinstance(value, list):
                for item in value:
                    s = str(item).strip()
                    if s:
                        out.append(s)

        # stable dedup + cap
        dedup: list[str] = []
        seen: set[str] = set()
        for item in out:
            if item in seen:
                continue
            seen.add(item)
            dedup.append(item)
        return dedup[: max(1, int(settings.memory_reflect_max_notes))]
