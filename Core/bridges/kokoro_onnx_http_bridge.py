"""
Module: bridges/kokoro_onnx_http_bridge.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# Kokoro ONNX HTTP bridge: expose /v1/audio/speech and /tts for Core TTS routing.

from __future__ import annotations

import io
import logging
import os
import re
import wave

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from kokoro_onnx import Kokoro
from pydantic import BaseModel


logger = logging.getLogger("kokoro_bridge")


class OpenAISpeechReq(BaseModel):
    """OpenAISpeechReq: main class container for related behavior in this module."""
    model: str = "kokoro"
    input: str
    voice: str = "af_sky"
    response_format: str = "wav"
    speed: float = 1.0
    lang: str = "en-us"


class LegacyTTSReq(BaseModel):
    """LegacyTTSReq: main class container for related behavior in this module."""
    text: str
    voice: str = "af_sky"
    speed: float = 1.0
    format: str = "wav"
    lang: str = "en-us"


def _to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    # Convert float32 waveform (-1~1) to PCM16 wav bytes for HTTP response.
    """Internal helper `_to_wav_bytes` used by this module implementation."""
    pcm16 = np.clip(audio, -1.0, 1.0)
    pcm16 = (pcm16 * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


MODEL_PATH = os.getenv(
    "KOKORO_MODEL_PATH",
    os.path.abspath("./assets/kokoro/kokoro-v1.0.onnx"),
)
VOICES_PATH = os.getenv(
    "KOKORO_VOICES_PATH",
    os.path.abspath("./assets/kokoro/voices-v1.0.bin"),
)
DEFAULT_VOICE = os.getenv("KOKORO_VOICE", "af_sky")
DEFAULT_LANG = os.getenv("KOKORO_LANG", "en-us")
HOST = os.getenv("KOKORO_HOST", "127.0.0.1")
PORT = int(os.getenv("KOKORO_PORT", "9880"))
CHUNK_CHARS = max(40, int(os.getenv("KOKORO_CHUNK_CHARS", "180")))


if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(f"Kokoro model not found: {MODEL_PATH}")
if not os.path.exists(VOICES_PATH):
    raise FileNotFoundError(f"Kokoro voices not found: {VOICES_PATH}")

kokoro = Kokoro(MODEL_PATH, VOICES_PATH)
app = FastAPI(title="Kokoro ONNX HTTP Bridge")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _normalize_text(text: str) -> str:
    """Internal helper `_normalize_text` used by this module implementation."""
    return re.sub(r"\s+", " ", text).strip()


def _split_text_chunks(text: str, max_chars: int) -> list[str]:
    """Internal helper `_split_text_chunks` used by this module implementation."""
    if len(text) <= max_chars:
        return [text]

    # Prefer sentence-like boundaries to reduce audible artifacts.
    segments = [seg.strip() for seg in re.split(r"(?<=[。！？!?；;,.，])", text) if seg.strip()]
    if not segments:
        segments = [text]

    chunks: list[str] = []
    buf = ""
    for seg in segments:
        candidate = f"{buf} {seg}".strip() if buf else seg
        if len(candidate) <= max_chars:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        if len(seg) <= max_chars:
            buf = seg
            continue
        # Hard split very long segment.
        for i in range(0, len(seg), max_chars):
            part = seg[i : i + max_chars].strip()
            if part:
                chunks.append(part)
    if buf:
        chunks.append(buf)
    return chunks or [text]


def _safe_kokoro_create(text: str, voice: str, speed: float, lang: str) -> tuple[np.ndarray, int]:
    """Internal helper `_safe_kokoro_create` used by this module implementation."""
    try:
        return kokoro.create(text=text, voice=voice, speed=speed, lang=lang)
    except IndexError as exc:
        # Work around kokoro_onnx token-boundary bug when input lands around max phoneme length.
        if "index 510" not in str(exc) or len(text) < 2:
            raise
        mid = len(text) // 2
        left = text[:mid].strip()
        right = text[mid:].strip()
        if not left or not right:
            raise

        left_audio, left_sr = _safe_kokoro_create(left, voice, speed, lang)
        right_audio, right_sr = _safe_kokoro_create(right, voice, speed, lang)
        if left_sr != right_sr:
            raise RuntimeError("Kokoro returned inconsistent sample rates across chunks")
        return np.concatenate([left_audio, right_audio]), left_sr


def _synthesize_text(text: str, voice: str, speed: float, lang: str) -> tuple[np.ndarray, int]:
    """Internal helper `_synthesize_text` used by this module implementation."""
    chunks = _split_text_chunks(text, CHUNK_CHARS)
    all_audio: list[np.ndarray] = []
    sample_rate: int | None = None

    for chunk in chunks:
        audio, sr = _safe_kokoro_create(chunk, voice, speed, lang)
        if sample_rate is None:
            sample_rate = sr
        elif sample_rate != sr:
            raise RuntimeError("Kokoro returned inconsistent sample rates")
        all_audio.append(audio)

    if not all_audio or sample_rate is None:
        raise RuntimeError("No audio generated")
    return np.concatenate(all_audio), sample_rate


@app.get("/")
async def root() -> dict[str, str]:
    """Public API `root` used by other modules or route handlers."""
    return {"status": "ok", "service": "kokoro_onnx_http_bridge"}


@app.post("/v1/audio/speech")
async def openai_speech(req: OpenAISpeechReq) -> Response:
    """Public API `openai_speech` used by other modules or route handlers."""
    text = _normalize_text(req.input or "")
    if not text:
        raise HTTPException(status_code=400, detail="input is required")
    if req.speed <= 0:
        raise HTTPException(status_code=400, detail="speed must be > 0")

    voice = req.voice or DEFAULT_VOICE
    lang = req.lang or DEFAULT_LANG

    try:
        audio, sample_rate = _synthesize_text(text=text, voice=voice, speed=float(req.speed), lang=lang)
    except Exception as exc:
        logger.exception("Kokoro synthesis failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"kokoro synthesis failed: {exc}") from exc

    wav_bytes = _to_wav_bytes(audio, sample_rate)
    return Response(content=wav_bytes, media_type="audio/wav")


@app.post("/tts")
async def legacy_tts(req: LegacyTTSReq) -> Response:
    """Public API `legacy_tts` used by other modules or route handlers."""
    text = _normalize_text(req.text or "")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    if req.speed <= 0:
        raise HTTPException(status_code=400, detail="speed must be > 0")

    voice = req.voice or DEFAULT_VOICE
    lang = req.lang or DEFAULT_LANG

    try:
        audio, sample_rate = _synthesize_text(text=text, voice=voice, speed=float(req.speed), lang=lang)
    except Exception as exc:
        logger.exception("Kokoro synthesis failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"kokoro synthesis failed: {exc}") from exc

    wav_bytes = _to_wav_bytes(audio, sample_rate)
    return Response(content=wav_bytes, media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
