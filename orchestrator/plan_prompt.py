"""Prompt builder for the Nexus planning LLM call.

Converts a TaskPacket dict (+ optional workspace context) into the system +
user messages that ask the local Ollama model to produce a Plan JSON object.
"""

from __future__ import annotations

from typing import Optional

SYSTEM_PROMPT = """\
You are Nexus's planning engine. Given a TaskPacket describing a coding task, \
produce a structured implementation plan.

Return ONLY a valid JSON object with exactly these keys:
  "summary"               - string: one sentence describing what will be built
  "assumptions"           - list[str]: things assumed true (env, deps, existing code)
  "target_files"          - list[str]: files that will be created or modified
  "implementation_steps"  - list[str]: ordered steps to complete the task
  "risks"                 - list[str]: things that could go wrong
  "rollback_plan"         - string: how to undo the changes if something breaks
  "acceptance_tests"      - list[str]: verifiable criteria for success (binary pass/fail)
  "verification_commands" - list[str]: shell or test commands to verify the result
  "requires_user_approval"- true

Rules:
- Do not include any text, markdown, code fences, or explanation outside the JSON.
- requires_user_approval must always be true.
- Be specific about file paths in target_files (use relative paths from repo root).
- implementation_steps must be ordered and actionable — no vague steps.
- verification_commands must be runnable as-is (e.g. "pytest tests/test_router.py").
- If workspace context is provided, reference existing files where relevant and avoid
  re-implementing what already exists.
"""


def build_planning_prompt(packet: dict, context_text: Optional[str] = None) -> str:
    """Convert a TaskPacket dict into the user message for the planner LLM.

    Args:
        packet: TaskPacket dict from task_packet.py
        context_text: Optional pre-formatted workspace context string from
                      context_reader.format_context_for_prompt(). When provided,
                      injected before the TaskPacket so the planner sees existing
                      code and build history.
    """
    lines = []

    # Inject context first so it frames the task
    if context_text and context_text.strip():
        lines.append("=== Workspace Context ===")
        lines.append(context_text.strip())
        lines.append("")
        lines.append("=== Task ===")

    lines.append(f"Goal: {packet.get('goal', 'unknown')}")
    lines.append(f"Request type: {packet.get('request_type', 'code_plan')}")

    if packet.get("repo"):
        lines.append(f"Repository: {packet['repo']}")

    if packet.get("constraints"):
        lines.append("Constraints:")
        for c in packet["constraints"]:
            lines.append(f"  - {c}")

    if packet.get("likely_files"):
        lines.append("Files likely involved:")
        for f in packet["likely_files"]:
            lines.append(f"  - {f}")

    if packet.get("acceptance_tests"):
        lines.append("Acceptance tests (from task packet):")
        for t in packet["acceptance_tests"]:
            lines.append(f"  - {t}")

    if packet.get("do_not_touch"):
        lines.append("Do NOT modify:")
        for f in packet["do_not_touch"]:
            lines.append(f"  - {f}")

    if packet.get("required_output"):
        lines.append(f"Required output artifact: {packet['required_output']}")

    lines.append("\nGenerate the Plan JSON now.")
    return "\n".join(lines)
