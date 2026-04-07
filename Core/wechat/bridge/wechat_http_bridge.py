"""
Module: bridges/wechat_http_bridge.py

Beginner note:
- This bridge provides a stable WeChat HTTP contract for Core.
- It supports local queue mode and optional upstream forwarding mode.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from collections import deque
from typing import Any

import httpx
from fastapi import Body, FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware


logger = logging.getLogger("wechat_http_bridge")

HOST = os.getenv("WECHAT_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.getenv("WECHAT_BRIDGE_PORT", "9010"))
INBOX_MAX = max(50, int(os.getenv("WECHAT_BRIDGE_INBOX_MAX", "2000")))
OUTBOX_MAX = max(50, int(os.getenv("WECHAT_BRIDGE_OUTBOX_MAX", "2000")))
WECHAT_BRIDGE_PROVIDER = os.getenv("WECHAT_BRIDGE_PROVIDER", "local").strip().lower()
UPSTREAM_POLL_URL = os.getenv("WECHAT_UPSTREAM_POLL_URL", "").strip()
UPSTREAM_SEND_URL = os.getenv("WECHAT_UPSTREAM_SEND_URL", "").strip()
UPSTREAM_POLL_INTERVAL_SEC = max(0.2, float(os.getenv("WECHAT_UPSTREAM_POLL_INTERVAL_SEC", "0.8")))

GEWECHAT_BASE_URL = os.getenv("GEWECHAT_BASE_URL", "http://127.0.0.1:2531/v2/api").strip()
GEWECHAT_SEND_URL = os.getenv("GEWECHAT_SEND_URL", "").strip()
GEWECHAT_TOKEN = os.getenv("GEWECHAT_TOKEN", "").strip()
GEWECHAT_TOKEN_HEADER = os.getenv("GEWECHAT_TOKEN_HEADER", "X-GEWE-TOKEN").strip() or "X-GEWE-TOKEN"
GEWECHAT_APP_ID = os.getenv("GEWECHAT_APP_ID", "").strip()
GEWECHAT_ATS_RAW = os.getenv("GEWECHAT_ATS", "[]").strip()

WCFERRY_AUTO_RECV = os.getenv("WCFERRY_AUTO_RECV", "1").strip() not in {"0", "false", "False"}
ITCHAT_ENABLE_CMD_QR = int(os.getenv("ITCHAT_ENABLE_CMD_QR", "2"))
ITCHAT_HOT_RELOAD = os.getenv("ITCHAT_HOT_RELOAD", "1").strip() not in {"0", "false", "False"}
ITCHAT_RETRY_SEC = max(2.0, float(os.getenv("ITCHAT_RETRY_SEC", "5")))

SECURE_RELAY_SEND_URL = os.getenv("SECURE_RELAY_SEND_URL", "").strip()
SECURE_RELAY_SHARED_SECRET = os.getenv("SECURE_RELAY_SHARED_SECRET", "").strip()
SECURE_RELAY_SIGN_HEADER = os.getenv("SECURE_RELAY_SIGN_HEADER", "X-Relay-Signature").strip() or "X-Relay-Signature"
SECURE_RELAY_TS_HEADER = os.getenv("SECURE_RELAY_TS_HEADER", "X-Relay-Timestamp").strip() or "X-Relay-Timestamp"
SECURE_RELAY_NONCE_HEADER = os.getenv("SECURE_RELAY_NONCE_HEADER", "X-Relay-Nonce").strip() or "X-Relay-Nonce"
SECURE_RELAY_WINDOW_SEC = max(30, int(float(os.getenv("SECURE_RELAY_WINDOW_SEC", "300"))))

try:
    GEWECHAT_ATS = json.loads(GEWECHAT_ATS_RAW)
except Exception:
    GEWECHAT_ATS = []


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _dig(payload: Any, *path: str) -> Any:
    cur = payload
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _first_non_empty(*values: Any) -> str:
    for value in values:
        s = _as_str(value)
        if s:
            return s
    return ""


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _secure_relay_signature(payload: Any, timestamp: str, nonce: str) -> str:
    if not SECURE_RELAY_SHARED_SECRET:
        return ""
    body = _canonical_json(payload)
    sign_source = f"{timestamp}.{nonce}.{body}".encode("utf-8")
    return hmac.new(SECURE_RELAY_SHARED_SECRET.encode("utf-8"), sign_source, hashlib.sha256).hexdigest()


def _build_secure_relay_headers(payload: Any) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    signature = _secure_relay_signature(payload, timestamp, nonce)
    return {
        SECURE_RELAY_TS_HEADER: timestamp,
        SECURE_RELAY_NONCE_HEADER: nonce,
        SECURE_RELAY_SIGN_HEADER: signature,
    }


def _verify_secure_relay_signature(payload: Any, timestamp: str, nonce: str, signature: str) -> tuple[bool, str]:
    if not SECURE_RELAY_SHARED_SECRET:
        return False, "missing shared secret"
    if not timestamp or not nonce or not signature:
        return False, "missing auth headers"

    try:
        ts = int(timestamp)
    except Exception:
        return False, "invalid timestamp"

    if abs(int(time.time()) - ts) > SECURE_RELAY_WINDOW_SEC:
        return False, "timestamp expired"

    expected = _secure_relay_signature(payload, timestamp, nonce)
    if not expected:
        return False, "signature build failed"
    if not hmac.compare_digest(expected, signature):
        return False, "signature mismatch"

    return True, "ok"

_inbox: deque[dict[str, Any]] = deque(maxlen=INBOX_MAX)
_outbox: deque[dict[str, Any]] = deque(maxlen=OUTBOX_MAX)
_inbox_lock = asyncio.Lock()
_poll_task: asyncio.Task | None = None
_wcf_task: asyncio.Task | None = None
_wcf_client: Any | None = None
_itchat_client: Any | None = None
_itchat_thread: threading.Thread | None = None
_itchat_ready = False
_itchat_state = "idle"
_itchat_last_error = ""
_itchat_last_event_ts = 0.0
_runtime_loop: asyncio.AbstractEventLoop | None = None


def _try_init_wcf_client() -> Any | None:
    if WECHAT_BRIDGE_PROVIDER != "wcferry":
        return None
    try:
        from wcferry import Wcf  # type: ignore

        client = Wcf()
        if WCFERRY_AUTO_RECV and hasattr(client, "enable_receiving_msg"):
            try:
                client.enable_receiving_msg()
            except TypeError:
                client.enable_receiving_msg(pyq=False)
        return client
    except Exception as exc:
        logger.warning("wcferry init failed: %s", exc)
        return None


def _try_init_itchat_client(loop: asyncio.AbstractEventLoop) -> tuple[Any | None, threading.Thread | None]:
    if WECHAT_BRIDGE_PROVIDER != "itchat":
        return None, None

    try:
        import itchat  # type: ignore
        from itchat.content import TEXT  # type: ignore
    except Exception as exc:
        logger.warning("itchat import failed: %s", exc)
        return None, None

    global _runtime_loop
    _runtime_loop = loop

    @itchat.msg_register([TEXT], isFriendChat=True, isGroupChat=True, isMpChat=False)
    def _on_text_msg(msg: dict[str, Any]) -> None:
        text = msg.get("Text")
        if not isinstance(text, str):
            text = _as_str(msg.get("Content"))

        mapped = {
            "id": _as_str(msg.get("MsgId")) or uuid.uuid4().hex,
            "from": _as_str(msg.get("FromUserName")),
            "text": text,
            "timestamp": _as_float(msg.get("CreateTime"), time.time()),
            "raw": msg,
        }

        if _runtime_loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(_enqueue_messages([mapped]), _runtime_loop)
        except Exception as exc:
            logger.warning("itchat enqueue failed: %s", exc)

    def _run() -> None:
        global _itchat_ready, _itchat_state, _itchat_last_error, _itchat_last_event_ts
        while True:
            try:
                _itchat_state = "logging_in"
                _itchat_last_error = ""
                _itchat_last_event_ts = time.time()
                logger.info("itchat login starting (enableCmdQR=%s)", ITCHAT_ENABLE_CMD_QR)
                itchat.auto_login(hotReload=ITCHAT_HOT_RELOAD, enableCmdQR=ITCHAT_ENABLE_CMD_QR)
                _itchat_ready = True
                _itchat_state = "running"
                _itchat_last_event_ts = time.time()
                logger.info("itchat login successful")
                itchat.run(blockThread=True)
                _itchat_ready = False
                _itchat_state = "stopped"
                _itchat_last_event_ts = time.time()
            except Exception as exc:
                _itchat_ready = False
                _itchat_state = "error"
                _itchat_last_error = traceback.format_exc(limit=3).strip()
                _itchat_last_event_ts = time.time()
                logger.warning("itchat run failed, retry in %ss: %s", ITCHAT_RETRY_SEC, exc)
                time.sleep(ITCHAT_RETRY_SEC)

    thread = threading.Thread(target=_run, name="itchat_worker", daemon=True)
    thread.start()
    return itchat, thread

@asynccontextmanager
async def _lifespan(_: FastAPI):
    await _startup()
    try:
        yield
    finally:
        await _shutdown()


app = FastAPI(title="WeChat HTTP Bridge", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _normalize_inbound(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one inbound message shape to bridge contract."""
    text = _first_non_empty(
        raw.get("text"),
        raw.get("content"),
        raw.get("message"),
        raw.get("msg"),
        _dig(raw, "Content", "string"),
        _dig(raw, "Data", "Content", "string"),
        _dig(raw, "Data", "Content"),
        _dig(raw, "data", "Content", "string"),
        _dig(raw, "data", "Content"),
    )
    if not text:
        return None

    sender = _first_non_empty(
        raw.get("from"),
        raw.get("sender"),
        raw.get("talker"),
        raw.get("wxid"),
        _dig(raw, "FromUserName", "string"),
        _dig(raw, "Data", "FromUserName", "string"),
        _dig(raw, "Data", "FromUserName"),
        _dig(raw, "data", "FromUserName", "string"),
        _dig(raw, "data", "FromUserName"),
    )
    ts = _as_float(
        raw.get("ts")
        or raw.get("timestamp")
        or _dig(raw, "CreateTime")
        or _dig(raw, "Data", "CreateTime")
        or _dig(raw, "data", "CreateTime"),
        time.time(),
    )
    msg_id = _first_non_empty(
        raw.get("id"),
        raw.get("msg_id"),
        raw.get("msgId"),
        _dig(raw, "MsgId"),
        _dig(raw, "Data", "MsgId"),
        _dig(raw, "Data", "NewMsgId"),
        _dig(raw, "data", "MsgId"),
        _dig(raw, "data", "NewMsgId"),
    ) or uuid.uuid4().hex

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

    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]

    if "text" in payload or "content" in payload or "message" in payload:
        return [payload]
    if "Data" in payload or "TypeName" in payload or "MsgId" in payload:
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


