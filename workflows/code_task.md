# Workflow: Code Task

The full plan → approve → implement → verify → memory loop.

---

## Trigger
Nexus classifies request as `code-plan`.

## Steps

```
1. NEXUS: Build TaskPacket from request
   → Fill: Goal, Repo, Constraints, Files likely involved,
           Acceptance tests, Do not touch, Required output

2. NEXUS → CODEX: Send TaskPacket as planning prompt
   → Codex reads repo (MCP filesystem_read)
   → Codex outputs: PLAN.md

3. NEXUS: Review PLAN.md
   → Check: Does plan stay within Do not touch?
   → Check: Are acceptance criteria addressed?
   → Check: Does plan match Goal?
   → Decision: APPROVE / REJECT / REQUEST_REVISION

4. [If APPROVE] NEXUS → SONNET: Send approved PLAN.md + relevant files
   → Sonnet implements changes
   → Sonnet outputs: IMPLEMENTATION_REPORT.md + changed files

5. NEXUS → REVIEWER: Run acceptance checklist
   → Input: TaskPacket acceptance tests + IMPLEMENTATION_REPORT.md
   → Output: Verification report (PASS/FAIL per criterion)

6. [If PASS] NEXUS: Store memory
   → Write task summary to Supabase memories
   → Write session summary to session_summaries/
   → Summarize to user

7. [If FAIL] NEXUS → SONNET: Send failure report + revision request
   → Loop back to step 4 (max 3 iterations before escalating to user)
```

## Artifacts

| File | Created by | Consumed by |
|---|---|---|
| `task_packet.json` | Nexus | Codex |
| `PLAN.md` | Codex | Nexus (review), Sonnet |
| `IMPLEMENTATION_REPORT.md` | Sonnet | Reviewer |
| `VERIFICATION_REPORT.md` | Reviewer | Nexus |
| `session_summaries/{task}.md` | Nexus | Memory |
