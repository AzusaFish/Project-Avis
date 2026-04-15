"""
Module: app/services/tts_profiles.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# TTS 档案加载器：从 YAML 读取说话人和情绪参数。

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


class TTSProfiles:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        if not self.path.exists():
            self.data = {}
            return
        with self.path.open("r", encoding="utf-8") as f:
            self.data = yaml.safe_load(f) or {}

    def resolve(self, speaker: str, emotion: str | None = None) -> dict[str, Any]:
        speakers = self.data.get("speakers", {})
        base = dict(speakers.get(speaker, {}))
        by_emotion = base.pop("by_emotion", {})
        if emotion and isinstance(by_emotion, dict):
            override = by_emotion.get(emotion, {})
            if isinstance(override, dict):
                base.update(override)
        ref_audio = base.get("ref_audio_path")
        if isinstance(ref_audio, str) and ref_audio.strip():
            base["ref_audio_path"] = self._resolve_path(ref_audio)
        return base

    def default_speaker(self) -> str:
        value = str(self.data.get("default_speaker", "")).strip()
        return value

    def _resolve_path(self, raw_path: str) -> str:
        expanded = os.path.expandvars(os.path.expanduser(raw_path.strip()))
        candidate = Path(expanded)
        if not candidate.is_absolute():
            candidate = (self.path.parent / candidate).resolve()
        return str(candidate)
