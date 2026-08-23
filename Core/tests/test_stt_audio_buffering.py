from __future__ import annotations

import asyncio
import base64
from contextlib import suppress

from app.agent.loop import AgentLoop


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
