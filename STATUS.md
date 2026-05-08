# STATUS.md — Nexus V5

> Last updated: 2026-05-08
> Status: **Phase 1 — in progress**
> Predecessor: [Nexus V4](https://github.com/Johnny3116/nexus-v4) (complete)

---

## Phase Status

| Phase | Status | Description |
|---|---|---|
| **Phase 1** — Orchestrator Router | 🔄 In progress | Request classifier → intent type |
| **Phase 2** — Agent Configs | 🔲 Not started | Agent prompt contracts (markdown, not code) |
| **Phase 3** — Task Contracts | 🔲 Not started | TaskPacket system, structured I/O for all agents |
| **Phase 4** — MCP Read-Only | 🔲 Not started | Filesystem read, repo inspect, docs search, memory query |
| **Phase 5** — Build Loop | 🔲 Not started | Full plan → approve → implement → test → memory |

---

## First Milestone: TaskPacket Generator

Given a natural language request, produce reliable orchestration output:

- [ ] TaskPacket dataclass (`orchestrator/task_packet.py`)
- [ ] Intent router — classifies: chat / skill / code-plan / code-build / memory / avatar / admin
- [ ] TaskPacket builder — fills fields from classified request
- [ ] Codex planning prompt generator
- [ ] Sonnet build prompt generator
- [ ] Acceptance checklist generator
- [ ] Memory summary template
- [ ] Test: `"Add memory search to Discord bot"` → full packet output

No agent automation yet. Just reliable, validated orchestration.

---

## V4 Foundation (stable, running)

| Service | Status |
|---|---|
| Avatar server + VRM client | ✅ Live |
| Voicebox TTS + lipsync | ✅ Live |
| Discord bot | ✅ Live |
| Telegram bot | ✅ Live |
| Ollama (qwen2.5-coder:7b) | ✅ Live, GPU-pinned |
| Workspace directory | ✅ `C:\Users\Nexus\Nexus\workspace\` |
| Supabase Nexus-AI | ✅ Full access (service_role CREATE) |
| Scheduled task restart-on-failure | ✅ 3x / 1 min on all 5 tasks |

---

## Agent Credentials Status

| Agent | Credential | Status |
|---|---|---|
| Nexus (coordinator) | OLLAMA_URL + OLLAMA_MODEL | ✅ In .env |
| Codex (planner) | CODEX_JWT | ⚠️ Expires — check before Phase 2 |
| Sonnet (builder) | ANTHROPIC_API_KEY | ⚠️ Verify credits before Phase 3 |
| MCP | per-server configs | 🔲 Not configured yet |
