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
    # Initialize provider settings and routing configuration.
    def __init__(self) -> None:
        self.provider = settings.llm_provider.lower().strip()
        self.base_url = settings.llm_base_url.rstrip("/")
        self.model = settings.llm_model
        self.model_profile = settings.llm_model_profile.lower().strip()
        self.api_key = settings.llm_api_key
        self.temperature = settings.llm_temperature
        self.top_p = settings.llm_top_p
        self.ollama_base_url = settings.ollama_base_url.rstrip("/")
        self.ollama_model = settings.ollama_model
        self.gguf_base_url = settings.gguf_base_url.rstrip("/")
        self.gguf_model = settings.gguf_model
        self.gguf_qwen_model = settings.gguf_qwen_model
        self.gguf_internvl_model = settings.gguf_internvl_model
        self.force_json = settings.llm_force_json
        self.force_json_retries = max(0, settings.llm_force_json_retries)
        self.force_json_disable_stream = settings.llm_force_json_disable_stream

    # Check if provider follows OpenAI-compatible API.
    def _using_openai_compatible(self) -> bool:
        return self.provider in {"openai", "gguf", "llama_cpp", "ollama"}

    # Ensure the base URL ends with /v1.
    @staticmethod
    def _ensure_v1_base(url: str) -> str:
        base = url.rstrip("/")
        if base.endswith("/v1"):
            return base
        return f"{base}/v1"

    # Resolve the effective base URL and model for the provider.
    def _active_openai_base_and_model(self) -> tuple[str, str]:
        if self.provider in {"gguf", "llama_cpp"}:
            if self.model_profile == "qwen":
                return self.gguf_base_url, self.gguf_qwen_model
            if self.model_profile == "internvl":
                return self.gguf_base_url, self.gguf_internvl_model
            return self.gguf_base_url, self.gguf_model
        if self.provider == "ollama":
            return self._ensure_v1_base(self.ollama_base_url), self.ollama_model
        return self.base_url, self.model

    # Try to coerce a JSON object from raw model text.
    @staticmethod
    def _coerce_json_object(text: str) -> dict[str, object] | None:
        raw = text.strip()
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        snippet = raw[start : end + 1]
        try:
            obj = json.loads(snippet)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            return None
        return None

    # Dump a JSON object with consistent encoding settings.
    @staticmethod
    def _dump_json(obj: dict[str, object]) -> str:
        return json.dumps(obj, ensure_ascii=False)

    # Build retry messages that instruct strict JSON output.
    @staticmethod
    def _build_json_retry_messages(
        base_messages: list[dict[str, object]],
        attempt: int,
    ) -> list[dict[str, object]]:
        messages = [dict(m) for m in base_messages]
        messages.append(
            {
                "role": "system",
                "content": (
                    "Return only a single valid JSON object. "
                    "Do not wrap it in markdown or add extra text."
                ),
            }
        )
        if attempt > 0:
            messages.append(
                {
                    "role": "user",
                    "content": "Your previous response was not valid JSON. Output only JSON.",
                }
            )
        return messages

    # Generate JSON strictly by retrying until a valid object is returned.
    async def _generate_openai_json_strict(self, messages: list[dict[str, object]]) -> str:
        attempts = max(1, self.force_json_retries + 1)
        for attempt in range(attempts):
            attempt_messages = self._build_json_retry_messages(messages, attempt)
            text = await self._generate_openai_compatible(attempt_messages)
            obj = self._coerce_json_object(text)
            if obj is not None:
                return self._dump_json(obj)
        fallback = {"action": "idle", "emotion": "neutral", "text": ""}
        return self._dump_json(fallback)

    # Generate a non-streaming completion from the active provider.
    @retry(stop=stop_after_attempt(2), wait=wait_fixed(0.2))
    async def generate(self, messages: list[dict[str, object]]) -> str:
        if self._using_openai_compatible():
            if self.force_json:
                return await self._generate_openai_json_strict(messages)
            return await self._generate_openai_compatible(messages)
        return await self._generate_openai_compatible(messages)

    # Stream completion deltas from the active provider.
    async def generate_stream(self, messages: list[dict[str, object]]) -> AsyncIterator[str]:
        if self._using_openai_compatible():
            if self.force_json and self.force_json_disable_stream:
                text = await self._generate_openai_json_strict(messages)
                yield text
                return
            async for delta in self._generate_stream_openai_compatible(messages):
                yield delta
            return
        async for delta in self._generate_stream_openai_compatible(messages):
            yield delta

    # Call an OpenAI-compatible chat completion endpoint.
    async def _generate_openai_compatible(self, messages: list[dict[str, object]]) -> str:
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

    # Stream deltas from an OpenAI-compatible endpoint.
    async def _generate_stream_openai_compatible(
        self, messages: list[dict[str, object]]
    ) -> AsyncIterator[str]:
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

    # Check provider/model availability via the /models endpoint.
    async def check_ready(self) -> dict[str, object]:
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
