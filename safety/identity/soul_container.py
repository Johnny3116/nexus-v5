"""Soul Container — Doctrine 6 enforcement.

Two jobs:
  1. Build identity blocks for LLM system prompts (soul.md injection)
  2. Light post-processing to catch assistant-isms the model slips in

The soul.md is strong enough to carry personality through system prompt alone.
This module just catches the edge cases.
"""

from __future__ import annotations

import re
import logging
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("nexus.identity")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_IDENTITY_DIR = Path(__file__).parent
_SOUL_PATH = _IDENTITY_DIR / "soul.md"
_SOUL_CORE_PATH = _IDENTITY_DIR / "soul-core.md"
_DOCTRINES_PATH = _IDENTITY_DIR / "doctrines.md"

# Task types that get the slim core soul (no doctrine summary).
# Doctrines are enforced as middleware — the model doesn't need to recite them
# every chat turn. Slim prompt → ~3k fewer prefill tokens → ~10s saved on Qwen.
_SLIM_PROMPT_TASKS = {"chat", "conversation", "voice"}

# ---------------------------------------------------------------------------
# Soul Loader — hot-reloadable
# ---------------------------------------------------------------------------

class SoulLoader:
    """Loads and caches soul.md + doctrines.md with file-watch hot reload.

    Checks file modification time on each access. If the file changed on
    disk, it reloads automatically — no service restart needed.
    """

    def __init__(self) -> None:
        self._soul_text: str = ""
        self._soul_core_text: str = ""
        self._doctrines_text: str = ""
        self._soul_mtime: float = 0.0
        self._soul_core_mtime: float = 0.0
        self._doctrines_mtime: float = 0.0
        self._lock = threading.Lock()
        # Initial load
        self._reload_soul()
        self._reload_soul_core()
        self._reload_doctrines()

    # -- Public API --

    @property
    def soul(self) -> str:
        """Current soul.md content. Auto-reloads if file changed."""
        if self._file_changed(_SOUL_PATH, self._soul_mtime):
            self._reload_soul()
        return self._soul_text

    @property
    def soul_core(self) -> str:
        """Slim soul-core.md content. Falls back to full soul if missing."""
        if self._file_changed(_SOUL_CORE_PATH, self._soul_core_mtime):
            self._reload_soul_core()
        return self._soul_core_text or self.soul

    @property
    def doctrines(self) -> str:
        """Current doctrines.md content. Auto-reloads if file changed."""
        if self._file_changed(_DOCTRINES_PATH, self._doctrines_mtime):
            self._reload_doctrines()
        return self._doctrines_text

    def mtimes(self) -> tuple[float, float, float]:
        """Tuple usable as a cache key — bumps whenever any source file changes."""
        # Touching the properties triggers a reload check.
        _ = self.soul, self.soul_core, self.doctrines
        return (self._soul_mtime, self._soul_core_mtime, self._doctrines_mtime)

    # -- Internal --

    def _file_changed(self, path: Path, cached_mtime: float) -> bool:
        try:
            return path.stat().st_mtime > cached_mtime
        except FileNotFoundError:
            return False

    def _reload_soul(self) -> None:
        with self._lock:
            try:
                self._soul_text = _SOUL_PATH.read_text(encoding="utf-8")
                self._soul_mtime = _SOUL_PATH.stat().st_mtime
                logger.info("Soul loaded: %s (%d chars)", _SOUL_PATH.name, len(self._soul_text))
            except FileNotFoundError:
                logger.error("soul.md not found at %s — identity will be empty!", _SOUL_PATH)
                self._soul_text = ""

    def _reload_soul_core(self) -> None:
        with self._lock:
            try:
                self._soul_core_text = _SOUL_CORE_PATH.read_text(encoding="utf-8")
                self._soul_core_mtime = _SOUL_CORE_PATH.stat().st_mtime
                logger.info("Soul (core) loaded: %s (%d chars)", _SOUL_CORE_PATH.name, len(self._soul_core_text))
            except FileNotFoundError:
                logger.warning("soul-core.md missing — slim prompts will fall back to full soul.md")
                self._soul_core_text = ""

    def _reload_doctrines(self) -> None:
        with self._lock:
            try:
                self._doctrines_text = _DOCTRINES_PATH.read_text(encoding="utf-8")
                self._doctrines_mtime = _DOCTRINES_PATH.stat().st_mtime
                logger.info("Doctrines loaded: %s (%d chars)", _DOCTRINES_PATH.name, len(self._doctrines_text))
            except FileNotFoundError:
                logger.error("doctrines.md not found at %s — safety rules will be missing!", _DOCTRINES_PATH)
                self._doctrines_text = ""


# Singleton
_loader: Optional[SoulLoader] = None
_loader_lock = threading.Lock()


