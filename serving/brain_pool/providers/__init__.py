"""BrainPool providers — one file per backend.

Each provider exposes the same async interface:
    async def chat(messages: list[dict], **kwargs) -> ProviderResult
"""

from dataclasses import dataclass


@dataclass
class ProviderResult:
    content: str
    model_used: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
