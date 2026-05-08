# MCP Security Policy

MCP servers are treated like loaded weapons with better branding. This policy governs how they are integrated into V5.

---

## Core Rules

1. **No agent gets every tool.** Tool access is defined per-agent in `allowed_tools.json`. If a tool isn't on an agent's allowlist, it cannot be called — regardless of what the LLM requests.

2. **Read before write.** All MCP integrations ship read-only in Phase 4. Write access is added explicitly, one tool at a time, after the read path is stable.

3. **Confirmation gates on all destructive actions.** The following always require explicit Nexus confirmation before executing:
   - File delete or overwrite (outside `workspace/`)
   - Git commit, push, PR creation
   - Supabase schema changes (CREATE TABLE, DROP, ALTER)
   - Bulk memory updates
   - Any action that cannot be trivially undone

4. **Workspace scoping.** Agent file write access is restricted to `workspace/`. Full filesystem write is never granted to any agent without explicit session authorization.

5. **Tool output sanitization.** MCP tool results are sanitized before injection into LLM context. Prompt injection via tool results is a real attack vector — treat external data as untrusted.

6. **No secrets in tool calls.** MCP tool calls must not contain API keys, tokens, or credentials. Credentials are managed by the server, not passed through agent prompts.

---

## Per-Agent Allowlists

See `allowed_tools.json` for the current allowlist per agent.

| Agent | Allowed Tools |
|---|---|
| nexus-coordinator | memory_read, memory_write, avatar_control, skill_invoke |
| codex-planner | filesystem_read, repo_read, docs_search |
| sonnet-builder | filesystem_read, filesystem_write (workspace only), memory_read |
| reviewer | filesystem_read, test_runner |

---

## Threat Model

**Prompt injection via tool results:** A malicious document or file read could inject instructions into the LLM's context. Mitigations:
- Wrap tool results in clearly delimited blocks before injection
- Never inject raw tool output directly into the system prompt
- Validate that tool result fields match expected schema before use

**Scope creep:** Agents requesting tools outside their allowlist. Mitigation: allowlist enforcement at the MCP client layer, not just the prompt.

**Credential exposure:** MCP servers should never echo credentials in their responses. Audit any new MCP server for this before adding to the allowlist.

---

## Adding a New MCP Server

Before adding any new MCP server to the system:

1. Document it in `servers.md` — name, purpose, what data it accesses
2. Define its allowlist entry in `allowed_tools.json`
3. Start read-only — no write tools on first integration
4. Test that tool output sanitization handles its response format
5. Add to `security_policy.md` threat notes if it accesses sensitive data
