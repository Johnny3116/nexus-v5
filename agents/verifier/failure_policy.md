# Verifier Agent — Failure Policy

What happens when one or more files fail verification.

## Immediate Response

On verify failure, the build attempt is considered failed.
The verifier returns passed: false with per-file detail.

## Retry Escalation

If attempt < MAX_ATTEMPTS (3):
- Format error context from failed file details (one line per failed file)
- Feed error context into next builder call under "=== Previous Attempt Failed ==="
- Increment attempt counter

If attempt == MAX_ATTEMPTS:
- Log error: "All N attempts exhausted for plan {plan_id} -- last verify: {summary}"
- build_response sent with success: false
- No further retries

## Error Context Format (fed to builder)

```
Attempt N produced files that failed verification:
  path/to/file.py: SyntaxError: invalid syntax (line 42)
  path/to/other.py: SyntaxError: unexpected EOF (line 100)
Fix these errors in your next output.
```

## Partial Failure

If some files pass and some fail, the entire attempt is considered failed.
No files from a failed attempt are retained.

## Auto-Pass Cases

- written_files is empty -> passed: true, summary: "no files to verify" (graceful skip)
- Extension not in check list -> individual file auto-passes
