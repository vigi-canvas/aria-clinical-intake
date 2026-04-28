"""
FastAPI entry point for the Clinical Intake Voice Agent.
"""
import asyncio
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

load_dotenv()

from auth import get_credentials
from brief_generator import generate_brief
from session import GeminiLiveSession
from state_extractor import apply_extraction, extract_intake_state
from state_machine import IntakeStateMachine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s — %(message)s',
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Clinical Intake Voice Agent — Aria")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "live_model": os.environ.get("GEMINI_LIVE_MODEL", "not set"),
        "rest_model": os.environ.get("GEMINI_MODEL", "not set"),
    }


@app.websocket("/ws/session")
async def ws_session(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connected: %s", websocket.client)

    try:
        creds = get_credentials()
    except FileNotFoundError as e:
        await websocket.send_json({'type': 'error', 'code': 'AUTH_MISSING', 'message': str(e)})
        await websocket.close()
        return

    sm     = IntakeStateMachine()
    gemini = GeminiLiveSession(sm, creds)

    # Mutable flags shared between tasks
    brief_sent = [False]
    stop_event = asyncio.Event()

    # Lock so concurrent tasks never interleave WebSocket frames
    ws_lock = asyncio.Lock()

    async def ws_send(data: dict):
        """Thread-safe serialised WebSocket send."""
        async with ws_lock:
            try:
                await websocket.send_json(data)
            except Exception:
                stop_event.set()

    try:
        await gemini.start()
        await ws_send({'type': 'phase', 'phase': sm.phase})
        await ws_send({'type': 'connected'})

        # Trigger Aria to speak first — without this the session waits for
        # patient audio before saying anything.
        await gemini.trigger_greeting()

        async def receive_from_browser():
            """Forward browser mic PCM to Gemini Live."""
            try:
                async for message in websocket.iter_bytes():
                    if stop_event.is_set():
                        break
                    try:
                        await gemini.send_audio(message)
                    except Exception as e:
                        logger.warning("send_audio failed: %s", e)
                        stop_event.set()
                        break
            except WebSocketDisconnect:
                stop_event.set()

        async def send_to_browser():
            """Stream Gemini responses to the browser and manage state."""
            try:
                async for chunk in gemini.receive():
                    if stop_event.is_set():
                        break

                    await ws_send(chunk)

                    if chunk['type'] == 'error':
                        logger.error("Gemini error: %s — %s",
                                     chunk.get('code'), chunk.get('message'))
                        stop_event.set()
                        break

                    if chunk['type'] == 'turn_complete':
                        asyncio.create_task(
                            _extract_and_advance(ws_send, sm, creds, brief_sent, stop_event)
                        )
            finally:
                stop_event.set()

        await asyncio.gather(receive_from_browser(), send_to_browser())

    except WebSocketDisconnect:
        logger.info("Browser WebSocket disconnected cleanly")
    except Exception as e:
        logger.exception("Unhandled session error")
        try:
            await ws_send({'type': 'error', 'code': 'SESSION_ERROR', 'message': str(e)})
        except Exception:
            pass
    finally:
        await gemini.close()
        logger.info("Session cleaned up — phase=%s transcript_len=%d",
                    sm.phase, len(sm.transcript))


async def _extract_and_advance(
    ws_send,
    sm: IntakeStateMachine,
    creds,
    brief_sent: list,
    stop_event: asyncio.Event,
):
    """
    Background task: extract state from transcript after each agent turn,
    advance the phase when criteria are met, and trigger brief generation
    when the session reaches DONE.
    """
    try:
        prev_phase = sm.phase
        data       = await extract_intake_state(sm, creds)
        changed    = apply_extraction(sm, data)

        if changed:
            logger.info("State updated: %s", changed)

        did_advance = _check_and_advance_phase(sm)

        # If Aria delivered the closing farewell, force-advance to DONE
        if data.get('closing_complete') and sm.phase != 'DONE':
            while sm.phase != 'DONE':
                sm.advance_phase()
            did_advance = True

        if did_advance or changed:
            await ws_send({'type': 'phase', 'phase': sm.phase})
            await ws_send({
                'type': 'state_update',
                'patient_name': sm.patient_name,
                'chief_complaint': sm.chief_complaint,
                'hpi': sm.hpi_fields,
                'ros_systems': sm.ros_systems,
            })

        if did_advance:
            logger.info("Phase advanced: %s → %s", prev_phase, sm.phase)

        if sm.phase == 'DONE' and not brief_sent[0]:
            brief_sent[0] = True
            await _send_brief(ws_send, sm, creds)
            await ws_send({'type': 'session_complete'})
            stop_event.set()

    except Exception as e:
        logger.exception("Error in state extraction task")
        await ws_send({'type': 'error', 'code': 'STATE_ERROR', 'message': str(e)})


def _check_and_advance_phase(sm: IntakeStateMachine) -> bool:
    """Advance phase if completion criteria are met. Returns True if advanced."""
    prev = sm.phase

    if sm.phase == 'GREETING' and sm.patient_name:
        sm.advance_phase()
    elif sm.phase == 'CHIEF_COMPLAINT' and sm.chief_complaint:
        sm.advance_phase()
    elif sm.phase == 'HPI' and sm.hpi_complete():
        sm.advance_phase()
    elif sm.phase == 'ROS' and sm.ros_complete():
        sm.advance_phase()
    elif sm.phase == 'CLOSING':
        sm.advance_phase()

    return sm.phase != prev


async def _send_brief(ws_send, sm: IntakeStateMachine, creds):
    """Generate and send the clinical brief with transcript fallback on failure."""
    try:
        await ws_send({'type': 'brief_generating'})
        brief = await generate_brief(sm.transcript, creds)
        await ws_send({'type': 'brief', 'data': brief})
        logger.info("Clinical brief sent successfully")
    except ValueError as e:
        logger.error("Brief generation failed: %s", e)
        await ws_send({
            'type': 'brief_error',
            'message': str(e),
            'transcript': sm.transcript,
        })
    except Exception as e:
        logger.exception("Unexpected error generating brief")
        await ws_send({
            'type': 'brief_error',
            'message': f"Brief generation failed: {e}",
            'transcript': sm.transcript,
        })
