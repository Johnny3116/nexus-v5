"""Avatar pipeline server.

Receives chat from the browser chatbar (WebSocket) and HTTP /chat.
Routes every message through local Ollama (direct streaming via llm_stream).
Converts LLM output to audio via Voicebox TTS, broadcasts to the VRM client.

No external AI services. No relay. Just Ollama + Voicebox locally.
"""

import asyncio
import json
import logging
import uuid
import time
from pathlib import Path
from typing import Optional, Set

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# V5: Add Nexus root to path so orchestrator package is importable
import os as _os, sys as _sys
_NEXUS_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..', '..'))
if _NEXUS_ROOT not in _sys.path:
    _sys.path.insert(0, _NEXUS_ROOT)
del _os, _sys

# Load .env so ANTHROPIC_API_KEY and other secrets are in os.environ at startup
from dotenv import load_dotenv as _load_dotenv
from pathlib import Path as _Path
_load_dotenv(_Path(_NEXUS_ROOT) / '.env')
del _load_dotenv, _Path
# M12: event bus
from events.event_bus import publish as _bus_publish
from events.event_types import Event as _BusEvent, EventType as _ET

# Register built-in event subscribers at startup
try:
    from events.subscribers import register_all as _reg_subs
    _reg_subs()
    del _reg_subs
except Exception as _bus_init_err:
    import logging as _log
    _log.getLogger(__name__).warning("Event bus init failed: %s", _bus_init_err)
    del _bus_init_err, _log



logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="nexus-avatar")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Connection tracking ---
active_connections: Set[WebSocket] = set()
status_connections: Set[WebSocket] = set()

AUDIO_DIR = Path(__file__).parent.parent / "client" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


# --- Broadcast helpers ---

async def notify_clients(message: dict):
    if not active_connections:
        return
    data = json.dumps(message)
    coros = [ws.send_text(data) for ws in list(active_connections)]
    results = await asyncio.gather(*coros, return_exceptions=True)
    for ws, res in zip(list(active_connections), results):
        if isinstance(res, Exception):
            active_connections.discard(ws)


async def broadcast_status(count: int):
    msg = json.dumps({"type": "count_update", "count": count})
    await asyncio.gather(
        *[ws.send_text(msg) for ws in list(status_connections)],
        return_exceptions=True,
    )


# --- TTS + broadcast task (runs in parallel per sentence) ---

async def _tts_and_broadcast(
    sentence_text: str,
    sentence_idx: int,
    prev_done: Optional[asyncio.Event],
    my_done: asyncio.Event,
):
    loop = asyncio.get_running_loop()
    try:
        from process.tts_func.sovits_ping import sovits_gen, get_wav_duration
        from process.tts_func.tts_preprocess import clean_llm_output

        clean = clean_llm_output(sentence_text)
        if not clean.strip():
            return

        out_path = AUDIO_DIR / f"chat_{uuid.uuid4().hex}.wav"
        t0 = time.monotonic()
        await loop.run_in_executor(None, lambda: sovits_gen(clean, output_wav_pth=str(out_path)))
        duration = await loop.run_in_executor(None, get_wav_duration, str(out_path))
        logger.info(
            "TTS sentence #%d: %.2fs for %.2fs audio | %r",
            sentence_idx, time.monotonic() - t0, duration, clean[:60],
        )

        # Wait for previous sentence to broadcast first (preserves order).
        if prev_done is not None:
            await prev_done.wait()

        await notify_clients({
            "type": "start_animation",
            "audio_path": f"/audio/{out_path.name}",
            "expression": "neutral",
            "audio_text": sentence_text,
            "audio_duraction": int(duration * 1000),
            "queue": True,
        })
    except Exception as exc:
        logger.error("TTS/broadcast error on sentence #%d: %s", sentence_idx, exc)
    finally:
        my_done.set()


# --- Core chat pipeline: Ollama streaming -> parallel TTS -> ordered broadcast ---

