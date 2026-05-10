"""serving.brain_pool — the singleton routing brain.

All LLM calls across Nexus flow through `BrainPool`. Providers live in
`serving/brain_pool/providers/`. Routing + fallback chain config lives in
`serving/brain_pool/routing_rules.yaml`.
"""

from serving.brain_pool.brain_pool import BrainPool, get_brain_pool  # noqa: F401
