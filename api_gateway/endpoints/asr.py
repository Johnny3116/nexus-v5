"""Whisper ASR endpoint — POST /v1/asr

Accepts a multipart audio upload, transcribes via Faster-Whisper running on
NexusBody GPU/CPU, returns the text transcript.

Model is a lazy singleton — loaded on first request, reused for all subsequent
calls. Transcription runs in a thread executor to avoid blocking the event loop.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

logger = logging.getLogger("nexus.asr")
router = APIRouter(prefix="/v1", tags=["asr"])

_MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")
_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

_model: Optional[object] = None
_model_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")

_MIME_EXT: dict[str, str] = {
    "audio/webm": ".webm",
    "audio/wav": ".wav",
    "audio/wave": ".wav",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
}


def _load_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel  # deferred — keep import-time fast
                logger.info(
                    "Loading Whisper model '%s' on device '%s' (%s)",
                    _MODEL_SIZE, _DEVICE, _COMPUTE_TYPE,
                )
                _model = WhisperModel(
                    _MODEL_SIZE, device=_DEVICE, compute_type=_COMPUTE_TYPE
                )
                logger.info("Whisper model ready")
    return _model


@router.post("/asr")
async def transcribe(file: UploadFile = File(...)):
    """Transcribe an audio file to text.

    Returns: ``{"text": str, "language": str, "duration": float}``
    """
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="empty audio file")

    mime = (file.content_type or "audio/webm").split(";")[0].strip()
    suffix = _MIME_EXT.get(mime, ".webm")
    tmp_path: Optional[str] = None

    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        loop = asyncio.get_running_loop()

        def _run() -> tuple[str, str, float]:
            model = _load_model()
            segments, info = model.transcribe(
                tmp_path,
                beam_size=1,                       # greedy — ~3-5x faster on CPU than beam=5
                without_timestamps=True,           # skip alignment work for chat turns
                condition_on_previous_text=False,  # each utterance is independent
                vad_filter=True,                   # skip silent segments — avoids hanging on silence
                vad_parameters={"min_silence_duration_ms": 300},
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            return text, info.language, info.duration

        # 60s hard ceiling — executor uses a dedicated thread so it never blocks the event loop
        text, language, duration = await asyncio.wait_for(
            loop.run_in_executor(_executor, _run),
            timeout=60.0,
        )
        logger.info("ASR: '%s...' (lang=%s, %.1fs)", text[:60], language, duration)
        return JSONResponse(
            {"text": text, "language": language, "duration": round(duration, 2)}
        )

    except asyncio.TimeoutError:
        logger.error("ASR timed out after 60s")
        raise HTTPException(status_code=504, detail="transcription timed out")
    except ValueError as exc:
        # VAD found no speech segments (silent or non-speech audio)
        if "iterable argument is empty" in str(exc) or "empty" in str(exc).lower():
            logger.info("ASR: no speech detected in audio")
            return JSONResponse({"text": "", "language": "unknown", "duration": 0.0})
        logger.exception("ASR value error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("ASR transcription failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