async def _run_chat_pipeline(message: str, sender: Optional[WebSocket] = None):
    """Stream sentences from Ollama, TTS each in parallel, broadcast in order."""
    if not message.strip():
        return

    t0 = time.monotonic()

    try:
        from process.llm_funcs.llm_stream import stream_sentences

        sentences_seen = 0
        prev_evt: Optional[asyncio.Event] = None

        async for sentence in stream_sentences(message):
            sentences_seen += 1
            if sentences_seen == 1:
                logger.info("First sentence latency: %.2fs", time.monotonic() - t0)
            my_evt = asyncio.Event()
            asyncio.create_task(_tts_and_broadcast(sentence, sentences_seen, prev_evt, my_evt))
            prev_evt = my_evt

        if sentences_seen > 0:
            logger.info("Chat complete: %d sentences in %.2fs", sentences_seen, time.monotonic() - t0)
            return

        logger.warning("Ollama returned empty response")

    except Exception as exc:
        logger.error("Chat pipeline failed: %s", exc)
        if sender:
            try:
                await sender.send_text(json.dumps({"type": "chat_error", "error": str(exc)}))
            except Exception:
                pass



# V5/M6: TaskPacket + Plan pipeline with workspace context - code_plan route
async def _run_task_packet_pipeline(message: str, sender: Optional[WebSocket] = None):
    """Generate a TaskPacket, gather workspace context, then produce a Plan.

    Pipeline: router -> task_packet -> context_reader -> planner -> WS plan_response
    Falls back to chat only if TaskPacket generation fails.
    If planner fails, returns task_packet + planner_error (no chat fallback).
    Milestone 6: context_reader runs read-only before planner call.
    """
    try:
        from orchestrator.task_packet import generate_task_packet
        from orchestrator.router import classify_message

        route = classify_message(message)
        logger.info(
            "V5 route: %s (%.2f) - %s", route.route, route.confidence, route.reason
        )

        packet = await generate_task_packet(message)

    except Exception as exc:
        logger.error("TaskPacket pipeline failed (%s) - falling back to chat", exc)
        await _run_chat_pipeline(message, sender)
        return

    # Gather workspace context (read-only, never raises to caller)
    context = {}
    context_text = ""
    context_summary = "context unavailable"
    try:
        from orchestrator.context_reader import gather_context, format_context_for_prompt
        context = gather_context(packet)
        context_text = format_context_for_prompt(context)
        context_summary = context.get("summary", "no prior context")
        logger.info("Context: %s", context_summary)
    except Exception as ctx_exc:
        logger.warning("Context reader failed (%s) - planning without context", ctx_exc)

    # Generate the Plan (no fallback to chat here)
    plan = None
    planner_error = None
    try:
        from orchestrator.planner import generate_plan
        plan = await generate_plan(packet, context_text=context_text)
        logger.info("Plan generated for: %.60s", message)
    except Exception as exc:
        planner_error = str(exc)
        logger.error("Planner failed (%s) - returning task_packet without plan", exc)

    # Register plan for approval gate
    plan_id = None
    if plan is not None:
        try:
            from orchestrator.plan_store import register as _register_plan
            plan_id = _register_plan(plan, packet, route.route, route.confidence)
            logger.info("Plan registered: %s", plan_id)
        except Exception as reg_exc:
            logger.error("plan_store.register failed: %s", reg_exc)

    if sender:
        response: dict = {
            "type": "plan_response",
            "route": route.route,
            "confidence": route.confidence,
            "task_packet": packet,
            "context_summary": context_summary,
        }
        if plan is not None:
            response["plan"] = plan
        if plan_id is not None:
            response["plan_id"] = plan_id
        if planner_error is not None:
            response["planner_error"] = planner_error
        response["revision_round"] = 0
        await sender.send_text(json.dumps(response))
        # M12: PLAN_CREATED
        if plan_id:
            await _bus_publish(_BusEvent(
                type=_ET.PLAN_CREATED, plan_id=plan_id,
                data={"goal": packet.get("goal", ""), "route": route.route,
                      "revision_round": 0},
            ))
        logger.info(
            "plan_response sent: has_plan=%s has_error=%s context=%s",
            plan is not None,
            planner_error is not None,
            context_summary,
        )


