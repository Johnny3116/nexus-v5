"""TTS adapter — Voicebox HTTP (local :17493, zero-shot voice cloning).

Drop-in replacement for the Kokoro adapter. Preserves the exact sync
signature so server.py needs no changes. Kokoro version preserved as
`sovits_ping.kokoro.py` for rollback.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import requests
import soundfile as sf

VOICEBOX_URL = os.getenv("VOICEBOX_URL", "http://127.0.0.1:17493")
PROFILE_ID = os.getenv("VOICEBOX_PROFILE_ID", "4d91abe5-1aa1-414f-8966-167455bd19d1")
ENGINE = os.getenv("VOICEBOX_ENGINE", "chatterbox_turbo")
LANGUAGE = os.getenv("VOICEBOX_LANG", "en")
POLL_TIMEOUT = int(os.getenv("VOICEBOX_TIMEOUT", "180"))
VOICEBOX_DATA_DIR = Path(os.getenv("VOICEBOX_DATA_DIR", r"C:\Users\Nexus\Nexus\voicebox\data"))


def get_wav_duration(path: str) -> float:
    with sf.SoundFile(path) as f:
        return len(f) / f.samplerate


def sovits_gen(in_text: str, output_wav_pth: str = "output.wav") -> str | None:
    """Synthesize `in_text` to WAV at `output_wav_pth`. Returns path on success, None on failure."""
    try:
        resp = requests.post(
            f"{VOICEBOX_URL}/generate",
            json={"profile_id": PROFILE_ID, "text": in_text, "language": LANGUAGE, "engine": ENGINE},
            timeout=30,
        )
        resp.raise_for_status()
        gen_id = resp.json()["id"]

        deadline = time.time() + POLL_TIMEOUT
        while time.time() < deadline:
            h = requests.get(f"{VOICEBOX_URL}/history/{gen_id}", timeout=10).json()
            status = h.get("status")
            if status == "completed":
                src = VOICEBOX_DATA_DIR / h["audio_path"]
                data, sr = sf.read(str(src))
                sf.write(output_wav_pth, data, sr)
                return output_wav_pth
            if status == "failed":
                print("Voicebox generation failed:", h.get("error"))
                return None
            time.sleep(1)
        print("Voicebox generation timed out after", POLL_TIMEOUT, "s")
        return None
    except Exception as e:
        print("Error in voicebox sovits_gen:", e)
        return None


if __name__ == "__main__":
    start = time.time()
    out = sovits_gen("If you hear this, Voicebox TTS is working.", "output_test.wav")
    print(f"{time.time() - start:.2f}s -> {out}")
