# CHANGELOG — Nexus AI

All notable changes to the Nexus AI project.

---

## [Nexus Desktop v1.1.0 + Phase 2A] — 2026-05-11 — Tool Calling (workspace ops)

> First chunk of Phase 2 lands today. Nexus can now actually create/read/write/list/delete files in the workspace instead of just pasting code in chat.

### Added
- **`bridges/tools.js`** — OpenAI-style function schemas + executor. Workspace tools: `workspace_list`, `workspace_read`, `workspace_write`, `workspace_delete`. Conditional `discord_send` tool — only registered when `DISCORD_WEBHOOK_URL` is set.
- **`bridges/ollama-bridge.js`** — `streamChat()` now accepts `tools` + `toolExecutor`. When tools are passed it switches from streaming to non-streaming requests (Ollama doesn't reliably emit `tool_calls` mid-stream), runs a tool-call loop (max 4 rounds), and forwards each call/result via `onToolCall` / `onToolResult` callbacks. When no tools, streaming path is unchanged.
- **System-prompt rule #8** — "When John asks you to CREATE/SAVE/WRITE/MAKE/DELETE a file — use the workspace tools. Do NOT paste file contents in chat as a substitute."
- **IPC events** `chat:tool-call` and `chat:tool-result` — main → renderer.
- **Renderer rendering** — tool calls show as a compact monospace bubble with a wrench icon (`🔧 workspace_write  hello.py  (24 chars)`); results show as a one-line follow-up in green (ok) or red (error). Tool calls persist in chat history (`message.toolCalls` array) so reloading a chat replays them.

### Changed
- **`main.js`** chat:send handler — passes tools only when a workspace is configured (otherwise the model could call tools that immediately fail). Uses non-streaming temperature 0.4 in tool mode for more deterministic tool selection.
- Mistral 7B-instruct confirmed working with Ollama native tools API.

### Why non-streaming when tools are enabled
Ollama streams text tokens but tool_calls only land in the final `done: true` chunk. Mixing the two reliably is fiddly — V5.3b's avatar pipeline made the same call. Trade-off: tool-enabled chats lose the typewriter effect; user sees ~1-3s pause then full response. Phase 2B could add hybrid streaming if it matters.

### Approval gates — what's NOT yet implemented
Doctrine 4 calls for Discord-reaction approval on writes/deletes. For the desktop app, all workspace tools auto-execute since they're scoped to the user-picked workspace folder (no traversal escape, no system access). Discord/Supabase tools when added in Phase 2B should gate behind an in-app confirm dialog.

---

## [Nexus Desktop v1.1.0] — 2026-05-11 — Chat UI + Bridges + Hard Soul Conditioning (Phase 1)

> Desktop companion app at `nexus-desktop/`. Versioned independently from Nexus AI core. Installs to `%LOCALAPPDATA%\Programs\Nexus Desktop\`.

### Added
- **Chat UI** (`nexus-desktop/renderer/`)
  - `chat.html` + `chat.js` + `neon.css` — vanilla HTML/CSS/JS, black + neon-purple theme
  - Tabs: Chat (default) + Avatar (iframe to NexusBody avatar server)
  - Side panel with chat list grouped by folder, new-chat button
  - Message bubbles: user = neon green, Nexus = neon purple
  - Streaming responses (NDJSON from Ollama) with typing cursor
  - Settings modal: workspace picker, Ollama model picker, bridge status indicators
- **Bridges** (`nexus-desktop/bridges/`)
  - `ollama-bridge.js` — chat completion with HARD soul + doctrines injection on every call. Cannot be bypassed by renderer; user-added "extra system prompt" is appended to soul, never substituted.
  - `workspace-bridge.js` — scoped FS R/W (rejects absolute paths and `..` traversal — Nexus only sees inside the user-picked folder)
  - `discord-bridge.js` — webhook send (bot listener deferred to Phase 2)
  - `registry.js` — central bridge status surface
- **Soul** (`nexus-desktop/soul/`)
  - `soul.md` + `doctrines.md` copied from `safety/identity/` so the desktop is self-contained for cloud edits (Lovable, web Claude)
  - System message wrapped with 5 non-negotiable identity rules ("you are Nexus, never claim to be ChatGPT/Llama/Mistral/Qwen/etc.")
- **Storage**
  - Chats: one JSON per chat in `data/chats/` (gitignored)
  - App settings in `data/app-settings.json` (gitignored, machine-specific)
  - Auto-titles chat from first user message (48-char preview)
- **Tool server** — kept legacy Express server on :8889 for avatar iframe → local tools (unchanged from v1.0.0)
- **NSIS installer** v1.1.0 — installs to `%LOCALAPPDATA%\Programs\Nexus Desktop\` with `.env` template, custom installer.nsh writes defaults

### Changed
- `package.json` — v1.0.0 → v1.1.0; description rewritten; build files list now includes `bridges/`, `soul/`, `skills/`, `config/mcp.json`; excludes `data/`, `releases/`, `voice/recordings/`
- `main.js` — loads `chat.html` (was `index.html`); adds 15+ IPC handlers for chat/workspace/settings/models/bridges; chat history persistence; iframe injection now skips main frame (only injects into avatar iframe)
- `preload.js` — exposes `window.nexus.{chat,workspace,settings,models,bridges,avatar,clipboard}`; kept legacy `window.nexusDesktop` for avatar iframe compat
- `.gitignore` — added `data/`, `voice/recordings/`, `*.wav`, `*.mp3`, `release/`, `config/app-settings.json`

### Fixed
- **`ENOTDIR` crash on packaged launch** — `main.js` was creating `data/` and `chats/` under `__dirname`, which resolves inside the read-only `app.asar` archive when packaged. Switched writable paths (chats, settings) to `app.getPath('userData')` (`%APPDATA%\nexus-desktop\data\`). Read-only paths (soul, doctrines) stay next to `main.js` — Electron's fs shim handles asar reads transparently.
- **Nexus reported wrong workspace path** — `soul.md` had `C:\Users\Nexus\Nexus\workspace\` hardcoded, so she spoke that path back even when the bridge was pointing at a different folder the user picked in Settings. Fix layered in two parts: (1) `nexus-desktop/soul/soul.md` rewritten to be path-agnostic — tells Nexus to read the workspace path from the "Runtime Context" section, never from memory. (2) `bridges/ollama-bridge.js` now builds a Runtime Context block (workspace path, model, date, app version, machine) fresh on every Ollama call and injects it AFTER the doctrines, with an explicit "Runtime Context overrides anything in the soul" rule added to the non-negotiable rules. Soul itself is still cached for speed; runtime block is rebuilt per call.

### Infrastructure
- **WorkstationPrime source deleted** — desktop source canonical home is now `C:\Users\Nexus\Nexus\nexus-desktop\` on NexusBody (previously `\\workstationprime\c$\Users\Johnn\Jarvis-Assistant\Projects\nexus-desktop` — that copy removed, will be re-cloned from GitHub when needed)
- **Git LFS** — installer EXEs in `nexus-desktop/releases/` tracked via LFS (.gitattributes added at repo root)
- **First install on NexusBody** — installed to `%LOCALAPPDATA%\Programs\Nexus Desktop\`, Desktop shortcut at `C:\Users\Nexus\Desktop\Nexus Desktop.lnk`

### Deferred to Phase 2
- Tool calling — Nexus invokes bridges autonomously (currently chat-only; she can talk about files but can't open them herself)
- Voice — Whisper STT, TTS routed through GPT-SoVITS, "Hello Nexus" wake word with mic toggle
- Folder management UI (folders are labels-only; rename/move chats requires JSON edit)
- Discord/Supabase/MCP wiring from chat itself (currently only via avatar's existing connectors)

### Deferred to Phase 3
- Ollama Modelfile that bakes soul into a custom `nexus:latest` model (belt-and-suspenders for hard conditioning)
- Auto-updater, code signing

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
