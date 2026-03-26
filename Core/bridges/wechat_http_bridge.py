"""
Module: bridges/wechat_http_bridge.py

Beginner note:
- This bridge provides a stable WeChat HTTP contract for Core.
- It supports local queue mode and optional upstream forwarding mode.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import deque
from typing import Any

import httpx
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware


logger = logging.getLogger("wechat_http_bridge")

HOST = os.getenv("WECHAT_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.getenv("WECHAT_BRIDGE_PORT", "9010"))
INBOX_MAX = max(50, int(os.getenv("WECHAT_BRIDGE_INBOX_MAX", "2000")))
OUTBOX_MAX = max(50, int(os.getenv("WECHAT_BRIDGE_OUTBOX_MAX", "2000")))
UPSTREAM_POLL_URL = os.getenv("WECHAT_UPSTREAM_POLL_URL", "").strip()
UPSTREAM_SEND_URL = os.getenv("WECHAT_UPSTREAM_SEND_URL", "").strip()
UPSTREAM_POLL_INTERVAL_SEC = max(0.2, float(os.getenv("WECHAT_UPSTREAM_POLL_INTERVAL_SEC", "0.8")))

_inbox: deque[dict[str, Any]] = deque(maxlen=INBOX_MAX)
_outbox: deque[dict[str, Any]] = deque(maxlen=OUTBOX_MAX)
_inbox_lock = asyncio.Lock()
_poll_task: asyncio.Task | None = None

app = FastAPI(title="WeChat HTTP Bridge")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _normalize_inbound(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one inbound message shape to bridge contract."""
    text = str(
        raw.get("text")
        or raw.get("content")
        or raw.get("message")
        or raw.get("msg")
        or ""
    ).strip()
    if not text:
        return None

    sender = str(
        raw.get("from")
        or raw.get("sender")
        or raw.get("talker")
        or raw.get("wxid")
        or ""
    ).strip()
    ts = float(raw.get("ts") or raw.get("timestamp") or time.time())
    msg_id = str(raw.get("id") or raw.get("msg_id") or uuid.uuid4().hex)

    return {
        "id": msg_id,
        "from": sender,
        "text": text,
        "timestamp": ts,
        "raw": raw,
    }


def _extract_messages(payload: Any) -> list[dict[str, Any]]:
    """Extract candidate message list from common payload structures."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("messages", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]

    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("messages", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]

    if "text" in payload or "content" in payload or "message" in payload:
        return [payload]
    return []


async def _enqueue_messages(raw_messages: list[dict[str, Any]]) -> int:
    """Normalize and enqueue inbound messages."""
    normalized = []
    for msg in raw_messages:
        item = _normalize_inbound(msg)
        if item is not None:
            normalized.append(item)
    if not normalized:
        return 0

    async with _inbox_lock:
        _inbox.extend(normalized)
    return len(normalized)


async def _upstream_poll_loop() -> None:
    """Optional task: poll upstream endpoint and enqueue inbound messages."""
    if not UPSTREAM_POLL_URL:
        return
    logger.info("Upstream poll enabled: %s", UPSTREAM_POLL_URL)

    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                resp = await client.get(UPSTREAM_POLL_URL)
                resp.raise_for_status()
                payload = resp.json()
                count = await _enqueue_messages(_extract_messages(payload))
                if count:
                    logger.info("upstream poll enqueued %s messages", count)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("upstream poll failed: %s", exc)
            await asyncio.sleep(UPSTREAM_POLL_INTERVAL_SEC)


@app.on_event("startup")
async def _startup() -> None:
    """Bridge startup hook."""
    global _poll_task
    if UPSTREAM_POLL_URL:
        _poll_task = asyncio.create_task(_upstream_poll_loop(), name="wechat_upstream_poll")


@app.on_event("shutdown")
async def _shutdown() -> None:
    """Bridge shutdown hook."""
    global _poll_task
    if _poll_task is None:
        return
    _poll_task.cancel()
    await asyncio.gather(_poll_task, return_exceptions=True)
    _poll_task = None


@app.get("/")
async def root() -> dict[str, Any]:
    """Basic status endpoint."""
    return {
        "status": "ok",
        "service": "wechat_http_bridge",
        "upstream_poll_enabled": bool(UPSTREAM_POLL_URL),
        "upstream_send_enabled": bool(UPSTREAM_SEND_URL),
    }


@app.post("/push")
@app.post("/receive")
@app.post("/ingest")
async def push(payload: Any = Body(default={})) -> dict[str, Any]:
    """Ingest inbound messages from external WeChat adapter."""
    messages = _extract_messages(payload)
    count = await _enqueue_messages(messages)
    return {"ok": True, "accepted": count}


@app.get("/poll")
async def poll(
    limit: int = Query(default=20, ge=1, le=200),
    timeout_sec: float = Query(default=0.0, ge=0.0, le=25.0),
) -> dict[str, Any]:
    """Core-facing pull endpoint: pops messages from inbound queue."""
    deadline = time.monotonic() + timeout_sec
    while True:
        async with _inbox_lock:
            if _inbox:
                out = []
                for _ in range(min(limit, len(_inbox))):
                    out.append(_inbox.popleft())
                return {"messages": out, "count": len(out)}
        if timeout_sec <= 0 or time.monotonic() >= deadline:
            return {"messages": [], "count": 0}
        await asyncio.sleep(0.1)


@app.post("/send")
async def send(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Tool-facing send endpoint: forward upstream or keep local outbox log."""
    to = str(
        payload.get("to")
        or payload.get("target")
        or payload.get("wxid")
        or payload.get("receiver")
        or ""
    ).strip()
    text = str(
        payload.get("text")
        or payload.get("content")
        or payload.get("message")
        or ""
    ).strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    outbound = dict(payload)
    if to:
        outbound["to"] = to
    outbound["text"] = text

    if UPSTREAM_SEND_URL:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(UPSTREAM_SEND_URL, json=outbound)
            resp.raise_for_status()
            try:
                upstream_data = resp.json()
            except Exception:
                upstream_data = {"raw": resp.text}
        return {"ok": True, "message": "forwarded", "upstream": upstream_data}

    record = {
        "id": uuid.uuid4().hex,
        "to": to,
        "text": text,
        "timestamp": time.time(),
        "raw": outbound,
    }
    _outbox.append(record)
    logger.info("wechat send queued locally: to=%s text=%s", to or "<broadcast>", text[:80])
    return {"ok": True, "message": "queued locally", "id": record["id"]}


@app.get("/sent")
async def sent(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    """Debug endpoint: inspect latest outbound records."""
    values = list(_outbox)[-limit:]
    return {"items": values, "count": len(values)}


@app.get("/queue")
async def queue_state() -> dict[str, Any]:
    """Debug endpoint: inspect queue lengths."""
    return {"inbox_size": len(_inbox), "outbox_size": len(_outbox)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
