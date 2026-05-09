# Coordinator Agent — Routing Table

Maps route types to downstream pipelines.

| Route | Pipeline | Task Packet | User-Visible |
|---|---|---|---|
| `chat` | llm_stream → TTS → VRM broadcast | No | Yes (streamed) |
| `avatar` | notify_clients (direct WS payload) | No | Yes (animation) |
| `skill` | skill_runner (planned) | No | Yes |
| `code_plan` | task_packet → context_reader → planner → plan_response WS | Yes | Yes (plan card) |
| `code_build` | (future: execute existing plan directly) | No | Yes |
| `memory` | memory store (planned) | No | Yes |
| `admin` | admin handler (planned) | No | Yes |
| `unknown` | fallback to chat | No | Yes |

## Future: LLM Routing (Phase 2)

When the coordinator model is configured, keyword matching will be replaced with
an Ollama call using this agent's system.md as the system prompt.

The LLM receives the raw message and returns a JSON RouteDecision:
  {"route": "code_plan", "confidence": 0.90, "reason": "...", "requires_task_packet": true}
