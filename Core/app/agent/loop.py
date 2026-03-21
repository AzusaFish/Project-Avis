"""
Module: app/agent/loop.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# Agent 主循环：消费事件、调用模型、执行工具并驱动前端。

from __future__ import annotations

import asyncio
import logging

from app.agent.context_manager import ContextManager
from app.agent.memory import MemoryFacade
from app.agent.planner import parse_model_action
from app.agent.prompt_builder import build_system_prompt
from app.core.bus import EventBus
from app.core.config import settings
from app.core.events import AgentActionType, Event, EventType
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
        # `_running` 相当于主循环停止标志位。

    async def run_forever(self) -> None:
        # 启动主事件循环，不断消费总线事件并分派处理。
        # 这是整个系统的“中枢调度器”。
        """Public API `run_forever` used by other modules or route handlers."""
        self._running = True
        logger.info("agent loop started")
        while self._running:
            # 事件驱动：按到达顺序逐个处理，避免复杂锁竞争。
            event = await self.bus.consume()
            try:
                await self._handle_event(event)
            except Exception:
                # 单条事件失败不应导致主循环退出，否则后续所有请求都会堆积。
                logger.exception("agent loop event handling failed")

    async def _emit_assistant_stream(self, text: str) -> None:
        # 将完整文本切分为小块推送前端，实现“边生成边显示”的体验。
        # C++ 类比：类似把大字符串按块增量 flush 到 UI。
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

    def stop(self) -> None:
        # 外部停止入口：将循环标记置为 False。
        """Public API `stop` used by other modules or route handlers."""
        self._running = False

    async def _handle_event(self, event: Event) -> None:
        # 统一处理不同事件类型，驱动 STT/LLM/Tool/TTS 全链路。
        # 这个函数是“状态机 + 分发器”的角色。
        """Internal helper `_handle_event` used by this module implementation."""
        if event.event_type == EventType.USER_AUDIO_CHUNK:
            # 音频事件先转文本，再回灌为 USER_TEXT，统一后续处理链路。
            audio = event.payload.get("audio", "")
            sample_rate = int(event.payload.get("sample_rate", 16000))
            if audio:
                # 先语音转文本，再重新投递 USER_TEXT，实现链路复用。
                text = (await self.stt.transcribe_chunk(audio, sample_rate=sample_rate)).strip()
                if text:
                    await self.bus.publish(
                        Event(
                            event_type=EventType.USER_TEXT,
                            source="stt",
                            payload={"text": text},
                        )
                    )
            return

        if event.event_type == EventType.USER_INTERRUPTION:
            # 用户插嘴时立即打断 TTS。
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

        user_text = event.payload.get("text", "").strip()
        if not user_text and event.event_type != EventType.SCHEDULE_TICK:
            return

        if event.event_type == EventType.SCHEDULE_TICK:
            # 定时主动话题不依赖用户输入文本。
            user_text = "Silence timeout reached. Start a proactive topic briefly."
        else:
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

        history = await self.memory.recent_dialogue()
        persona_examples = self.memory.retrieve_persona_examples(query=user_text)
        ctx = self.ctx_manager.build_slice(
            system_prompt=self._system_prompt,
            persona_examples=persona_examples,
            history=history,
            latest_input=user_text,
        )

        try:
            if settings.llm_stream:
                # 流式聚合：边接收 token 边拼接，末尾再统一交给动作解析。
                chunks: list[str] = []
                async for delta in self.llm.generate_stream(ctx.render_messages()):
                    chunks.append(delta)
                model_text = "".join(chunks)
            else:
                model_text = await self.llm.generate(ctx.render_messages())
        except Exception as exc:
            logger.exception("llm request failed")
            await self._emit_runtime_error(
                "LLM 服务暂时不可用（可能是 Ollama 忙碌或模型未就绪）。"
                "请稍后重试，或检查 /health/deps 与 Ollama 日志。"
            )
            return

        # LLM 输出必须是动作 JSON；失败时 planner 内部会回退到“普通说话”。
        plan = parse_model_action(model_text)

        if plan.action.action_type == AgentActionType.TOOL_CALL and plan.action.tool_name:
            # 工具调用走“再入队”模式：把结果作为 TOOL_RESULT 让下一轮继续推理。
            tool_result = await self.tools.call(plan.action.tool_name, plan.action.tool_args or {})
            await self.bus.publish(
                Event(
                    event_type=EventType.TOOL_RESULT,
                    source="tool",
                    payload={"text": f"Tool result: {tool_result}"},
                )
            )
            return

        if plan.action.action_type == AgentActionType.SPEAK and plan.action.content:
            # speak 分支：写记忆 -> 推字幕 -> 播语音 -> 推动作 -> 发响应事件。
            text = plan.action.content.strip()
            await self.memory.append_dialogue("assistant", text)
            await self._emit_assistant_stream(text)
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
