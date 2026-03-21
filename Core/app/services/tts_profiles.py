"""
Module: app/services/tts_profiles.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# TTS 档案加载器：从 YAML 读取说话人和情绪参数。

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class TTSProfiles:
    """TTSProfiles: main class container for related behavior in this module."""
    def __init__(self, path: str) -> None:
        # 记录配置路径并在启动时立即加载一次。
        """Initialize the object state and cache required dependencies."""
        self.path = Path(path)
        self.data: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        # 从 YAML 文件重新加载全部说话人配置。
        # safe_load: 只解析基础 YAML 类型，安全性比 load 更高。
        """Public API `reload` used by other modules or route handlers."""
        if not self.path.exists():
            self.data = {}
            return
        with self.path.open("r", encoding="utf-8") as f:
            self.data = yaml.safe_load(f) or {}

    def resolve(self, speaker: str, emotion: str | None = None) -> dict[str, Any]:
        # 按 speaker 取基础参数，再按 emotion 合并覆盖项。
        # 典型用法：`atri + happy` 会覆盖 ref_audio_path/prompt_text 等字段。
        """Public API `resolve` used by other modules or route handlers."""
        speakers = self.data.get("speakers", {})
        base = dict(speakers.get(speaker, {}))
        by_emotion = base.pop("by_emotion", {})
        if emotion and isinstance(by_emotion, dict):
            override = by_emotion.get(emotion, {})
            if isinstance(override, dict):
                base.update(override)
        return base

    def default_speaker(self) -> str:
        """Public API `default_speaker` used by other modules or route handlers."""
        value = str(self.data.get("default_speaker", "")).strip()
        return value
