# bridges/

Connectors between the chat UI and external systems. Each bridge is a single
module that exposes a small, audited surface area.

## Wiring

```
renderer (chat.js)
    │ window.nexus.* (preload.js)
    ▼
main.js  ── ipcMain.handle ──▶  bridges/registry.js
                                      │
                                      ├─ ollama-bridge       (local LLM, soul injection)
                                      ├─ workspace-bridge    (scoped FS read/write)
                                      ├─ discord-bridge      (webhook send)
                                      ├─ supabase-bridge     (Phase 2 — see tools/supabase.js)
                                      └─ mcp-bridge          (Phase 2 — see tools/mcp-client.js)
```

## Soul conditioning is non-negotiable

`ollama-bridge.js` prepends `soul/soul.md` + `soul/doctrines.md` as the system
message on **every** call. The renderer cannot bypass this. Even if the user
edits the system-prompt textarea in the UI, that text is *appended* to the
soul, not substituted for it.

This is the "hard conditioning that overrides native Ollama" — it works with
any Ollama model because we never trust the model's defaults. The model is
told what it is on every turn.

A second layer (a custom Ollama Modelfile that bakes the soul into the model
weights' system prompt) lands in Phase 3.

## Workspace scoping

`workspace-bridge.js` is the *only* file-system surface available to chat.
Every path is resolved against the workspace root and rejected if it escapes.
Nothing outside the user-chosen workspace folder is reachable.

## Adding a new bridge

1. Create `bridges/your-bridge.js` exporting a small API.
2. Register it in `bridges/registry.js`.
3. Add IPC handlers in `main.js` (`bridges:your-bridge:action`).
4. Expose to renderer in `preload.js`.
5. Update `bridges/README.md` (this file) with the wiring.

## Phase 2 work

- [ ] Tool calling — let Nexus invoke bridges autonomously (not just respond)
- [ ] Discord bot listener (currently send-only)
- [ ] Supabase memory read/write from chat
- [ ] MCP servers discoverable from chat sidebar
- [ ] Voice bridges (TTS, Whisper, wake word) — see `voice/README.md`
