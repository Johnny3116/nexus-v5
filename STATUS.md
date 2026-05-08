# STATUS.md — Nexus V5

> Last updated: 2026-05-08
> Status: **IN PROGRESS — planning phase**
> Predecessor: [Nexus V4](https://github.com/Johnny3116/nexus-v4) (complete)

---

## Build Status

| Phase | Status | Description |
|---|---|---|
| Phase 1 — Tool Use | 🔲 Not started | Tool call parsing, built-in file tools, result injection |
| Phase 2 — Skills | 🔲 Not started | Skill registry, YAML skill specs, initial skill set |
| Phase 3 — MCP | 🔲 Not started | MCP server runner, Supabase/filesystem/search integrations |
| Phase 4 — Workspace | 🔲 Not started | Workspace index, cross-session file memory, self-tasking |

---

## V4 Foundation (all stable, running)

| Service | Status |
|---|---|
| Avatar server + VRM client | ✅ Live |
| Voicebox TTS + lipsync | ✅ Live |
| Discord bot | ✅ Live |
| Telegram bot | ✅ Live |
| Ollama (qwen2.5-coder:7b) | ✅ Live, GPU-pinned |
| Workspace directory | ✅ Created |
| Supabase Nexus-AI | ✅ Full access (service_role) |

---

## Next Up

Phase 1 — Tool Use:
1. Define tool call format for qwen2.5-coder output
2. Implement tool parser in avatar server
3. Wire `read_file` / `write_file` / `list_dir` (workspace-scoped)
4. Inject tool results back into LLM context
5. Test full tool loop via avatar chatbar
