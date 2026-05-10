"""<nexus_task> XML parser — extracts structured tasks from Brain output.

SECURITY: only parse Brain output. Never parse raw user input or RAG content.
Call strip_user_content() on untrusted text BEFORE it reaches the Brain.
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger("nexus.skills.task_parser")

_TASK_BLOCK_RE = re.compile(
    r"<nexus_task\b[^>]*(?:/>|>.*?</nexus_task>)",
    re.DOTALL | re.IGNORECASE,
)

_STRIP_TASK_RE = re.compile(
    r"<nexus_task\b[^>]*(?:/>|>.*?</nexus_task>)\s*",
    re.DOTALL | re.IGNORECASE,
)


def strip_user_content(text: str) -> str:
    """Remove <nexus_task> blocks from untrusted text (injection defense)."""
    cleaned = _STRIP_TASK_RE.sub("", text)
    if cleaned != text:
        logger.warning("INJECTION DEFENSE: stripped %d <nexus_task> block(s)", len(_STRIP_TASK_RE.findall(text)))
    return cleaned


def parse_tasks(brain_output: str) -> list[dict]:
    """Parse all <nexus_task> blocks from Brain output.

    Returns list of {"skill": str, "action": str, "params": dict}.
    """
    tasks = []
    for raw in _TASK_BLOCK_RE.findall(brain_output):
        task = _parse_single(raw)
        if task:
            tasks.append(task)
    return tasks


def _parse_single(raw: str) -> Optional[dict]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        logger.warning("malformed nexus_task (skipped): %s", exc)
        return None

    skill = root.attrib.get("skill", "").strip()
    action = root.attrib.get("action", "").strip()
    if not skill or not action:
        # Try child element format (from task_xml_sanitizer)
        skill = skill or (root.findtext("skill") or "").strip()
        action = action or (root.findtext("action") or "").strip()
    if not skill or not action:
        logger.warning("nexus_task missing skill/action: %r", raw[:200])
        return None

    params: dict[str, str] = {}
    for child in root:
        if child.tag == "param":
            name = child.attrib.get("name", "").strip()
            if name:
                params[name] = (child.text or "").strip()
    for k, v in root.attrib.items():
        if k not in ("skill", "action"):
            params.setdefault(k, v)

    return {"skill": skill, "action": action, "params": params}