async def _run_builder(
    plan_id: str,
    plan: dict,
    task_packet: dict,
    sender: Optional[WebSocket],
) -> None:
    """Build from approved plan with retry loop, verify, test, log, broadcast build_response.

    Pipeline: select_builder -> [build -> verify -> test -> retry?]x3 -> build_log -> WS
    Selects Sonnet if ANTHROPIC_API_KEY is set, else Ollama qwen2.5-coder.
    Milestone 7: verify failure feeds errors back, retries (max 3).
    Milestone 9: test failure also feeds back into retry loop.
    Milestone 12: publishes BUILD_STARTED, BUILD_ATTEMPT_FAILED, BUILD_RETRIED,
                  TEST_PASSED, TEST_FAILED, WORKSPACE_WRITTEN, BUILD_COMPLETE events.
    """
    import os as _os
    api_key = _os.getenv("ANTHROPIC_API_KEY", "")

    goal = plan.get("summary", task_packet.get("goal", ""))
    builder_used = "unknown"
    result: dict = {
        "success": False,
        "written_files": [],
        "notes": "",
        "error": None,
    }
    verify_result: dict = {"passed": False, "results": [], "summary": "not run"}
    test_result: dict = {"passed": True, "tests_run": 0, "output": "", "summary": "not run"}

    MAX_ATTEMPTS = 3
    attempt = 0
    error_context = ""

    try:
        if api_key:
            from orchestrator.sonnet_builder import build_from_plan
            builder_used = f"sonnet:{_os.getenv('ANTHROPIC_BUILD_MODEL', 'claude-sonnet-4-6')}"
            logger.info("Builder: Sonnet selected for plan %s", plan_id)
        else:
            from orchestrator.builder import build_from_plan
            builder_used = "ollama"
            logger.info("Builder: Ollama selected for plan %s (no ANTHROPIC_API_KEY)", plan_id)

        from orchestrator.verifier import verify_files
        from orchestrator.test_runner import run_tests

        # M12: BUILD_STARTED
        await _bus_publish(_BusEvent(
            type=_ET.BUILD_STARTED, plan_id=plan_id,
            data={"builder": builder_used, "goal": goal},
        ))

        while attempt < MAX_ATTEMPTS:
            attempt += 1
            logger.info("Build attempt %d/%d for plan %s", attempt, MAX_ATTEMPTS, plan_id)

            try:
                result = await build_from_plan(plan, task_packet, error_context=error_context)
            except Exception as build_exc:
                result = {
                    "success": False,
                    "written_files": [],
                    "notes": "",
                    "error": str(build_exc),
                }
                logger.error("Builder raised on attempt %d: %s", attempt, build_exc)

            if not result["success"]:
                await _bus_publish(_BusEvent(
                    type=_ET.BUILD_ATTEMPT_FAILED, plan_id=plan_id,
                    data={"attempt": attempt, "reason": result.get("error", "build error"),
                          "stage": "build"},
                ))
                if attempt < MAX_ATTEMPTS:
                    error_context = (
                        f"Attempt {attempt} failed: {result.get('error', 'unknown build error')}. "
                        "Rewrite your output correctly."
                    )
                    logger.warning("Build failed on attempt %d -- retrying", attempt)
                    await _bus_publish(_BusEvent(
                        type=_ET.BUILD_RETRIED, plan_id=plan_id,
                        data={"attempt": attempt + 1, "reason": "build_error"},
                    ))
                    continue
                break

            # Syntax verification
            if result["written_files"]:
                verify_result = verify_files(result["written_files"])
                logger.info(
                    "Verify attempt %d: %s for plan %s",
                    attempt, verify_result["summary"], plan_id,
                )
            else:
                verify_result = {"passed": True, "results": [], "summary": "no files to verify"}

            if not verify_result["passed"]:
                await _bus_publish(_BusEvent(
                    type=_ET.BUILD_ATTEMPT_FAILED, plan_id=plan_id,
                    data={"attempt": attempt, "reason": verify_result["summary"],
                          "stage": "verify"},
                ))
                if attempt < MAX_ATTEMPTS:
                    failed_details = [
                        f"  {r['file']}: {r['error']}"
                        for r in verify_result.get("results", [])
                        if not r.get("ok")
                    ]
                    error_context = (
                        f"Attempt {attempt} produced files that failed verification:\n"
                        + "\n".join(failed_details)
                        + "\nFix these errors in your next output."
                    )
                    logger.warning(
                        "Verify failed on attempt %d (%s) -- retrying",
                        attempt, verify_result["summary"],
                    )
                    await _bus_publish(_BusEvent(
                        type=_ET.BUILD_RETRIED, plan_id=plan_id,
                        data={"attempt": attempt + 1, "reason": "verify_failed"},
                    ))
                else:
                    logger.error(
                        "All %d attempts exhausted for plan %s -- last verify: %s",
                        MAX_ATTEMPTS, plan_id, verify_result["summary"],
                    )
                continue

            # Test execution (M9)
            test_result = run_tests(result["written_files"])
            logger.info(
                "Test run attempt %d: %s for plan %s",
                attempt, test_result["summary"], plan_id,
            )

            if test_result["passed"] or test_result["tests_run"] == 0:
                if test_result["tests_run"] > 0:
                    # M12: TEST_PASSED
                    await _bus_publish(_BusEvent(
                        type=_ET.TEST_PASSED, plan_id=plan_id,
                        data={"tests_run": test_result["tests_run"], "attempt": attempt},
                    ))
                break

            # M12: TEST_FAILED
            await _bus_publish(_BusEvent(
                type=_ET.TEST_FAILED, plan_id=plan_id,
                data={"attempt": attempt, "summary": test_result["summary"],
                      "tests_run": test_result["tests_run"]},
            ))

            if attempt < MAX_ATTEMPTS:
                error_context = (
                    f"Attempt {attempt} verify passed but tests failed ({test_result['summary']}):\n"
                    + test_result["output"][:2000]
                    + "\nFix your implementation so all tests pass."
                )
                logger.warning(
                    "Tests failed on attempt %d (%s) -- retrying",
                    attempt, test_result["summary"],
                )
                await _bus_publish(_BusEvent(
                    type=_ET.BUILD_RETRIED, plan_id=plan_id,
                    data={"attempt": attempt + 1, "reason": "test_failed"},
                ))
            else:
                logger.error(
                    "All %d attempts exhausted for plan %s -- last test: %s",
                    MAX_ATTEMPTS, plan_id, test_result["summary"],
                )

    except Exception as exc:
        result["error"] = str(exc)
        logger.error("Builder setup crashed for plan %s: %s", plan_id, exc)

    # M12: WORKSPACE_WRITTEN (only when files were produced)
    if result.get("written_files"):
        await _bus_publish(_BusEvent(
            type=_ET.WORKSPACE_WRITTEN, plan_id=plan_id,
            data={"files": result["written_files"], "count": len(result["written_files"])},
        ))

    try:
        from orchestrator.build_log import append_entry
        append_entry(
            plan_id=plan_id,
            goal=goal,
            builder_used=builder_used,
            written_files=result.get("written_files", []),
            verify_result=verify_result,
            build_error=result.get("error"),
        )
    except Exception as log_exc:
        logger.error("build_log failed: %s", log_exc)

    final_success = (
        result["success"]
        and verify_result.get("passed", False)
        and (test_result.get("passed", True) or test_result.get("tests_run", 0) == 0)
    )

    # --- M13: write workspace manifest ---
    try:
        from orchestrator.manifest_writer import write_manifest as _write_manifest
        _write_manifest(
            plan_id=plan_id,
            goal=task_packet.get("goal", ""),
            builder_used=builder_used,
            written_files=result.get("written_files", []),
            verify_result=verify_result,
            test_result=test_result,
            attempt_count=attempt_count,
            success=final_success,
            error=result.get("error"),
        )
    except Exception as _manifest_err:
        logger.warning("Manifest write failed: %s", _manifest_err)

    if sender:
        try:
            await sender.send_text(json.dumps({
                "type": "build_response",
                "plan_id": plan_id,
                "success": final_success,
                "written_files": result["written_files"],
                "notes": result["notes"],
                "error": result["error"],
                "verify_result": verify_result,
                "test_result": test_result,
                "builder_used": builder_used,
                "attempt_count": attempt,
            }))
        except Exception as ws_exc:
            logger.error("Failed to send build_response for plan %s: %s", plan_id, ws_exc)

    # M12: BUILD_COMPLETE
    await _bus_publish(_BusEvent(
        type=_ET.BUILD_COMPLETE, plan_id=plan_id,
        data={
            "success": final_success,
            "attempt_count": attempt,
            "files_written": len(result.get("written_files", [])),
            "builder": builder_used,
            "verify_summary": verify_result.get("summary"),
            "test_summary": test_result.get("summary"),
        },
    ))

    if final_success:
        logger.info(
            "Build complete: %s file(s), verify=PASS, tests=%s, builder=%s, attempts=%d, plan=%s",
            len(result["written_files"]), test_result["summary"], builder_used, attempt, plan_id,
        )
    else:
        logger.error(
            "Build failed after %d attempt(s) for plan %s: build_err=%s verify=%s test=%s",
            attempt, plan_id, result["error"],
            verify_result.get("summary"), test_result.get("summary"),
        )


