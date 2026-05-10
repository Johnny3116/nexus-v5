"""TTS adapter — Kokoro-82M ONNX (local, CPU/GPU, ~300ms).

Drop-in replacement for the Edge-TTS adapter. Preserves the exact sync
signature so server.py needs no changes. Edge-TTS version preserved as
`sovits_ping.edge-tts.py` for rollback.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from threading import Lock

import soundfile as sf
from kokoro_onnx import Kokoro

_HERE = Path(__file__).parent
_MODEL_PATH = _HERE / "kokoro-v1.0.onnx"
_VOICES_PATH = _HERE / "voices-v1.0.bin"

VOICE = os.getenv("KOKORO_VOICE", "af_bella")
SPEED = float(os.getenv("KOKORO_SPEED", "1.0"))
LANG = os.getenv("KOKORO_LANG", "en-us")

_kokoro: Kokoro | None = None
_load_lock = Lock()


def _load() -> Kokoro:
    global _kokoro
    if _kokoro is None:
        with _load_lock:
            if _kokoro is None:
                _kokoro = Kokoro(str(_MODEL_PATH), str(_VOICES_PATH))
    return _kokoro


def get_wav_duration(path: str) -> float:
    with sf.SoundFile(path) as f:
        return len(f) / f.samplerate


def sovits_gen(in_text: str, output_wav_pth: str = "output.wav") -> str | None:
    """Synthesize `in_text` to WAV at `output_wav_pth`. Returns path on success, None on failure."""
    try:
        k = _load()
        samples, sample_rate = k.create(in_text, voice=VOICE, speed=SPEED, lang=LANG)
        sf.write(output_wav_pth, samples, sample_rate)
        return output_wav_pth
    except Exception as e:
        print("Error in kokoro sovits_gen:", e)
        return None


if __name__ == "__main__":
    start = time.time()
    out = sovits_gen("If you hear this, Kokoro TTS is working.", "output_test.wav")
    print(f"{time.time() - start:.2f}s -> {out}")
