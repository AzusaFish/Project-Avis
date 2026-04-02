"""
Module: app/services/llm_router.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# LLM 路由层：统一封装 Ollama 与 OpenAI 兼容接口（含流式）。

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed

from app.core.config import settings


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
        self.gguf_base_url = settings.gguf_base_url.rstrip("/")
        self.gguf_model = settings.gguf_model

    def _using_openai_compatible(self) -> bool:
        """Return true when provider speaks OpenAI-compatible /v1/chat/completions."""
        return self.provider in {"openai", "gguf", "llama_cpp", "ollama"}

    @staticmethod
    def _ensure_v1_base(url: str) -> str:
        """Normalize OpenAI-compatible base url to .../v1 form."""
        base = url.rstrip("/")
        if base.endswith("/v1"):
            return base
        return f"{base}/v1"

    def _active_openai_base_and_model(self) -> tuple[str, str]:
        if self.provider in {"gguf", "llama_cpp"}:
            return self.gguf_base_url, self.gguf_model
        if self.provider == "ollama":
            return self._ensure_v1_base(self.ollama_base_url), self.ollama_model
        return self.base_url, self.model

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(0.2))
    async def generate(self, messages: list[dict[str, str]]) -> str:
        # 非流式生成入口：按 provider 路由到对应后端。
        # tenacity.retry: 失败时自动重试，减少偶发网络抖动影响。
        """Public API `generate` used by other modules or route handlers."""
        if self._using_openai_compatible():
            return await self._generate_openai_compatible(messages)
        return await self._generate_openai_compatible(messages)

    async def generate_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        # 流式生成入口：逐段产出 token/文本片段。
        """Public API `generate_stream` used by other modules or route handlers."""
        if self._using_openai_compatible():
            async for delta in self._generate_stream_openai_compatible(messages):
                yield delta
            return
        async for delta in self._generate_stream_openai_compatible(messages):
            yield delta

    async def _generate_openai_compatible(self, messages: list[dict[str, str]]) -> str:
        # 调用 OpenAI 兼容的 chat/completions 非流式接口。
        # headers 里 Bearer token 只在 openai-compatible 模式使用。
        """Internal helper `_generate_openai_compatible` used by this module implementation."""
        base_url, model_name = self._active_openai_base_and_model()
        url = f"{base_url}/chat/completions"
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": settings.llm_max_output,
            "response_format": {"type": "json_object"},
        }
        if self.provider in {"gguf", "llama_cpp"}:
            payload["stop"] = ["<|im_end|>", "<|im_start|>"]
        headers = {}
        if self.api_key and self.api_key != "EMPTY":
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def _generate_stream_openai_compatible(
        self, messages: list[dict[str, str]]
    ) -> AsyncIterator[str]:
        # 解析 OpenAI SSE 数据流并提取增量文本。
        # SSE 每行以 `data: ` 开头，`[DONE]` 表示流结束。
        """Internal helper `_generate_stream_openai_compatible` used by this module implementation."""
        base_url, model_name = self._active_openai_base_and_model()
        url = f"{base_url}/chat/completions"
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": settings.llm_max_output,
            "stream": True,
            "response_format": {"type": "json_object"},
        }
        if self.provider in {"gguf", "llama_cpp"}:
            payload["stop"] = ["<|im_end|>", "<|im_start|>"]
        headers = {}
        if self.api_key and self.api_key != "EMPTY":
            headers["Authorization"] = f"Bearer {self.api_key}"

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
        # 依赖体检：检查 OpenAI-compatible /models 与目标模型可用性。
        """Public API `check_ready` used by other modules or route handlers."""
        if not self._using_openai_compatible():
            return {"provider": self.provider, "ok": True, "detail": "skip check"}

        base_url, model_name = self._active_openai_base_and_model()
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{base_url}/models")
                resp.raise_for_status()
                data = resp.json()
                names = [m.get("id", "") for m in data.get("data", [])]
                found = any(model_name == n for n in names)
                return {
                    "provider": self.provider,
                    "ok": found,
                    "model": model_name,
                    "available_models": names,
                }
        except Exception as exc:
            return {"provider": self.provider, "ok": False, "error": str(exc)}
