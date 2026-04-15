"""
Module: app/core/events.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 事件与动作的数据结构定义：系统内部统一消息协议。

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class EventType(str, Enum):
    USER_TEXT = "user_text"
    USER_AUDIO_CHUNK = "user_audio_chunk"
    USER_INTERRUPTION = "user_interruption"
    WECHAT_MESSAGE = "wechat_message"
    GAME_STATE = "game_state"
    SCHEDULE_TICK = "schedule_tick"
    TOOL_RESULT = "tool_result"
    AGENT_RESPONSE = "agent_response"
    TTS_STOP = "tts_stop"
    LIVE2D_CONTROL = "live2d_control"


@dataclass(slots=True)
class Event:
    event_type: EventType
    source: str
    payload: dict[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid4()))
    ts: datetime = field(default_factory=datetime.utcnow)


class AgentActionType(str, Enum):
    SPEAK = "speak"
    TOOL_CALL = "tool_call"
    LIVE2D = "live2d"
    THINK = "think"
    ASK = "ask"
    IDLE = "idle"


class AgentState(str, Enum):
    IDLE = "idle"
    ASKING = "asking"
    THINKING = "thinking"


@dataclass(slots=True)
class AgentAction:
    action_type: AgentActionType
    content: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    emotion: str | None = None