async def _replan(
    task_packet: dict,
    revision_feedback: str,
    revision_round: int,
    sender: Optional[WebSocket],
) -> None:
    """Re-run planner with user revision feedback, send updated plan_response.

    Milestone 8: plan revision gate.  Called when user sends
    plan_decision with decision="revise" and a feedback string.
    Re-gathers workspace context (workspace may have changed), re-runs
    Ollama planner with revision_feedback injected, registers the new
    plan, and broadcasts a fresh plan_response WS message.
    """
    # Re-gather context (workspace may have changed since original plan)
    context_text = ""
    context_summary = "context unavailable"
    try:
        from orchestrator.context_reader import gather_context, format_context_for_prompt
        context = gather_context(task_packet)
        context_text = format_context_for_prompt(context)
        context_summary = context.get("summary", "no prior context")
    except Exception as ctx_exc:
        logger.warning("Context reader failed during revision (%s) - planning without context", ctx_exc)

    plan = None
    planner_error = None
    try:
        from orchestrator.planner import generate_plan
        plan = await generate_plan(
            task_packet,
            context_text=context_text,
            revision_feedback=revision_feedback,
        )
        logger.info(
            "Revision plan %d generated for goal: %.60s",
            revision_round, task_packet.get("goal", ""),
        )
    except Exception as exc:
        planner_error = str(exc)
        logger.error("Revision planner failed (round %d): %s", revision_round, exc)

    from orchestrator.plan_store import register as _register_plan
    plan_id = _register_plan(
        plan or {},
        task_packet,
        route=task_packet.get("request_type", "code_plan"),
        confidence=1.0,
        revision_round=revision_round,
    )

    if sender:
        try:
            await sender.send_text(json.dumps({
                "type": "plan_response",
                "task_packet": task_packet,
                "plan": plan,
                "plan_id": plan_id,
                "planner_error": planner_error,
                "revision_round": revision_round,
                "context_summary": context_summary,
            }))
        except Exception as ws_exc:
            logger.error("Failed to send revision plan_response (round %d): %s", revision_round, ws_exc)
        # M12: PLAN_REVISED
        await _bus_publish(_BusEvent(
            type=_ET.PLAN_REVISED, plan_id=plan_id,
            data={"revision_round": revision_round, "goal": task_packet.get("goal", "")},
        ))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    active_connections.add(ws)
    logger.info("Client connected: %s (total %d)", ws.client, len(active_connections))
    await broadcast_status(len(active_connections))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("type") == "plan_decision":
                plan_id_d = msg.get("plan_id", "")
                decision = msg.get("decision", "")
                try:
                    from orchestrator.plan_store import consume as _consume_plan
                    entry = _consume_plan(plan_id_d)
                    if entry is None:
                        await ws.send_text(json.dumps({
                            "type": "plan_error",
                            "error": f"Unknown or already-decided plan_id: {plan_id_d!r}",
                        }))
                    elif decision == "approve":
                        logger.info("Plan approved: %s | goal=%.60s", plan_id_d,
                                    entry["task_packet"].get("goal", ""))
                        # Notify immediately — build may take a while
                        await ws.send_text(json.dumps({
                            "type": "plan_approved",
                            "plan_id": plan_id_d,
                            "message": "Plan approved. Starting builder...",
                        }))
                        # M12: PLAN_APPROVED
                        await _bus_publish(_BusEvent(
                            type=_ET.PLAN_APPROVED, plan_id=plan_id_d,
                            data={"goal": entry["task_packet"].get("goal", "")},
                        ))
                        # Run builder as background task so WS stays responsive
                        asyncio.create_task(
                            _run_builder(plan_id_d, entry["plan"],
                                         entry["task_packet"], ws)
                        )
                    elif decision == "reject":
                        logger.info("Plan rejected: %s", plan_id_d)
                        await ws.send_text(json.dumps({
                            "type": "plan_rejected",
                            "plan_id": plan_id_d,
                            "message": "Plan rejected.",
                        }))
                        # M12: PLAN_REJECTED
                        await _bus_publish(_BusEvent(
                            type=_ET.PLAN_REJECTED, plan_id=plan_id_d,
                        ))
                    elif decision == "revise":
                        feedback = msg.get("feedback", "").strip()
                        if not feedback:
                            await ws.send_text(json.dumps({
                                "type": "plan_error",
                                "error": "Revision requires a non-empty feedback string.",
                            }))
                        else:
                            revision_round = entry.get("revision_round", 0) + 1
                            logger.info(
                                "Plan revision %d requested: %.60s",
                                revision_round, entry["task_packet"].get("goal", ""),
                            )
                            await ws.send_text(json.dumps({
                                "type": "plan_revision_ack",
                                "plan_id": plan_id_d,
                                "revision_round": revision_round,
                                "message": f"Revision {revision_round} in progress...",
                            }))
                            asyncio.create_task(
                                _replan(
                                    task_packet=entry["task_packet"],
                                    revision_feedback=feedback,
                                    revision_round=revision_round,
                                    sender=ws,
                                )
                            )
                    else:
                        await ws.send_text(json.dumps({
                            "type": "plan_error",
                            "error": f"Unknown decision {decision!r}. Use approve, reject, or revise.",
                        }))
                except Exception as exc:
                    logger.error("plan_decision handler failed (%s)", exc)
                    await ws.send_text(json.dumps({"type": "plan_error", "error": str(exc)}))

            elif msg.get("type") == "user_chat":
                text = msg.get("message", "")
                logger.info("WS user_chat: %s", text[:80])
                await ws.send_text(json.dumps({"type": "chat_ack", "status": "thinking"}))

                # V5: classify before routing
                try:
                    from orchestrator.router import classify_message
                    _route = classify_message(text)
                    logger.info(
                        "V5 route: %s (%.2f) - %s",
                        _route.route, _route.confidence, _route.reason
                    )
                    if _route.route == "code_plan":
                        asyncio.create_task(_run_task_packet_pipeline(text, ws))
                    else:
                        asyncio.create_task(_run_chat_pipeline(text, ws))
                except Exception as _route_err:
                    logger.error("Router error (%s) - falling back to chat", _route_err)
                    asyncio.create_task(_run_chat_pipeline(text, ws))
    except WebSocketDisconnect:
        active_connections.discard(ws)
        logger.info("Client disconnected: %s (total %d)", ws.client, len(active_connections))
        await broadcast_status(len(active_connections))
    except Exception as exc:
        logger.error("WS error: %s", exc)
        active_connections.discard(ws)
        await broadcast_status(len(active_connections))


