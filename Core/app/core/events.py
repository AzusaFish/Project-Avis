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
    """EventType: main class container for related behavior in this module."""
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
    # 统一事件实体：所有输入、工具结果、输出都转成此结构。
    # 字段语义：
    # - event_type: 事件类型（决定处理分支）
    # - source: 来源标识（frontend/stt/wechat/...）
    # - payload: 动态数据载体（dict，按 event_type 解释）
    # - event_id: 追踪 ID，便于日志关联
    # - ts: 事件创建时间（UTC）
    """Event: main class container for related behavior in this module."""
    event_type: EventType
    source: str
    payload: dict[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid4()))
    ts: datetime = field(default_factory=datetime.utcnow)


class AgentActionType(str, Enum):
    # LLM 规划后可执行动作类型。
    # 这层是“模型输出协议”，不是用户输入事件。
    """AgentActionType: main class container for related behavior in this module."""
    SPEAK = "speak"
    TOOL_CALL = "tool_call"
    LIVE2D = "live2d"
    IDLE = "idle"


@dataclass(slots=True)
class AgentAction:
    # 动作参数容器：
    # - SPEAK 主要用 content/emotion
    # - TOOL_CALL 主要用 tool_name/tool_args
    """AgentAction: main class container for related behavior in this module."""
    action_type: AgentActionType
    content: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    emotion: str | None = None