def _normalize_wcf_inbound(raw: Any) -> dict[str, Any] | None:
    text = _as_str(getattr(raw, "content", ""))
    if not text:
        return None

    sender = _first_non_empty(getattr(raw, "sender", ""), getattr(raw, "roomid", ""))
    msg_id = _first_non_empty(getattr(raw, "id", ""), getattr(raw, "msgid", "")) or uuid.uuid4().hex
    ts = _as_float(getattr(raw, "ts", None), time.time())
    return {
        "id": msg_id,
        "from": sender,
        "text": text,
        "timestamp": ts,
        "raw": {
            "sender": _as_str(getattr(raw, "sender", "")),
            "roomid": _as_str(getattr(raw, "roomid", "")),
            "type": getattr(raw, "type", None),
            "content": text,
            "thumb": _as_str(getattr(raw, "thumb", "")),
            "extra": _as_str(getattr(raw, "extra", "")),
        },
    }


async def _wcf_poll_loop() -> None:
    if _wcf_client is None:
        return
    logger.info("wcferry poll enabled")
    while True:
        try:
            msg = await asyncio.to_thread(_wcf_client.get_msg)
            item = _normalize_wcf_inbound(msg)
            if item is None:
                continue
            async with _inbox_lock:
                _inbox.append(item)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("wcferry poll failed: %s", exc)
            await asyncio.sleep(0.5)


