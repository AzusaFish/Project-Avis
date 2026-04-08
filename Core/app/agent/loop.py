"""
Module: app/agent/loop.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# Agent 主循环：消费事件、调用模型、执行工具并驱动前端。

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import re
from contextlib import suppress
from pathlib import Path

from app.agent.context_manager import ContextManager, rough_token_count
from app.agent.memory import MemoryFacade
from app.agent.planner import parse_model_action
from app.agent.prompt_builder import build_system_prompt
from app.core.bus import EventBus
from app.core.config import settings
from app.core.events import AgentActionType, AgentState, Event, EventType
from app.core.time_utils import format_now_local
from app.inputs.scheduler import mark_activity
from app.services.llm_router import LLMRouter
from app.services.frontend_gateway import FrontendGateway
from app.services.stt_service import STTService
from app.services.tts_service import TTSService
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

EMOTION_TO_ACTION = {
    "neutral": "普通",
    "happy": "开心",
    "angry": "生气",
    "sad": "难过",
    "thinking": "得意",
    "surprised": "惊讶",
}


class AgentLoop:
    """AgentLoop: main class container for related behavior in this module."""
    def __init__(
        self,
        bus: EventBus,
        llm: LLMRouter,
        tts: TTSService,
        stt: STTService,
        memory: MemoryFacade,
        tools: ToolRegistry,
        frontend: FrontendGateway,
    ) -> None:
        """Initialize the object state and cache required dependencies."""
        self.bus = bus
        self.llm = llm
        self.tts = tts
        self.stt = stt
        self.memory = memory
        self.tools = tools
        self.frontend = frontend
        self.ctx_manager = ContextManager()
        self._running = False
        self._system_prompt = build_system_prompt()
        self._audio_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=64)
        self._audio_worker_task: asyncio.Task | None = None
        self._stt_flush_gap_sec = 0.45
        self._stt_max_buffer_sec = 8.0
        self._kv_summary = ""
        self._kv_state_loaded = False
        self._turns_since_kv_compress = max(0, int(settings.kv_compress_min_turns))
        self._agent_state = AgentState.IDLE
        self._think_chain_count = 0
        # `_running` 相当于主循环停止标志位。

    async def _set_agent_state(self, state: AgentState) -> None:
        """Internal helper `_set_agent_state` used by this module implementation."""
        if self._agent_state == state:
            return
        self._agent_state = state
        await self.frontend.broadcast(
            {
                "protocol": "Live2DProtocol",
                "version": "1.1",
                "action": "agent_state",
                "code": 0,
                "message": "",
                "data": {"state": state.value},
            }
        )

    def _ensure_audio_worker(self) -> None:
        """Keep one STT audio worker alive; restart if previous task crashed."""
        if self._audio_worker_task and not self._audio_worker_task.done():
            return
        self._audio_worker_task = asyncio.create_task(self._audio_worker(), name="audio_worker")

    @staticmethod
    def _decode_audio_payload(payload: dict[str, object]) -> tuple[bytes, int] | None:
        """Decode one queue payload into pcm bytes and sample rate."""
        audio = str(payload.get("audio", ""))
        if not audio:
            return None
        try:
            pcm = base64.b64decode(audio)
        except Exception:
            return None
        if not pcm:
            return None
        try:
            sample_rate = int(payload.get("sample_rate", 16000))
        except Exception:
            sample_rate = 16000
        if sample_rate < 8000 or sample_rate > 96000:
            sample_rate = 16000
        return pcm, sample_rate

    async def _audio_worker(self) -> None:
        """Consume audio chunks serially to protect event loop from STT backpressure."""
        while self._running:
            payload = await self._audio_queue.get()
            taken = 1
            try:
                decoded_chunks: list[tuple[bytes, int]] = []
                first = self._decode_audio_payload(payload)
                if first is not None:
                    decoded_chunks.append(first)

                buffered_sec = 0.0
                if decoded_chunks:
                    buffered_sec = len(decoded_chunks[0][0]) / (2 * decoded_chunks[0][1])

                while self._running and buffered_sec < self._stt_max_buffer_sec:
                    try:
                        next_payload = await asyncio.wait_for(
                            self._audio_queue.get(),
                            timeout=self._stt_flush_gap_sec,
                        )
                    except TimeoutError:
                        break
                    taken += 1
                    decoded = self._decode_audio_payload(next_payload)
                    if decoded is None:
                        continue
                    decoded_chunks.append(decoded)
                    buffered_sec += len(decoded[0]) / (2 * decoded[1])

                if not decoded_chunks:
                    continue

                sample_rate = decoded_chunks[0][1]
                merged_parts: list[bytes] = []
                for pcm, sr in decoded_chunks:
                    if sr != sample_rate:
                        logger.warning(
                            "audio chunk sample_rate changed within one utterance: %s -> %s; dropping mismatched chunk",
                            sample_rate,
                            sr,
                        )
                        continue
                    merged_parts.append(pcm)
                if not merged_parts:
                    continue

                merged_pcm = b"".join(merged_parts)
                buffered_sec = len(merged_pcm) / (2 * sample_rate)
                timeout_sec = max(6.0, min(18.0, buffered_sec * 2.0 + 2.0))
                merged_b64 = base64.b64encode(merged_pcm).decode("ascii")
                text = (
                    await self.stt.transcribe_chunk(
                        merged_b64,
                        sample_rate=sample_rate,
                        timeout_sec=timeout_sec,
                    )
                ).strip()
                if text:
                    mark_activity()
                    await self.bus.publish(
                        Event(
                            event_type=EventType.USER_TEXT,
                            source="stt",
                            payload={"text": text},
                        )
                    )
            except Exception:
                logger.exception("audio worker failed while transcribing chunk")
            finally:
                for _ in range(taken):
                    self._audio_queue.task_done()

    async def run_forever(self) -> None:
        # 启动主事件循环，不断消费总线事件并分派处理。
        # 这是整个系统的“中枢调度器”。
        """Public API `run_forever` used by other modules or route handlers."""
        self._running = True
        self._ensure_audio_worker()
        await self._ensure_kv_state()
        logger.info("agent loop started")
        while self._running:
            self._ensure_audio_worker()
            # 事件驱动：按到达顺序逐个处理，避免复杂锁竞争。
            event = await self.bus.consume()
            try:
                await self._handle_event(event)
            except Exception:
                # 单条事件失败不应导致主循环退出，否则后续所有请求都会堆积。
                logger.exception("agent loop event handling failed")

    async def _emit_assistant_stream(self, text: str) -> None:
        # 将完整文本切分为小块推送前端，实现“边生成边显示”的体验。
        """Internal helper `_emit_assistant_stream` used by this module implementation."""
        step = max(1, settings.assistant_stream_chunk_chars)
        interval = max(0.0, settings.assistant_stream_interval_ms / 1000.0)
        current = ""
        for i in range(0, len(text), step):
            current += text[i : i + step]
            await self.frontend.broadcast(
                {
                    "protocol": "Live2DProtocol",
                    "version": "1.1",
                    "action": "assistant_stream",
                    "code": 0,
                    "message": "",
                    "data": {"text": current},
                }
            )
            if interval > 0:
                await asyncio.sleep(interval)

    async def _emit_runtime_error(self, text: str) -> None:
        # On runtime failure, push a visible assistant message to frontend instead of silent drop.
        """Internal helper `_emit_runtime_error` used by this module implementation."""
        err_text = text.strip()
        if not err_text:
            return
        await self.frontend.broadcast(
            {
                "protocol": "Live2DProtocol",
                "version": "1.1",
                "action": "assistant_stream",
                "code": 1,
                "message": "runtime_error",
                "data": {"text": err_text},
            }
        )
        await self.frontend.broadcast(
            {
                "protocol": "Live2DProtocol",
                "version": "1.1",
                "action": "add_history",
                "code": 1,
                "message": "runtime_error",
                "data": {"role": "assistant", "text": err_text},
            }
        )

    @staticmethod
    def _estimate_speech_duration_sec(text: str, speed: float = 1.0) -> float:
        """Estimate speech playback time to reduce premature subtitle replacement."""
        content = str(text or "").strip()
        if not content:
            return 0.0
        # A simple heuristic for English-like TTS pace with punctuation pause.
        chars_per_sec = 14.0 * max(0.5, float(speed))
        punctuation = sum(content.count(ch) for ch in ",.;:!?")
        return max(0.8, len(content) / chars_per_sec + punctuation * 0.08)

    @staticmethod
    def _messages_to_prompt_text(messages: list[dict[str, object]]) -> str:
        """Internal helper `_messages_to_prompt_text` used by this module implementation."""
        lines: list[str] = []
        for item in messages:
            role = str(item.get("role", "user")).upper()
            content_obj = item.get("content", "")
            if isinstance(content_obj, list):
                rendered_parts: list[str] = []
                for part in content_obj:
                    if not isinstance(part, dict):
                        rendered_parts.append(str(part))
                        continue
                    part_type = str(part.get("type", "")).lower()
                    if part_type == "text":
                        rendered_parts.append(str(part.get("text", "")))
                    elif part_type == "image_url":
                        rendered_parts.append("[IMAGE]")
                    else:
                        rendered_parts.append(f"[{part_type or 'PART'}]")
                content = "\n".join(x for x in rendered_parts if x)
            else:
                content = str(content_obj)
            lines.append(f"[{role}]\n{content}")
        return "\n\n".join(lines)

    @staticmethod
    def _clamp_reply_text(text: str, max_chars: int) -> str:
        """Clamp overly long model outputs to keep replies concise and TTS-friendly."""
        content = str(text or "").strip()
        limit = max(80, int(max_chars))
        if len(content) <= limit:
            return content

        cut = content[:limit]
        punct = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"), cut.rfind(";"))
        if punct >= int(limit * 0.55):
            cut = cut[: punct + 1]
        else:
            space = cut.rfind(" ")
            if space >= int(limit * 0.55):
                cut = cut[:space]
        return cut.rstrip() + "..."

    @staticmethod
    def _image_file_to_data_url(path_str: str) -> str:
        """Load local image file and convert to data URL for multimodal chat payload."""
        path = Path(path_str)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"image file not found: {path}")
        mime, _ = mimetypes.guess_type(path.name)
        if not mime:
            mime = "image/png"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{data}"

    async def _emit_llm_debug(self, *, stage: str, messages: list[dict[str, object]], raw_output: str = "") -> None:
        """Internal helper `_emit_llm_debug` used by this module implementation."""
        if not settings.llm_debug_to_frontend:
            return
        await self.frontend.broadcast(
            {
                "protocol": "Live2DProtocol",
                "version": "1.1",
                "action": "llm_debug",
                "code": 0,
                "message": "",
                "data": {
                    "stage": stage,
                    "messages": messages,
                    "prompt_text": self._messages_to_prompt_text(messages),
                    "raw_output": raw_output,
                },
            }
        )

    @staticmethod
    def _extract_partial_speak_text(raw: str) -> str | None:
        """Best-effort incremental parse for {"action":"speak","text":"..."} stream."""
        if '"speak"' not in raw.lower():
            return None

        m = re.search(r'"text"\s*:\s*"', raw)
        if not m:
            return None

        i = m.end()
        escaped = False
        complete = False
        encoded_parts: list[str] = []
        while i < len(raw):
            ch = raw[i]
            if escaped:
                encoded_parts.append("\\" + ch)
                escaped = False
                i += 1
                continue
            if ch == "\\":
                escaped = True
                i += 1
                continue
            if ch == '"':
                complete = True
                break
            encoded_parts.append(ch)
            i += 1

        encoded = "".join(encoded_parts)
        if not encoded and not complete:
            return ""

        # Drop unfinished trailing escape for partial chunks.
        if escaped and encoded.endswith("\\"):
            encoded = encoded[:-1]

        try:
            return str(json.loads(f'"{encoded}"'))
        except Exception:
            # Partial stream may contain unfinished escapes; keep a readable fallback.
            return encoded.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')

    def stop(self) -> None:
        # 外部停止入口：将循环标记置为 False。
        """Public API `stop` used by other modules or route handlers."""
        self._running = False
        if self._audio_worker_task:
            self._audio_worker_task.cancel()

    async def _ensure_kv_state(self) -> None:
        # 从 SQLite 元信息恢复上次的压缩摘要，保证重启后记忆连续。
        """Internal helper `_ensure_kv_state` used by this module implementation."""
        if self._kv_state_loaded:
            return
        try:
            self._kv_summary = (await self.memory.sqlite.get_meta("kv_summary_text", "")).strip()
        except Exception:
            logger.exception("failed to load kv summary state")
            self._kv_summary = ""
        self._kv_state_loaded = True

    @staticmethod
    def _history_token_estimate(history: list[dict[str, str]], latest_input: str) -> int:
        # 粗略估算上下文 token，触发阈值时进入压缩流程。
        """Internal helper `_history_token_estimate` used by this module implementation."""
        total = rough_token_count(latest_input)
        for item in history:
            total += rough_token_count(str(item.get("content", "")))
        return total

    async def _compress_history_with_llm(
        self,
        history: list[dict[str, str]],
        latest_input: str,
    ) -> str:
        # 调用 LLM 生成高密度对话摘要（JSON 输出）。
        """Internal helper `_compress_history_with_llm` used by this module implementation."""
        source_messages = history[-max(12, int(settings.kv_compress_source_messages)):]
        payload = [
            {
                "role": str(m.get("role", "user")),
                "content": str(m.get("content", ""))[:700],
            }
            for m in source_messages
            if str(m.get("content", "")).strip()
        ]
        if not payload:
            return ""

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a context compressor. Return JSON only with key `summary`. "
                    "Write a dense but factual summary preserving user preferences, ongoing tasks, "
                    "important commitments, and unresolved questions."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Compress the following conversation for future context reuse. "
                    "Keep it concise and avoid duplication.\n\n"
                    f"latest_input: {latest_input}\n"
                    + json.dumps(payload, ensure_ascii=False)
                ),
            },
        ]

        raw = await self.llm.generate(messages)
        data = json.loads(raw)
        summary = str(data.get("summary") or data.get("compressed_summary") or "").strip()
        return summary[:3000]

    async def _maybe_compress_history(
        self,
        history: list[dict[str, str]],
        latest_input: str,
    ) -> list[dict[str, str]]:
        # 当历史 token 过高时进行压缩，并用“摘要 + 最近对话尾部”替换短期上下文。
        """Internal helper `_maybe_compress_history` used by this module implementation."""
        await self._ensure_kv_state()

        if not history:
            return history

        history_tokens = self._history_token_estimate(history=history, latest_input=latest_input)
        should_compress = (
            bool(settings.kv_compress_enabled)
            and history_tokens >= int(settings.kv_compress_trigger_tokens)
            and self._turns_since_kv_compress >= int(settings.kv_compress_min_turns)
        )

        if should_compress:
            try:
                summary = await self._compress_history_with_llm(history=history, latest_input=latest_input)
                if summary:
                    self._kv_summary = summary
                    self._turns_since_kv_compress = 0
                    await self.memory.sqlite.set_meta("kv_summary_text", summary)
                    logger.info("kv compression updated summary (len=%s)", len(summary))
            except Exception:
                logger.exception("kv compression failed")

        if not self._kv_summary:
            return history

        keep_turns = max(2, int(settings.kv_compress_keep_last_turns))
        tail_count = keep_turns * 2
        tail = history[-tail_count:] if len(history) > tail_count else history
        return [{"role": "system", "content": f"[KV_SUMMARY]\n{self._kv_summary}"}, *tail]

    async def _handle_event(self, event: Event) -> None:
        # 统一处理不同事件类型，驱动 STT/LLM/Tool/TTS 全链路。
        # 这个函数是“状态机 + 分发器”的角色。
        """Internal helper `_handle_event` used by this module implementation."""
        if event.event_type == EventType.USER_AUDIO_CHUNK:
            # 主循环只做入队，重活交给单 worker，避免 STT 堵塞事件循环。
            audio = str(event.payload.get("audio", ""))
            if audio:
                mark_activity(kind="user_audio")
                sample_rate = int(event.payload.get("sample_rate", 16000))
                packet = {"audio": audio, "sample_rate": sample_rate}
                try:
                    self._audio_queue.put_nowait(packet)
                except asyncio.QueueFull:
                    # 丢弃最旧切片，优先保留最新语音。
                    with suppress(asyncio.QueueEmpty):
                        _ = self._audio_queue.get_nowait()
                        self._audio_queue.task_done()
                    self._audio_queue.put_nowait(packet)
            return

        if event.event_type == EventType.USER_INTERRUPTION:
            # 用户插嘴时立即打断 TTS。
            mark_activity(kind="user_interruption")
            await self.tts.stop_current()
            await self.bus.publish(Event(event_type=EventType.TTS_STOP, source="agent", payload={}))
            return

        if event.event_type not in {
            EventType.USER_TEXT,
            EventType.WECHAT_MESSAGE,
            EventType.GAME_STATE,
            EventType.SCHEDULE_TICK,
            EventType.TOOL_RESULT,
        }:
            return

        raw_user_text = event.payload.get("text", "").strip()
        silent_input = bool(event.payload.get("silent", False))
        system_inject = bool(event.payload.get("system_inject", False))
        is_think_followup = event.source == "agent_think" and silent_input and system_inject
        if not raw_user_text and event.event_type != EventType.SCHEDULE_TICK:
            return

        if not is_think_followup:
            self._think_chain_count = 0

        vision_image_data_url: str | None = None

        if event.event_type == EventType.SCHEDULE_TICK:
            # 定时主动事件：根据积极度动态调整策略。
            engagement = float(event.payload.get("engagement", 0.5))
            can_start_topic = bool(event.payload.get("can_start_topic", True))
            prefer_tool = bool(event.payload.get("prefer_tool", False))
            dynamic_silence = int(event.payload.get("dynamic_silence_sec", settings.proactive_silence_sec))
            if not can_start_topic:
                user_text = (
                    "Silence timeout reached. User may be away. "
                    f"engagement={engagement:.2f}, silence_window={dynamic_silence}s. "
                    "Prefer action 'idle'. Only call a tool if it is truly useful. "
                    "Do not start a proactive topic now."
                )
            elif prefer_tool:
                user_text = (
                    "Silence timeout reached. "
                    f"engagement={engagement:.2f}, silence_window={dynamic_silence}s. "
                    "You may choose speak/tool_call/idle. Prefer a brief utility-first check or tool-assisted action. "
                    "If there is no real value, choose idle."
                )
            else:
                user_text = (
                    "Silence timeout reached. "
                    f"engagement={engagement:.2f}, silence_window={dynamic_silence}s. "
                    "You may start a brief proactive topic, or choose idle if not needed."
                )
        elif event.event_type == EventType.TOOL_RESULT:
            # 工具回调写入 system 记忆，避免污染 user 语义。
            tool_name = str(event.payload.get("tool_name", "")).strip().lower()
            tool_result = str(event.payload.get("tool_result", "")).strip()
            if tool_name == "desktop_screenshot":
                screenshot_path = ""
                screenshot_question = "Describe what is shown on the screenshot and answer naturally."
                if tool_result:
                    try:
                        obj = json.loads(tool_result)
                        screenshot_path = str(obj.get("screenshot_path", "")).strip()
                        q = str(obj.get("question", "")).strip()
                        if q:
                            screenshot_question = q
                    except Exception:
                        screenshot_path = ""

                if screenshot_path:
                    try:
                        vision_image_data_url = self._image_file_to_data_url(screenshot_path)
                        await self.memory.append_dialogue(
                            "system",
                            f"[TOOL_RESULT] screenshot_path={screenshot_path}",
                        )
                        user_text = (
                            "You now have a fresh desktop screenshot. "
                            f"Task: {screenshot_question}. "
                            "Interpret the image directly yourself and reply concisely in style."
                        )
                    except Exception as exc:
                        await self.memory.append_dialogue(
                            "system",
                            f"[TOOL_RESULT] screenshot unusable: {exc}",
                        )
                        user_text = "Use the latest tool result and continue the conversation naturally."
                else:
                    await self.memory.append_dialogue("system", f"[TOOL_RESULT] {raw_user_text}")
                    user_text = "Use the latest tool result and continue the conversation naturally."
            else:
                await self.memory.append_dialogue("system", f"[TOOL_RESULT] {raw_user_text}")
                user_text = "Use the latest tool result and continue the conversation naturally."
        else:
            user_text = raw_user_text
            if system_inject:
                await self.memory.append_dialogue("system", user_text)
            elif silent_input:
                await self.memory.append_dialogue("system", f"[SILENT_INPUT] {user_text}")
            else:
                mark_activity(kind="user_text", text=user_text)
                await self.memory.append_dialogue("user", user_text)
                await self.frontend.broadcast(
                    {
                        "protocol": "Live2DProtocol",
                        "version": "1.1",
                        "action": "add_history",
                        "code": 0,
                        "message": "",
                        "data": {"role": "user", "text": user_text},
                    }
                )

        await self._set_agent_state(AgentState.THINKING)

        self._turns_since_kv_compress += 1

        history_limit = max(16, int(settings.kv_compress_source_messages) * 2)
        history = await self.memory.recent_dialogue(limit=history_limit)
        history = await self._maybe_compress_history(history=history, latest_input=user_text)

        persona_examples = self.memory.retrieve_persona_examples(query=user_text)
        long_term_notes = self.memory.retrieve_long_term_notes(
            query=user_text,
            top_k=max(1, int(settings.memory_recall_top_k)),
        )
        system_prompt = (
            self._system_prompt
            + "\n"
            + f"[System Context] Current local time is {format_now_local()}."
        )
        if long_term_notes:
            compact_notes = [x.strip() for x in long_term_notes if str(x).strip()]
            if compact_notes:
                system_prompt += "\n[Long-term Memory Notes]\n" + "\n".join(
                    f"- {x}" for x in compact_notes[: max(1, int(settings.memory_recall_top_k))]
                )
        ctx = self.ctx_manager.build_slice(
            system_prompt=system_prompt,
            persona_examples=persona_examples,
            history=history,
            latest_input=user_text,
        )

        messages = ctx.render_messages()
        if vision_image_data_url and messages:
            messages[-1] = {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": vision_image_data_url}},
                ],
            }
        await self._emit_llm_debug(stage="request", messages=messages)

        stream_preview_text = ""
        try:
            if settings.llm_stream:
                # 真流式：在 JSON 生成过程中实时提取 text 字段并推给前端。
                chunks: list[str] = []
                last_stream_text = ""
                async for delta in self.llm.generate_stream(messages):
                    chunks.append(delta)
                    raw_partial = "".join(chunks)
                    partial_text = self._extract_partial_speak_text(raw_partial)
                    if partial_text is None or partial_text == last_stream_text:
                        continue
                    last_stream_text = partial_text
                    stream_preview_text = partial_text
                    await self.frontend.broadcast(
                        {
                            "protocol": "Live2DProtocol",
                            "version": "1.1",
                            "action": "assistant_stream",
                            "code": 0,
                            "message": "",
                            "data": {"text": partial_text},
                        }
                    )
                model_text = "".join(chunks)
            else:
                model_text = await self.llm.generate(messages)
        except Exception as exc:
            logger.exception("llm request failed")
            await self._emit_runtime_error(
                "LLM 服务暂时不可用（可能是推理服务忙碌或模型未就绪）。"
                "请稍后重试，或检查 /health/deps 与 LLM 服务日志。"
            )
            return

        await self._emit_llm_debug(stage="response", messages=messages, raw_output=model_text)

        # LLM 输出必须是动作 JSON；失败时 planner 内部会回退到“普通说话”。
        plan = parse_model_action(model_text)

        if plan.action.action_type == AgentActionType.TOOL_CALL and plan.action.tool_name:
            # 工具调用走“再入队”模式：把结果作为 TOOL_RESULT 让下一轮继续推理。
            self._think_chain_count = 0
            tool_result = await self.tools.call(plan.action.tool_name, plan.action.tool_args or {})
            await self.bus.publish(
                Event(
                    event_type=EventType.TOOL_RESULT,
                    source="tool",
                    payload={
                        "text": f"Tool result: {tool_result}",
                        "tool_name": plan.action.tool_name,
                        "tool_result": tool_result,
                    },
                )
            )
            return

        if plan.action.action_type == AgentActionType.THINK:
            # think 分支：先把当前续说内容输出给用户，再静默注入继续下一句。
            text = self._clamp_reply_text(plan.action.content or "", settings.assistant_max_chars)
            if text:
                mark_activity(kind="assistant_response")
                await self.memory.append_dialogue("assistant", text)

                if settings.llm_stream:
                    if stream_preview_text != text:
                        await self.frontend.broadcast(
                            {
                                "protocol": "Live2DProtocol",
                                "version": "1.1",
                                "action": "assistant_stream",
                                "code": 0,
                                "message": "",
                                "data": {"text": text},
                            }
                        )
                else:
                    await self._emit_assistant_stream(text)

                if not settings.tts_streaming_mode:
                    await self.tts.speak(text=text, emotion=plan.action.emotion or "thinking")

                await self.frontend.broadcast(
                    {
                        "protocol": "Live2DProtocol",
                        "version": "1.1",
                        "action": "add_history",
                        "code": 0,
                        "message": "",
                        "data": {"role": "assistant", "text": text},
                    }
                )
                await self.frontend.broadcast(
                    {
                        "protocol": "Live2DProtocol",
                        "version": "1.1",
                        "action": "live2d_action",
                        "code": 0,
                        "message": "",
                        "data": {
                            "action_name": EMOTION_TO_ACTION.get(plan.action.emotion or "thinking", "得意")
                        },
                    }
                )
                await self.bus.publish(
                    Event(
                        event_type=EventType.AGENT_RESPONSE,
                        source="agent",
                        payload={"text": text, "emotion": plan.action.emotion or "thinking"},
                    )
                )

            max_rounds = max(1, int(settings.think_max_continuations))
            next_round = self._think_chain_count + 1
            if next_round >= max_rounds:
                self._think_chain_count = 0
                await self._set_agent_state(AgentState.IDLE)
                return

            self._think_chain_count = next_round

            if settings.tts_streaming_mode and text:
                await asyncio.sleep(self._estimate_speech_duration_sec(text, settings.kokoro_speed))

            await self.bus.publish(
                Event(
                    event_type=EventType.USER_TEXT,
                    source="agent_think",
                    payload={
                        "text": "[SYSTEM: Continue speaking naturally from where you stopped. Output the next visible segment only.]",
                        "silent": True,
                        "system_inject": True,
                    },
                )
            )
            return

        if plan.action.action_type == AgentActionType.ASK:
            # ask 分支：输出提问后交还控制权，等待用户输入。
            self._think_chain_count = 0
            text = self._clamp_reply_text(plan.action.content or "", settings.assistant_max_chars)
            if text:
                await self.memory.append_dialogue("assistant", text)
                if settings.llm_stream:
                    if stream_preview_text != text:
                        await self.frontend.broadcast(
                            {
                                "protocol": "Live2DProtocol",
                                "version": "1.1",
                                "action": "assistant_stream",
                                "code": 0,
                                "message": "",
                                "data": {"text": text},
                            }
                        )
                else:
                    await self._emit_assistant_stream(text)

                if not settings.tts_streaming_mode:
                    await self.tts.speak(text=text, emotion=plan.action.emotion or "neutral")

                await self.frontend.broadcast(
                    {
                        "protocol": "Live2DProtocol",
                        "version": "1.1",
                        "action": "add_history",
                        "code": 0,
                        "message": "",
                        "data": {"role": "assistant", "text": text},
                    }
                )

            await self._set_agent_state(AgentState.ASKING)
            await self.frontend.broadcast(
                {
                    "protocol": "Live2DProtocol",
                    "version": "1.1",
                    "action": "show_user_text_input",
                    "code": 0,
                    "message": "",
                    "data": {"reason": "ask", "prompt": text},
                }
            )
            return

        if plan.action.action_type == AgentActionType.SPEAK and plan.action.content:
            # speak 分支：写记忆 -> 推字幕 -> 播语音 -> 推动作 -> 发响应事件。
            self._think_chain_count = 0
            text = self._clamp_reply_text(plan.action.content, settings.assistant_max_chars)
            mark_activity(kind="assistant_response")
            await self.memory.append_dialogue("assistant", text)
            if settings.llm_stream:
                if stream_preview_text != text:
                    await self.frontend.broadcast(
                        {
                            "protocol": "Live2DProtocol",
                            "version": "1.1",
                            "action": "assistant_stream",
                            "code": 0,
                            "message": "",
                            "data": {"text": text},
                        }
                    )
            else:
                await self._emit_assistant_stream(text)

            # Streaming mode relies on frontend incremental TTS playback.
            if not settings.tts_streaming_mode:
                await self.tts.speak(text=text, emotion=plan.action.emotion or "neutral")
            await self.frontend.broadcast(
                {
                    "protocol": "Live2DProtocol",
                    "version": "1.1",
                    "action": "add_history",
                    "code": 0,
                    "message": "",
                    "data": {"role": "assistant", "text": text},
                }
            )
            await self.frontend.broadcast(
                {
                    "protocol": "Live2DProtocol",
                    "version": "1.1",
                    "action": "live2d_action",
                    "code": 0,
                    "message": "",
                    "data": {
                        "action_name": EMOTION_TO_ACTION.get(plan.action.emotion or "neutral", "普通")
                    },
                }
            )
            await self.bus.publish(
                Event(
                    event_type=EventType.AGENT_RESPONSE,
                    source="agent",
                    payload={"text": text, "emotion": plan.action.emotion or "neutral"},
                )
            )
            await self._set_agent_state(AgentState.IDLE)
            return

        if plan.action.action_type == AgentActionType.IDLE:
            self._think_chain_count = 0
            await self._set_agent_state(AgentState.IDLE)

