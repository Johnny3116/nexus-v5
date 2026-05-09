# Builder Agent — Retry Behavior

When a build attempt fails verification or tests, the builder retries with
accumulated error context (up to MAX_ATTEMPTS = 3).

## Retry Loop

```
attempt 1: build_from_plan(plan, task_packet, error_context="")
  -> verify_files()
    -> run_tests()
      [all pass] -> done
      [fail]     -> format error_context, increment attempt

attempt 2: build_from_plan(..., error_context="Attempt 1: <details>")
  -> verify_files() -> run_tests()
      [all pass] -> done
      [fail]     -> append to error_context

attempt 3: build_from_plan(..., error_context="Attempt 1: ... Attempt 2: ...")
  -> verify_files() -> run_tests()
      [all pass] -> done
      [fail]     -> final failure, send build_response(success=false)
```

## Error Context Format

Injected into user message under "=== Previous Attempt Failed ===":

| Failure | Format |
|---|---|
| Build error | `Attempt N failed: {error}. Rewrite your output correctly.` |
| Verify fail | One line per failed file: `  path/to/file.py: SyntaxError: ...` |
| Test fail | Full test output (capped at 2000 chars) + fix instruction |

## Success Condition

```
success = (
    result["success"]
    and verify_result["passed"]
    and (test_result["passed"] or test_result["tests_run"] == 0)
)
```

`tests_run == 0` means no test files were found — graceful skip, not a failure.

## Hard Limits

- MAX_ATTEMPTS = 3 (enforced in _run_builder in server.py)
- Error context is cumulative across all prior attempts in the same build run
- Each build run is independent — retry counter resets on new plan approval
