# Coordinator Agent — System

The coordinator is the entry point for all incoming requests to Nexus. It classifies
user messages into intent types and routes them to the appropriate pipeline.

## Role

- Receives: raw user message (string)
- Produces: RouteDecision (route type, confidence, reason)
- Does not: call LLMs, modify state, or access workspace

## Phase

Phase 1: rule-based keyword matching (current)
Phase 2: Ollama-backed LLM classifier (planned — replaces keyword matching)

## Model

None (Phase 1 is rule-based).
Phase 2 will use the local Ollama coordinator model defined in .env (COORDINATOR_MODEL).
