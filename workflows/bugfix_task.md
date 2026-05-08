# Workflow: Bug Fix Task

Lighter than a full code task — triage first, then targeted fix.

---

## Trigger
Nexus classifies request as `code-plan` with bug/error/fix keywords.

## Steps

```
1. NEXUS: Build minimal TaskPacket
   → Goal: fix the specific bug
   → Constraints: minimal change surface, no refactor scope creep
   → Acceptance tests: specific — "the error no longer occurs"

2. NEXUS → CODEX: Triage prompt
   → "What is the likely cause? What is the minimal fix?"
   → Codex outputs: TRIAGE.md (root cause + proposed fix location)

3. NEXUS: Review triage
   → Is root cause plausible?
   → Is fix scope minimal?

4. [If approved] NEXUS → SONNET: Targeted fix from TRIAGE.md
   → Sonnet outputs: fix + regression test

5. NEXUS: Verify fix
   → Does the specific error no longer occur?
   → Did anything else break? (regression check)

6. [If pass] Memory store + summary
```