def _get_loader() -> SoulLoader:
    global _loader
    if _loader is None:
        with _loader_lock:
            if _loader is None:
                _loader = SoulLoader()
    return _loader


# ---------------------------------------------------------------------------
# Job 1: System Prompt Builder
# ---------------------------------------------------------------------------

_TASK_HINTS = {
    "chat": "You are in conversation mode. Voice and text chat with John.",
    "conversation": "You are in conversation mode. Voice and text chat with John.",
    "coding": "You are in coding mode. Focus on code quality, architecture, and GitHub operations.",
    "reasoning": "You are in reasoning mode. Think carefully and explain your logic.",
    "local": "You are in local execution mode. Be precise and structured.",
    "heartbeat": "You are evaluating what needs attention. Be brief.",
    "voice": "You are generating a voice response. Keep it short — this goes to TTS.",
}

# Cache the static portion of the identity block keyed on (task_type, mtimes).
# Timestamp is appended dynamically per call. Saves a string concat + the
# ~1.5KB doctrine regex parse on every chat turn.
_block_cache: dict[tuple, str] = {}
_block_cache_lock = threading.Lock()


def get_identity_block(task_type: str = "chat") -> str:
    """Build the identity block prepended to every LLM system prompt.

    Chat/voice/conversation get the slim soul-core (no doctrine summary —
    doctrines are enforced as middleware, the model doesn't need to recite
    them). Reasoning/coding/complex/local/heartbeat get the full soul + a
    condensed doctrine list for self-aware tool work.

    Args:
        task_type: BrainPool task type. Drives hint + slim/full selection.

    Returns:
        Complete identity block string ready for system prompt injection.
    """
    loader = _get_loader()
    hint = _TASK_HINTS.get(task_type, "")
    slim = task_type in _SLIM_PROMPT_TASKS

    cache_key = (task_type, slim, loader.mtimes())
    cached = _block_cache.get(cache_key)
    if cached is None:
        if slim:
            static = (
                f"{loader.soul_core}\n"
                f"\n---\n\n"
                f"## Current Context\n\n"
                f"- Task type: {task_type}\n"
                f"- {hint}\n"
            )
        else:
            static = (
                f"{loader.soul}\n"
                f"\n---\n\n"
                f"## Active Doctrines (Summary)\n\n"
                f"{_condense_doctrines(loader.doctrines)}\n"
                f"\n---\n\n"
                f"## Current Context\n\n"
                f"- Task type: {task_type}\n"
                f"- {hint}\n"
            )
        with _block_cache_lock:
            # Drop old entries (mtime bumps invalidate everything anyway).
            if len(_block_cache) > 32:
                _block_cache.clear()
            _block_cache[cache_key] = static
            cached = static

    # Timestamp varies every call — append outside the cache.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"{cached}- Timestamp: {now}\n"


def _condense_doctrines(full_doctrines: str) -> str:
    """Extract just the doctrine titles and one-line summaries.

    The full doctrines.md is ~140 lines — too much for every system prompt.
    We inject a condensed version with the key rules. The full text is
    enforced by nexus-core middleware anyway, so the LLM just needs awareness.
    """
    lines = full_doctrines.split("\n")
    condensed = []

    for line in lines:
        # Grab doctrine headers: "## Doctrine 1: Network Isolation"
        if line.startswith("## Doctrine"):
            condensed.append(f"- **{line.lstrip('# ').strip()}**")
        # Grab enforcement lines for context
        elif line.startswith("**Enforcement:**"):
            condensed.append(f"  {line.strip()}")

    if not condensed:
        return "Doctrines active but could not be parsed. Enforce all safety rules."

    return "\n".join(condensed)


# ---------------------------------------------------------------------------
# Job 2: Output Filter
# ---------------------------------------------------------------------------

# -- Assistant-isms to strip --
# These are phrases that break Nexus's character. If the LLM slips one in,
# we remove it. The soul.md should prevent most of these, but models drift.

_ASSISTANT_ISMS: list[re.Pattern] = [
    # Filler openers
    re.compile(r"^Certainly[!.]?\s*", re.IGNORECASE),
    re.compile(r"^Of course[!.]?\s*", re.IGNORECASE),
    re.compile(r"^Absolutely[!.]?\s*", re.IGNORECASE),
    re.compile(r"^Great question[!.]?\s*", re.IGNORECASE),
    re.compile(r"^That's a great question[!.]?\s*", re.IGNORECASE),
    re.compile(r"^Sure thing[!.]?\s*", re.IGNORECASE),
    re.compile(r"^I'd be happy to\s+", re.IGNORECASE),
    re.compile(r"^I would be happy to\s+", re.IGNORECASE),

    # AI identity breaks
    re.compile(r"As an AI( language model)?,?\s*", re.IGNORECASE),
    re.compile(r"As a large language model,?\s*", re.IGNORECASE),
    re.compile(r"I don't have personal (opinions|feelings|experiences),?\s*(but\s*)?", re.IGNORECASE),

    # Over-apologizing chains
    re.compile(r"^(I'm sorry|I apologize|My apologies)[.,]?\s*(I'm sorry|I apologize|My apologies)[.,]?\s*", re.IGNORECASE),
]

