# CHANGELOG — Nexus AI

All notable changes to the Nexus AI project.

---

## [V5.3b] — 2026-05-11 — Tool-Calling Connectors

### Added
- **Connector Registry** (`orchestrator/connectors/`) — pluggable system for external service access
  - `connector_schema.py` — Pydantic models (ConnectorMeta, ConnectorStatus, ConnectorRunRequest/Response)
  - `registry.py` — central catalog with register/get/list/enable/disable
  - `supabase_connector.py` — read/write access to 17 Supabase tables with allowlist security
- **Connector REST API** (`api_gateway/endpoints/connectors.py`)
  - `GET /v1/connectors` — list all connectors with health status
  - `GET /v1/connectors/{id}/status` — single connector info
  - `POST /v1/connectors/{id}/enable` / `disable` — toggle connectors
  - `POST /v1/connectors/{id}/run` — execute search/read/write/list actions
- **Event bus**: `CONNECTOR_CALL` and `CONNECTOR_ERROR` event types
- **Avatar frontend connector panel** (`client/connectorPanel.js`)
  - Status indicator button (top-right) with green/red dot
  - Expandable panel showing all connectors with enable/disable toggles
  - Quick Search UI for Supabase tables (memories, games, anime, etc.)
- **Avatar server proxy routes** — browser talks to :8001 only, gateway secrets never exposed
- **Ollama tool-calling** (`llm_stream.py` V5.3b)
  - `search_memories` — search Supabase memory during conversation
  - `save_memory` — persist new facts to agent_memories
  - `read_table` — browse game data, anime lists, or any allowed table
  - Max 3 tool rounds per message, auto-fallback to text response

### Changed
- **Soul container**: `_SLIM_PROMPT_TASKS` reduced to `{"voice"}` only — avatar chat now gets full `soul.md`
- **Avatar task type**: new `"avatar"` task type with concise-but-expressive personality hint
- **Token limit**: `OLLAMA_NUM_PREDICT` raised from 120 to 200 for avatar chat
- **TTS adapter**: switched from Kokoro (`af_bella`) back to Voicebox (Chatterbox Turbo, custom voice)
- **TTS preprocessing**: added emoji stripping, markdown removal before voice synthesis
- **Memory loading**: avatar chat now loads top 8 Supabase memories into system prompt
- **Avatar Chat Rules**: "2-3 sentences, concise, personality shows, speakable" (replaces 20-word max)
- **prompt_builder.py**: avatar task type loads memories but skips RAG (latency tradeoff)
- **API gateway main.py**: wired connectors import + router

### Fixed
- `prompt_builder.py` syntax error from literal newlines in string (CRLF encoding issue)
- Voicebox URL: was `http://` to Tailscale HTTPS proxy (SSL error) — fixed to `http://127.0.0.1:17493`
- TTS reading emoji names aloud — now stripped before synthesis

### Infrastructure
- **Nexus Control Panel** (`scripts/utilities/nexus-control.ps1` on WorkstationPrime)
  - Desktop shortcut: `Nexus Control.bat`
  - [1] Service status (Avatar, Gateway, Voicebox, Ollama, Connector proxy)
  - [2] Restart all services remotely via SSH
  - [3] Show recent changes (git log + modified files + connector status)
  - [4] Open avatar page in browser

---

## [V5.2] — 2026-05-07 — MVP Local Stack

### Added
- Avatar server on :8001 with WebSocket chat pipeline
- Ollama streaming (qwen2.5-coder:7b) with soul.md injection
- Voicebox TTS (Chatterbox Turbo) on :17493
- VRM client (Three.js + pixiv-vrm) on :5180
- Discord bot (discord.py direct to Ollama)
- Telegram bot (python-telegram-bot direct to Ollama)
- Subtitles system (word-by-word streaming over TTS audio)
- Wake word detection ("Hey Nexus")
- Per-channel conversation history

### Architecture
- 100% local — no cloud AI, no relay, no hybrid
- All services on NexusBody over Tailscale mesh
- Scheduled Tasks for auto-start on logon
