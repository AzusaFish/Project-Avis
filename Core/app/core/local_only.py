from ipaddress import ip_address

ALLOWED_ORIGINS = (
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
)


def is_loopback_client(host: str | None) -> bool:
    if not host:
        return False
    try:
        address = ip_address(host)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped.is_loopback if mapped is not None else address.is_loopback


def has_allowed_origin(headers: list[tuple[bytes, bytes]]) -> bool:
    for name, value in headers:
        if name.lower() == b"origin":
            return value.decode("ascii", errors="ignore").rstrip("/") in ALLOWED_ORIGINS
    return True


class LocalOnlyMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        if client and is_loopback_client(client[0]) and has_allowed_origin(scope.get("headers", [])):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                }
            )
            await send({"type": "http.response.body", "body": b"Local access only"})
