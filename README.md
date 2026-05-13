# Nexus AI — V5 (Closed) → V6

> **V5 is closed as of 2026-05-13.** This document is the final V5 state. V6 planning begins fresh.

---

## V5 — What Was Built

V5 launched as an orchestration experiment (task packets, plan/build/verify pipelines) and evolved into a fully-running homelab AI with a personality, a face, a voice, and a desktop companion app.

**What V5 shipped, from start to finish:**

| Area | What Landed |
|---|---|
| **Orchestration** (M1–M18) | Router, task packets, plan→build→verify loop, retry gates, event bus, agent model configs, history store |
| **MVP Local Stack** (V5.2) | Ollama + Voicebox TTS + VRM avatar + Discord/Telegram bots + subtitles + wake word |
| **Connector Registry** (V5.3) | Supabase connector (17-table allowlist), REST API, browser connector panel, Nexus Control Panel |
| **Tool-Calling** (V5.3b) | Nexus invokes `search_memories` / `save_memory` / `read_table` mid-conversation |
| **Continuous Voice Mode** (V5.4) | Energy-based VAD, state machine, Whisper ASR, hands-free pipeline, status badges |
| **Reliability** (V5.4.1) | RAG activated, soul container unified across all LLM paths, avatar watchdog (auto-restart <10s) |
| **Nexus Desktop** (v1.0.0→v1.1.0) | Electron companion app — neon chat UI, hard-conditioned soul, streaming responses |
| **Desktop Widget** | Avatar tab embedded in desktop app — live VRM avatar alongside chat in one window |
| **Workspace Tool Calling** (Phase 2A) | Desktop can `create / read / write / delete` files in the user's workspace folder |

**Architecture on V5 close:**

```
Browser chatbar ──► Avatar server :8001 (WebSocket)
                         │
                         ├── Ollama :11434 (qwen2.5-coder:7b)  ← LLM (LOCAL)
                         ├── Voicebox :17493 (Chatterbox Turbo) ← TTS (LOCAL)
                         ├── API Gateway :8000                  ← ASR + connectors
                         └── VRM client :5180                   ← avatar display

Browser mic ──► voiceMode.js (VAD) ──► :8001/asr ──► :8000/v1/asr (Whisper)

Nexus Desktop (Electron)
  ├── Chat tab — neon UI, hard-conditioned soul, workspace tool calling
  └── Widget tab — live VRM avatar iframe (the "Desktop Widget")

Discord / Telegram bots ──► Ollama (per-channel history)
```

---

## V6 — Starting Backlog

V6 picks up where V5 stopped. No spec yet — priorities:

- GitHub connector (browse repos, issues, PRs from chat)
- Local docs / Obsidian connector
- Upgrade Ollama base model to a chat-tuned variant (qwen2.5-coder:7b is code-focused)
- Interruptible TTS — speak while Nexus is mid-sentence
- Wake-word triggered voice mode entry ("Hey Nexus")
- Wire workspace tool-calling into Discord / Telegram bots
- Thread `session_id` across all bots for unified cross-channel memory
- Confirmation gates for write actions (Doctrine 4 compliance in connectors)

---

## Reference Docs

- [CHANGELOG.md](CHANGELOG.md) — Full version history
- [STATUS.md](STATUS.md) — Live service status + capability matrix
- [nexus-desktop/README.md](nexus-desktop/README.md) — Desktop companion app docs

---

*V5 closed 2026-05-13 · Johnathan*
