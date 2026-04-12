"""
Module: app/agent/context_manager.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 上下文管理：在 token 预算内裁剪历史、范例与最新输入。

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import settings


def rough_token_count(text: str) -> int:
    # 快速近似估算，避免每次都依赖重量级 tokenizer。
    # 这里只做经验估算，不是精确 token 数。
    """Public API `rough_token_count` used by other modules or route handlers."""
    return max(1, len(text) // 3)


@dataclass(slots=True)
class ContextSlice:
    """ContextSlice: main class container for related behavior in this module."""
    system_prompt: str
    persona_examples: list[str]
    short_history: list[dict[str, str]]
    latest_input: str

    def render_messages(self) -> list[dict[str, str]]:
        # 按模型可直接消费的 chat messages 结构输出上下文切片。
        """Public API `render_messages` used by other modules or route handlers."""
        messages: list[dict[str, str]] = [{"role": "system", "content": self.system_prompt}]
        if self.persona_examples:
            messages.append(
                {
                    "role": "system",
                    "content": "Persona style examples:\n" + "\n".join(self.persona_examples),
                }
            )
        for item in self.short_history:
            role = str(item.get("role", "user")).strip().lower()
            if role not in {"user", "assistant", "system", "tool"}:
                role = "user"
            messages.append({"role": role, "content": str(item.get("content", ""))})

        latest = str(self.latest_input or "")
        latest_norm = latest.strip()
        should_append_latest = bool(latest_norm)
        if should_append_latest and self.short_history:
            last_content = str(self.short_history[-1].get("content", "")).strip()
            if last_content == latest_norm:
                should_append_latest = False

        if should_append_latest:
            messages.append({"role": "user", "content": latest})
        return messages


class ContextManager:
    """ContextManager: main class container for related behavior in this module."""
    def __init__(self) -> None:
        # 初始化上下文预算参数，统一从配置读取。
        """Initialize the object state and cache required dependencies."""
        self.max_context = settings.llm_max_context
        self.reserve_response = settings.context_reserved_for_response
        self.reserve_tools = settings.context_reserved_for_tools

    def build_slice(
        self,
        system_prompt: str,
        persona_examples: list[str],
        history: list[dict[str, Any]],
        latest_input: str,
    ) -> ContextSlice:
        # 在预算限制下选择“recent_window + pinned_items”的双通道上下文。
        """Public API `build_slice` used by other modules or route handlers."""
        budget = self.max_context - self.reserve_response - self.reserve_tools
        if budget <= 0:
            budget = max(512, self.max_context // 2)

        used = rough_token_count(system_prompt) + rough_token_count(latest_input)

        selected_examples: list[str] = []
        for ex in persona_examples:
            t = rough_token_count(ex)
            if used + t > budget:
                break
            selected_examples.append(ex)
            used += t

        recent_window = max(1, int(getattr(settings, "memory_context_recent_window", 16)))
        pinned_limit = max(0, int(getattr(settings, "memory_context_pinned_limit", 8)))
        pin_threshold = float(getattr(settings, "memory_pin_importance_threshold", 0.9))

        normalized_history: list[dict[str, object]] = []
        for idx, item in enumerate(history):
            line = str(item.get("content", "") or "")
            if not line:
                continue
            role = str(item.get("role", "user")).strip().lower()
            if role not in {"user", "assistant", "system", "tool"}:
                role = "user"
            t = int(item.get("token_estimate", 0) or 0)
            if t <= 0:
                t = rough_token_count(line)
            normalized_history.append(
                {
                    "idx": idx,
                    "role": role,
                    "content": line,
                    "importance_score": float(item.get("importance_score", 0.0) or 0.0),
                    "token_estimate": t,
                }
            )

        selected_idx: set[int] = set()

        # 通道 1：最近窗口，按新到旧优先保留。
        recent_items = normalized_history[-recent_window:]
        for item in reversed(recent_items):
            t = int(item["token_estimate"])
            if used + t > budget:
                continue
            selected_idx.add(int(item["idx"]))
            used += t

        # 通道 2：高重要钉住项（限定数量，避免挤爆预算）。
        pinned_pool = [
            item
            for item in normalized_history[:-recent_window]
            if float(item["importance_score"]) >= pin_threshold
        ]
        pinned_pool.sort(key=lambda x: (float(x["importance_score"]), int(x["idx"])), reverse=True)
        for item in pinned_pool[:pinned_limit]:
            idx = int(item["idx"])
            if idx in selected_idx:
                continue
            t = int(item["token_estimate"])
            if used + t > budget:
                continue
            selected_idx.add(idx)
            used += t

        selected_history: list[dict[str, str]] = []
        for item in normalized_history:
            idx = int(item["idx"])
            if idx not in selected_idx:
                continue
            selected_history.append(
                {
                    "role": str(item["role"]),
                    "content": str(item["content"]),
                }
            )

        return ContextSlice(
            system_prompt=system_prompt,
            persona_examples=selected_examples,
            short_history=selected_history,
            latest_input=latest_input,
        )
