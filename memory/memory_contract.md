# Memory Contract

What gets stored, how, and when. Every agent that writes memory follows this contract.

---

## Storage Layers

| Layer | What | When |
|---|---|---|
| Supabase `memories` | Durable facts, completed task summaries, learned preferences | After verified task completion |
| Supabase `conversations` + `messages` | Full conversation history per channel | Every message |
| `workspace/` files | Working notes, in-progress task state, session scratch | During active work |
| `session_summaries/` | Human-readable per-session log | End of session |
| Obsidian HOMEBASE | User-facing reference docs, project notes | When content is worth reading later |

---

## What Gets Stored After a Completed Build

After Nexus verifies a build:

1. **Task summary** → `memories` table
   ```
   type: task_completion
   content: [goal, what changed, acceptance result]
   tags: [repo, files touched, agent used]
   ```

2. **Session summary** → `session_summaries/YYYY-MM-DD-{task}.md`
   ```
   # Session: [task goal]
   Date:
   Result: PASS / FAIL
   Files changed:
   Key decisions:
   What to know next time:
   ```

3. **Skill learnings** (if a new pattern emerged) → Supabase `memories`

---

## What Does NOT Get Stored

- Raw tool output or MCP responses
- Intermediate planning drafts (only final approved plan)
- Failed verification runs (unless they contain useful debugging info)
- Secrets, tokens, credentials — ever

---

## Memory Promotion Queue

`promotion_queue.md` holds items flagged for Supabase promotion that haven't been written yet (e.g. mid-session notes, pending summaries). Nexus reviews and promotes at session end.