async def _startup() -> None:
    """Bridge startup hook."""
    global _poll_task, _wcf_task, _wcf_client, _itchat_client, _itchat_thread
    if UPSTREAM_POLL_URL:
        _poll_task = asyncio.create_task(_upstream_poll_loop(), name="wechat_upstream_poll")
    _wcf_client = _try_init_wcf_client()
    if _wcf_client is not None:
        _wcf_task = asyncio.create_task(_wcf_poll_loop(), name="wechat_wcf_poll")
    _itchat_client, _itchat_thread = _try_init_itchat_client(asyncio.get_running_loop())


async def _shutdown() -> None:
    """Bridge shutdown hook."""
    global _poll_task, _wcf_task
    if _poll_task is None:
        pass
    else:
        _poll_task.cancel()
        await asyncio.gather(_poll_task, return_exceptions=True)
        _poll_task = None

    if _wcf_task is None:
        return
    _wcf_task.cancel()
    await asyncio.gather(_wcf_task, return_exceptions=True)
    _wcf_task = None


@app.get("/")
async def root() -> dict[str, Any]:
    """Basic status endpoint."""
    wcferry_login = False
    if _wcf_client is not None:
        try:
            wcferry_login = bool(await asyncio.to_thread(_wcf_client.is_login))
        except Exception:
            wcferry_login = False

    return {
        "status": "ok",
        "service": "wechat_http_bridge",
        "provider": WECHAT_BRIDGE_PROVIDER,
        "upstream_poll_enabled": bool(UPSTREAM_POLL_URL),
        "upstream_send_enabled": bool(UPSTREAM_SEND_URL),
        "wcferry_ready": _wcf_client is not None,
        "wcferry_login": wcferry_login,
        "itchat_ready": _itchat_ready,
        "itchat_state": _itchat_state,
        "itchat_last_error": _itchat_last_error,
        "itchat_last_event_ts": _itchat_last_event_ts,
        "secure_relay_send_configured": bool(SECURE_RELAY_SEND_URL),
        "secure_relay_secret_configured": bool(SECURE_RELAY_SHARED_SECRET),
    }


