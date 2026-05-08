# Nexus V5

Building on the stable V4 foundation, V5 gives Nexus the ability to **use tools, run skills, connect to external services via MCP, and work autonomously in a persistent workspace**.

V4 proved the core loop: local Ollama brain, voice, avatar, Discord, Telegram — all working cleanly on one machine. V5 is about what Nexus can *do* with that brain.

---

## What's New in V5

| Feature | Description |
|---|---|
| **Tool use** | Nexus can call tools during a conversation — file ops, web search, code execution, API calls |
| **Skills** | Persistent, callable skill definitions Nexus can invoke by name — reusable capability modules |
| **MCP integration** | Model Context Protocol support — connect Nexus to external services and data sources |
| **Workspace** | Autonomous read/write access to `workspace/` — Nexus can create, edit, and persist files between sessions |
| **Supabase schema control** | Nexus can create and manage her own tables in Nexus-AI Supabase — self-evolving memory |

---

## Architecture

```
                    NexusBody (Windows 11, GPU)
                    ──────────────────────────────────────────
Browser ───────────► VRM Client (Three.js / pixiv-vrm)
                           │ WebSocket
                           ▼
                    Avatar Server (FastAPI)
                           │
             ┌─────────────┼──────────────┐
             ▼             ▼              ▼
          Ollama       Voicebox       Tool Router
      (qwen2.5-coder)  (Chatterbox)       │
       soul.md injected                   ├── Skills
                                          ├── MCP servers
                                          ├── Workspace (R/W)
                                          └── Supabase


Discord ──────────► discord_bot.py ──► Ollama + Tool Router
Telegram ─────────► telegram_bot.py ──► Ollama + Tool Router
```

---

## V5 Goals

### Phase 1 — Tool Use
- [ ] Tool call parsing — detect `<tool>` or function-call format in Ollama output
- [ ] Built-in tools: `read_file`, `write_file`, `list_dir` (workspace-scoped)
- [ ] Tool result injection — feed output back into LLM context, complete the loop
- [ ] Wire into all three channels (avatar, Discord, Telegram)

### Phase 2 — Skills
- [ ] Skill definition format — YAML or markdown skill specs in `skills/`
- [ ] Skill registry — Nexus can list and invoke skills by name
- [ ] Initial skills: `web_search`, `summarize`, `remember`, `create_note`
- [ ] Skill output routed back through soul container

### Phase 3 — MCP
- [ ] MCP server runner — launch and connect local MCP servers
- [ ] Initial MCP integrations: Supabase, filesystem, web search
- [ ] MCP tool discovery — Nexus can query available MCP tools dynamically

### Phase 4 — Autonomous Workspace
- [ ] Workspace index — Nexus maintains a manifest of workspace files
- [ ] Cross-session memory via workspace files (supplements Supabase)
- [ ] Self-tasking — Nexus can queue work items in workspace and pick them up

---

## Carried from V4

- All V4 services continue running unchanged (avatar, voice, Discord, Telegram)
- soul.md remains the personality source — injected on every call
- Supabase Nexus-AI for structured memory (service_role now has full CREATE access)
- Workspace directory: `C:\Users\Nexus\Nexus\workspace\`

---

## Stack

| Layer | Tech |
|---|---|
| LLM | Ollama — `qwen2.5-coder:7b` (evaluate upgrade in V5) |
| Tool routing | Python — integrated into avatar server and bots |
| Skills | YAML/markdown skill specs + Python invoker |
| MCP | Python MCP client lib |
| Workspace | Local filesystem, scoped to `workspace/` |
| Memory | Supabase Nexus-AI (pgvector, structured tables) |
| TTS | Chatterbox via Voicebox |
| Avatar | Three.js + `@pixiv/three-vrm` |
| Bots | discord.py + python-telegram-bot |
| Networking | Tailscale |
| OS | Windows 11 + Python 3.12 |

---

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — Technical breakdown (in progress)
- [STATUS.md](STATUS.md) — Current build status
- [V4 repo](https://github.com/Johnny3116/nexus-v4) — Stable V4 reference
