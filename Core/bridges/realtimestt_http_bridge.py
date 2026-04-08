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
import os
from dataclasses import dataclass

import websockets
from fastapi import FastAPI
from pydantic import BaseModel


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

    async def ensure_connected(self) -> None:
        # 按需建立双 WS 连接，并启动后台接收协程。
        # RealtimeSTT 使用“控制通道 + 数据通道”双连接模型。
        """Public API `ensure_connected` used by other modules or route handlers."""
        if self.control_ws is None or self.data_ws is None:
            self.control_ws = await websockets.connect(self.control_ws_url, ping_interval=20)
            self.data_ws = await websockets.connect(self.data_ws_url, ping_interval=20)
            self.recv_task = asyncio.create_task(self._recv_loop())

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
                msg_type = obj.get("type", "")
                if msg_type in {"realtime", "fullSentence"}:
                    text = str(obj.get("text", "")).strip()
                    if text:
                        try:
                            self.queue.put_nowait(TextMessage(msg_type=msg_type, text=text))
                        except asyncio.QueueFull:
                            _ = self.queue.get_nowait()
                            self.queue.put_nowait(TextMessage(msg_type=msg_type, text=text))
        except Exception:
            self.control_ws = None
            self.data_ws = None

    async def _send_control(self, command: dict) -> None:
        # 通过 control_ws 发送控制命令（start/stop 等）。
        """Internal helper `_send_control` used by this module implementation."""
        assert self.control_ws is not None
        await self.control_ws.send(json.dumps(command))

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
            await self.ensure_connected()
            assert self.data_ws is not None

            while not self.queue.empty():
                # 清理上次残留消息，避免串包。
                _ = self.queue.get_nowait()

            pcm = base64.b64decode(pcm_base64)
            safe_sample_rate = max(1, int(sample_rate))
            audio_duration_sec = len(pcm) / (2 * safe_sample_rate)

            await self._send_control({"command": "call_method", "method": "start", "args": [], "kwargs": {}})
            await self.data_ws.send(self._build_binary_packet(pcm, sample_rate))
            settle_sec = min(1.5, max(0.15, audio_duration_sec * 0.35))
            await asyncio.sleep(settle_sec)
            await self._send_control({"command": "call_method", "method": "stop", "args": [], "kwargs": {}})

            deadline = asyncio.get_running_loop().time() + timeout_sec
            last_realtime = ""
            while asyncio.get_running_loop().time() < deadline:
                remain = max(0.05, deadline - asyncio.get_running_loop().time())
                try:
                    msg = await asyncio.wait_for(self.queue.get(), timeout=remain)
                except TimeoutError:
                    break
                if msg.msg_type == "fullSentence":
                    return msg.text
                last_realtime = msg.text
            return last_realtime


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


@app.post("/transcribe")
async def transcribe(req: TranscribeReq) -> dict[str, str]:
    # HTTP 转写入口：调用桥接器并返回文本结果。
    """Public API `transcribe` used by other modules or route handlers."""
    text = await bridge.transcribe(req.audio, req.sample_rate, req.timeout_sec)
    return {"text": text}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
