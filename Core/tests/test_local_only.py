import asyncio

from app.core.local_only import LocalOnlyMiddleware, has_allowed_origin, is_loopback_client


def test_loopback_addresses_are_accepted() -> None:
    assert is_loopback_client("127.0.0.1")
    assert is_loopback_client("::1")
    assert is_loopback_client("::ffff:127.0.0.1")
    assert not is_loopback_client("192.168.1.10")
    assert not is_loopback_client(None)
    assert has_allowed_origin([(b"origin", b"http://tauri.localhost")])
    assert not has_allowed_origin([(b"origin", b"https://untrusted.example")])


def test_remote_http_and_websocket_are_rejected() -> None:
    async def run_case() -> None:
        reached = []

        async def inner(scope, receive, send) -> None:
            reached.append(scope["type"])

        middleware = LocalOnlyMiddleware(inner)
        for scope_type, expected_type in (("http", "http.response.start"), ("websocket", "websocket.close")):
            messages = []

            async def send(message) -> None:
                messages.append(message)

            async def receive():
                return {}

            await middleware({"type": scope_type, "client": ("192.168.1.10", 1234)}, receive, send)
            assert messages[0]["type"] == expected_type
        assert not reached

        await middleware({"type": "http", "client": ("127.0.0.1", 1234)}, receive, send)
        assert reached == ["http"]

        await middleware(
            {
                "type": "websocket",
                "client": ("127.0.0.1", 1234),
                "headers": [(b"origin", b"https://untrusted.example")],
            },
            receive,
            send,
        )
        assert messages[-1]["type"] == "websocket.close"

    asyncio.run(run_case())
