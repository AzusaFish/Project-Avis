import asyncio
import json

import httpx
import pytest

from app.services.llm_router import LLMRouter


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("force_json", [False, True])
def test_json_response_format_respects_configuration(monkeypatch, stream, force_json) -> None:
    requests = []
    reply = '{"action":"speak","text":"Hello"}' if force_json else "Hello"

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if payload.get("stream"):
            chunk = json.dumps({"choices": [{"delta": {"content": reply}}]})
            return httpx.Response(200, text=f"data: {chunk}\n\ndata: [DONE]\n\n")
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kwargs: client_class(transport=httpx.MockTransport(handle), **kwargs),
    )
    router = LLMRouter()
    router.force_json = force_json
    router.force_json_disable_stream = False

    async def run_case() -> str:
        messages = [{"role": "user", "content": "Hi"}]
        if stream:
            return "".join([chunk async for chunk in router.generate_stream(messages)])
        return await router.generate(messages)

    result = asyncio.run(run_case())
    assert result
    assert len(requests) == 1
    if force_json:
        assert requests[0]["response_format"] == {"type": "json_object"}
    else:
        assert "response_format" not in requests[0]
