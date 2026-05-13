"""nexus-gateway â€” FastAPI entrypoint.

Launched by PM2 per `orchestration/deployments/ecosystem.config.js`:
    uvicorn api_gateway.main:app --host <tailscale-ip> --port 8000

This module is the HTTP boundary. It:
  - mounts the tailscale allowlist middleware
  - registers /v1/chat, /v1/memory, /v1/task (501), /v1/skill (501), /health
  - owns no inference, no safety filtering, no personality logic

All LLM work is delegated to `serving/brain_pool/`; memory CRUD goes
through `kv_cache/cold/supabase_client.py`. Phase 3/4 will slot soul
container, injection scanner, and safety tier gates into the middleware
stack below the allowlist.
"""

from __future__ import annotations

import os
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api_gateway.auth.tailscale_allowlist import TailscaleAllowlistMiddleware
from api_gateway.config.settings import get_settings
from api_gateway.endpoints import asr, chat, connectors, health, memory, skill, task, workspace
import orchestrator.connectors.supabase_connector  # auto-register
from safety.input_filters.injection_middleware import InjectionScannerMiddleware
from safety.output_filters.approval_queue import ApprovalQueue
from serving.brain_pool.brain_pool import get_brain_pool
from serving.skills.agentic_loop import AgenticLoop
from serving.skills.skill_manager import get_skill_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("nexus.api_gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(
        "nexus-gateway starting â€” bind=%s:%d nexus_agent=%s ollama=%s",
        settings.gateway_host,
        settings.gateway_port,
        settings.nexus_agent_http_url,
        settings.ollama_url,
    )
    # Warm the BrainPool singleton so the first /v1/chat call doesn't pay setup cost.
    get_brain_pool()

    # â”€â”€ Track D: shared AgenticLoop + scheduler + heartbeat â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    try:
        from kv_cache.cold.supabase_client import get_supabase
        db = get_supabase()
    except Exception:
        db = None
    approval_queue = ApprovalQueue(db=db)
    agentic_loop = AgenticLoop(skill_manager=get_skill_manager(), approval_queue=approval_queue)
    app.state.approval_queue = approval_queue
    app.state.agentic_loop = agentic_loop

    bg_tasks: list[asyncio.Task] = []
    try:
        from orchestration.autonomy.scheduler import Scheduler
        scheduler = Scheduler(loop_runner=agentic_loop.run)
        scheduler.load()
        app.state.scheduler = scheduler
        bg_tasks.append(asyncio.create_task(scheduler.start_background_loop(60)))
        logger.info("scheduler started with %d tasks", scheduler.status()["tasks_total"])
    except Exception as exc:
        logger.warning("scheduler skipped: %s", exc)

    # Pre-warm Whisper so the first voice-mode request isn't a cold model load.
    # Runs in the executor — never blocks gateway startup.
    try:
        from api_gateway.endpoints.asr import _load_model
        asyncio.get_running_loop().run_in_executor(None, _load_model)
        logger.info("Whisper pre-warm scheduled")
    except Exception as exc:
        logger.warning("Whisper pre-warm skipped: %s", exc)

    if os.environ.get("NEXUS_HEARTBEAT_ENABLED", "1") == "1":
        try:
            from orchestration.autonomy.heartbeat import Heartbeat
            heartbeat = Heartbeat()
            heartbeat.load()
            heartbeat.agentic_loop = agentic_loop  # dispatch target for <nexus_task> blocks
            app.state.heartbeat = heartbeat
            bg_tasks.append(asyncio.create_task(heartbeat.start()))
            logger.info("heartbeat started (interval=%dm)", heartbeat._config.interval_minutes)
        except Exception as exc:
            logger.warning("heartbeat skipped: %s", exc)
    else:
        logger.info("heartbeat disabled via NEXUS_HEARTBEAT_ENABLED=0")

    yield

    for t in bg_tasks:
        t.cancel()
    await get_brain_pool().close()
    logger.info("nexus-gateway shut down")


app = FastAPI(
    title="nexus-gateway",
    version="0.1.0",
    description="Nexus AI â€” public HTTP gateway (BrainPool + memory + health).",
    lifespan=lifespan,
)

# CORS â€” allow nexus-hub from any Tailscale device + localhost dev.
_cors_origins = [
    "https://nexusbody.tail344870.ts.net:5174",   # hub HTTPS (primary)
    "https://localhost:5174",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://100.84.78.77:5174",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Doctrine A10 rule #3 â€” scan POST bodies for prompt injection.
# Added before Tailscale so that the allowlist runs first (outermost).
app.add_middleware(InjectionScannerMiddleware)

# Doctrine 1 â€” Tailscale-only, enforced at the edge.
app.add_middleware(TailscaleAllowlistMiddleware)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(memory.router)
app.include_router(task.router)
app.include_router(skill.router)
app.include_router(workspace.router)
app.include_router(connectors.router)
app.include_router(asr.router)


# Convenience for `python -m api_gateway.main` during dev.
if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "api_gateway.main:app",
        host=s.gateway_host,
        port=s.gateway_port,
        reload=False,
    )
