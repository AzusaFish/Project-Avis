"""
Module: bridges/realtimestt_http_bridge.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# RealtimeSTT 桥接服务：将双 WS 协议转换为 HTTP /transcribe。

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import websockets
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


logger = logging.getLogger(__name__)

CONTROL_TIMEOUT_SEC = max(0.1, float(os.getenv("STT_BRIDGE_CONTROL_TIMEOUT_SEC", "0.2")))
REALTIME_IDLE_RETURN_SEC = max(0.05, float(os.getenv("STT_BRIDGE_REALTIME_IDLE_RETURN_SEC", "0.22")))
FULL_SENTENCE_WAIT_MAX_SEC = max(0.4, float(os.getenv("STT_BRIDGE_FULL_SENTENCE_WAIT_MAX_SEC", "2.0")))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


CLEAR_BEFORE_FEED = _env_bool("STT_BRIDGE_CLEAR_BEFORE_FEED", False)
STOP_AFTER_FEED = _env_bool("STT_BRIDGE_STOP_AFTER_FEED", False)


class TranscribeReq(BaseModel):
    # HTTP 请求体模型。FastAPI 会自动校验字段并生成文档。
    """TranscribeReq: main class container for related behavior in this module."""
    audio: str
    sample_rate: int = 16000
    timeout_sec: float = 12.0


@dataclass(slots=True)
class TextMessage:
    """TextMessage: main class container for related behavior in this module."""
    msg_type: str
    text: str


class ProbeReq(BaseModel):
    """ProbeReq: main class container for related behavior in this module."""
    methods: list[str] = ["clear_audio_queue", "stop"]


class RealtimeSTTBridge:
    """RealtimeSTTBridge: main class container for related behavior in this module."""
    def __init__(self, control_ws: str, data_ws: str) -> None:
        # 初始化控制通道、数据通道与内部结果队列。
        """Initialize the object state and cache required dependencies."""
        self.control_ws_url = control_ws
        self.data_ws_url = data_ws
        self.control_ws = None
        self.data_ws = None
        self.queue: asyncio.Queue[TextMessage] = asyncio.Queue(maxsize=128)
        self.recv_task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.control_lock = asyncio.Lock()
        self.control_responses: deque[dict[str, Any]] = deque(maxlen=40)
        self.data_events: deque[dict[str, Any]] = deque(maxlen=80)
        self.connected_at = ""
        self.transcribe_count = 0
        self.transcribe_failures = 0
        self.last_error = ""
        self.last_transcribe: dict[str, Any] = {}

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _drain_queue(self) -> int:
        dropped = 0
        while not self.queue.empty():
            _ = self.queue.get_nowait()
            dropped += 1
        return dropped

    async def _mark_broken(self, reason: str) -> None:
        self.last_error = str(reason)
        self.transcribe_failures += 1
        logger.warning("realtimestt bridge connection reset: %s", reason)
        try:
            if self.recv_task is not None:
                self.recv_task.cancel()
        except Exception:
            pass
        self.recv_task = None
        try:
            if self.control_ws is not None:
                await self.control_ws.close()
        except Exception:
            pass
        try:
            if self.data_ws is not None:
                await self.data_ws.close()
        except Exception:
            pass
        self.control_ws = None
        self.data_ws = None

    async def ensure_connected(self) -> None:
        # 按需建立双 WS 连接，并启动后台接收协程。
        # RealtimeSTT 使用“控制通道 + 数据通道”双连接模型。
        """Public API `ensure_connected` used by other modules or route handlers."""
        if self.recv_task is not None and self.recv_task.done():
            self.recv_task = None
            self.control_ws = None
            self.data_ws = None

        if self.control_ws is None or self.data_ws is None:
            self.control_ws = await websockets.connect(self.control_ws_url, ping_interval=20)
            self.data_ws = await websockets.connect(self.data_ws_url, ping_interval=20)
            self.recv_task = asyncio.create_task(self._recv_loop())
            self.connected_at = self._now_iso()

    async def _recv_loop(self) -> None:
        # 接收 data_ws 的识别结果并写入本地消息队列。
        # 结果类型常见：realtime（中间结果）/fullSentence（最终句子）。
        """Internal helper `_recv_loop` used by this module implementation."""
        assert self.data_ws is not None
        try:
            async for message in self.data_ws:
                if isinstance(message, bytes):
                    continue
                try:
                    obj = json.loads(message)
                except Exception:
                    continue
                msg_type = str(obj.get("type", "")).strip()
                self.data_events.append(
                    {
                        "ts": self._now_iso(),
                        "type": msg_type,
                        "text": str(obj.get("text", ""))[:240],
                    }
                )
                if msg_type in {"realtime", "fullSentence"}:
                    text = str(obj.get("text", "")).strip()
                    if text:
                        try:
                            self.queue.put_nowait(TextMessage(msg_type=msg_type, text=text))
                        except asyncio.QueueFull:
                            _ = self.queue.get_nowait()
                            self.queue.put_nowait(TextMessage(msg_type=msg_type, text=text))
        except Exception as exc:
            await self._mark_broken(f"data recv failed: {exc}")

    async def _send_control(self, command: dict, timeout_sec: float = 2.0) -> dict[str, Any]:
        # 通过 control_ws 发送控制命令（start/stop 等）。
        """Internal helper `_send_control` used by this module implementation."""
        async with self.control_lock:
            await self.ensure_connected()
            assert self.control_ws is not None
            await self.control_ws.send(json.dumps(command))
            raw = await asyncio.wait_for(self.control_ws.recv(), timeout=max(0.1, timeout_sec))
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            try:
                obj = json.loads(str(raw))
            except Exception:
                obj = {"status": "unknown", "raw": str(raw)}
            self.control_responses.append(
                {
                    "ts": self._now_iso(),
                    "request": command,
                    "response": obj,
                }
            )
            return obj

    async def probe_control(self, methods: list[str]) -> dict[str, Any]:
        """Call a list of control methods and return raw acknowledgements."""
        out: dict[str, Any] = {}
        try:
            await self.ensure_connected()
        except Exception as exc:
            out["_connect"] = {"status": "error", "message": str(exc)}
            return out
        for method_name in methods:
            method = str(method_name or "").strip()
            if not method:
                continue
            try:
                out[method] = await self._send_control(
                    {"command": "call_method", "method": method, "args": [], "kwargs": {}},
                    timeout_sec=2.0,
                )
            except Exception as exc:
                out[method] = {"status": "error", "message": str(exc)}
        return out

    def debug_state(self) -> dict[str, Any]:
        """Export bridge runtime state and recent control/data activity."""
        return {
            "connected": {
                "control": self.control_ws is not None,
                "data": self.data_ws is not None,
                "since": self.connected_at,
                "recv_task_alive": bool(self.recv_task and not self.recv_task.done()),
            },
            "latency_tuning": {
                "control_timeout_sec": CONTROL_TIMEOUT_SEC,
                "realtime_idle_return_sec": REALTIME_IDLE_RETURN_SEC,
                "full_sentence_wait_max_sec": FULL_SENTENCE_WAIT_MAX_SEC,
                "clear_before_feed": CLEAR_BEFORE_FEED,
                "stop_after_feed": STOP_AFTER_FEED,
            },
            "queue_size": int(self.queue.qsize()),
            "transcribe_count": int(self.transcribe_count),
            "transcribe_failures": int(self.transcribe_failures),
            "last_error": self.last_error,
            "last_transcribe": dict(self.last_transcribe),
            "recent_control": list(self.control_responses),
            "recent_data": list(self.data_events),
        }

    @staticmethod
    def _build_binary_packet(pcm: bytes, sample_rate: int) -> bytes:
        # 组装 RealtimeSTT 所需的“元数据长度 + 元数据 + PCM”二进制包。
        # 前 4 字节是 little-endian 长度，后面紧跟 metadata JSON 和原始 PCM。
        """Internal helper `_build_binary_packet` used by this module implementation."""
        metadata = json.dumps({"sampleRate": int(sample_rate)}).encode("utf-8")
        return len(metadata).to_bytes(4, byteorder="little") + metadata + pcm

    async def transcribe(self, pcm_base64: str, sample_rate: int, timeout_sec: float) -> str:
        # 执行一次完整转写流程，优先返回 fullSentence，超时回退 realtime。
        # 串行化转写请求，避免多请求并发时串音。
        # 这里用 asyncio.Lock 达到“同一时刻只允许一个转写会话”。
        """Public API `transcribe` used by other modules or route handlers."""
        async with self.lock:
            self.transcribe_count += 1
            ts_start = self._now_iso()
            await self.ensure_connected()
            assert self.data_ws is not None

            dropped = self._drain_queue()

            try:
                pcm = base64.b64decode(pcm_base64, validate=True)
            except Exception:
                pcm = base64.b64decode(pcm_base64)

            safe_sample_rate = max(1, int(sample_rate))
            audio_duration_sec = len(pcm) / (2 * safe_sample_rate)

            # NOTE:
            # New RealtimeSTT server versions disallow control method "start".
            # The recorder loop is already running server-side, so we only clear/stop before feed.
            if CLEAR_BEFORE_FEED:
                try:
                    _ = await self._send_control(
                        {"command": "call_method", "method": "clear_audio_queue", "args": [], "kwargs": {}},
                        timeout_sec=CONTROL_TIMEOUT_SEC,
                    )
                except Exception:
                    pass

            await self.data_ws.send(self._build_binary_packet(pcm, sample_rate))

            deadline = asyncio.get_running_loop().time() + max(
                0.25,
                min(float(timeout_sec), FULL_SENTENCE_WAIT_MAX_SEC),
            )
            last_realtime = ""
            full_sentence = ""
            waited_ms = 0
            while asyncio.get_running_loop().time() < deadline:
                loop_now = asyncio.get_running_loop().time()
                remain_total = max(0.01, deadline - loop_now)
                if last_realtime:
                    remain = min(remain_total, REALTIME_IDLE_RETURN_SEC)
                else:
                    remain = remain_total
                t0 = asyncio.get_running_loop().time()
                try:
                    msg = await asyncio.wait_for(self.queue.get(), timeout=remain)
                except TimeoutError:
                    waited_ms += int((asyncio.get_running_loop().time() - t0) * 1000)
                    # Once we already have realtime text, return quickly on idle gap.
                    if last_realtime:
                        break
                    break
                waited_ms += int((asyncio.get_running_loop().time() - t0) * 1000)
                if msg.msg_type == "fullSentence":
                    full_sentence = msg.text
                    break
                if msg.msg_type == "realtime":
                    last_realtime = msg.text

            if STOP_AFTER_FEED:
                # Optional compatibility mode for deployments that require explicit stop.
                try:
                    _ = await self._send_control(
                        {"command": "call_method", "method": "stop", "args": [], "kwargs": {}},
                        timeout_sec=CONTROL_TIMEOUT_SEC,
                    )
                except Exception:
                    pass

            final_text = full_sentence or last_realtime
            self.last_transcribe = {
                "ts": ts_start,
                "sample_rate": int(sample_rate),
                "audio_sec": round(audio_duration_sec, 3),
                "queue_dropped": int(dropped),
                "waited_ms": int(waited_ms),
                "result_type": "fullSentence" if full_sentence else ("realtime" if last_realtime else "empty"),
                "result_preview": final_text[:200],
            }
            return final_text
        
        


CONTROL_WS = os.getenv("STT_CONTROL_WS_URL", "ws://127.0.0.1:8011")
DATA_WS = os.getenv("STT_DATA_WS_URL", "ws://127.0.0.1:8012")
HOST = os.getenv("STT_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.getenv("STT_BRIDGE_PORT", "9000"))

bridge = RealtimeSTTBridge(CONTROL_WS, DATA_WS)
app = FastAPI(title="RealtimeSTT HTTP Bridge")


@app.get("/")
async def root() -> dict[str, str]:
    # 桥接服务健康检查。
    """Public API `root` used by other modules or route handlers."""
    return {"status": "ok", "service": "realtimestt_http_bridge"}


@app.get("/debug/state")
async def debug_state() -> dict[str, Any]:
    """Expose bridge internal state for STT troubleshooting."""
    return bridge.debug_state()


@app.post("/debug/probe-control")
async def debug_probe_control(req: ProbeReq) -> dict[str, Any]:
    """Run control method probes and return the raw server acknowledgements."""
    methods = [str(x).strip() for x in req.methods if str(x).strip()]
    if not methods:
        methods = ["clear_audio_queue", "stop"]
    result = await bridge.probe_control(methods)
    return {"ok": True, "result": result}


@app.get("/debug/probe-control")
async def debug_probe_control_help() -> dict[str, Any]:
    """Browser-friendly hint for probe endpoint usage."""
    return {
        "ok": True,
        "hint": "Use POST with JSON body, e.g. {\"methods\":[\"clear_audio_queue\",\"stop\"]}",
        "example": {
            "method": "POST",
            "url": "/debug/probe-control",
            "json": {"methods": ["clear_audio_queue", "stop"]},
        },
    }


@app.post("/transcribe")
async def transcribe(req: TranscribeReq) -> dict[str, str]:
    # HTTP 转写入口：调用桥接器并返回文本结果。
    """Public API `transcribe` used by other modules or route handlers."""
    try:
        text = await bridge.transcribe(req.audio, req.sample_rate, req.timeout_sec)
        return {"text": text}
    except Exception as exc:
        bridge.last_error = str(exc)
        raise HTTPException(status_code=503, detail=f"stt transcribe failed: {exc}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
