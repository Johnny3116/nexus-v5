# Planner Agent — Constraints

Hard limits enforced regardless of what the LLM produces.

## Always True

- `requires_user_approval` is always `True`. The planner cannot approve its own plan.
- Planning runs are read-only: no file writes, no subprocess calls, no network during planning.
- Planning is local-only: no external MCP or cloud API calls in the plan phase.

## Context Limits

- Workspace context injected before the task (from context_reader.py):
  - File list from workspace/output/
  - Last 3 build log entries
  - Related file snippets (<=800 chars each, <=2KB total)
- Context is read-only.

## Revision Limits

- revision_round is tracked and incremented per revision.
- No hard cap on revision rounds (user may revise before approving).
- Each revision re-gathers workspace context (workspace may have changed).

## Model

Default: Ollama local model (env: OLLAMA_MODEL, default qwen2.5-coder:7b).
Temperature: 0.1 (low -- we want deterministic structured output).
Format: json (enforced in Ollama API call).
Future: configurable per-request to route to cloud planner (Sonnet, Codex).
