"""TTS adapter — Edge-TTS (Microsoft free endpoint).

Works both standalone (`asyncio.run`) and inside uvicorn's event loop
(uses `nest_asyncio` or thread fallback).
"""

from __future__ import annotations

import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor

import edge_tts
import soundfile as sf

VOICE = os.getenv("EDGE_TTS_VOICE", "en-US-JennyNeural")
_pool = ThreadPoolExecutor(max_workers=2)


def get_wav_duration(path: str) -> float:
    with sf.SoundFile(path) as f:
        return len(f) / f.samplerate


async def _synthesize_async(text: str, output_path: str) -> None:
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output_path)


def _run_in_new_loop(text: str, output_path: str) -> None:
    """Run edge-tts in a fresh event loop on a thread (safe from inside uvicorn)."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_synthesize_async(text, output_path))
    finally:
        loop.close()


def sovits_gen(in_text: str, output_wav_pth: str = "output.wav") -> str | None:
    """Synthesize text to audio file. Works inside or outside an event loop."""
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            future = _pool.submit(_run_in_new_loop, in_text, output_wav_pth)
            future.result(timeout=30)
        else:
            asyncio.run(_synthesize_async(in_text, output_wav_pth))

        return output_wav_pth
    except Exception as e:
        print("Error in edge-tts sovits_gen:", e)
        return None


if __name__ == "__main__":
    start = time.time()
    out = sovits_gen("If you hear this, Edge TTS is working.", "output_test.mp3")
    print(f"{time.time() - start:.2f}s -> {out}")
