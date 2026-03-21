"""
Module: app/agent/context_manager.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 上下文管理：在 token 预算内裁剪历史、范例与最新输入。

from __future__ import annotations

from dataclasses import dataclass

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
    short_history: list[str]
    latest_input: str

    def render_messages(self) -> list[dict[str, str]]:
        # 按模型可直接消费的 chat messages 结构输出上下文切片。
        # 注意：这里把历史行统一放到 user role，是当前实现的简化策略。
        """Public API `render_messages` used by other modules or route handlers."""
        messages: list[dict[str, str]] = [{"role": "system", "content": self.system_prompt}]
        if self.persona_examples:
            messages.append(
                {
                    "role": "system",
                    "content": "Persona style examples:\n" + "\n".join(self.persona_examples),
                }
            )
        for line in self.short_history:
            messages.append({"role": "user", "content": line})
        messages.append({"role": "user", "content": self.latest_input})
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
        history: list[str],
        latest_input: str,
    ) -> ContextSlice:
        # 在预算限制下选择“系统提示 + 人格示例 + 历史 + 最新输入”的子集。
        # 为回复和工具调用预留 token，剩余预算用于上下文。
        # C++ 类比：像一个“预算受限的贪心裁剪器”。
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

        selected_history: list[str] = []
        for line in reversed(history):
            t = rough_token_count(line)
            if used + t > budget:
                break
            selected_history.append(line)
            used += t

        selected_history.reverse()
        return ContextSlice(
            system_prompt=system_prompt,
            persona_examples=selected_examples,
            short_history=selected_history,
            latest_input=latest_input,
        )
