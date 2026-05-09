# Coordinator Agent — Routing Rules

## Priority Order

Rules are checked in this order. First match wins.

1. admin       — system/health check keywords
2. memory      — memory operation keywords
3. avatar      — avatar control keywords
4. code_build  — references an existing plan to execute
5. skill       — explicit skill invocation
6. code_plan   — planning/implementation work requested
7. chat        — fallback (no pattern matched)

## Trigger Keywords

### admin (confidence: 0.80)
restart, status, health check, is it running, check the bot, service,
scheduled task, avatar server, discord bot, telegram bot, ollama

### memory (confidence: 0.80)
remember, forget, recall, memory, memorize, store this, save this,
look up what, what did, last time, you said, we discussed

### avatar (confidence: 0.80)
animate, animation, pose, expression, lipsync, say out loud, speak out loud

### code_build (confidence: 0.80)
implement from, build from, execute plan, run the plan, apply plan,
plan approved, plan.md

### skill (confidence: 0.80)
run skill, use skill, invoke skill, call skill, execute skill

### code_plan (confidence: 0.75) [requires_task_packet: true]
plan, implement, build, refactor, add feature, wire, create, repo, github,
task packet, fix bug, fix the, add a, add to, update the, integrate,
migrate, write a, write the

### chat (confidence: 0.60) [fallback]
No keywords matched.

## Notes

- Matching is case-insensitive on the full lowercased message
- "First match wins" — priority order above is enforced in router.py
- Confidence values are advisory; not used for hard gating currently
