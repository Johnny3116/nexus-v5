"""agent_loader.py -- loads agent config markdown files from the agents/ directory.

Provides a simple, cached interface to load any agent's markdown documents.
Prompts and behavioral contracts live in agents/ as versioned markdown files,
not embedded in Python strings.

Usage:
    from orchestrator.agent_loader import load, get_system_prompt

    system = get_system_prompt("planner")           # agents/planner/system.md
    contract = load("builder", "output_contract")   # agents/builder/output_contract.md
    policy = load("verifier", "failure_policy")     # agents/verifier/failure_policy.md
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# agents/ is at the Nexus root, one level above orchestrator/
_AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


@lru_cache(maxsize=64)
def load(agent: str, doc: str) -> str:
    """Load an agent markdown document.

    Args:
        agent: agent directory name -- coordinator, planner, builder, verifier
        doc:   document name without extension -- system, rules, output_contract, etc.

    Returns:
        Document content stripped of leading/trailing whitespace.

    Raises:
        FileNotFoundError: if the markdown file does not exist.
    """
    path = _AGENTS_DIR / agent / f"{doc}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"Agent doc not found: agents/{agent}/{doc}.md "
            f"(resolved: {path})"
        )
    content = path.read_text(encoding="utf-8").strip()
    logger.debug("Loaded agent doc: agents/%s/%s.md (%d chars)", agent, doc, len(content))
    return content


def get_system_prompt(agent: str) -> str:
    """Convenience: load agents/{agent}/system.md."""
    return load(agent, "system")


def list_docs(agent: str) -> list[str]:
    """Return available document names (stems) for an agent."""
    agent_dir = _AGENTS_DIR / agent
    if not agent_dir.exists():
        return []
    return [p.stem for p in sorted(agent_dir.iterdir()) if p.suffix == ".md"]


_model_config_cache: dict = {}


def load_model_config(agent: str) -> dict:
    """Load agents/{agent}/model.json.

    Returns parsed JSON dict. Returns empty dict if file does not exist,
    so callers can always safely use .get() with a default.

    Cached in _model_config_cache per agent name.
    Call reload_all() to re-read after editing model.json files at runtime.
    """
    if agent in _model_config_cache:
        return _model_config_cache[agent]
    import json as _json
    path = _AGENTS_DIR / agent / "model.json"
    if not path.exists():
        logger.debug("No model.json for agent %s -- env defaults apply", agent)
        result: dict = {}
    else:
        result = _json.loads(path.read_text(encoding="utf-8"))
        logger.debug(
            "Model config %s: provider=%s model=%s",
            agent, result.get("provider"), result.get("model"),
        )
    _model_config_cache[agent] = result
    return result


def reload_all() -> None:
    """Clear all caches -- call after editing agent markdown or model.json files at runtime."""
    load.cache_clear()
    _model_config_cache.clear()
    logger.info("agent_loader: all caches cleared")
