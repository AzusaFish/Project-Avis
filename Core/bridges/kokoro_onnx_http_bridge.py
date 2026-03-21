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
    voice: str | None = None
    response_format: str = "wav"
    speed: float | None = None
    lang: str | None = None


class LegacyTTSReq(BaseModel):
    """LegacyTTSReq: main class container for related behavior in this module."""
    text: str
    voice: str | None = None
    speed: float | None = None
    format: str = "wav"
    lang: str | None = None


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
DEFAULT_VOICE = os.getenv("KOKORO_VOICE", "af_sky").strip()
DEFAULT_LANG = os.getenv("KOKORO_LANG", "en-us").strip()
DEFAULT_SPEED = float(os.getenv("KOKORO_SPEED", "1.0"))
HOST = os.getenv("KOKORO_HOST", "127.0.0.1")
PORT = int(os.getenv("KOKORO_PORT", "9880"))
CHUNK_CHARS = max(40, int(os.getenv("KOKORO_CHUNK_CHARS", "180")))
MIN_CHUNK_CHARS = max(8, int(os.getenv("KOKORO_MIN_CHUNK_CHARS", "24")))


if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(f"Kokoro model not found: {MODEL_PATH}")
if not os.path.exists(VOICES_PATH):
    raise FileNotFoundError(f"Kokoro voices not found: {VOICES_PATH}")

kokoro = Kokoro(MODEL_PATH, VOICES_PATH)
AVAILABLE_VOICES = set(kokoro.voices)
FALLBACK_VOICE = os.getenv("KOKORO_FALLBACK_VOICE", "af_sky").strip()
_WARNED_MISSING_VOICES: set[str] = set()
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


def _resolve_voice(voice: str) -> str:
    """Return a valid Kokoro voice, falling back gracefully if missing."""
    if voice in AVAILABLE_VOICES:
        return voice

    candidates = [
        FALLBACK_VOICE,
        "af_sky",
    ]
    fallback = next((v for v in candidates if v in AVAILABLE_VOICES), None)
    if fallback is None:
        fallback = next(iter(AVAILABLE_VOICES))

    if voice not in _WARNED_MISSING_VOICES:
        _WARNED_MISSING_VOICES.add(voice)
        preview = ", ".join(sorted(AVAILABLE_VOICES)[:12])
        logger.warning(
            "Requested voice '%s' not found; falling back to '%s'. "
            "Set KOKORO_VOICE or KOKORO_FALLBACK_VOICE to an available voice. "
            "Available preview: %s",
            voice,
            fallback,
            preview,
        )
    return fallback


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

    # Merge very short pieces to avoid unstable tiny-utterance synthesis.
    merged: list[str] = []
    for part in chunks:
        if merged and len(part) < MIN_CHUNK_CHARS:
            merged[-1] = f"{merged[-1]} {part}".strip()
        else:
            merged.append(part)
    if len(merged) > 1 and len(merged[-1]) < MIN_CHUNK_CHARS:
        merged[-2] = f"{merged[-2]} {merged[-1]}".strip()
        merged.pop()

    return merged or [text]


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
    speed = float(req.speed) if req.speed is not None else DEFAULT_SPEED
    if speed <= 0:
        raise HTTPException(status_code=400, detail="speed must be > 0")

    voice = _resolve_voice(req.voice or DEFAULT_VOICE)
    lang = req.lang or DEFAULT_LANG

    try:
        audio, sample_rate = _synthesize_text(text=text, voice=voice, speed=speed, lang=lang)
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
    speed = float(req.speed) if req.speed is not None else DEFAULT_SPEED
    if speed <= 0:
        raise HTTPException(status_code=400, detail="speed must be > 0")

    voice = _resolve_voice(req.voice or DEFAULT_VOICE)
    lang = req.lang or DEFAULT_LANG

    try:
        audio, sample_rate = _synthesize_text(text=text, voice=voice, speed=speed, lang=lang)
    except Exception as exc:
        logger.exception("Kokoro synthesis failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"kokoro synthesis failed: {exc}") from exc

    wav_bytes = _to_wav_bytes(audio, sample_rate)
    return Response(content=wav_bytes, media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn

    if DEFAULT_VOICE not in AVAILABLE_VOICES:
        logger.warning(
            "KOKORO_VOICE '%s' not available, service will auto-fallback at runtime.",
            DEFAULT_VOICE,
        )

    uvicorn.run(app, host=HOST, port=PORT)
