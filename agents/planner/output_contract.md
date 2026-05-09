# Planner Agent — Output Contract

The planner must return a single JSON object. No markdown, no code fences, no explanation.

## Schema

```json
{
  "summary": "one sentence describing what will be built",
  "assumptions": ["string", "..."],
  "target_files": ["relative/path/to/file.py", "..."],
  "implementation_steps": ["Step 1: ...", "Step 2: ...", "..."],
  "risks": ["string", "..."],
  "rollback_plan": "how to undo if something breaks",
  "acceptance_tests": ["binary pass/fail criterion", "..."],
  "verification_commands": ["pytest tests/test_foo.py", "..."],
  "requires_user_approval": true
}
```

## Field Rules

| Field | Type | Rules |
|---|---|---|
| `summary` | string | One sentence, imperative voice |
| `assumptions` | list[str] | Non-empty; covers env, deps, existing state |
| `target_files` | list[str] | Relative paths from repo root; no absolute paths |
| `implementation_steps` | list[str] | Ordered; each step is actionable |
| `risks` | list[str] | May be empty `[]` if no known risks |
| `rollback_plan` | string | Concrete — e.g. "delete workspace/output/foo.py" |
| `acceptance_tests` | list[str] | Binary — verifiable YES/NO in seconds |
| `verification_commands` | list[str] | Runnable as-is; may be empty |
| `requires_user_approval` | bool | **Always true. Enforced in code even if LLM omits it.** |

## Coercion

planner.py coerces the raw LLM output:
- `requires_user_approval` is forced to `True` regardless of LLM output
- Missing list fields default to `[]`
- Missing string fields default to `""`