@app.websocket("/ws_status")
async def ws_status(ws: WebSocket):
    await ws.accept()
    status_connections.add(ws)
    await ws.send_text(json.dumps({"type": "count_update", "count": len(active_connections)}))
    try:
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text("pong")
    except (WebSocketDisconnect, Exception):
        status_connections.discard(ws)


# --- HTTP endpoints ---

class ChatInput(BaseModel):
    message: str


@app.post("/chat")
async def chat_http(req: ChatInput):
    """Text in -> Ollama -> TTS -> broadcast to VRM clients."""
    await _run_chat_pipeline(req.message)
    return {"status": "ok", "message": req.message}


class TalkRequest(BaseModel):
    audio_path: str
    expression: str = "neutral"
    audio_text: str
    audio_duraction: int


@app.post("/talk")
async def talk(req: TalkRequest):
    payload = {
        "type": "start_animation",
        "audio_path": req.audio_path,
        "expression": req.expression,
        "audio_text": req.audio_text,
        "audio_duraction": req.audio_duraction,
    }
    await notify_clients(payload)
    return {"status": "sent"}


class AnimationPayload(BaseModel):
    animate_type: str
    animation_url: str
    play_once: Optional[bool] = False
    crop_start: Optional[float] = 0.0
    crop_end: Optional[float] = 0.0
    lock_position: Optional[bool] = False
    track_position: Optional[bool] = True


