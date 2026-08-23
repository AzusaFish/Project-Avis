"""
Module: app/tools/live2d_tool.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# Live2D 控制工具：生成动作指令，供前端执行。

from __future__ import annotations

import json
from typing import Any

from app.services.frontend_gateway import FrontendGateway


def _norm_key(text: str) -> str:
    return "".join(ch for ch in text.strip().lower() if ch not in {" ", "_", "-"})


ACTION_ALIASES = {
    _norm_key("neutral"): "普通",
    _norm_key("normal"): "普通",
    _norm_key("idle"): "普通",
    _norm_key("普通"): "普通",
    _norm_key("happy"): "开心",
    _norm_key("smile"): "开心",
    _norm_key("开心"): "开心",
    _norm_key("angry"): "生气",
    _norm_key("mad"): "生气",
    _norm_key("生气"): "生气",
    _norm_key("sad"): "难过",
    _norm_key("难过"): "难过",
    _norm_key("thinking"): "得意",
    _norm_key("think"): "得意",
    _norm_key("得意"): "得意",
    _norm_key("surprised"): "惊讶",
    _norm_key("surprise"): "惊讶",
    _norm_key("wow"): "惊讶",
    _norm_key("惊讶"): "惊讶",
}

MOTION_ALIASES = {
    _norm_key("nod"): "TapHead",
    _norm_key("headnod"): "TapHead",
    _norm_key("点头"): "TapHead",
    _norm_key("shake"): "Flick",
    _norm_key("headshake"): "Flick",
    _norm_key("摇头"): "Flick",
    _norm_key("wave"): "TapBody",
    _norm_key("hello"): "TapBody",
    _norm_key("招手"): "TapBody",
}


class Live2DControlTool:
    name = "live2d_control"

    def __init__(self, frontend: FrontendGateway | None = None) -> None:
        self._frontend = frontend

    async def call(self, args: dict) -> str:
        action_name = self._resolve_action_name(
            args.get("action_name") or args.get("action") or args.get("emotion")
        )

        expression = self._resolve_expression(args.get("expression"))
        motion_group = self._resolve_motion_group(
            args.get("motion_group") or args.get("motion") or args.get("gesture")
        )
        motion_index = self._resolve_motion_index(args.get("motion_index") or args.get("index"))

        # If explicit expression is provided but no action name, derive one for compatibility.
        if expression is not None and not action_name:
            if isinstance(expression, str):
                action_name = self._resolve_action_name(expression)
            if not action_name:
                action_name = "普通"

        if not action_name:
            action_name = "普通"

        payload_data: dict[str, Any] = {"action_name": action_name}
        if expression is not None:
            payload_data["expression"] = expression
        if motion_group:
            payload_data["motion_group"] = motion_group
        if motion_index is not None:
            payload_data["motion_index"] = motion_index

        if self._frontend is not None:
            await self._frontend.broadcast(
                {
                    "protocol": "Live2DProtocol",
                    "version": "1.1",
                    "action": "live2d_action",
                    "code": 0,
                    "message": "",
                    "data": payload_data,
                }
            )

        return json.dumps(
            {
                "ok": True,
                "tool": "live2d_control",
                "applied": payload_data,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _resolve_action_name(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return ACTION_ALIASES.get(_norm_key(text), text)

    @staticmethod
    def _resolve_motion_group(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return MOTION_ALIASES.get(_norm_key(text), text)

    @staticmethod
    def _resolve_expression(value: Any) -> str | int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if not text:
            return None
        if text.lstrip("+-").isdigit():
            try:
                return int(text)
            except Exception:
                pass
        return ACTION_ALIASES.get(_norm_key(text), text)

    @staticmethod
    def _resolve_motion_index(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if not text:
            return None
        try:
            return int(float(text))
        except Exception:
            return None
