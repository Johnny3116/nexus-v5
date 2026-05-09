"""build_prompt.py — converts an approved Plan into an Ollama implementation prompt.

The builder LLM receives the full plan context and is asked to produce
concrete code. Output must be JSON so we can parse file names and content.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

SYSTEM_PROMPT = """\
You are Nexus's code builder. You receive an approved implementation plan and \
produce working code files.

Return ONLY a valid JSON object with this exact structure:
{
  "files": [
    {
      "path": "relative/path/to/file.py",
      "content": "full file content as a string"
    }
  ],
  "notes": "any important implementation notes (string, may be empty)"
}

Rules:
- All file paths must be relative (no leading slash, no ../ traversal).
- Produce complete, working files — no placeholders, no TODOs unless unavoidable.
- Follow the plan's implementation steps in order.
- Respect the do_not_touch list — never include those files in output.
- Keep files focused and minimal — no extra features beyond what the plan specifies.
- Always include a test file named test_<module_name>.py that imports the main module and tests each function using assert statements or unittest.TestCase. The test file must be runnable standalone with 'python test_<module_name>.py' and exit 0 on success.
- Return ONLY the JSON object. No markdown, no explanation, no code fences.
"""


def build_implementation_prompt(plan: dict, task_packet: dict, error_context: str = "") -> str:
    """Convert an approved Plan + TaskPacket into the user message for the builder LLM.

    Args:
        plan: approved Plan dict from planner.py
        task_packet: TaskPacket dict from task_packet.py
        error_context: optional string describing prior failed attempts (M7 retry loop).
                       When provided, injected at the end so the builder knows what
                       went wrong and can correct its output.
    """
    lines = [
        f"Goal: {task_packet.get('goal', plan.get('summary', 'unknown'))}",
        f"Summary: {plan.get('summary', '')}",
    ]

    if task_packet.get("repo"):
        lines.append(f"Repository context: {task_packet['repo']}")

    if task_packet.get("constraints"):
        lines.append("Constraints:")
        for c in task_packet["constraints"]:
            lines.append(f"  - {c}")

    if plan.get("assumptions"):
        lines.append("Assumptions:")
        for a in plan["assumptions"]:
            lines.append(f"  - {a}")

    if plan.get("target_files"):
        lines.append("Files to create/modify:")
        for f in plan["target_files"]:
            lines.append(f"  - {f}")
        # M9: explicitly request test file for Python modules
        py_mods = [
            f for f in plan["target_files"]
            if f.endswith(".py") and not Path(f).stem.startswith("test_")
        ]
        if py_mods:
            test_names = ", ".join(
                f"test_{Path(f).stem}.py" for f in py_mods[:2]
            )
            lines.append(
                f"You MUST also include: {test_names} "
                "(standalone test file using assert or unittest — see system instructions)"
            )

    if task_packet.get("do_not_touch"):
        lines.append("DO NOT touch these files:")
        for f in task_packet["do_not_touch"]:
            lines.append(f"  - {f}")

    if plan.get("implementation_steps"):
        lines.append("Implementation steps (follow in order):")
        for i, s in enumerate(plan["implementation_steps"], 1):
            lines.append(f"  {i}. {s}")

    if plan.get("acceptance_tests"):
        lines.append("The implementation must satisfy:")
        for t in plan["acceptance_tests"]:
            lines.append(f"  - {t}")

    if error_context and error_context.strip():
        lines.append("")
        lines.append("=== Previous Attempt Failed ===")
        lines.append(error_context.strip())
        lines.append("Fix the above errors in your new output.")

    lines.append("\nGenerate the implementation JSON now.")
    return "\n".join(lines)
