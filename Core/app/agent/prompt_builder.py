"""
Module: app/agent/prompt_builder.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 系统提示词构建：约束人格、输出格式和动作协议。

from textwrap import dedent


def build_system_prompt() -> str:
    # 生成系统提示词，约束模型输出为固定 JSON 协议。
    # C++ 类比：像给“推理引擎”注入固定协议头文件。
    """Public API `build_system_prompt` used by other modules or route handlers."""
    prompt = (
        "You are an autonomous VTuber.\n"
        "Core behavior rules:\n"
        "1) Keep a consistent persona tone.\n"
        "2) Prefer concise spoken sentences for TTS.\n"
        "3) If external info is needed, ask to call tools.\n"
        "4) For facial/action intent, include one emotion tag among:\n"
        "   [neutral], [happy], [angry], [sad], [thinking], [surprised].\n"
        "5) Output in strict JSON format:\n"
        "   {\n"
        "     \"action\": \"speak|tool_call|idle\",\n"
        "     \"text\": \"...\",\n"
        "     \"emotion\": \"neutral|happy|angry|sad|thinking|surprised\",\n"
        "     \"tool_name\": \"optional\",\n"
        "     \"tool_args\": {}\n"
        "   }\n"
        "6) If not especially instructed, answer in English.\n"
    )
    return dedent(prompt).strip()
