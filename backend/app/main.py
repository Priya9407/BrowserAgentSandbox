import asyncio
import json
import logging
import uuid
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app.agent.playwright_agent import run_browser_agent_async

logging.basicConfig(level=logging.INFO)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

action_queue: asyncio.Queue = asyncio.Queue()
active_connections: list[WebSocket] = []

# In-memory chat session history  { session_id: [messages] }
chat_sessions: dict[str, list[dict]] = {}


# ---------------------------------------------------------------------------
# Helper — push any payload to all WebSocket clients
# ---------------------------------------------------------------------------
async def _broadcast(payload: dict):
    await action_queue.put(payload)


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------
@app.get("/")
def home():
    return {"status": "running"}


# ---------------------------------------------------------------------------
# /run-agent  (existing flow, unchanged)
# ---------------------------------------------------------------------------
@app.post("/run-agent")
async def run_agent(
    page: str = "shopping",
    user_task: str = "Buy the laptop",
    auto_approve_escalated: bool = False,
):
    page_files = {
        "shopping": "shopping.html",
        "login": "login.html",
        "hidden": "hidden.html",
        "testshopping": "testshopping.html",
        "flight_visible": "flight_visible.html",
        "opacity_download": "opacity_download.html",
        "color_email": "color_email.html",
        "visibility_transfer": "visibility_transfer.html",
        "fontsize_exfil": "fontsize_exfil.html",
        "zindex_privilege": "zindex_privilege.html",
        "aria_hidden": "aria_hidden.html",
        "clip_path_api": "clip_path_api.html",
        "benign_checkout": "benign_checkout.html",
    }

    project_root = Path(__file__).resolve().parents[2]
    page_file = page_files.get(page, "shopping.html")
    page_uri = (project_root / "test-pages" / page_file).as_uri()

    asyncio.create_task(
        run_browser_agent_async(
            action_queue,
            page_uri=page_uri,
            user_task=user_task,
            headless=False,
            auto_approve_escalated=auto_approve_escalated,
        )
    )
    return {"status": "started", "page": page_file}


# ---------------------------------------------------------------------------
# /chat  — the new chat-driven entrypoint
#
# Request body:
#   goal   : free-text goal the user typed ("search for the price of RTX 4090")
#   url    : optional starting URL (defaults to our benign shopping page)
#   headless: bool, default True so the browser stays out of the way
#
# How it works:
#   1. Creates a session_id and records the user message in chat_sessions.
#   2. Broadcasts a chat_status "planning" event over WebSocket immediately
#      so the UI can show a spinner/status line without waiting.
#   3. Fires off the agent task in the background (non-blocking).
#   4. Returns { session_id } immediately — the rest arrives over WebSocket.
#
# WebSocket message types emitted during a /chat run:
#   { type: "chat_status",  session_id, status, text }
#     status values: "planning" | "step" | "done" | "error"
#   { type: "action",       session_id, action, policy }   ← existing action-feed events
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    goal: str
    url: str | None = None
    headless: bool = True


@app.post("/chat")
async def chat(body: ChatRequest):
    session_id = str(uuid.uuid4())

    # Record the user message
    chat_sessions[session_id] = [
        {"role": "user", "text": body.goal}
    ]

    # Immediate "planning" status so the UI reacts right away
    await _broadcast({
        "type": "chat_status",
        "session_id": session_id,
        "status": "planning",
        "text": f'Planning how to: "{body.goal}"',
    })

    # Resolve the start URL
    project_root = Path(__file__).resolve().parents[2]
    if body.url:
        page_uri = body.url
    else:
        # Default demo page — benign shopping so ordinary tasks work
        page_uri = (project_root / "test-pages" / "benign_checkout.html").as_uri()

    # Launch agent in the background, passing a status_callback so it can
    # emit chat_status events at each step without knowing about WebSockets.
    async def status_callback(status: str, text: str, step_event: dict | None = None):
        msg = {"role": "agent", "text": text}
        chat_sessions[session_id].append(msg)
        payload = {
            "type": "chat_status",
            "session_id": session_id,
            "status": status,
            "text": text,
        }
        if step_event:
            payload["step_event"] = step_event
        await _broadcast(payload)

    asyncio.create_task(
        _run_chat_agent(
            session_id=session_id,
            goal=body.goal,
            page_uri=page_uri,
            headless=body.headless,
            status_callback=status_callback,
        )
    )

    return {"session_id": session_id, "status": "started"}


