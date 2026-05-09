"""Prompt builder for the Nexus planning LLM call.

Converts a TaskPacket dict (+ optional workspace context) into the system +
user messages that ask the local Ollama model to produce a Plan JSON object.
"""

from __future__ import annotations

from typing import Optional

from orchestrator.agent_loader import get_system_prompt as _load_system_prompt

SYSTEM_PROMPT = _load_system_prompt("planner")


def build_planning_prompt(packet: dict, context_text: Optional[str] = None, revision_feedback: str = "") -> str:
    """Convert a TaskPacket dict into the user message for the planner LLM.

    Args:
        packet: TaskPacket dict from task_packet.py
        context_text: Optional pre-formatted workspace context string from
                      context_reader.format_context_for_prompt(). When provided,
                      injected before the TaskPacket so the planner sees existing
                      code and build history.
        revision_feedback: Optional user feedback on a prior plan. When provided,
                           injected at the end as a Revision Request block so the
                           planner revises accordingly (M8).
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

    if revision_feedback and revision_feedback.strip():
        lines.append("")
        lines.append("=== Revision Request ===")
        lines.append(revision_feedback.strip())
        lines.append("Revise the plan to address the feedback above, then generate updated Plan JSON.")
    else:
        lines.append("\nGenerate the Plan JSON now.")
    return "\n".join(lines)
