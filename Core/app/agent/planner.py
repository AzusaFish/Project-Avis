"""
Module: app/agent/planner.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 规划器：解析 LLM 输出 JSON，得到可执行动作。

from __future__ import annotations

import json
from dataclasses import dataclass

from app.core.events import AgentAction, AgentActionType


@dataclass(slots=True)
class PlannerResult:
    """PlannerResult: main class container for related behavior in this module."""
    action: AgentAction
    raw_text: str


def parse_model_action(raw_text: str) -> PlannerResult:
    # 将模型文本解析为结构化动作；失败时使用可执行的兜底动作。
    """Public API `parse_model_action` used by other modules or route handlers."""
    text = raw_text.strip()
    try:
        payload = json.loads(text)
        action_name = payload.get("action", "speak")
        action_type = AgentActionType(action_name)
        action = AgentAction(
            action_type=action_type,
            content=payload.get("text"),
            tool_name=payload.get("tool_name"),
            tool_args=payload.get("tool_args") or {},
            emotion=payload.get("emotion", "neutral"),
        )
        return PlannerResult(action=action, raw_text=text)
    except Exception:
        # 兜底策略：解析失败时按普通说话处理，避免中断主循环。
        # 这样即使模型偶发输出非 JSON，系统也不会“卡死”。
        fallback = AgentAction(
            action_type=AgentActionType.SPEAK,
            content=text,
            emotion="neutral",
        )
        return PlannerResult(action=fallback, raw_text=text)
