# Nexus V5

V4 gave Nexus a brain, a voice, and three input channels. V5 gives her the ability to **plan, delegate, build, and remember** — while staying fully in control of what agents do and why.

V5 is not "autonomous AI." It is **Nexus-managed delegation**: a structured system where Nexus coordinates specialist agents, enforces task contracts, and owns every decision about what gets approved and executed.

---

## Agent Split

| Agent | Role | Model |
|---|---|---|
| **Nexus** | Coordinator · personality · user interface · final approval | Ollama (local) |
| **Codex** | Planning · repo analysis · task breakdown · PR proposals | OpenAI Codex (OAuth) |
| **Sonnet / Claude Code** | Implementation · refactor · test writing | Claude Sonnet (API) |
| **MCP** | Tool bridge — filesystem, GitHub, docs, memory, search | MCP servers (local) |
| **Supabase / Obsidian** | Structured memory · human-readable project state | Nexus-AI project |

No agent gets every tool. Each agent has an explicit allowlist and operates within a defined contract.

---

## Request Flow

```
User → Nexus
         │
         ▼
    Router classifies:
    chat | skill | code-plan | code-build | memory | avatar | admin
         │
    [dev work path]
         │
         ▼
    Nexus builds TaskPacket
    ┌─────────────────────────────┐
    │ Goal:                       │
    │ Repo:                       │
    │ Constraints:                │
    │ Files likely involved:      │
    │ Acceptance tests:           │
    │ Do not touch:               │
    │ Required output:            │
    └─────────────────────────────┘
         │
         ▼
    Codex → PLAN.md
         │
         ▼
    Nexus reviews plan → approve / reject / revise
         │
         ▼
    Sonnet implements from approved plan
         │
         ▼
    Nexus runs verification (acceptance checklist)
         │
         ▼
    Nexus summarizes → stores memory → done
```

---

## Repo Structure

```
Nexus/
  orchestrator/
    router.py           # Classifies requests → intent type
    task_packet.py      # TaskPacket dataclass + builder
    agent_runner.py     # Calls Codex / Sonnet with contracts
    verifier.py         # Runs acceptance checklist against output

  agents/
    nexus-coordinator.md   # Nexus persona + routing logic
    codex-planner.md       # Codex prompt contract
    sonnet-builder.md      # Sonnet prompt contract
    reviewer.md            # Review/verification agent contract

  skills/
    registry.py            # Skill lookup by name
    skill_contract.md      # What a skill is, how it's called
    github_skill.py        # GitHub operations (read-only first)
    memory_skill.py        # Supabase memory read/write
    avatar_skill.py        # Trigger avatar animations/speech

  mcp/
    servers.md             # MCP server inventory + purpose
    allowed_tools.json     # Per-agent tool allowlists
    security_policy.md     # Read/write separation, confirmation gates

  memory/
    memory_contract.md     # What gets stored, how, when
    promotion_queue.md     # Items waiting for Supabase promotion
    session_summaries/     # Per-session work logs

  workflows/
    code_task.md           # Full plan→build→verify workflow
    bugfix_task.md         # Bug triage → fix → test workflow
    research_task.md       # Research → summarize → store workflow
    release_task.md        # Release checklist workflow
```

---

## Build Phases

### Phase 1 — Orchestrator Router
Create a Nexus router that classifies requests into intent types.
Milestone: given any input, output correct intent + route. No agents yet.

### Phase 2 — Agent Configs
Define all agents as markdown prompt contracts, not hardcoded logic.
Milestone: any agent can be called with a TaskPacket and returns structured output.

### Phase 3 — Task Contracts
Every agent writes structured output only. TaskPacket in, structured response out.
Milestone: full plan→build→verify round trip on a test task, all output validated.

### Phase 4 — MCP (Read-Only First)
Add MCP tool access: filesystem read, repo inspect, docs search, memory query.
No write tools until Phase 4 is stable. Write tools behind confirmation gates.
Milestone: Nexus can answer "what files does X touch?" without hallucinating.

### Phase 5 — Build Loop
Wire the full loop: plan → approve → implement → test → summarize → memory.
Milestone: "Add memory search to Discord bot" → working PR, verified, memory stored.

---

## First Milestone: TaskPacket System

Before any agent automation, build a reliable local TaskPacket generator.

Given: `"Add memory search to Discord bot"`
Output:
- Task packet (structured)
- Codex planning prompt
- Sonnet build prompt
- Acceptance checklist
- Memory summary template

No code-writing automation yet. Just reliable orchestration. Once that's solid, wire the agents in.

---

## Security Rules

- **No agent gets every tool.** Tool access is per-agent allowlist in `mcp/allowed_tools.json`.
- **Read before write.** All MCP integrations start read-only. Write access added explicitly per tool per agent.
- **Confirmation gates on destructive actions.** File deletes, git pushes, schema changes — always confirm before execute.
- **MCP servers are treated like loaded weapons.** Prompt injection via tool results is a real attack vector. Validate and sanitize before injecting into LLM context.
- **Nexus owns final approval.** No agent auto-executes without Nexus confirming the plan first.

---

## Credentials

All agent credentials live in `.env` — never in code or docs.

| Variable | Purpose |
|---|---|
| `CODEX_JWT` | Codex OAuth JWT (chatgpt.com backend) |
| `ANTHROPIC_API_KEY` | Claude Sonnet API key |
| `OLLAMA_URL` | Local Ollama endpoint |
| `SUPABASE_URL` / `SUPABASE_KEY` | Nexus-AI Supabase project |

---

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — Technical breakdown
- [STATUS.md](STATUS.md) — Build status by phase
- [V4 repo](https://github.com/Johnny3116/nexus-v4) — Stable V4 reference
