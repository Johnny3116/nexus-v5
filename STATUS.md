# STATUS.md — Nexus AI

> Last updated: 2026-05-07
> Architecture: MVP — 100% Local Ollama + Avatar + Discord + Telegram
> Tested: 2026-05-07 — all pipelines confirmed working end-to-end

---

## Architecture

```
Browser chatbar ──► Avatar server :8001 (WebSocket)
                         │
                         ├── Ollama :11434 (qwen2.5-coder:7b)  ← LLM brain (LOCAL ONLY)
                         │         soul.md injected every call
                         └── Voicebox :17493 (chatterbox)      ← TTS (LOCAL ONLY)
                                  │
                                  └── VRM client :5180 (HTTPS)  ← avatar display

Discord bot ──► Ollama :11434  (direct, per-channel history)
Telegram bot ──► Ollama :11434 (direct, per-chat history)
```

**No cloud AI. No relay. No hybrid. Everything runs on NexusBody.**

---

## Services

| Service | Port | TLS | Process | Started by |
|---|---|---|---|---|
| Ollama | :11434 (localhost) | — | ollama app | Ollama system service |
| Voicebox TTS | :17493 (localhost) | — | `voicebox/backend/` Python | Scheduled Task `Nexus-Voicebox` |
| Avatar server | :8001 (Tailscale via TS serve) | TS cert | `serving/avatar-pipeline/server/server.py` | Scheduled Task `Nexus-Avatar-Pipeline` |
| VRM client | :5180 (Tailscale direct) | Python HTTPS (TS cert) | `client/` Python one-liner | Scheduled Task `Nexus-Avatar-Client` |
| Discord bot | — | — | `chat/discord_bot.py` | Scheduled Task `Nexus-Discord-Bot` |
| Telegram bot | — | — | `chat/telegram_bot.py` | Scheduled Task `Nexus-Telegram-Bot` |

**Note on :5180:** The VRM client runs its own Python HTTPS server using the Tailscale cert.
Tailscale serve is NOT proxying :5180 (removed — caused double-TLS 502).
The Python server handles TLS directly: https://nexusbody.tail344870.ts.net:5180

---

## Folder Structure

```
C:\Users\Nexus\Nexus\
├── .env                              # All credentials (never commit)
├── STATUS.md                         # This file
├── pyproject.toml                    # Python deps
├── chat/                             # Discord + Telegram bots
│   ├── discord_bot.py                # discord.py → Ollama (direct)
│   ├── telegram_bot.py               # python-telegram-bot → Ollama (direct)
│   └── history/                      # per-channel conversation JSON (gitignore)
├── serving/
│   └── avatar-pipeline/
│       ├── server/server.py          # FastAPI WS hub → stream_sentences → Voicebox → VRM
│       ├── client/                   # VRM browser UI (Three.js / pixiv-vrm / HTTPS :5180)
│       └── server/process/
│           ├── llm_funcs/llm_stream.py   # async sentence stream from Ollama
│           ├── tts_func/sovits_ping.py   # calls Voicebox :17493
│           └── tts_func/tts_preprocess.py
├── voicebox/                         # Chatterbox TTS engine
│   └── backend/                      # FastAPI on :17493
├── safety/
│   └── identity/
│       └── soul.md                   # Nexus personality — injected into every LLM call
├── archive/                          # Old components (OpenClaw, api_gateway, etc.)
└── model-registry/
    └── qwen2-5-coder-7b/             # Qwen model config
```

---

## Capability Status

| Capability | Status | Notes |
|---|---|---|
| Chat (avatar chatbar) | Live | WS → Ollama → TTS → VRM broadcast — tested 2026-05-07 |
| Avatar / VRM | Live | yami_no_eyez.vrm at nexusbody.tail344870.ts.net:5180 |
| Voice (TTS + lipsync) | Live | Chatterbox via Voicebox :17493, ~5s per sentence |
| Discord chat | Live | discord.py → Ollama, per-channel history |
| Telegram chat | Live | python-telegram-bot → Ollama, per-chat history — tested 2026-05-07 |
| Ollama (Qwen 2.5-Coder 7b) | Online | localhost:11434, pinned in VRAM |

---

## Performance (warm Ollama)

| Metric | Value |
|---|---|
| First token latency (warm) | ~3s |
| First token latency (cold) | ~24s |
| TTS generation per sentence | ~4-5s |
| Typical audio duration | 0.5-2s |

---

## Key Config (.env)

| Variable | Purpose |
|---|---|
| `OLLAMA_URL` | Ollama base URL (default: http://127.0.0.1:11434) |
| `OLLAMA_MODEL` | Model name (default: qwen2.5-coder:7b) |
| `VOICEBOX_URL` | Voicebox base URL (default: http://127.0.0.1:17493) |
| `VOICEBOX_PROFILE_ID` | Voice profile UUID for chatterbox |
| `DISCORD_BOT_TOKEN` | Discord bot token |
| `DISCORD_ALLOWED_CHANNEL_IDS` | Comma-separated channel IDs bot responds in |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Telegram chat ID to respond to |

---

## Startup Order

1. Ollama (auto, always running)
2. Voicebox TTS (`Nexus-Voicebox` task)
3. Avatar server (`Nexus-Avatar-Pipeline` task)
4. VRM client HTTP server (`Nexus-Avatar-Client` task)
5. Discord bot (`Nexus-Discord-Bot` task)
6. Telegram bot (`Nexus-Telegram-Bot` task)

All tasks trigger on logon (Interactive only). If a service dies, restart manually:
`schtasks /Run /TN "<TaskName>"`

---

## Access

| Resource | URL / Address |
|---|---|
| Avatar / VRM page | https://nexusbody.tail344870.ts.net:5180 |
| Avatar server (health) | https://nexusbody.tail344870.ts.net:8001/health |
| Voicebox | http://localhost:17493 (localhost only) |
| Ollama | http://localhost:11434 (localhost only) |

---

## Open Items

- [ ] Swap yami_no_eyez.vrm for Nexus Arachne VRM (drider design)
- [ ] Thread session_id through Discord/Telegram → avatar (unified memory)
- [ ] Add `/clear` command to bots to reset conversation history
- [ ] ASR (Whisper) — needs wiring to avatar server for voice input
- [ ] Evaluate upgrading Ollama model from qwen2.5-coder:7b to a larger model
- [ ] Fix: scheduled tasks are Interactive only — won't auto-start without a logged-in user
