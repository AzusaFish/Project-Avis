import asyncio
from contextlib import suppress

from app.agent.loop import AgentLoop
from app.core.bus import EventBus
from app.core.events import Event, EventType


def test_audio_and_interrupt_do_not_wait_for_normal_event_consumer() -> None:
    async def run_case() -> None:
        bus = EventBus(maxsize=1)
        await bus.publish(Event(event_type=EventType.USER_TEXT, source="test", payload={"text": "busy"}))
        await bus.publish(Event(event_type=EventType.USER_AUDIO_CHUNK, source="test", payload={"audio": "first"}))
        await bus.publish(Event(event_type=EventType.USER_AUDIO_CHUNK, source="test", payload={"audio": "latest"}))
        await bus.publish(Event(event_type=EventType.USER_INTERRUPTION, source="test", payload={}))

        assert (await bus.consume_input()).event_type == EventType.USER_INTERRUPTION
        assert (await bus.consume_input()).payload["audio"] == "latest"
        assert (await bus.consume()).event_type == EventType.USER_TEXT

    asyncio.run(run_case())


def test_interrupt_cancels_an_active_response() -> None:
    async def run_case() -> None:
        loop = object.__new__(AgentLoop)
        loop._running = True
        loop.bus = EventBus()
        loop._active_event_task = asyncio.create_task(asyncio.sleep(30))
        handled = asyncio.Event()

        async def handle_event(event: Event) -> None:
            handled.set()

        loop._handle_event = handle_event
        worker = asyncio.create_task(loop._input_worker())
        try:
            await loop.bus.publish(Event(event_type=EventType.USER_INTERRUPTION, source="test", payload={}))
            await asyncio.wait_for(handled.wait(), timeout=1)
            with suppress(asyncio.CancelledError):
                await loop._active_event_task
            assert loop._active_event_task.cancelled()
        finally:
            loop._running = False
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker

    asyncio.run(run_case())


def test_new_utterance_resets_stt_duplicate_suppression() -> None:
    async def run_case() -> None:
        class FakeTts:
            async def stop_current(self) -> None:
                return None

        loop = object.__new__(AgentLoop)
        loop.bus = EventBus()
        loop.tts = FakeTts()
        loop._last_stt_text = "你好"
        loop._last_stt_at = 123.0

        await loop._handle_event(Event(event_type=EventType.USER_INTERRUPTION, source="test", payload={}))

        assert loop._last_stt_text == ""
        assert loop._last_stt_at == 0.0
        assert (await loop.bus.consume()).event_type == EventType.TTS_STOP

    asyncio.run(run_case())