@app.post("/animate")
async def animate(payload: AnimationPayload):
    anim_type = payload.animate_type
    if anim_type == "auto":
        url_lower = payload.animation_url.lower()
        anim_type = "start_vrma" if url_lower.endswith(".vrma") else "start_mixamo"

    msg = {
        "type": anim_type,
        "animation_url": payload.animation_url,
        "play_once": payload.play_once,
        "crop_start": payload.crop_start,
        "crop_end": payload.crop_end,
        "lock_position": payload.lock_position,
        "track_position": payload.track_position,
    }
    await notify_clients(msg)
    return {"status": "sent"}


class SetStateRequest(BaseModel):
    state: str


@app.post("/set_state")
async def set_state(req: SetStateRequest):
    valid = {"idle", "listening", "thinking", "talking"}
    if req.state not in valid:
        return {"status": "error", "message": f"Invalid state: {req.state}", "valid_states": list(valid)}
    await notify_clients({"type": "set_state", "state": req.state})
    return {"status": "state_set", "state": req.state}


@app.get("/health")
async def health():
    return {"status": "ok", "connections": len(active_connections)}


@app.get("/status")
async def status_page():
    html = f"""<!DOCTYPE html>
<html><head><title>Nexus Avatar</title></head>
<body><h1>Nexus Avatar Server</h1>
<p>VRM clients connected: <span id="count">{len(active_connections)}</span></p>
<script>
  const ws = new WebSocket(`ws://${{location.host}}/ws_status`);
  ws.onmessage = e => {{
    const m = JSON.parse(e.data);
    if (m.type === 'count_update') document.getElementById('count').textContent = m.count;
  }};
</script></body></html>"""
    return HTMLResponse(html)



