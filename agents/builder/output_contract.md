# Builder Agent — Output Contract

The builder must return a single JSON object. No markdown, no code fences, no explanation.

## Schema

```json
{
  "files": [
    {
      "path": "relative/path/to/file.py",
      "content": "full file content as a string"
    }
  ],
  "notes": "any important implementation notes (string, may be empty)"
}
```

## Field Rules

| Field | Type | Rules |
|---|---|---|
| `files` | list[object] | Non-empty; each object has `path` and `content` |
| `files[].path` | string | Relative; no `../` traversal; extension in allowlist |
| `files[].content` | string | Full file content; no placeholders unless truly unavoidable |
| `notes` | string | Free-form; may be empty string `""` |

## File Extension Allowlist

Only these extensions are written to disk (enforced by builder.py):
`.py`, `.js`, `.ts`, `.json`, `.md`, `.yaml`, `.yml`, `.toml`, `.txt`, `.html`, `.css`

## Sandbox

- All files written to workspace/output/ only
- Path traversal blocked via resolve().relative_to() before any write
- Writes are atomic (temp file then rename)

## Test File Rule

For every .py file whose name does not start with test_, the builder must also
produce test_<module_name>.py. This is enforced by an explicit hint injected
into the user message (see build_prompt.py).
