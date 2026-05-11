# Nexus Desktop

Electron app that gives Nexus a real chat window + her existing avatar in one
place, with bridges to the local filesystem, MCP servers, Supabase, and
Discord. Designed to be the daily-driver UI when you don't want to use Discord
or the avatar standalone.

## Architecture

```
main.js  ← Electron main process
  │
  ├── BrowserWindow loads → renderer/chat.html (Chat tab + Avatar tab)
  ├── Tool server on :8889 (Express)  ← for avatar iframe → local tools
  └── IPC handlers → bridges/registry.js
                        │
                        ├── ollama-bridge      ← chat with HARD soul injection
                        ├── workspace-bridge   ← scoped FS R/W
                        ├── discord-bridge     ← webhook send
                        ├── supabase (existing) and mcp (existing) — Phase 2
```

The renderer is plain HTML / CSS / vanilla JS — no framework. Theme is black +
purple neon. Messages: user = green bubbles, Nexus = purple bubbles.

## How Nexus stays Nexus

`bridges/ollama-bridge.js` prepends `soul/soul.md` + `soul/doctrines.md` as
the system message on **every** Ollama call, wrapped with non-negotiable
identity rules ("you are Nexus, never claim to be ChatGPT/Llama/etc."). The
renderer cannot bypass this — even a custom "extra system prompt" from the
settings panel is **appended** to the soul, not substituted for it.

If you swap the model in settings, the soul stays. If you fine-tune a new
model, the soul stays. This is the "hard conditioning" layer.

A future Phase 3 enhancement bakes the same soul into an Ollama Modelfile
(`nexus:latest`) as belt-and-suspenders.

## Folder layout

```
nexus-desktop/
├── main.js              ← Electron entry, IPC handlers, tool server
├── preload.js           ← contextBridge — exposes window.nexus to renderer
├── renderer/
│   ├── chat.html        ← main UI (loaded by Electron)
│   ├── chat.js          ← chat logic
│   ├── neon.css         ← black + purple theme
│   ├── nexus-client.js  ← injected into avatar iframe (legacy, kept)
│   └── index.html       ← legacy avatar wrapper (still here for reference)
├── bridges/             ← chat-side connectors (see bridges/README.md)
├── tools/               ← Express endpoints exposed to avatar iframe (legacy)
├── skills/              ← Phase 2 work — local skills
├── soul/                ← soul.md + doctrines.md (copy of safety/identity/)
├── voice/               ← Phase 2 — TTS, Whisper, wake word
├── config/
│   ├── mcp.json         ← MCP servers
│   └── app-settings.json← user settings (gitignored)
├── data/                ← gitignored — chats, app state, user data
│   └── chats/           ← one JSON per chat
└── releases/            ← built installers (LFS-tracked)
```

## Run locally

```powershell
cd C:\Users\Nexus\Nexus\nexus-desktop
npm install
copy .env.example .env   # then edit
npm start
```

On first launch:

1. Click ⚙ Settings (top-right) → pick a workspace folder
2. Pick your default Ollama model
3. Start chatting — Nexus loads with soul + doctrines on every turn

## Build installer

```powershell
npm run build           # NSIS installer
npm run build:portable  # portable .exe
```

Output lands in `dist/` (gitignored). Hand-promote the `.exe` to `releases/`
for the GitHub Release.

## Working on this from the cloud (Lovable, web Claude, etc.)

Everything in this repo is portable — no PC-specific paths, no secrets. To
develop from a browser:

1. Make edits in the cloud IDE, push to `Johnny3116/nexus-v5/main`
2. On NexusBody: `git pull` then `npm start`

What stays local (never pushed):
- `.env` (machine-specific tokens / URLs)
- `data/` (chats, app settings, workspace path)
- `voice/recordings/` (audio — Phase 2)
- `node_modules/`, `dist/`

See `.gitignore` for the full list.

## Phase roadmap

| Phase | What |
|---|---|
| 1 ✅ | Chat UI, soul-conditioned Ollama bridge, workspace bridge, tabs |
| 2 ⬜ | Tool calling (Nexus invokes bridges autonomously), Discord/Supabase/MCP wiring from chat, voice (Whisper + TTS + wake word) |
| 3 ⬜ | Ollama Modelfile bake-in, auto-update, code signing, settings polish |
