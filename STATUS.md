# STATUS.md — Nexus AI

> Last updated: 2026-05-11 (Nexus Desktop v1.1.0 Phase 1 shipped)
> Architecture: V5.3b — Local Ollama + Avatar + Connectors + Tool-Calling
> Tested: 2026-05-11 — avatar chat, voice, connectors, tool-calling confirmed working
> Companion app: Nexus Desktop v1.1.0 installed to `%LOCALAPPDATA%\Programs\Nexus Desktop\` on NexusBody (testing in progress)

---

## Architecture

```
Browser chatbar ──► Avatar server :8001 (WebSocket)
                         │
                         ├── Ollama :11434 (qwen2.5-coder:7b)  ← LLM brain (LOCAL)
                         │         soul.md injected every call
                         │         tool-calling: search_memories, save_memory, read_table
                         │
                         ├── Voicebox :17493 (chatterbox)       ← TTS (LOCAL)
                         │         custom voice profile 4d91abe5
                         │
                         ├── API Gateway :8000 (localhost)       ← connector dispatch
                         │         │
                         │         └── Connector Registry
                         │               └── Supabase Connector (read/write)
                         │
                         └── VRM client :5180 (HTTPS)            ← avatar display

Discord bot ──► Ollama :11434  (direct, per-channel history)
Telegram bot ──► Ollama :11434 (direct, per-chat history)

Connector panel (browser) ──► :8001/connectors (proxy) ──► :8000/v1/connectors (gateway)
```

**No cloud AI. All LLM inference on NexusBody. Secrets server-side only.**

---

## Services

| Service | Port | Binds to | Process | Status |
|---|---|---|---|---|
| Ollama | :11434 | localhost | ollama app | Online |
| Voicebox TTS | :17493 | localhost | `voicebox/backend/` Python | Online |
| API Gateway | :8000 | localhost | `api_gateway/main.py` uvicorn | Online |
| Avatar server | :8001 | 0.0.0.0 (+ TS serve) | `serving/avatar-pipeline/server/server.py` | Online |
| VRM client | :5180 | Tailscale IP | `client/` Python HTTPS | Online |
| Discord bot | — | — | `chat/discord_bot.py` | Online |
| Telegram bot | — | — | `chat/telegram_bot.py` | Online |
| Nexus Desktop (companion) | :8889 (tool srv) | localhost | `nexus-desktop/main.js` Electron | Installed v1.1.0, testing |

---

## Nexus Desktop (companion app — v1.1.0)

| | |
|---|---|
| **Source** | `nexus-desktop/` in this repo (Electron + vanilla HTML/JS, ~290 lines main.js, ~250 lines chat.js) |
| **Installed** | `C:\Users\Nexus\AppData\Local\Programs\Nexus Desktop\` |
| **User data** | `%APPDATA%\Nexus Desktop\data\` — chats (one JSON per chat), app settings |
| **Shortcut** | `C:\Users\Nexus\Desktop\Nexus Desktop.lnk` |
| **LLM** | Local Ollama (default `nexus-base:latest`, switchable in Settings) |
| **Soul** | `nexus-desktop/soul/soul.md` + `doctrines.md` — HARD-injected as system prompt on every Ollama call. Cannot be bypassed; user-set "extra system prompt" is appended, not substituted. |
| **Tabs** | Chat (default) — black + neon-purple UI; Avatar — iframe to `https://nexusbody.tail344870.ts.net:8001` |
| **Bridges** | `ollama-bridge`, `workspace-bridge` (scoped FS R/W), `discord-bridge` (webhook send) |
| **Phase 2 deferred** | Voice (Whisper + TTS + "Hello Nexus" wake word), tool calling so Nexus invokes bridges autonomously, Discord bot listener, Supabase/MCP wiring from chat |

---

## Connectors (V5.3)

| Connector | Status | Actions | Danger Level |
|---|---|---|---|
| Supabase Memory | Enabled / Healthy | search, read, write, list | Medium |
| GitHub (planned) | Not built | — | — |
| Local Docs (planned) | Not built | — | — |
| Gmail (planned) | Not built | — | — |

### Supabase Allowed Tables
`memories` (70), `agent_memories` (12), `game_notes` (25), `games` (3),
`game_currencies` (19), `game_builds`, `anime_series`, `anime_notes`, `anime_characters`

### Tool-Calling (V5.3b)
Nexus can invoke tools during conversation via Ollama's native function calling:
- `search_memories` — search any allowed Supabase table
- `save_memory` — persist facts to agent_memories
- `read_table` — browse rows with filters

Max 3 tool rounds per message. Results fed back to model for natural response.

---

## Folder Structure

