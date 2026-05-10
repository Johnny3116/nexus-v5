"""Shared Pydantic models + enums used across api_gateway and serving.

Ported from V4 `shared/types.py`; reduced to what Phase 1 (chat + light
memory) actually needs. Task/skill models come back when those endpoints
move off 501.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskType(str, Enum):
    """Routing key for BrainPool. Maps to a provider via routing_rules.yaml."""
    chat = "chat"
    conversation = "conversation"
    voice = "voice"
    reasoning = "reasoning"
    coding = "coding"
    tools = "tools"
    complex = "complex"
    memory_write = "memory_write"
    local = "local"
    heartbeat = "heartbeat"


class Provider(str, Enum):
    """Which backend actually handled a request."""
    claude = "claude"
    codex = "codex"
    qwen = "qwen"
    gateway = "gateway"  # alias for codex (Nexus-Agent gateway carrier)


class MemoryCategory(str, Enum):
    server = "server"
    user = "user"
    system = "system"
    learned = "learned"


class Severity(str, Enum):
    info = "INFO"
    warn = "WARN"
    critical = "CRITICAL"
    emergency = "EMERGENCY"


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    identity_id: str = "john"
    task_type: TaskType = TaskType.chat
    conversation_id: Optional[str] = None
    platform: str = "api"


class ChatResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    response: str
    provider: Provider
    model_used: str
    latency_ms: int
    conversation_id: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0
    fallback_used: bool = False


# ---------------------------------------------------------------------------
# Memory (light CRUD — phase 3 adds RAG wiring)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Task (agentic loop) + Skill (direct invoke)
# ---------------------------------------------------------------------------

class TaskRequest(BaseModel):
    message: str
    identity_id: str = "john"
    conversation_id: Optional[str] = None
    max_iterations: int = 6

    # Field-level injection scan. Middleware skips /v1/task; this is the gate.
    # When task payloads grow nested fields (steps, context), add validators
    # that call scan_nested() on the structured sections.
    @field_validator("message")
    @classmethod
    def _scan_message(cls, v: str) -> str:
        from safety.input_filters.injection_scanner import PromptInjectionDetected, require_clean
        try:
            return require_clean(v)
        except PromptInjectionDetected as exc:
            raise ValueError(
                {"error": "prompt_injection_blocked", "field": "message",
                 "rules": [h.rule for h in exc.hits]}
            )


class TaskResponse(BaseModel):
    response: str
    tasks_executed: list[dict[str, Any]] = Field(default_factory=list)
    iterations: int
    source: str
    request_id: str
    success: bool
    error: Optional[str] = None


class SkillInvokeRequest(BaseModel):
    skill: str
    action: str = "run"
    params: dict[str, Any] = Field(default_factory=dict)
    identity_id: str = "john"


class SkillInvokeResponse(BaseModel):
    skill: str
    action: str
    result: dict[str, Any]


class MemoryRequest(BaseModel):
    content: str
    category: MemoryCategory = MemoryCategory.user
    identity_id: str = "john"
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryRecord(BaseModel):
    # id is int in the phase-1 table, will be uuid/str after migration
    id: str | int
    content: str
    category: MemoryCategory
    identity_id: Optional[str] = None  # column pending migration
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class MemoryResponse(BaseModel):
    memories: list[MemoryRecord]
    total: int


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class ProviderHealth(BaseModel):
    claude: str = "unknown"
    codex: str = "unknown"
    qwen: str = "unknown"


class HealthResponse(BaseModel):
    status: str
    service: str = "nexus-gateway"
    version: str = "0.1.0"
    providers: ProviderHealth
    endpoints: dict[str, str]
