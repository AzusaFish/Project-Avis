"""
Module: bridges/genie_tts_http_bridge.py

Beginner note:
- This file exposes Kokoro-compatible HTTP endpoints backed by Genie-TTS.
- Read class/function docstrings below to understand data flow.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel


logger = logging.getLogger("genie_tts_bridge")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GENIE_DATA_DIR = str((PROJECT_ROOT / "assets" / "genie").resolve())
os.environ.setdefault("GENIE_DATA_DIR", DEFAULT_GENIE_DATA_DIR)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import genie_tts as genie
except Exception as exc:  # pragma: no cover - runtime dependency
    genie = None
    _GENIE_IMPORT_ERROR = exc
else:
    _GENIE_IMPORT_ERROR = None


class _GenieExtraReq(BaseModel):
    """_GenieExtraReq: shared optional fields for Genie runtime control."""

    character_name: str | None = None
    genie_character: str | None = None
    genie_character_name: str | None = None
    genie_predefined_character: str | None = None
    genie_onnx_model_dir: str | None = None
    genie_reference_audio_path: str | None = None
    genie_ref_audio_path: str | None = None
    genie_reference_text: str | None = None
    genie_ref_audio_text: str | None = None
    genie_language: str | None = None


class OpenAISpeechReq(_GenieExtraReq):
    """OpenAISpeechReq: request model for /v1/audio/speech compatibility."""

    model: str = "kokoro"
    input: str
    voice: str | None = None
    response_format: str = "wav"
    speed: float | None = None
    lang: str | None = None


class LegacyTTSReq(_GenieExtraReq):
    """LegacyTTSReq: request model for /tts compatibility."""

    text: str
    voice: str | None = None
    speed: float | None = None
    format: str = "wav"
    lang: str | None = None


@dataclass(frozen=True)
class GenieRuntimeSpec:
    """Resolved runtime spec for one synthesis request."""

    runtime_character: str
    language: str
    onnx_model_dir: str
    reference_audio_path: str
    reference_audio_text: str


def _to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """Convert float waveform (-1~1) to PCM16 wav bytes."""
    pcm16 = np.clip(audio, -1.0, 1.0)
    pcm16 = (pcm16 * 32767.0).astype(np.int16)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fp:
        tmp_path = Path(fp.name)
    try:
        with wave.open(str(tmp_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm16.tobytes())
        return tmp_path.read_bytes()
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def _first_non_empty(*values: str | None) -> str:
    """Return first non-empty trimmed string, or empty string."""
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_text(text: str) -> str:
    """Collapse repeated whitespace for stable synthesis input."""
    return re.sub(r"\s+", " ", text).strip()


def _normalize_lang(lang: str) -> str:
    """Map user language variants to Genie language codes."""
    value = (lang or "").strip().lower()
    if value.startswith(("zh", "cn")):
        return "zh"
    if value.startswith(("ja", "jp")):
        return "jp"
    return "en"


def _resolve_path(path: str) -> str:
    """Resolve a possibly-relative path against Core project root."""
    if not path:
        return ""
    p = Path(path)
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    return str(p)


def _parse_voice_aliases(raw: str) -> dict[str, str]:
    """Parse GENIE_VOICE_ALIASES like 'atri:thirtyseven,foo:bar'."""
    mapping: dict[str, str] = {"atri": "thirtyseven"}
    text = (raw or "").strip()
    if not text:
        return mapping
    for part in text.split(","):
        pair = part.strip()
        if ":" not in pair:
            continue
        source, target = pair.split(":", 1)
        source = source.strip().lower()
        target = target.strip()
        if source and target:
            mapping[source] = target
    return mapping


DEFAULT_VOICE = os.getenv("KOKORO_VOICE", "atri").strip() or "atri"
DEFAULT_LANG = os.getenv("KOKORO_LANG", "en-us").strip() or "en-us"
DEFAULT_SPEED = float(os.getenv("KOKORO_SPEED", "1.0"))
DEFAULT_REFERENCE_AUDIO_PATH = os.getenv(
    "GENIE_REFERENCE_AUDIO_PATH",
    str((PROJECT_ROOT / "assets" / "voices" / "neutral.wav").resolve()),
).strip()
DEFAULT_REFERENCE_TEXT = os.getenv(
    "GENIE_REFERENCE_TEXT",
    "Hello, this is Atri speaking. We can do this together.",
).strip()
DEFAULT_PREDEFINED_CHARACTER = os.getenv("GENIE_PREDEFINED_CHARACTER", "thirtyseven").strip() or "thirtyseven"
VOICE_ALIASES = _parse_voice_aliases(os.getenv("GENIE_VOICE_ALIASES", "atri:thirtyseven"))
HOST = os.getenv("KOKORO_HOST", "127.0.0.1")
PORT = int(os.getenv("KOKORO_PORT", "9880"))
_SAMPLE_RATE_FALLBACK = int(os.getenv("GENIE_SAMPLE_RATE_FALLBACK", "32000"))

_genie_lock = Lock()
_loaded_models: dict[str, str] = {}
_configured_references: dict[str, str] = {}
_warned_missing_reference_paths: set[str] = set()

app = FastAPI(title="Genie TTS HTTP Bridge")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_genie() -> None:
    """Raise a clear HTTP error when genie_tts is not installed."""
    if genie is None:
        detail = (
            "genie_tts import failed. Install `genie-tts` in Core runtime env. "
            f"Import error: {_GENIE_IMPORT_ERROR}"
        )
        raise HTTPException(status_code=503, detail=detail)


def _resolve_runtime_spec(req: _GenieExtraReq, voice: str | None, lang: str | None) -> GenieRuntimeSpec:
    """Resolve profile-like fields from request into one runtime spec."""
    requested_character = _first_non_empty(
        req.character_name,
        req.genie_character_name,
        req.genie_character,
        voice,
        DEFAULT_VOICE,
    )
    requested_character = requested_character or DEFAULT_PREDEFINED_CHARACTER
    language = _normalize_lang(_first_non_empty(req.genie_language, lang, DEFAULT_LANG))
    onnx_model_dir = _resolve_path(_first_non_empty(req.genie_onnx_model_dir))

    runtime_character = requested_character
    if not onnx_model_dir:
        runtime_character = _first_non_empty(
            req.genie_predefined_character,
            VOICE_ALIASES.get(requested_character.lower(), ""),
            requested_character,
            DEFAULT_PREDEFINED_CHARACTER,
        )

    reference_audio_path = _resolve_path(
        _first_non_empty(
            req.genie_reference_audio_path,
            req.genie_ref_audio_path,
            DEFAULT_REFERENCE_AUDIO_PATH,
        )
    )
    reference_audio_text = _first_non_empty(
        req.genie_reference_text,
        req.genie_ref_audio_text,
        DEFAULT_REFERENCE_TEXT,
    )

    return GenieRuntimeSpec(
        runtime_character=runtime_character,
        language=language,
        onnx_model_dir=onnx_model_dir,
        reference_audio_path=reference_audio_path,
        reference_audio_text=reference_audio_text,
    )


def _ensure_character_loaded(spec: GenieRuntimeSpec) -> None:
    """Load character runtime (onnx or predefined) exactly once per config key."""
    model_key = (
        f"onnx::{spec.onnx_model_dir}::{spec.language}"
        if spec.onnx_model_dir
        else f"predefined::{spec.runtime_character}"
    )
    if _loaded_models.get(spec.runtime_character) == model_key:
        return

    if spec.onnx_model_dir:
        if not Path(spec.onnx_model_dir).exists():
            raise RuntimeError(f"Genie ONNX model dir not found: {spec.onnx_model_dir}")
        genie.load_character(
            character_name=spec.runtime_character,
            onnx_model_dir=spec.onnx_model_dir,
            language=spec.language,
        )
    else:
        genie.load_predefined_character(spec.runtime_character)

    _loaded_models[spec.runtime_character] = model_key


def _ensure_reference_audio(spec: GenieRuntimeSpec) -> None:
    """Bind reference audio for cloning when the path exists."""
    if not spec.reference_audio_path:
        return

    if not Path(spec.reference_audio_path).exists():
        if spec.reference_audio_path not in _warned_missing_reference_paths:
            _warned_missing_reference_paths.add(spec.reference_audio_path)
            logger.warning("Reference audio file not found: %s", spec.reference_audio_path)
        return

    ref_key = f"{spec.reference_audio_path}::{spec.reference_audio_text}"
    if _configured_references.get(spec.runtime_character) == ref_key:
        return

    genie.set_reference_audio(
        character_name=spec.runtime_character,
        audio_path=spec.reference_audio_path,
        audio_text=spec.reference_audio_text,
    )
    _configured_references[spec.runtime_character] = ref_key


def _invoke_genie_tts(
    character_name: str,
    text: str,
    save_path: str,
    speed: float,
) -> Any:
    """Call genie.tts with several signature-compatible variants."""
    attempts: list[dict[str, Any]] = []
    for char_key in ("character_name", "character"):
        base = {char_key: character_name, "text": text, "save_path": save_path}
        attempts.append({**base, "play": False, "speed": speed})
        attempts.append({**base, "play": False})
        attempts.append(base)

    last_type_error: Exception | None = None
    for kwargs in attempts:
        try:
            return genie.tts(**kwargs)
        except TypeError as exc:
            last_type_error = exc
            continue

    if last_type_error is not None:
        raise RuntimeError(f"genie.tts signature mismatch: {last_type_error}") from last_type_error
    raise RuntimeError("genie.tts failed before invocation")


def _result_to_wav_bytes(result: Any) -> bytes | None:
    """Convert non-file return value from genie.tts into wav bytes when possible."""
    if isinstance(result, (bytes, bytearray)):
        return bytes(result)
    if isinstance(result, np.ndarray):
        return _to_wav_bytes(result, _SAMPLE_RATE_FALLBACK)
    if (
        isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[0], np.ndarray)
        and isinstance(result[1], int)
    ):
        return _to_wav_bytes(result[0], int(result[1]))
    return None


def _synthesize_wav_bytes(text: str, spec: GenieRuntimeSpec, speed: float) -> bytes:
    """Run Genie inference and return wav bytes."""
    _require_genie()

    with _genie_lock:
        _ensure_character_loaded(spec)
        _ensure_reference_audio(spec)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fp:
            wav_path = Path(fp.name)
        try:
            result = _invoke_genie_tts(
                character_name=spec.runtime_character,
                text=text,
                save_path=str(wav_path),
                speed=speed,
            )
            if wav_path.exists() and wav_path.stat().st_size > 0:
                return wav_path.read_bytes()
            converted = _result_to_wav_bytes(result)
            if converted:
                return converted
            raise RuntimeError("Genie produced no wav output file and no in-memory audio")
        finally:
            try:
                wav_path.unlink()
            except OSError:
                pass


@app.get("/")
async def root() -> dict[str, str]:
    """Health probe endpoint."""
    status = "ok" if genie is not None else "degraded"
    return {"status": status, "service": "genie_tts_http_bridge"}


@app.post("/v1/audio/speech")
async def openai_speech(req: OpenAISpeechReq) -> Response:
    """OpenAI-style compatibility endpoint for TTSService."""
    text = _normalize_text(req.input or "")
    if not text:
        raise HTTPException(status_code=400, detail="input is required")

    speed = float(req.speed) if req.speed is not None else DEFAULT_SPEED
    if speed <= 0:
        raise HTTPException(status_code=400, detail="speed must be > 0")

    if req.response_format.lower() != "wav":
        logger.warning("response_format=%s requested; bridge still returns wav", req.response_format)

    spec = _resolve_runtime_spec(req=req, voice=req.voice, lang=req.lang)
    try:
        wav_bytes = await asyncio.to_thread(_synthesize_wav_bytes, text, spec, speed)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Genie synthesis failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"genie synthesis failed: {exc}") from exc
    return Response(content=wav_bytes, media_type="audio/wav")


@app.post("/tts")
async def legacy_tts(req: LegacyTTSReq) -> Response:
    """Legacy compatibility endpoint used by fallback calls."""
    text = _normalize_text(req.text or "")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    speed = float(req.speed) if req.speed is not None else DEFAULT_SPEED
    if speed <= 0:
        raise HTTPException(status_code=400, detail="speed must be > 0")

    if req.format.lower() != "wav":
        logger.warning("format=%s requested; bridge still returns wav", req.format)

    spec = _resolve_runtime_spec(req=req, voice=req.voice, lang=req.lang)
    try:
        wav_bytes = await asyncio.to_thread(_synthesize_wav_bytes, text, spec, speed)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Genie synthesis failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"genie synthesis failed: {exc}") from exc
    return Response(content=wav_bytes, media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