# -- Tool call patterns that should never appear in user-facing chat --

_TOOL_LEAK_PATTERNS: list[re.Pattern] = [
    # Raw JSON tool calls
    re.compile(r'\{\s*"tool_call"', re.IGNORECASE),
    re.compile(r'\{\s*"function_call"', re.IGNORECASE),
    re.compile(r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"', re.IGNORECASE),
    # XML-style tool tags
    re.compile(r'<tool_call>.*?</tool_call>', re.DOTALL),
    re.compile(r'<function_call>.*?</function_call>', re.DOTALL),
    re.compile(r'<\|tool_call\|>.*?<\|/tool_call\|>', re.DOTALL),
]

# -- Code block protection regex --
_CODE_BLOCK = re.compile(r"```[\s\S]*?```")

# -- Word count limits --
_SOFT_CAP = 300   # Normal responses
_HARD_CAP = 500   # Excited mode / detailed technical responses


class FilterResult:
    """Result of running the output filter.

    Attributes:
        text: The cleaned output text.
        was_modified: Whether any changes were made.
        warnings: List of issues found (for logging/audit).
        over_soft_cap: True if response exceeded soft word cap.
        over_hard_cap: True if response exceeded hard word cap.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.was_modified = False
        self.warnings: list[str] = []
        self.over_soft_cap = False
        self.over_hard_cap = False

    def flag(self, warning: str) -> None:
        self.warnings.append(warning)
        self.was_modified = True


def filter_output(text: str) -> FilterResult:
    """Run the output filter on LLM-generated text.

    This is the Doctrine 6 enforcement point. Every outbound response
    passes through here before reaching the user.

    The filter is intentionally light:
      - Strip assistant-isms
      - Catch tool call leakage
      - Flag (don't truncate) over-length responses
      - Protect code blocks from modification

    Args:
        text: Raw LLM output.

    Returns:
        FilterResult with cleaned text and any warnings.
    """
    result = FilterResult(text)
    working = text

    # Step 1: Extract code blocks so we don't touch them
    code_blocks: list[str] = []
    placeholder_prefix = "\x00CODEBLOCK"

    def _stash_code(match: re.Match) -> str:
        idx = len(code_blocks)
        code_blocks.append(match.group(0))
        return f"{placeholder_prefix}{idx}\x00"

    working = _CODE_BLOCK.sub(_stash_code, working)

    # Step 2: Strip assistant-isms
    for pattern in _ASSISTANT_ISMS:
        cleaned = pattern.sub("", working)
        if cleaned != working:
            result.flag(f"Stripped assistant-ism: {pattern.pattern[:40]}...")
            working = cleaned

    # Step 3: Catch tool call leakage
    for pattern in _TOOL_LEAK_PATTERNS:
        if pattern.search(working):
            result.flag(f"Tool call leaked into output — stripped: {pattern.pattern[:40]}...")
            working = pattern.sub("[action executed]", working)

    # Step 4: Restore code blocks
    for idx, block in enumerate(code_blocks):
        working = working.replace(f"{placeholder_prefix}{idx}\x00", block)

    # Step 5: Check response length
    word_count = len(working.split())
    if word_count > _HARD_CAP:
        result.over_hard_cap = True
        result.flag(f"Response is {word_count} words (hard cap: {_HARD_CAP})")
        logger.warning("Output exceeded hard cap: %d words", word_count)
    elif word_count > _SOFT_CAP:
        result.over_soft_cap = True
        result.flag(f"Response is {word_count} words (soft cap: {_SOFT_CAP})")

    # Clean up: collapse multiple blank lines, strip trailing whitespace
    working = re.sub(r"\n{3,}", "\n\n", working)
    working = working.strip()

    if working != text.strip():
        result.was_modified = True

    result.text = working
    return result


# ---------------------------------------------------------------------------
# Convenience: one-call personality enforcement
# ---------------------------------------------------------------------------

def enforce(text: str, log_warnings: bool = True) -> str:
    """Filter output and return cleaned text. Logs warnings by default.

    This is the simplest API for services that just want to run the filter
    and get clean text back without inspecting the FilterResult.

    Args:
        text: Raw LLM output.
        log_warnings: Whether to log filter warnings. Default True.

    Returns:
        Cleaned text string.
    """
    result = filter_output(text)

    if log_warnings and result.warnings:
        for w in result.warnings:
            logger.info("Soul filter: %s", w)

    return result.text
