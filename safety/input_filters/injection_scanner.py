"""Prompt-injection scanner for externally fetched content.

Doctrine §10, rule #3: ALL externally fetched content (web, GitHub, RSS)
passes through this scanner before reaching the brain. A hit blocks the
content and notifies observability with the matched pattern.

The patterns below are intentionally broad — false positives are safer
than silent passes. When a legitimate doc triggers a rule, John escalates
by whitelisting the source, not by relaxing the rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Known adversarial patterns. Extend as we see new jailbreaks in the wild.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("role_override",
     re.compile(r"(?i)\b(ignore|disregard|override)\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts?|system\s+messages?)")),
    ("system_prompt_exfil",
     re.compile(r"(?i)(reveal|repeat|print|show)\s+(your\s+)?(system|initial|hidden)\s+(prompt|instructions|rules)")),
    ("identity_swap",
     re.compile(r"(?i)(you\s+are\s+now|act\s+as|pretend\s+to\s+be|roleplay\s+as)\s+[A-Z][A-Za-z0-9_-]{2,}")),
    ("tool_injection_xml",
     re.compile(r"<(nexus_task|tool_call|function_call)\b[^>]*>", re.IGNORECASE)),
    ("exfil_secrets",
     re.compile(r"(?i)(print|dump|output|cat|echo)\s+.*(\.env|openai|anthropic|aws|tailscale|service.?key|secret|token)")),
    ("shell_injection",
     re.compile(r"(?im)(^|\s)(rm\s+-rf|:(){:|:&};:|curl[^|]*\|\s*(sh|bash))")),
    ("data_url_script",
     re.compile(r"(?i)data:text/html[^,]*,\s*<script")),
]


@dataclass
class ScannerHit:
    rule: str
    snippet: str


class PromptInjectionDetected(Exception):
    def __init__(self, hits: list[ScannerHit]) -> None:
        self.hits = hits
        super().__init__("prompt injection patterns found: " + ", ".join(h.rule for h in hits))


def scan(content: str, *, max_snippet: int = 160) -> list[ScannerHit]:
    hits: list[ScannerHit] = []
    for name, pat in _PATTERNS:
        m = pat.search(content)
        if m:
            start = max(0, m.start() - 40)
            end = min(len(content), m.end() + 40)
            snippet = content[start:end].replace("\n", " ").strip()[:max_snippet]
            hits.append(ScannerHit(rule=name, snippet=snippet))
    return hits


def require_clean(content: str) -> str:
    hits = scan(content)
    if hits:
        raise PromptInjectionDetected(hits)
    return content


def scan_nested(obj: object) -> list[ScannerHit]:
    """Walk a JSON-like structure, scan every string leaf. Returns all hits."""
    hits: list[ScannerHit] = []
    if isinstance(obj, str):
        hits.extend(scan(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            hits.extend(scan_nested(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            hits.extend(scan_nested(v))
    return hits
