# trigger_test.py
import requests
import time
from pathlib import Path
import asyncio 

BASE_URL = "http://localhost:8001"
def vrm_talk(aud_path, expression, audio_text, audio_duraction):
    url = "http://localhost:8001/talk"
    payload = {
        "audio_path": aud_path,
        "expression": expression,
        "audio_text": audio_text,
        "audio_duraction": audio_duraction,
    }
    resp = requests.post(url, json=payload)
    print("Status:", resp.status_code)
    print("Response:", resp.json())


def vrm_animate(
    animation_type,
    animate_url,
    play_once=False,
    crop_start=0.0,
    crop_end=0.0,
    lock_position=False,
    track_position=True,
):
    """
    Play a VRMA or Mixamo animation.

    Args:
        animation_type: "start_vrma", "start_mixamo", or "auto" (auto-detect from extension)
        animate_url: Path to animation file (.vrma or .fbx)
        play_once: If True, play animation once then stop
        crop_start: Seconds to crop from start
        crop_end: Seconds to crop from end
        lock_position: If True, animation plays in place (no root translation)
        track_position: If True, character stays at end position after animation (default True)
    """
    url = f"{BASE_URL}/animate"
    payload = {
        "animate_type": animation_type,
        "animation_url": animate_url,
        "play_once": play_once,
        "crop_start": crop_start,
        "crop_end": crop_end,
        "lock_position": lock_position,
        "track_position": track_position,
    }
    resp = requests.post(url, json=payload)
    print(f"[animate] Status: {resp.status_code}")
    print(f"[animate] Response: {resp.json()}")
    return resp