@app.post("/push")
@app.post("/receive")
@app.post("/ingest")
async def push(payload: Any = Body(default={})) -> dict[str, Any]:
    """Ingest inbound messages from external WeChat adapter."""
    if WECHAT_BRIDGE_PROVIDER == "secure_relay":
        raise HTTPException(
            status_code=403,
            detail="unsigned ingest is disabled when WECHAT_BRIDGE_PROVIDER=secure_relay; use /secure-relay/ingest",
        )

    messages = _extract_messages(payload)
    count = await _enqueue_messages(messages)
    return {"ok": True, "accepted": count}


@app.post("/secure-relay/ingest")
async def secure_relay_ingest(
    payload: Any = Body(default={}),
    relay_signature: str = Header(default="", alias=SECURE_RELAY_SIGN_HEADER),
    relay_timestamp: str = Header(default="", alias=SECURE_RELAY_TS_HEADER),
    relay_nonce: str = Header(default="", alias=SECURE_RELAY_NONCE_HEADER),
) -> dict[str, Any]:
    """Ingest signed payload from trusted relay."""
    if WECHAT_BRIDGE_PROVIDER != "secure_relay":
        raise HTTPException(status_code=403, detail="/secure-relay/ingest is only enabled for secure_relay provider")

    ok, reason = _verify_secure_relay_signature(payload, relay_timestamp, relay_nonce, relay_signature)
    if not ok:
        raise HTTPException(status_code=401, detail=f"secure relay auth failed: {reason}")

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

    if WECHAT_BRIDGE_PROVIDER == "gewechat":
        if not GEWECHAT_TOKEN:
            raise HTTPException(status_code=503, detail="GEWECHAT_TOKEN is required when WECHAT_BRIDGE_PROVIDER=gewechat")
        if not GEWECHAT_APP_ID:
            raise HTTPException(status_code=503, detail="GEWECHAT_APP_ID is required when WECHAT_BRIDGE_PROVIDER=gewechat")
        if not to:
            raise HTTPException(status_code=400, detail="to is required when WECHAT_BRIDGE_PROVIDER=gewechat")

        url = GEWECHAT_SEND_URL or f"{GEWECHAT_BASE_URL.rstrip('/')}/message/postText"
        req_json = {
            "appId": GEWECHAT_APP_ID,
            "toWxid": to,
            "content": text,
            "ats": GEWECHAT_ATS,
        }
        headers = {GEWECHAT_TOKEN_HEADER: GEWECHAT_TOKEN}

        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(url, json=req_json, headers=headers)
            resp.raise_for_status()
            try:
                upstream_data = resp.json()
            except Exception:
                upstream_data = {"raw": resp.text}

        if isinstance(upstream_data, dict) and int(upstream_data.get("ret", 200)) != 200:
            return {
                "ok": False,
                "message": "gewechat send failed",
                "upstream": upstream_data,
            }

        return {"ok": True, "message": "forwarded", "upstream": upstream_data}

    if WECHAT_BRIDGE_PROVIDER == "wcferry":
        if _wcf_client is None:
            raise HTTPException(
                status_code=503,
                detail="wcferry is not ready. Please install wcferry and ensure WeChat PC is logged in.",
            )
        if not to:
            raise HTTPException(status_code=400, detail="to is required when WECHAT_BRIDGE_PROVIDER=wcferry")

        login_ok = await asyncio.to_thread(_wcf_client.is_login)
        if not login_ok:
            raise HTTPException(status_code=503, detail="WeChat is not logged in on this machine.")

        ret = await asyncio.to_thread(_wcf_client.send_text, text, to)
        if int(ret) != 0:
            return {"ok": False, "message": "wcferry send failed", "ret": ret}
        return {"ok": True, "message": "forwarded", "ret": ret}

    if WECHAT_BRIDGE_PROVIDER == "itchat":
        if _itchat_client is None or not _itchat_ready:
            raise HTTPException(status_code=503, detail="itchat is not ready. Please scan login QR in terminal.")
        if not to:
            raise HTTPException(status_code=400, detail="to is required when WECHAT_BRIDGE_PROVIDER=itchat")

        target = to
        if not target.startswith("@"):
            # If user passes nickname/remark, resolve to internal UserName first.
            try:
                friends = await asyncio.to_thread(_itchat_client.search_friends, name=target)
                if friends and isinstance(friends, list):
                    uname = _as_str(friends[0].get("UserName"))
                    if uname:
                        target = uname
            except Exception:
                pass

        try:
            await asyncio.to_thread(_itchat_client.send_msg, msg=text, toUserName=target)
        except Exception as exc:
            return {"ok": False, "message": f"itchat send failed: {exc}"}

        return {"ok": True, "message": "forwarded", "to": target}

    if WECHAT_BRIDGE_PROVIDER == "secure_relay":
        if not SECURE_RELAY_SEND_URL:
            raise HTTPException(status_code=503, detail="SECURE_RELAY_SEND_URL is required when WECHAT_BRIDGE_PROVIDER=secure_relay")
        if not SECURE_RELAY_SHARED_SECRET:
            raise HTTPException(status_code=503, detail="SECURE_RELAY_SHARED_SECRET is required when WECHAT_BRIDGE_PROVIDER=secure_relay")

        headers = _build_secure_relay_headers(outbound)
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(SECURE_RELAY_SEND_URL, json=outbound, headers=headers)
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


@app.post("/gewechat/callback")
async def gewechat_callback(payload: Any = Body(default={})) -> dict[str, Any]:
    """Gewechat callback alias: forwards payload to the common ingest path."""
    return await push(payload)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
