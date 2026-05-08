# Skill Contract

Every skill in the registry implements this interface.

---

## What a Skill Is

A skill is a named, callable unit of work with a defined input schema and output schema. Skills are not agents — they don't have their own LLM context. They are functions Nexus can invoke by name, passing structured input and receiving structured output.

## Interface

```python
class Skill:
    name: str                  # Unique identifier, snake_case
    description: str           # One sentence — what it does
    input_schema: dict         # JSON Schema for expected input
    output_schema: dict        # JSON Schema for output

    def run(self, input: dict) -> dict:
        """Execute the skill. Returns structured output."""
        ...
```

## Invocation

Nexus invokes a skill by name:
```python
result = registry.run("memory_search", {"query": "Discord message history"})
```

## Output Requirements

- Always return a dict matching `output_schema`
- Always include `"success": true/false`
- Always include `"error": null | "error message"` if success is false
- Never return raw exceptions to the caller

## Adding a Skill

1. Implement the class in `skills/`
2. Register it in `registry.py`
3. Add a usage example to this doc
4. Keep scope tight — one skill, one thing