```
C:\Users\Nexus\Nexus\
├── .env                              # All credentials (never commit)
├── STATUS.md                         # This file
├── CHANGELOG.md                      # Version history
├── pyproject.toml
├── api_gateway/                      # FastAPI gateway (:8000)
│   ├── main.py                       # Mounts all routers
│   ├── endpoints/
│   │   ├── chat.py                   # /v1/chat (soul + memories + RAG)
│   │   ├── connectors.py            # /v1/connectors (V5.3)
│   │   ├── memory.py                # /v1/memory (CRUD)
│   │   └── health.py, skill.py, task.py, workspace.py, asr.py
│   ├── auth/                         # Tailscale allowlist middleware
│   ├── config/                       # Settings, features
│   └── shared/types.py              # Pydantic models
├── orchestrator/
│   ├── connectors/                  # V5.3 Connector Registry
│   │   ├── registry.py              # Central connector catalog
│   │   ├── connector_schema.py      # Pydantic models
│   │   └── supabase_connector.py    # Supabase read/write (table allowlist)
│   ├── planner.py, builder.py, verifier.py, router.py
│   └── agent_loader.py
├── serving/
│   ├── avatar-pipeline/
│   │   ├── server/server.py         # FastAPI WS hub + connector proxy routes
│   │   ├── server/process/
│   │   │   ├── llm_funcs/llm_stream.py  # Ollama streaming + tool-calling (V5.3b)
│   │   │   ├── tts_func/sovits_ping.py  # Voicebox adapter (chatterbox)
│   │   │   └── tts_func/tts_preprocess.py  # Emoji/markdown stripping
│   │   └── client/                  # VRM browser UI
│   │       ├── index.html
│   │       ├── app.js, chatbar.js, connectorPanel.js
│   │       └── subtitles.js
│   └── brain_pool/
│       └── prompt_builder.py        # Soul + memories + RAG assembly
├── safety/
│   └── identity/
│       ├── soul.md                  # Full personality (injected for avatar/chat)
│       ├── soul-core.md             # Slim version (voice-only)
│       ├── soul_container.py        # Identity block builder + output filter
│       └── doctrines.md
├── events/
│   ├── event_bus.py
│   └── event_types.py              # Includes CONNECTOR_CALL/ERROR
├── chat/                            # Discord + Telegram bots
├── voicebox/                        # Chatterbox TTS engine
├── kv_cache/cold/supabase_client.py # Shared Supabase client
└── memory/                          # Memory layers
```

---

## Capability Status

| Capability | Status | Notes |
|---|---|---|
| Chat (avatar chatbar) | Live | WS -> Ollama -> TTS -> VRM broadcast |
| Avatar / VRM | Live | yami_no_eyez.vrm via Tailscale |
| Voice (TTS + lipsync) | Live | Chatterbox custom voice, ~5s/sentence |
| Subtitles | Live | Word-by-word streaming over TTS audio |
| Soul / personality | Live | Full soul.md for avatar, slim for pure voice |
| Connector panel (UI) | Live | V5.3 — Supabase status + search from browser |
| Tool-calling | Live | V5.3b — Nexus invokes search/save/read during chat |
| Memory (avatar) | Live | Top 8 user memories loaded per conversation |
| Discord chat | Live | discord.py -> Ollama, per-channel history |
| Telegram chat | Live | python-telegram-bot -> Ollama, per-chat history |
| Ollama | Online | qwen2.5-coder:7b, pinned in VRAM |
| API Gateway | Online | localhost:8000, connector dispatch |

---

## Performance (warm Ollama)

| Metric | Value |
|---|---|
| First token latency (warm) | ~3s |
| First token (with tool call) | ~6-10s (tool round + response) |
| TTS generation per sentence | ~4-5s |
| Connector search latency | ~1-2s (Supabase round-trip) |

---

## Key Config (.env)

| Variable | Purpose |
|---|---|
| `OLLAMA_URL` | Ollama base URL (default: http://127.0.0.1:11434) |
| `OLLAMA_MODEL` | Model name (default: qwen2.5-coder:7b) |
| `OLLAMA_NUM_PREDICT_VOICE` | Max tokens for avatar responses (default: 200) |
| `VOICEBOX_URL` | Voicebox base URL (default: http://127.0.0.1:17493) |
| `VOICEBOX_PROFILE_ID` | Voice profile UUID (4d91abe5-1aa1-414f-8966-167455bd19d1) |
| `VOICEBOX_ENGINE` | TTS engine (default: chatterbox_turbo) |
| `NEXUS_GATEWAY_URL` | Gateway URL for connector proxy (default: http://127.0.0.1:8000) |
| `SUPABASE_URL` | Supabase project URL (Nexus-AI instance) |
| `SUPABASE_SERVICE_KEY` | Supabase service role key (server-side only!) |
| `DISCORD_BOT_TOKEN` | Discord bot token |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |

---

## Startup Order

1. Ollama (auto, always running)
2. Voicebox TTS (Scheduled Task or `start-detached.ps1`)
3. API Gateway (`uvicorn api_gateway.main:app --host 127.0.0.1 --port 8000`)
4. Avatar server (`uvicorn server:app --host 0.0.0.0 --port 8001`)
5. VRM client (`Nexus-Avatar-Client` task)
6. Discord bot (`Nexus-Discord-Bot` task)
7. Telegram bot (`Nexus-Telegram-Bot` task)

**Remote management:** Use `Nexus Control.bat` on WorkstationPrime desktop.

---

## Access

| Resource | URL / Address |
|---|---|
| Avatar page | https://nexusbody.tail344870.ts.net:8001 |
| VRM client | https://nexusbody.tail344870.ts.net:5180 |
| Gateway health | http://localhost:8000/health (NexusBody only) |
| Connectors API | http://localhost:8000/v1/connectors (NexusBody only) |
| Voicebox | http://localhost:17493 (NexusBody only) |
| Ollama | http://localhost:11434 (NexusBody only) |

---

## Open Items

- [ ] Swap yami_no_eyez.vrm for Nexus Arachne VRM (drider design)
- [ ] GitHub connector (V5.4)
- [ ] Local docs / Obsidian connector (V5.4)
- [ ] Gmail connector (V5.5)
- [ ] Calendar connector (V5.5)
- [ ] MCP bridge connector (V5.6)
- [ ] Upgrade Ollama model from qwen2.5-coder:7b to a chat-tuned model
- [ ] Thread session_id through Discord/Telegram for unified memory
- [ ] Add `/clear` command to bots to reset conversation history
- [ ] ASR (Whisper) for voice input
- [ ] Confirmation gates for write actions in connector panel
- [ ] Fix: scheduled tasks are Interactive only — won't auto-start without logon
