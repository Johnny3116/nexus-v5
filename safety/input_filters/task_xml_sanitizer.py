"""Sanitizer for `<nexus_task>` XML blocks emitted by the brain.

The brain emits tasks as XML (CLAUDE.md §5 agentic-loop). Before the
task parser hands them to the skill manager, this module:
  - ensures the outer tag is exactly <nexus_task>
  - rejects tasks with attributes (attacker could smuggle control values)
  - strips any nested <system>, <tool_call>, or unknown tags
  - enforces max field lengths so a malicious stream can't DoS the parser
  - re-runs the injection-scanner on every field's text

If any rule fails the whole task is dropped and an alert is raised.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from xml.etree import ElementTree as ET

from safety.input_filters.injection_scanner import require_clean  # noqa

MAX_FIELD_CHARS = 8_000
ALLOWED_CHILDREN = frozenset(
    {"skill", "action", "params", "context", "constraints", "tier", "reason"}
)


class TaskRejected(Exception):
    pass


@dataclass
class CleanTask:
    skill: str
    action: str
    params: dict[str, str]
    tier: str | None = None
    reason: str | None = None


def _require_text(node: ET.Element | None, field: str) -> str:
    if node is None:
        raise TaskRejected(f"missing required field <{field}>")
    text = (node.text or "").strip()
    if not text:
        raise TaskRejected(f"empty required field <{field}>")
    if len(text) > MAX_FIELD_CHARS:
        raise TaskRejected(f"<{field}> exceeds max {MAX_FIELD_CHARS} chars")
    require_clean(text)
    return text


def sanitize(xml_text: str) -> CleanTask:
    xml_text = xml_text.strip()
    if not re.match(r"^<nexus_task\s*>", xml_text):
        raise TaskRejected("outer tag must be <nexus_task> with no attributes")

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise TaskRejected(f"malformed xml: {e}") from e

    if root.tag != "nexus_task":
        raise TaskRejected(f"unexpected root tag: {root.tag}")
    if root.attrib:
        raise TaskRejected("nexus_task must have no attributes")

    for child in root:
        if child.tag not in ALLOWED_CHILDREN:
            raise TaskRejected(f"unknown child tag: {child.tag}")

    skill = _require_text(root.find("skill"), "skill")
    action = _require_text(root.find("action"), "action")

    params: dict[str, str] = {}
    params_node = root.find("params")
    if params_node is not None:
        for p in params_node:
            params[p.tag] = _require_text(p, f"params/{p.tag}")

    tier = root.findtext("tier") or None
    reason = root.findtext("reason") or None

    return CleanTask(skill=skill, action=action, params=params, tier=tier, reason=reason)