async def _run_chat_agent(
    session_id: str,
    goal: str,
    page_uri: str,
    headless: bool,
    status_callback,
):
    """
    Wraps run_browser_agent_async with:
    - a pre-run "planning" step message
    - per-action status events (via action_queue, same as before)
    - a final "done" or "error" message
    """
    try:
        # Wrap the action_queue so every action payload also gets a
        # session_id and type="action" attached, keeping it compatible
        # with the existing ActionFeed while also letting ChatPanel filter
        # by session_id.
        tagged_queue: asyncio.Queue = asyncio.Queue()

        async def _forward_tagged():
            while True:
                item = await tagged_queue.get()
                if item is None:
                    break
                # Tag with session info for the chat panel
                item["type"] = "action"
                item["session_id"] = session_id
                await action_queue.put(item)

        forwarder = asyncio.create_task(_forward_tagged())

        result = await run_browser_agent_async(
            tagged_queue,
            page_uri=page_uri,
            user_task=goal,
            headless=headless,
            auto_approve_escalated=False,
            step_callback=status_callback,   # streams per-step progress to chat
            trace_id=session_id,             # keys the X-Ray placeholder trace file
        )

        # Signal forwarder to stop
        await tagged_queue.put(None)
        await forwarder

        # Bug fix (Milestone 3 item A): previously this sent "done"
        # unconditionally, even when the task was blocked by policy, hit a
        # CAPTCHA, or ran out of steps without finishing. Respect the real
        # outcome from run_browser_agent_async instead.
        if result and result.get("status") == "error":
            reason = result.get("reason") or "did not complete"
            await status_callback("error", f'Task ended without completing: "{goal}" — {reason}')
        else:
            await status_callback("done", f'Task complete: "{goal}"')

    except Exception as exc:
        logging.exception("Chat agent error for session %s", session_id)
        await status_callback("error", f"Agent error: {exc}")


# ---------------------------------------------------------------------------
# /chat-sessions  — return history for a session (or all sessions)
# ---------------------------------------------------------------------------
@app.get("/chat-sessions")
def get_chat_sessions():
    return chat_sessions


@app.get("/chat-sessions/{session_id}")
def get_chat_session(session_id: str):
    if session_id not in chat_sessions:
        return {"error": "session not found"}
    return chat_sessions[session_id]


# ---------------------------------------------------------------------------
# /resolve-escalation  (unchanged)
# ---------------------------------------------------------------------------
class EscalationResolution(BaseModel):
    action_id: str
    decision: str


@app.post("/resolve-escalation")
def resolve_escalation(payload: EscalationResolution):
    from app.agent.escalation_state import pending_escalations
    if payload.action_id in pending_escalations:
        pending_escalations[payload.action_id] = payload.decision
        return {"status": "success"}
    return {"status": "not found"}


# ---------------------------------------------------------------------------
# /resolve-captcha — human signals they solved a CAPTCHA in the browser
# ---------------------------------------------------------------------------
class CaptchaResolution(BaseModel):
    session_id: str


@app.post("/resolve-captcha")
def resolve_captcha(payload: CaptchaResolution):
    from app.agent.captcha_state import pending_captchas
    if payload.session_id in pending_captchas:
        pending_captchas[payload.session_id] = "resolved"
        return {"status": "success"}
    return {"status": "not found"}


# ---------------------------------------------------------------------------
# WebSocket broadcaster
# ---------------------------------------------------------------------------
async def broadcaster():
    while True:
        payload = await action_queue.get()
        message = json.dumps(payload)
        dead = []

        for conn in active_connections:
            try:
                await conn.send_text(message)
            except Exception as exc:
                logging.warning("WebSocket send failed, removing connection: %s", exc)
                dead.append(conn)

        for conn in dead:
            if conn in active_connections:
                active_connections.remove(conn)

        await asyncio.sleep(0)   # yield — no artificial 1 s delay for chat events


@app.on_event("startup")
async def start_broadcaster():
    asyncio.create_task(broadcaster())


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    active_connections.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        logging.info("Client disconnected — closing this connection cleanly.")
    except Exception as exc:
        logging.warning("WebSocket error, removing connection: %s", exc)
    finally:
        if ws in active_connections:
            active_connections.remove(ws)
