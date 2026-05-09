# Verifier Agent — System

The verifier checks that files produced by the builder are syntactically valid
before they are committed to the workspace build log.

## Role

- Receives: list of written file paths (absolute)
- Produces: verify_result dict {passed: bool, results: list, summary: str}
- Does not: run the code, call LLMs, or make network requests

## Verification Methods

| Extension | Method |
|---|---|
| .py  | py_compile.compile() -- catches syntax errors |
| .json | json.loads() -- catches malformed JSON |
| .js  | Brace/bracket balance heuristic |
| Other | Auto-pass (no verifier for that extension yet) |

## Output Format

```json
{
  "passed": true,
  "results": [
    {"file": "path/to/file.py", "ok": true, "error": null},
    {"file": "path/to/bad.py",  "ok": false, "error": "SyntaxError: invalid syntax (line 42)"}
  ],
  "summary": "3/3 files passed verification"
}
```

## Model

None -- verifier is deterministic code, not an LLM agent.
Future: may add import-tracing or type-check pass for .py files.
