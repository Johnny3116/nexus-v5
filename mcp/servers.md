# MCP Servers

Inventory of MCP servers planned for V5 integration.

---

## Phase 4 — Read-Only (first)

| Server | Purpose | Data accessed | Status |
|---|---|---|---|
| filesystem | Read source files, workspace | Local files (scoped) | 🔲 Not configured |
| supabase | Query Nexus-AI memory, knowledge | Nexus-AI DB tables | 🔲 Not configured |
| github | Read repo structure, file contents | Repos (read-only) | 🔲 Not configured |

## Phase 4+ — Write (after read is stable)

| Server | Purpose | Confirmation gate |
|---|---|---|
| filesystem-write | Write to workspace/ | None (workspace only) |
| github-write | Create PRs, commit | Always |
| supabase-write | Write memories, skill results | None for rows; confirmation for DDL |

## Adding a Server

Follow the process in `security_policy.md` before adding any server.
