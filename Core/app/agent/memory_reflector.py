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
    def __init__(self, memory: MemoryFacade, llm: LLMRouter) -> None:
        self.memory = memory
        self.llm = llm
        self._running = False
        self._score_debug: dict[str, Any] = {
            "last_run_at": "",
            "last_pending": 0,
            "last_triggered": False,
            "last_batch": 0,
            "last_updated": 0,
            "last_error": "",
        }

    def stop(self) -> None:
        self._running = False

    async def run_forever(self) -> None:
        self._running = True
        logger.info("memory reflector started")
        while self._running:
            try:
                await self._score_short_term_once()
                await self._tick_once()
            except Exception:
                logger.exception("memory reflector tick failed")
            await asyncio.sleep(max(10, int(settings.memory_reflect_poll_sec)))

    async def _score_short_term_once(self) -> None:
        self._score_debug.update(
            {
                "last_run_at": datetime.now().isoformat(timespec="seconds"),
                "last_triggered": False,
                "last_batch": 0,
                "last_updated": 0,
                "last_error": "",
            }
        )
        if not bool(getattr(settings, "memory_llm_scoring_enabled", True)):
            return

        sqlite = self.memory.sqlite
        pending = await sqlite.count_short_term_by_processed(processed_flag=0)
        self._score_debug["last_pending"] = int(pending)
        trigger_count = max(1, int(getattr(settings, "memory_llm_score_trigger_count", 24)))
        if pending < trigger_count:
            return
        self._score_debug["last_triggered"] = True

        batch_size = max(1, int(getattr(settings, "memory_llm_score_batch_size", 24)))
        rows = await sqlite.fetch_short_term_by_processed(processed_flag=0, limit=batch_size)
        if not rows:
            return
        self._score_debug["last_batch"] = len(rows)

        assessments = await self._assess_short_term_rows(rows)
        if not assessments:
            return

        updated = 0
        for item in assessments:
            msg_id = int(item.get("id", 0) or 0)
            if msg_id <= 0:
                continue
            importance = float(item.get("importance_score", 0.0) or 0.0)
            importance = max(0.0, min(1.5, importance))

            emo = item.get("emotion_vector")
            if isinstance(emo, dict):
                emotion_tag = str(emo.get("tag", "neutral") or "neutral").strip().lower()
                emotion_intensity = float(emo.get("intensity", 0.0) or 0.0)
            else:
                emotion_tag = "neutral"
                emotion_intensity = 0.0
            emotion_intensity = max(0.0, min(1.0, emotion_intensity))
            emotion_json = json.dumps(
                {
                    "tag": emotion_tag,
                    "intensity": emotion_intensity,
                },
                ensure_ascii=False,
            )
            ok = await sqlite.update_short_term_assessment(
                msg_id=msg_id,
                importance_score=importance,
                emotion_vector=emotion_json,
                processed_flag=1,
            )
            if ok:
                updated += 1

        if updated > 0:
            logger.info("memory llm scoring updated %s short-term rows", updated)
        self._score_debug["last_updated"] = int(updated)

    async def _assess_short_term_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        max_text = max(80, int(getattr(settings, "memory_llm_score_max_text", 360)))
        payload_rows: list[dict[str, Any]] = []
        for row in rows:
            msg_id = int(row.get("id", 0) or 0)
            if msg_id <= 0:
                continue
            payload_rows.append(
                {
                    "id": msg_id,
                    "role": str(row.get("role", "user") or "user"),
                    "source_event": str(row.get("source_event", "") or ""),
                    "text": str(row.get("text", "") or "").strip()[:max_text],
                }
            )

        if not payload_rows:
            return []

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a strict memory assessor. "
                    "Score each memory item by importance and emotion. "
                    "Return JSON only with this schema: "
                    "{\"assessments\":[{\"id\":int,\"importance_score\":float,\"emotion_vector\":{\"tag\":str,\"intensity\":float}}]}. "
                    "importance_score range: 0.0-1.5. "
                    "emotion_vector.tag must be one of [negative, positive, neutral]. "
                    "emotion_vector.intensity range: 0.0-1.0. "
                    "Do not output explanations."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Assess the following short-term memory items:\n\n"
                    + json.dumps(payload_rows, ensure_ascii=False)
                ),
            },
        ]

        try:
            raw = await self.llm.generate(messages)
            data = json.loads(raw)
        except Exception as exc:
            logger.warning("memory llm scoring failed: %s", exc)
            self._score_debug["last_error"] = str(exc)
            return []

        arr = data.get("assessments") if isinstance(data, dict) else None
        if not isinstance(arr, list):
            return []

        out: list[dict[str, Any]] = []
        seen: set[int] = set()
        for item in arr:
            if not isinstance(item, dict):
                continue
            msg_id = int(item.get("id", 0) or 0)
            if msg_id <= 0 or msg_id in seen:
                continue
            seen.add(msg_id)
            out.append(item)
        return out

    def get_score_debug_state(self) -> dict[str, Any]:
        return dict(self._score_debug)

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

        dedup: list[str] = []
        seen: set[str] = set()
        for item in out:
            if item in seen:
                continue
            seen.add(item)
            dedup.append(item)
        return dedup[: max(1, int(settings.memory_reflect_max_notes))]
