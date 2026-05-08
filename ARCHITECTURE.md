# Nexus V5 — Architecture

> Version: 5.0
> Status: Planning / Phase 1 in progress
> Predecessor: [Nexus V4](https://github.com/Johnny3116/nexus-v4)

---

## Design Principle

**Nexus-managed delegation, not multi-agent autonomy.**

Every request flows through Nexus. Nexus classifies, Nexus approves plans, Nexus confirms execution, Nexus stores memory. Specialist agents (Codex, Sonnet) are tools she delegates to — not autonomous actors with their own agency.

This is intentional. Multi-agent autonomy without a coordinator creates repos that become archaeological sites. Task contracts and structured output prevent that.

---

## Components

### Nexus (Coordinator)

- **Model:** Ollama local (qwen2.5-coder:7b — evaluate upgrade)
- **Role:** Personality, user-facing interface, request classification, plan approval, verification, memory storage
- **What it does NOT do:** Write production code, make unreversible tool calls, act without a plan
- **Config:** `agents/nexus-coordinator.md`

### Codex (Planner)

- **Model:** OpenAI Codex via OAuth JWT
- **Role:** Given a TaskPacket, produce a structured PLAN.md — file list, change summary, implementation steps, acceptance criteria
- **Scope:** Planning only. Codex does not write final code in the build loop — it produces the plan Sonnet builds from
- **Why Codex for planning:** Strong at repo analysis, reading existing code structure, proposing PRs
- **Config:** `agents/codex-planner.md`
- **Credential:** `CODEX_JWT` in `.env`

### Sonnet / Claude Code (Builder)

- **Model:** Claude Sonnet via Anthropic API
- **Role:** Given an approved PLAN.md, implement the changes — write code, tests, refactor
- **Scope:** Implementation only. Takes the approved plan as spec. Does not deviate from it without Nexus approval
- **Why Sonnet for building:** Strong at code generation, refactor, multi-file edits; Claude Code supports MCP natively
- **Config:** `agents/sonnet-builder.md`
- **Credential:** `ANTHROPIC_API_KEY` in `.env`

### MCP (Tool Bridge)

- **Role:** Connect Nexus and builder agents to external systems and data
- **Phase 4 start (read-only):** filesystem read, repo inspect, docs search, memory query
- **Phase 4+ (write, with gates):** filesystem write, GitHub PR create, Supabase write, web fetch
- **Security:** per-agent allowlists in `mcp/allowed_tools.json`; destructive actions require confirmation
- **Inventory:** `mcp/servers.md`

### Supabase / Obsidian (Memory)

- **Supabase Nexus-AI:** Structured memory — conversations, tasks, knowledge embeddings, skill registry
- **Obsidian HOMEBASE:** Human-readable project state, synced across devices via Syncthing
- **Memory contract:** `memory/memory_contract.md`

---

## Request Flow (Detailed)

```
1. User input arrives (avatar WS, Discord, Telegram)

2. Nexus Router classifies intent:
   ├── chat         → respond directly, no delegation
   ├── skill        → invoke named skill from registry
   ├── code-plan    → build TaskPacket → send to Codex
   ├── code-build   → take approved plan → send to Sonnet
   ├── memory       → query/store Supabase memory
   ├── avatar       → trigger animation/speech
   └── admin        → system status, restart, config

3. [code-plan path]
   Nexus builds TaskPacket:
     Goal, Repo, Constraints, Files likely involved,
     Acceptance tests, Do not touch, Required output

4. TaskPacket → Codex → PLAN.md
   Codex reads repo (via MCP filesystem), proposes:
     - Files to change
     - Change summary per file
     - Step-by-step implementation
     - Acceptance criteria

5. PLAN.md → Nexus review
   Nexus checks plan against TaskPacket constraints.
   Approves, rejects, or requests revision.

6. Approved PLAN.md → Sonnet
   Sonnet implements changes file by file.
   Writes tests per acceptance criteria.
   Outputs diff / changed files.

7. Nexus verifier runs acceptance checklist
   Checks each criterion from TaskPacket.
   Pass → continue. Fail → loop back to Sonnet with failure context.

8. Nexus summarizes changes → stores to Supabase + session_summaries/
```

---

## TaskPacket Format

```
# Task Packet

**Goal:** [what needs to happen, in one sentence]
**Repo:** [repo name and relevant path]
**Constraints:** [hard limits — e.g. "no breaking changes to API"]
**Files likely involved:** [best guess — Codex will refine]
**Acceptance tests:** [specific, binary-testable criteria]
**Do not touch:** [explicit exclusions]
**Required output:** [PLAN.md | diff | PR | code only]
```

TaskPackets are structured data, not prose. `task_packet.py` serializes/deserializes them.

---

## Agent Prompt Contracts

Each agent has a markdown spec in `agents/` that defines:
- Role and scope
- Input format (what it receives)
- Output format (what it must return — structured only)
- Hard limits (what it must never do)
- Example input/output

Agents are configured, not hardcoded. Swapping Codex for a different planner means updating `codex-planner.md`, not rewriting Python.

---

## Skill System

Skills are named, callable units of work with a defined contract:

```python
# Every skill implements this interface
class Skill:
    name: str
    description: str
    input_schema: dict
    output_schema: dict

    def run(self, input: dict) -> dict: ...
```

Skills live in `skills/`. The registry (`registry.py`) maps skill names to implementations. Nexus can invoke a skill by name from any channel.

Initial skills:
- `github_skill` — repo read, file fetch, PR status (read-only Phase 4)
- `memory_skill` — Supabase query/write, promotion queue
- `avatar_skill` — trigger animations, speech, emotional state

---

## MCP Security Model

```
Per-agent tool allowlists
  nexus-coordinator: [memory_read, memory_write, avatar_control]
  codex-planner:     [filesystem_read, repo_read, docs_search]
  sonnet-builder:    [filesystem_read, filesystem_write_workspace, memory_read]
  reviewer:          [filesystem_read, test_runner]

Read/write separation:
  filesystem_read   ← always available in Phase 4
  filesystem_write  ← workspace-scoped only, not full system
  github_write      ← requires Nexus confirmation
  supabase_write    ← behind confirmation gate

Destructive action gates:
  file delete, git push, schema change, bulk memory update
  → always prompt Nexus for explicit confirmation before executing
```

Prompt injection via MCP tool results is a real attack surface. Tool outputs are sanitized before injection into LLM context.

---

## File Structure

```
Nexus/
  orchestrator/
    router.py           # Intent classification
    task_packet.py      # TaskPacket dataclass + serialization
    agent_runner.py     # Calls agents with contracts, validates output
    verifier.py         # Acceptance checklist runner

  agents/               # Prompt contracts (markdown, not code)
    nexus-coordinator.md
    codex-planner.md
    sonnet-builder.md
    reviewer.md

  skills/
    registry.py
    skill_contract.md
    github_skill.py
    memory_skill.py
    avatar_skill.py

  mcp/
    servers.md
    allowed_tools.json
    security_policy.md

  memory/
    memory_contract.md
    promotion_queue.md
    session_summaries/

  workflows/
    code_task.md
    bugfix_task.md
    research_task.md
    release_task.md
```
