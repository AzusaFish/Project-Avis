from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest

from app.agent.loop import AgentLoop
from app.core.bus import EventBus
from app.core.events import Event, EventType


class _FakeStt:
    def __init__(self) -> None:
        self.called = asyncio.Event()
        self.audio_bytes = 0
        self.sample_rate = 0

    async def transcribe_chunk(
        self,
        pcm_base64: str,
        sample_rate: int = 16000,
        timeout_sec: float | None = None,
    ) -> str:
        self.audio_bytes = len(base64.b64decode(pcm_base64))
        self.sample_rate = sample_rate
        self.called.set()
        return ""


def test_audio_worker_keeps_short_frames_across_configured_flush_gap() -> None:
    async def run_case() -> None:
        stt = _FakeStt()
        loop = object.__new__(AgentLoop)
        loop._running = True
        loop._audio_queue = asyncio.Queue(maxsize=8)
        loop._stt_flush_gap_sec = 0.08
        loop._stt_max_buffer_sec = 0.3
        loop._stt_min_audio_sec = 0.2
        loop._stt_input_rms_gate_enabled = False
        loop._stt_silence_rms_threshold = 0.0
        loop._stt_noise_floor_ema = 0.0
        loop._stt_adaptive_multiplier = 2.0
        loop._stt_force_probe_after_skips = 8
        loop._stt_skipped_by_gate = 0
        loop._last_stt_text = ""
        loop.stt = stt

        frame = b"\x01\x00" * 2048
        payload = {
            "audio": base64.b64encode(frame).decode("ascii"),
            "sample_rate": 16000,
        }

        worker = asyncio.create_task(loop._audio_worker())
        try:
            await loop._audio_queue.put(payload)
            await asyncio.sleep(0.1)
            await loop._audio_queue.put(payload)
            await asyncio.wait_for(stt.called.wait(), timeout=0.7)
        finally:
            loop._running = False
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker

        assert stt.audio_bytes == len(frame) * 2
        assert stt.sample_rate == 16000

    asyncio.run(run_case())


@pytest.mark.parametrize(
    ("transcriptions", "times", "expected"),
    [
        (["Hello", "Hello"], [10.0, 10.1], ["Hello"]),
        (["Hello", "", "Hello"], [10.0, 10.1, 10.2], ["Hello", "Hello"]),
        (["Hello", "Hello"], [10.0, 20.0], ["Hello", "Hello"]),
    ],
)
def test_stt_deduplication_is_limited_to_one_utterance(
    monkeypatch, transcriptions, times, expected,
) -> None:
    clock = [0.0]
    monkeypatch.setattr("app.agent.loop.monotonic", lambda: clock[0], raising=False)

    async def run_case() -> None:
        bus = EventBus()
        loop = AgentLoop(
            bus=bus, llm=None, tts=AsyncMock(),
            stt=AsyncMock(transcribe_chunk=AsyncMock(side_effect=transcriptions)),
            memory=None, tools=None, frontend=None,
        )
        loop._running = True
        loop._stt_max_buffer_sec = 0.2
        loop._stt_input_rms_gate_enabled = False
        frame = b"\x01\x00" * 4000
        payload = {"audio": base64.b64encode(frame).decode("ascii"), "sample_rate": 16000}
        worker = asyncio.create_task(loop._audio_worker())
        try:
            for timestamp in times:
                clock[0] = timestamp
                await loop._audio_queue.put(payload)
                await asyncio.wait_for(loop._audio_queue.join(), timeout=1)
        finally:
            loop._running = False
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
        events = [await bus.consume() for _ in range(bus.qsize())]
        assert [event.payload["text"] for event in events] == expected

    asyncio.run(run_case())


def test_new_speech_interrupt_resets_transcript_deduplication() -> None:
    async def run_case() -> None:
        loop = AgentLoop(
            bus=EventBus(), llm=None, tts=AsyncMock(), stt=None,
            memory=None, tools=None, frontend=None,
        )
        loop._last_stt_text = "Hello"
        await loop._handle_event(
            Event(event_type=EventType.USER_INTERRUPTION, source="frontend", payload={})
        )
        assert loop._last_stt_text == ""

    asyncio.run(run_case())
