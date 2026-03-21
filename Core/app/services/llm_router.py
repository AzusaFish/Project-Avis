"""
Module: app/services/llm_router.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# LLM 路由层：统一封装 Ollama 与 OpenAI 兼容接口（含流式）。

from __future__ import annotations

import json
import logging
from typing import Any
from collections.abc import AsyncIterator

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMRouter:
    """LLMRouter: main class container for related behavior in this module."""
    def __init__(self) -> None:
        # provider 决定调用哪种后端协议。
        # C++ 类比：这是一个“运行时可切换后端的适配器/策略类”。
        """Initialize the object state and cache required dependencies."""
        self.provider = settings.llm_provider.lower().strip()
        self.base_url = settings.llm_base_url.rstrip("/")
        self.model = settings.llm_model
        self.api_key = settings.llm_api_key
        self.temperature = settings.llm_temperature
        self.top_p = settings.llm_top_p
        self.ollama_base_url = settings.ollama_base_url.rstrip("/")
        self.ollama_model = settings.ollama_model

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(0.2))
    async def generate(self, messages: list[dict[str, str]]) -> str:
        # 非流式生成入口：按 provider 路由到对应后端。
        # tenacity.retry: 失败时自动重试，减少偶发网络抖动影响。
        """Public API `generate` used by other modules or route handlers."""
        if self.provider == "ollama":
            return await self._generate_ollama(messages)
        return await self._generate_openai_compatible(messages)

    async def generate_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        # 流式生成入口：逐段产出 token/文本片段。
        """Public API `generate_stream` used by other modules or route handlers."""
        if self.provider == "ollama":
            async for delta in self._generate_stream_ollama(messages):
                yield delta
            return
        async for delta in self._generate_stream_openai_compatible(messages):
            yield delta

    async def _generate_openai_compatible(self, messages: list[dict[str, str]]) -> str:
        # 调用 OpenAI 兼容的 chat/completions 非流式接口。
        # headers 里 Bearer token 只在 openai-compatible 模式使用。
        """Internal helper `_generate_openai_compatible` used by this module implementation."""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": settings.llm_max_output,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def _generate_ollama(self, messages: list[dict[str, str]]) -> str:
        # 调用 Ollama /api/chat 非流式接口。
        """Internal helper `_generate_ollama` used by this module implementation."""
        url = f"{self.ollama_base_url}/api/chat"
        payload = {
            "model": self.ollama_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
        }
        async with httpx.AsyncClient(timeout=float(settings.ollama_timeout_sec)) as client:
            resp = await client.post(url, json=payload)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                # Some ollama deployments may temporarily return 5xx for /api/chat.
                if exc.response is not None and exc.response.status_code >= 500:
                    logger.warning("ollama /api/chat failed with %s, fallback to /api/generate", exc.response.status_code)
                    return await self._generate_ollama_fallback_generate(client, messages)
                raise
            data = resp.json()
            return self._extract_ollama_chat_content(data)

    async def _generate_stream_ollama(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        # 解析 Ollama 按行返回的流式 JSON 响应。
        # AsyncIterator[str]：调用方可 `async for` 增量读取文本。
        """Internal helper `_generate_stream_ollama` used by this module implementation."""
        url = f"{self.ollama_base_url}/api/chat"
        payload = {
            "model": self.ollama_model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
        }
        async with httpx.AsyncClient(timeout=float(settings.ollama_timeout_sec)) as client:
            try:
                async with client.stream("POST", url, json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if obj.get("done"):
                            break
                        msg = obj.get("message") or {}
                        delta = msg.get("content", "")
                        if delta:
                            yield delta
            except httpx.HTTPStatusError as exc:
                # Degrade gracefully: if stream endpoint returns 5xx, fallback to non-stream once.
                if exc.response is not None and exc.response.status_code >= 500:
                    logger.warning("ollama stream failed with %s, fallback to non-stream", exc.response.status_code)
                    text = await self._generate_ollama(messages)
                    if text:
                        yield text
                    return
                raise

    async def _generate_stream_openai_compatible(
        self, messages: list[dict[str, str]]
    ) -> AsyncIterator[str]:
        # 解析 OpenAI SSE 数据流并提取增量文本。
        # SSE 每行以 `data: ` 开头，`[DONE]` 表示流结束。
        """Internal helper `_generate_stream_openai_compatible` used by this module implementation."""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": settings.llm_max_output,
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        async with httpx.AsyncClient(timeout=40.0) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload_line = line[6:]
                    if payload_line.strip() == "[DONE]":
                        break
                    try:
                        obj = json.loads(payload_line)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta

    async def check_ready(self) -> dict[str, object]:
        # 依赖体检：检查 Ollama 在线状态和目标模型可用性。
        """Public API `check_ready` used by other modules or route handlers."""
        if self.provider != "ollama":
            return {"provider": self.provider, "ok": True, "detail": "skip ollama check"}

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{self.ollama_base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                names = [m.get("name", "") for m in data.get("models", [])]
                found = any(self.ollama_model in n for n in names)
                return {
                    "provider": "ollama",
                    "ok": found,
                    "model": self.ollama_model,
                    "available_models": names,
                }
        except Exception as exc:
            return {"provider": "ollama", "ok": False, "error": str(exc)}

    @staticmethod
    def _extract_ollama_chat_content(data: dict[str, Any]) -> str:
        """Internal helper `_extract_ollama_chat_content` used by this module implementation."""
        if "message" not in data or "content" not in data["message"]:
            raise RuntimeError("ollama response missing message.content")
        return str(data["message"]["content"])

    @staticmethod
    def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
        # Minimal role-aware prompt fallback for /api/generate.
        """Internal helper `_messages_to_prompt` used by this module implementation."""
        lines: list[str] = []
        for m in messages:
            role = str(m.get("role", "user")).upper()
            content = str(m.get("content", "")).strip()
            if content:
                lines.append(f"[{role}] {content}")
        lines.append("[ASSISTANT]")
        return "\n".join(lines)

    async def _generate_ollama_fallback_generate(
        self, client: httpx.AsyncClient, messages: list[dict[str, str]]
    ) -> str:
        """Internal helper `_generate_ollama_fallback_generate` used by this module implementation."""
        url = f"{self.ollama_base_url}/api/generate"
        payload = {
            "model": self.ollama_model,
            "prompt": self._messages_to_prompt(messages),
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
        }
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        text = str(data.get("response", "")).strip()
        if not text:
            raise RuntimeError("ollama fallback response is empty")
        return text
