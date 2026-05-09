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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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



# V5: TaskPacket + Plan pipeline - code_plan route
async def _run_task_packet_pipeline(message: str, sender: Optional[WebSocket] = None):
    """Generate a TaskPacket then a Plan. Returns plan_response over WS.

    Pipeline: router -> task_packet.py -> planner.py -> WS plan_response
    Falls back to chat only if TaskPacket generation fails.
    If planner fails, returns task_packet + planner_error (no chat fallback).
    Milestone 2: no file writes, no Codex, no Sonnet, no shell execution.
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

    # TaskPacket succeeded -- now generate the Plan (no fallback to chat here)
    plan = None
    planner_error = None
    try:
        from orchestrator.planner import generate_plan

        plan = await generate_plan(packet)
        logger.info("Plan generated for: %.60s", message)
    except Exception as exc:
        planner_error = str(exc)
        logger.error("Planner failed (%s) - returning task_packet without plan", exc)

    # Register plan so user can approve/reject by plan_id
    plan_id: str | None = None
    if plan is not None:
        try:
            from orchestrator.plan_store import register as _register_plan
            plan_id = _register_plan(plan, packet, route.route, route.confidence)
        except Exception as exc:
            logger.error("plan_store.register failed (%s)", exc)

    if sender:
        response: dict = {
            "type": "plan_response",
            "route": route.route,
            "confidence": route.confidence,
            "task_packet": packet,
        }
        if plan is not None:
            response["plan"] = plan
        if plan_id is not None:
            response["plan_id"] = plan_id
        if planner_error is not None:
            response["planner_error"] = planner_error
        await sender.send_text(json.dumps(response))
        logger.info(
            "plan_response sent: plan_id=%s has_plan=%s has_error=%s",
            plan_id, plan is not None, planner_error is not None,
        )


# --- WebSocket endpoints ---

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
                        await ws.send_text(json.dumps({
                            "type": "plan_approved",
                            "plan_id": plan_id_d,
                            "plan": entry["plan"],
                            "task_packet": entry["task_packet"],
                            "message": "Plan approved. Builder not wired yet (Milestone 4).",
                        }))
                    elif decision == "reject":
                        logger.info("Plan rejected: %s", plan_id_d)
                        await ws.send_text(json.dumps({
                            "type": "plan_rejected",
                            "plan_id": plan_id_d,
                            "message": "Plan rejected.",
                        }))
                    else:
                        await ws.send_text(json.dumps({
                            "type": "plan_error",
                            "error": f"Unknown decision {decision!r}. Use approve or reject.",
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


# Static files (must be last - catch-all)
app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")
app.mount("/", StaticFiles(directory=str(Path(__file__).parent.parent / "client"), html=True), name="vrm-client")


if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8001, reload=False)
