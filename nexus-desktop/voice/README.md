# voice/ — Phase 2

Placeholder for the voice subsystem. Nothing in here is wired yet.

## What lands here

| File | Purpose |
|---|---|
| `whisper.js`   | Whisper.cpp bridge for speech-to-text |
| `tts.js`       | Text-to-speech (system / edge-tts / hook to NexusServer GPT-SoVITS) |
| `wake.js`      | "Hello Nexus" wake-word detector (always-on, toggleable) |
| `mic.js`       | Mic stream capture with VAD (voice activity detection) |

## Design notes (drafted, not built)

- Wake word: lightweight detector (e.g. Porcupine free tier, or whisper-tiny
  on a 1s rolling buffer). Toggleable in settings. Off by default.
- Once wake fires: start full Whisper transcription, send to chat as a user
  message, stream Nexus's reply through TTS.
- TTS pipeline of preference:
  1. NexusServer GPT-SoVITS on :9880 (matches the avatar voice)
  2. Edge-TTS fallback if SoVITS is offline
  3. System TTS as last resort
- Recordings: never persisted unless user explicitly enables "save mic
  history" in settings. Default: discard immediately after transcription.

`*.wav` and `*.mp3` are gitignored — no audio ever pushed to GitHub.