# --- M10: Build History & Workspace Inspection ---

_WORKSPACE_OUTPUT = Path(__file__).resolve().parents[3] / "workspace" / "output"


@app.get("/builds")
async def list_builds(n: int = 20):
    """Return the n most recent build log entries."""
    try:
        from orchestrator.build_log import recent
        return {"builds": recent(n), "count_returned": n}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/builds/{plan_id}")
async def get_build(plan_id: str):
    """Return the build log entry for a specific plan_id."""
    try:
        from orchestrator.build_log import get_by_plan_id
        entry = get_by_plan_id(plan_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No build found for plan_id={plan_id!r}")
    return entry


@app.get("/workspace")
async def list_workspace():
    """List files in workspace/output/."""
    if not _WORKSPACE_OUTPUT.exists():
        return {"files": [], "count": 0, "directory": str(_WORKSPACE_OUTPUT)}
    try:
        files = [
            {
                "name": p.name,
                "size": p.stat().st_size,
                "modified": p.stat().st_mtime,
            }
            for p in sorted(_WORKSPACE_OUTPUT.iterdir())
            if p.is_file()
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"files": files, "count": len(files), "directory": str(_WORKSPACE_OUTPUT)}


@app.get("/workspace/files/{filename}")
async def read_workspace_file(filename: str):
    """Read a single file from workspace/output/."""
    try:
        resolved = (_WORKSPACE_OUTPUT / filename).resolve()
        resolved.relative_to(_WORKSPACE_OUTPUT.resolve())  # traversal check
    except ValueError:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    if not resolved.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {filename}")
    try:
        content = resolved.read_text(encoding="utf-8", errors="replace")
        return {"filename": filename, "content": content, "size": resolved.stat().st_size}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/workspace/files/{filename}")
async def delete_workspace_file(filename: str):
    """Delete a single file from workspace/output/."""
    try:
        resolved = (_WORKSPACE_OUTPUT / filename).resolve()
        resolved.relative_to(_WORKSPACE_OUTPUT.resolve())  # traversal check
    except ValueError:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    resolved.unlink()
    return {"status": "deleted", "filename": filename}


@app.delete("/workspace")
async def clear_workspace(confirm: str = ""):
    """Clear all files from workspace/output/. Requires ?confirm=true."""
    if confirm != "true":
        raise HTTPException(
            status_code=400,
            detail="Pass ?confirm=true to clear the workspace",
        )
    if not _WORKSPACE_OUTPUT.exists():
        return {"status": "ok", "deleted": 0}
    try:
        files = [p for p in _WORKSPACE_OUTPUT.iterdir() if p.is_file()]
        for f in files:
            f.unlink()
        return {"status": "cleared", "deleted": len(files)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# M13: Workspace Manifest endpoints
# ---------------------------------------------------------------------------

@app.get("/manifests")
async def list_manifests_endpoint(n: int = 20):
    from orchestrator.manifest_writer import list_manifests as _list_manifests
    return {"manifests": _list_manifests(n=n)}


@app.get("/manifests/{plan_id}")
async def get_manifest_endpoint(plan_id: str):
    from orchestrator.manifest_writer import read_manifest as _read_manifest
    entry = _read_manifest(plan_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No manifest for plan_id={plan_id!r}")
    return entry


# Static files (must be last - catch-all)
app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")
app.mount("/", StaticFiles(directory=str(Path(__file__).parent.parent / "client"), html=True), name="vrm-client")


if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8001, reload=False)
